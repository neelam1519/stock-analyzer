import math
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.backtest.engine import REGIME_SIZE, PortfolioConfig
from app.core.clock import utc_now
from app.models import Instrument, PaperOrder, PortfolioSnapshot, Position, RiskLimits, Trade

BOOK = "paper"
COSTS = PortfolioConfig()
DEFAULT_LIMITS = {
    "capital": Decimal(1000000),
    "risk_per_trade_pct": Decimal("1.0"),
    "max_position_pct": Decimal(20),
    "max_open_positions": 8,
    "daily_loss_limit_pct": Decimal(2),
    "weekly_loss_limit_pct": Decimal(5),
    "max_sector_pct": Decimal(40),
    "kill_switch": False,
}
GAP_UP_LIMIT = 0.03
COOLDOWN_DAYS = 7


def get_limits(db: Session) -> RiskLimits:
    limits = db.scalar(select(RiskLimits).order_by(RiskLimits.id).limit(1))
    if limits is None:
        limits = RiskLimits(**DEFAULT_LIMITS, updated_at=utc_now())
        db.add(limits)
        db.commit()
    return limits


def buy_fee(value: float) -> float:
    return value * COSTS.cost_pct / 100


def sell_fee(value: float) -> float:
    return value * COSTS.cost_pct / 100 + COSTS.fixed_sell_cost


@dataclass
class Account:
    capital: float
    cash: float
    invested: float
    market_value: float
    realized_pnl: float
    unrealized_pnl: float
    reserved: float
    open_positions: int
    pending_buys: int

    @property
    def equity(self) -> float:
        return self.cash + self.market_value

    @property
    def available_cash(self) -> float:
        return self.cash - self.reserved


def position_price(position: Position) -> float:
    return float(position.last_price if position.last_price is not None else position.avg_price)


def account(db: Session, book: str = BOOK) -> Account:
    limits = get_limits(db)
    capital = float(limits.capital)
    flows = db.execute(
        select(Trade.side, func.coalesce(func.sum(Trade.qty * Trade.price), 0), func.coalesce(func.sum(Trade.fees), 0))
        .where(Trade.book == book)
        .group_by(Trade.side)
    ).all()
    cash = capital
    for side, value, fees in flows:
        cash += float(value) - float(fees) if side == "SELL" else -(float(value) + float(fees))
    open_positions = list(db.scalars(select(Position).where(Position.book == book, Position.status == "open")))
    invested = sum(float(p.avg_price) * p.qty for p in open_positions)
    market_value = sum(position_price(p) * p.qty for p in open_positions)
    realized = db.scalar(
        select(func.coalesce(func.sum(Position.realized_pnl), 0)).where(
            Position.book == book, Position.status == "closed"
        )
    )
    pending = list(db.scalars(select(PaperOrder).where(PaperOrder.status == "pending", PaperOrder.side == "BUY")))
    reserved = sum(float(o.limit_price or 0) * o.qty * (1 + GAP_UP_LIMIT) for o in pending)
    return Account(
        capital=capital,
        cash=round(cash, 2),
        invested=round(invested, 2),
        market_value=round(market_value, 2),
        realized_pnl=round(float(realized or 0), 2),
        unrealized_pnl=round(market_value - invested, 2),
        reserved=round(reserved, 2),
        open_positions=len(open_positions),
        pending_buys=len(pending),
    )


def _equity_before(db: Session, day: date, book: str = BOOK) -> float | None:
    value = db.execute(
        select(PortfolioSnapshot.cash + PortfolioSnapshot.market_value)
        .where(PortfolioSnapshot.book == book, PortfolioSnapshot.snapshot_date < day)
        .order_by(PortfolioSnapshot.snapshot_date.desc())
        .limit(1)
    ).scalar()
    return float(value) if value is not None else None


def loss_limit_breach(db: Session, today: date, equity: float, limits: RiskLimits) -> str | None:
    capital = float(limits.capital)
    previous = _equity_before(db, today)
    if previous is not None and (equity - previous) / capital * 100 <= -float(limits.daily_loss_limit_pct):
        return f"daily loss limit {limits.daily_loss_limit_pct}% hit"
    week_start = today - timedelta(days=today.weekday())
    weekly_base = _equity_before(db, week_start)
    if weekly_base is not None and (equity - weekly_base) / capital * 100 <= -float(limits.weekly_loss_limit_pct):
        return f"weekly loss limit {limits.weekly_loss_limit_pct}% hit"
    return None


@dataclass
class EntryDecision:
    ok: bool
    reason: str
    qty: int = 0


class EntryGate:
    def __init__(self, db: Session, today: date, regime: str):
        self.db = db
        self.limits = get_limits(db)
        self.acct = account(db)
        self.today = today
        self.regime = regime
        self.breach = loss_limit_breach(db, today, self.acct.equity, self.limits)
        open_rows = db.execute(
            select(Position.instrument_id, Instrument.sector, Position.qty, Position.last_price, Position.avg_price)
            .join(Instrument, Instrument.id == Position.instrument_id)
            .where(Position.book == BOOK, Position.status == "open")
        ).all()
        pending_rows = db.execute(
            select(PaperOrder.instrument_id, Instrument.sector, PaperOrder.qty, PaperOrder.limit_price)
            .join(Instrument, Instrument.id == PaperOrder.instrument_id)
            .where(PaperOrder.status == "pending", PaperOrder.side == "BUY")
        ).all()
        self.held = {r.instrument_id for r in open_rows} | {r.instrument_id for r in pending_rows}
        self.slots_used = len(open_rows) + len(pending_rows)
        self.sector_count: dict[str, int] = {}
        self.sector_value: dict[str, float] = {}
        for r in open_rows:
            self._add_sector(r.sector, r.qty * float(r.last_price or r.avg_price))
        for r in pending_rows:
            self._add_sector(r.sector, r.qty * float(r.limit_price or 0))
        cutoff = utc_now() - timedelta(days=COOLDOWN_DAYS)
        self.cooling = set(
            db.scalars(
                select(Position.instrument_id).where(
                    Position.book == BOOK, Position.status == "closed", Position.closed_at >= cutoff
                )
            )
        )
        self.cash = self.acct.available_cash

    def _add_sector(self, sector: str | None, value: float) -> None:
        key = sector or "Other"
        self.sector_count[key] = self.sector_count.get(key, 0) + 1
        self.sector_value[key] = self.sector_value.get(key, 0.0) + value

    def check(self, instrument_id: int, sector: str | None, entry: float, stop: float) -> EntryDecision:
        limits, equity = self.limits, self.acct.equity
        if limits.kill_switch:
            return EntryDecision(False, "kill switch is on")
        if self.breach:
            return EntryDecision(False, self.breach)
        if instrument_id in self.held:
            return EntryDecision(False, "already held or ordered")
        if instrument_id in self.cooling:
            return EntryDecision(False, f"exited within {COOLDOWN_DAYS} days")
        if self.slots_used >= limits.max_open_positions:
            return EntryDecision(False, f"max {limits.max_open_positions} positions")
        key = sector or "Other"
        if self.sector_count.get(key, 0) >= COSTS.max_per_sector:
            return EntryDecision(False, f"max {COSTS.max_per_sector} positions in {key}")
        risk_per_share = entry - stop
        if risk_per_share <= 0:
            return EntryDecision(False, "invalid stop")
        risk_budget = equity * float(limits.risk_per_trade_pct) / 100 * REGIME_SIZE.get(self.regime, 0.5)
        sector_room = equity * float(limits.max_sector_pct) / 100 - self.sector_value.get(key, 0.0)
        reserve_price = entry * (1 + GAP_UP_LIMIT) * (1 + COSTS.cost_pct / 100)
        qty = math.floor(
            min(
                risk_budget / risk_per_share,
                equity * float(limits.max_position_pct) / 100 / entry,
                sector_room / entry,
                self.cash / reserve_price,
            )
        )
        if qty <= 0:
            return EntryDecision(False, "insufficient cash or sector room")
        self.held.add(instrument_id)
        self.slots_used += 1
        self.cash -= qty * reserve_price
        self._add_sector(sector, qty * entry)
        return EntryDecision(True, f"risk Rs {qty * risk_per_share:,.0f} ({self.regime} sizing)", qty)
