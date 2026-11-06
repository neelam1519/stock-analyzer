from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.core.config import get_settings
from app.models import (
    AppSetting,
    DailyCandle,
    IndicatorDaily,
    Instrument,
    PaperOrder,
    PortfolioSnapshot,
    Position,
    ResearchReport,
    Signal,
    Trade,
)
from app.signals.params import load_active_params
from app.trading.risk import BOOK, COSTS, GAP_UP_LIMIT, EntryGate, account, buy_fee, sell_fee

SLIP = COSTS.slippage_pct / 100


@dataclass
class PaperResult:
    planned: int = 0
    rejected: int = 0
    filled: int = 0
    cancelled: int = 0
    closed: int = 0
    exit_orders: int = 0
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"planned={self.planned} rejected={self.rejected} filled={self.filled} cancelled={self.cancelled} "
            f"closed={self.closed} exit_orders={self.exit_orders}"
        )


def _f(value) -> float:
    return float(value) if value is not None else 0.0


def close_position(db: Session, position: Position, price: float, reason: str, when: datetime) -> float:
    fill = round(price * (1 - SLIP), 2)
    value = fill * position.qty
    fees = round(sell_fee(value), 2)
    cost_basis = _f(position.avg_price) * position.qty
    buy_fees = round(buy_fee(cost_basis), 2)
    pnl = round(value - fees - cost_basis - buy_fees, 2)
    position.status = "closed"
    position.closed_at = when
    position.exit_price = fill
    position.realized_pnl = pnl
    position.exit_reason = reason
    position.last_price = fill
    position.last_price_at = when
    db.add(
        Trade(
            book=BOOK,
            instrument_id=position.instrument_id,
            position_id=position.id,
            side="SELL",
            qty=position.qty,
            price=fill,
            fees=fees,
            executed_at=when,
            order_ref=reason,
        )
    )
    for order in db.scalars(
        select(PaperOrder).where(PaperOrder.position_id == position.id, PaperOrder.status == "pending")
    ):
        order.status = "cancelled"
        order.reason = f"position closed by {reason}"
    return pnl


def _fill_buy(db: Session, order: PaperOrder, price: float, when: datetime, result: PaperResult) -> None:
    reference = _f(order.limit_price)
    if reference and price > reference * (1 + GAP_UP_LIMIT):
        order.status = "cancelled"
        order.reason = f"gapped up {((price / reference) - 1) * 100:.1f}% above {reference:.2f}"
        result.cancelled += 1
        return
    fill = round(price * (1 + SLIP), 2)
    stop_distance = reference - _f(order.stop_loss) if reference else fill * 0.05
    target_distance = _f(order.target) - reference if reference else fill * 0.1
    stop, target = round(fill - stop_distance, 2), round(fill + target_distance, 2)
    position = Position(
        book=BOOK,
        instrument_id=order.instrument_id,
        signal_id=order.signal_id,
        qty=order.qty,
        avg_price=fill,
        stop_loss=stop,
        target=target,
        initial_stop=stop,
        highest_close=fill,
        last_price=fill,
        last_price_at=when,
        status="open",
        opened_at=when,
    )
    db.add(position)
    db.flush()
    value = fill * order.qty
    db.add(
        Trade(
            book=BOOK,
            instrument_id=order.instrument_id,
            position_id=position.id,
            side="BUY",
            qty=order.qty,
            price=fill,
            fees=round(buy_fee(value), 2),
            executed_at=when,
            order_ref=f"paper-order-{order.id}",
        )
    )
    order.status = "filled"
    order.filled_price = fill
    order.filled_at = when
    order.position_id = position.id
    result.filled += 1


def fill_orders(db: Session, prices: dict[int, float], when: datetime | None = None) -> PaperResult:
    when = when or utc_now()
    result = PaperResult()
    pending = list(
        db.scalars(
            select(PaperOrder).where(PaperOrder.status == "pending").order_by(PaperOrder.side.desc(), PaperOrder.id)
        )
    )
    for order in pending:
        price = prices.get(order.instrument_id)
        if not price:
            continue
        if order.side == "SELL":
            position = db.get(Position, order.position_id) if order.position_id else None
            if position is None or position.status != "open":
                order.status = "cancelled"
                order.reason = "position not open"
                result.cancelled += 1
                continue
            close_position(db, position, price, order.reason or "signal", when)
            order.status = "filled"
            order.filled_price = position.exit_price
            order.filled_at = when
            result.closed += 1
        else:
            _fill_buy(db, order, price, when, result)
    db.commit()
    return result


def monitor_positions(db: Session, prices: dict[int, float], when: datetime | None = None) -> PaperResult:
    when = when or utc_now()
    result = PaperResult()
    for position in db.scalars(select(Position).where(Position.book == BOOK, Position.status == "open")):
        price = prices.get(position.instrument_id)
        if not price:
            continue
        position.last_price = price
        position.last_price_at = when
        if price <= _f(position.stop_loss):
            close_position(db, position, price, "stop", when)
            result.closed += 1
        elif position.target is not None and price >= _f(position.target):
            close_position(db, position, price, "target", when)
            result.closed += 1
    db.commit()
    return result


def _candles(db: Session, day: date, instrument_ids: list[int]) -> dict[int, DailyCandle]:
    if not instrument_ids:
        return {}
    rows = db.scalars(
        select(DailyCandle).where(DailyCandle.trade_date == day, DailyCandle.instrument_id.in_(instrument_ids))
    )
    return {c.instrument_id: c for c in rows}


def sessions_held(db: Session, opened: date, day: date) -> int:
    nifty = db.scalar(select(Instrument.id).where(Instrument.tradingsymbol == "NIFTY 50"))
    return (
        db.scalar(
            select(func.count()).where(
                DailyCandle.instrument_id == nifty, DailyCandle.trade_date > opened, DailyCandle.trade_date <= day
            )
        )
        or 0
    )


LAST_EOD_KEY = "paper.last_eod"


def _last_eod(db: Session) -> date | None:
    setting = db.get(AppSetting, LAST_EOD_KEY)
    return date.fromisoformat(setting.value) if setting else None


def _mark_eod(db: Session, day: date) -> None:
    setting = db.get(AppSetting, LAST_EOD_KEY) or AppSetting(key=LAST_EOD_KEY)
    setting.value = day.isoformat()
    setting.updated_at = utc_now()
    db.add(setting)


def end_of_day(db: Session, day: date, when: datetime | None = None) -> PaperResult:
    when = when or utc_now()
    params, _ = load_active_params(db)
    result = PaperResult()
    last = _last_eod(db)
    if last is not None and day < last:
        result.notes.append(f"already processed {last}")
        return result
    rerun = last == day

    pending = list(db.scalars(select(PaperOrder).where(PaperOrder.status == "pending", PaperOrder.as_of_date < day)))
    opens = _candles(db, day, [o.instrument_id for o in pending])
    fallback = {iid: float(c.open) for iid, c in opens.items()}
    if fallback:
        filled = fill_orders(db, fallback, when)
        result.filled += filled.filled
        result.cancelled += filled.cancelled
        result.closed += filled.closed

    positions = list(db.scalars(select(Position).where(Position.book == BOOK, Position.status == "open")))
    candles = _candles(db, day, [p.instrument_id for p in positions])
    indicators = {
        i.instrument_id: i
        for i in db.scalars(
            select(IndicatorDaily).where(
                IndicatorDaily.trade_date == day,
                IndicatorDaily.instrument_id.in_([p.instrument_id for p in positions] or [-1]),
            )
        )
    }
    sells = set(
        db.scalars(
            select(Signal.instrument_id).where(
                Signal.as_of_date == day, Signal.strategy == params.name, Signal.action == "SELL"
            )
        )
    )
    for position in positions:
        candle = candles.get(position.instrument_id)
        if candle is None:
            continue
        if rerun:
            _queue_signal_exit(db, position, day, sells, result)
            continue
        o, h, low, c = float(candle.open), float(candle.high), float(candle.low), float(candle.close)
        opened_today = position.opened_at.date() >= day if position.opened_at else False
        stop, target = _f(position.stop_loss), _f(position.target)
        if low <= stop:
            close_position(db, position, stop if opened_today else min(o, stop), "stop", when)
            result.closed += 1
            continue
        if target and h >= target:
            close_position(db, position, target if opened_today else max(o, target), "target", when)
            result.closed += 1
            continue
        position.last_price = c
        position.last_price_at = when
        position.highest_close = max(_f(position.highest_close), c)
        initial_risk = _f(position.avg_price) - _f(position.initial_stop)
        new_stop = stop
        if initial_risk > 0 and c >= _f(position.avg_price) + initial_risk:
            new_stop = max(new_stop, _f(position.avg_price))
        ind = indicators.get(position.instrument_id)
        if params.trail_atr and ind is not None and ind.atr14 is not None:
            new_stop = max(new_stop, _f(position.highest_close) - params.trail_atr * float(ind.atr14))
        position.stop_loss = round(new_stop, 2)
        if (
            params.max_hold_days
            and position.opened_at
            and sessions_held(db, position.opened_at.date(), day) >= params.max_hold_days
        ):
            close_position(db, position, c, "time", when)
            result.closed += 1
            continue
        _queue_signal_exit(db, position, day, sells, result)
    _mark_eod(db, day)
    db.commit()
    return result


def _queue_signal_exit(db: Session, position: Position, day: date, sells: set[int], result: PaperResult) -> None:
    if position.instrument_id not in sells:
        return
    exists = db.scalar(
        select(PaperOrder.id).where(PaperOrder.position_id == position.id, PaperOrder.status == "pending")
    )
    if exists:
        return
    db.add(
        PaperOrder(
            instrument_id=position.instrument_id,
            signal_id=None,
            side="SELL",
            qty=position.qty,
            order_type="OPEN",
            status="pending",
            as_of_date=day,
            position_id=position.id,
            reason="signal",
        )
    )
    result.exit_orders += 1


def plan_entries(db: Session, day: date) -> PaperResult:
    params, _ = load_active_params(db)
    result = PaperResult()
    already = db.scalar(select(PaperOrder.id).where(PaperOrder.as_of_date == day, PaperOrder.side == "BUY").limit(1))
    if already:
        result.notes.append("entries already planned for this session")
        return result
    for stale in db.scalars(
        select(PaperOrder).where(PaperOrder.status == "pending", PaperOrder.side == "BUY", PaperOrder.as_of_date < day)
    ):
        stale.status = "cancelled"
        stale.reason = "expired before fill"
        result.cancelled += 1

    model = get_settings().llm_model
    rows = db.execute(
        select(Signal, Instrument, ResearchReport.verdict)
        .join(Instrument, Instrument.id == Signal.instrument_id)
        .outerjoin(
            ResearchReport,
            and_(
                ResearchReport.instrument_id == Signal.instrument_id,
                ResearchReport.as_of_date == Signal.as_of_date,
                ResearchReport.model == model,
            ),
        )
        .where(Signal.as_of_date == day, Signal.strategy == params.name, Signal.action == "BUY")
        .order_by(Signal.score.desc())
    ).all()
    if not rows:
        db.commit()
        return result
    rows = sorted(rows, key=lambda r: (0 if r[2] == "buy" else 1, -float(r[0].score)))
    gate = EntryGate(db, day, rows[0][0].regime or "unknown", params)
    for signal, instrument, verdict in rows:
        if gate.slots_used >= gate.max_slots and not gate.limits.kill_switch:
            break
        if verdict == "avoid":
            decision_ok, reason, qty = False, "AI research verdict: avoid", 0
        else:
            decision = gate.check(instrument.id, instrument.sector, _f(signal.entry_price), _f(signal.stop_loss))
            decision_ok, reason, qty = decision.ok, decision.reason, decision.qty
        db.add(
            PaperOrder(
                instrument_id=instrument.id,
                signal_id=signal.id,
                side="BUY",
                qty=qty,
                order_type="OPEN",
                limit_price=signal.entry_price,
                stop_loss=signal.stop_loss,
                target=signal.target,
                status="pending" if decision_ok else "rejected",
                as_of_date=day,
                reason=(f"score {float(signal.score):.0f}" + (f", AI {verdict}" if verdict else "") + f"; {reason}")[
                    :200
                ],
            )
        )
        if decision_ok:
            result.planned += 1
        else:
            result.rejected += 1
            if gate.limits.kill_switch or gate.breach:
                break
    db.commit()
    return result


def snapshot(db: Session, day: date) -> PortfolioSnapshot:
    acct = account(db)
    snap = db.get(PortfolioSnapshot, (BOOK, day)) or PortfolioSnapshot(book=BOOK, snapshot_date=day)
    snap.cash = acct.cash
    snap.invested = acct.invested
    snap.market_value = acct.market_value
    snap.realized_pnl = acct.realized_pnl
    snap.unrealized_pnl = acct.unrealized_pnl
    db.add(snap)
    db.commit()
    return snap
