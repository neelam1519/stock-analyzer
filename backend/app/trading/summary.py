import time
from datetime import date
from threading import Lock
from typing import Any

from kiteconnect.exceptions import KiteException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.regime import market_regime
from app.core.calendar import cached_holidays, is_trading_day, next_trading_day
from app.core.clock import is_market_hours, now_ist
from app.kite import service
from app.models import PaperOrder, PortfolioSnapshot, Position
from app.trading.live_settings import load_live_settings
from app.trading.risk import BOOK, account, get_limits

KITE_TTL_SECONDS = 30
_cache: dict[str, tuple[float, dict]] = {}
_lock = Lock()


def _num(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def kite_figures(margins: dict, holdings: list[dict], positions: dict) -> dict:
    equity = margins or {}
    available = equity.get("available") or {}
    utilised = equity.get("utilised") or {}
    holdings_value = holdings_invested = holdings_day = holdings_pnl = 0.0
    for h in holdings or []:
        qty = _num(h.get("quantity")) + _num(h.get("t1_quantity"))
        last, close, avg = _num(h.get("last_price")), _num(h.get("close_price")), _num(h.get("average_price"))
        holdings_value += qty * last
        holdings_invested += qty * avg
        holdings_pnl += qty * (last - avg)
        if close:
            holdings_day += qty * (last - close)
    day_positions = (positions or {}).get("day") or []
    positions_day = sum(_num(p.get("m2m", p.get("pnl"))) for p in day_positions)
    open_positions = sum(1 for p in (positions or {}).get("net") or [] if _num(p.get("quantity")))
    today = holdings_day + positions_day
    base = holdings_value - holdings_day
    return {
        "available_cash": round(_num(available.get("live_balance", available.get("cash"))), 2),
        "opening_balance": round(_num(available.get("opening_balance")), 2),
        "used_margin": round(_num(utilised.get("debits")), 2),
        "net": round(_num(equity.get("net")), 2),
        "holdings_count": len(holdings or []),
        "holdings_value": round(holdings_value, 2),
        "holdings_invested": round(holdings_invested, 2),
        "holdings_pnl": round(holdings_pnl, 2),
        "positions_open": open_positions,
        "today_pnl": round(today, 2),
        "today_pnl_pct": round(today / base * 100, 2) if base > 0 else None,
    }


def _cached_kite(db: Session) -> dict:
    session = service.active_session(db)
    if session is None:
        return {"connected": False}
    key = session.user_id
    with _lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < KITE_TTL_SECONDS:
            return hit[1]
    try:
        kite = service.market_client(db)
        data = {
            "connected": True,
            "user_id": session.user_id,
            "expires_at": session.expires_at.isoformat() + "Z",
            **kite_figures(kite.margins("equity"), kite.holdings(), kite.positions()),
        }
    except (service.KiteNotConnected, service.KiteNotConfigured):
        return {"connected": False}
    except (KiteException, ValueError) as exc:
        data = {"connected": True, "user_id": session.user_id, "error": str(exc)[:200]}
    with _lock:
        _cache[key] = (time.monotonic(), data)
    return data


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def paper_figures(db: Session, today: date) -> dict:
    acct = account(db)
    previous = db.scalar(
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.book == BOOK, PortfolioSnapshot.snapshot_date < today)
        .order_by(PortfolioSnapshot.snapshot_date.desc())
        .limit(1)
    )
    base = float(previous.cash + previous.market_value) if previous is not None else acct.capital
    today_pnl = acct.equity - base
    pending = len(list(db.scalars(select(PaperOrder.id).where(PaperOrder.status == "pending"))))
    open_positions = len(list(db.scalars(select(Position.id).where(Position.book == BOOK, Position.status == "open"))))
    return {
        "equity": round(acct.equity, 2),
        "cash": acct.cash,
        "today_pnl": round(today_pnl, 2),
        "today_pnl_pct": round(today_pnl / base * 100, 2) if base else None,
        "total_return_pct": round((acct.equity / acct.capital - 1) * 100, 2) if acct.capital else 0.0,
        "open_positions": open_positions,
        "pending_orders": pending,
    }


def account_summary(db: Session) -> dict[str, Any]:
    now = now_ist()
    holidays = cached_holidays(db)
    trading_day = is_trading_day(now.date(), holidays)
    live = load_live_settings(db)
    regime = market_regime(db)
    return {
        "now_ist": now.isoformat(),
        "market": {
            "open": trading_day and is_market_hours(now),
            "trading_day": trading_day,
            "next_session": next_trading_day(now.date(), holidays).isoformat(),
        },
        "regime": {"name": regime.name, "vix": regime.vix, "nifty": regime.nifty_close},
        "mode": {"mode": live.mode, "dry_run": live.dry_run, "kill_switch": get_limits(db).kill_switch},
        "kite": _cached_kite(db),
        "paper": paper_figures(db, now.date()),
    }
