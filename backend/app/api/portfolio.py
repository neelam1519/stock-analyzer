from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.calendar import cached_holidays, next_trading_day
from app.core.clock import now_ist, utc_now
from app.core.db import get_db
from app.models import Instrument, PaperOrder, PortfolioSnapshot, Position
from app.scheduler import pipeline, runner, timers
from app.signals.generator import latest_session
from app.trading import paper
from app.trading.risk import BOOK, account, get_limits, position_price

router = APIRouter(tags=["portfolio"])


def _iso(value) -> str | None:
    return value.isoformat() + "Z" if value else None


def _position_dict(position: Position, instrument: Instrument) -> dict:
    price = position_price(position)
    entry = float(position.avg_price)
    initial_risk = entry - float(position.initial_stop or position.stop_loss or entry)
    exit_price = float(position.exit_price) if position.exit_price is not None else None
    reference = exit_price if position.status == "closed" and exit_price is not None else price
    return {
        "id": position.id,
        "symbol": instrument.tradingsymbol,
        "sector": instrument.sector,
        "qty": position.qty,
        "entry": entry,
        "price": price,
        "price_at": _iso(position.last_price_at),
        "stop": float(position.stop_loss) if position.stop_loss is not None else None,
        "initial_stop": float(position.initial_stop) if position.initial_stop is not None else None,
        "target": float(position.target) if position.target is not None else None,
        "value": round(price * position.qty, 2),
        "pnl": round(float(position.realized_pnl), 2)
        if position.status == "closed" and position.realized_pnl is not None
        else round((price - entry) * position.qty, 2),
        "pnl_pct": round((reference / entry - 1) * 100, 2) if entry else None,
        "r_multiple": round((reference - entry) / initial_risk, 2) if initial_risk > 0 else None,
        "opened_at": _iso(position.opened_at),
        "closed_at": _iso(position.closed_at),
        "exit_price": exit_price,
        "exit_reason": position.exit_reason,
        "status": position.status,
    }


def _order_dict(order: PaperOrder, symbol: str) -> dict:
    return {
        "id": order.id,
        "symbol": symbol,
        "side": order.side,
        "qty": order.qty,
        "status": order.status,
        "reference": float(order.limit_price) if order.limit_price is not None else None,
        "stop": float(order.stop_loss) if order.stop_loss is not None else None,
        "target": float(order.target) if order.target is not None else None,
        "filled_price": float(order.filled_price) if order.filled_price is not None else None,
        "as_of": order.as_of_date.isoformat() if order.as_of_date else None,
        "reason": order.reason,
        "created_at": _iso(order.created_at),
    }


@router.get("/portfolio")
def portfolio(db: Session = Depends(get_db)) -> dict:
    acct = account(db)
    limits = get_limits(db)
    positions = db.execute(
        select(Position, Instrument)
        .join(Instrument, Instrument.id == Position.instrument_id)
        .where(Position.book == BOOK, Position.status == "open")
        .order_by(Position.opened_at)
    ).all()
    session = latest_session(db)
    orders = db.execute(
        select(PaperOrder, Instrument.tradingsymbol)
        .join(Instrument, Instrument.id == PaperOrder.instrument_id)
        .where((PaperOrder.status == "pending") | (PaperOrder.as_of_date == session))
        .order_by(PaperOrder.id.desc())
        .limit(60)
    ).all()
    holidays = cached_holidays(db)
    return {
        "book": BOOK,
        "capital": acct.capital,
        "cash": acct.cash,
        "invested": acct.invested,
        "market_value": acct.market_value,
        "equity": round(acct.equity, 2),
        "total_return_pct": round((acct.equity / acct.capital - 1) * 100, 2) if acct.capital else 0,
        "realized_pnl": acct.realized_pnl,
        "unrealized_pnl": acct.unrealized_pnl,
        "reserved_for_orders": acct.reserved,
        "kill_switch": limits.kill_switch,
        "next_session": next_trading_day(now_ist().date(), holidays).isoformat(),
        "positions": [_position_dict(p, i) for p, i in positions],
        "orders": [_order_dict(o, s) for o, s in orders],
    }


@router.get("/portfolio/history")
def portfolio_history(limit: int = Query(default=200, le=1000), db: Session = Depends(get_db)) -> dict:
    closed = db.execute(
        select(Position, Instrument)
        .join(Instrument, Instrument.id == Position.instrument_id)
        .where(Position.book == BOOK, Position.status == "closed")
        .order_by(Position.closed_at.desc())
        .limit(limit)
    ).all()
    snapshots = db.scalars(
        select(PortfolioSnapshot).where(PortfolioSnapshot.book == BOOK).order_by(PortfolioSnapshot.snapshot_date)
    )
    items = [_position_dict(p, i) for p, i in closed]
    wins = [t for t in items if (t["pnl"] or 0) > 0]
    return {
        "closed": items,
        "stats": {
            "trades": len(items),
            "win_rate_pct": round(len(wins) / len(items) * 100, 1) if items else None,
            "realized_pnl": round(sum(t["pnl"] or 0 for t in items), 2),
        },
        "equity": [{"time": s.snapshot_date.isoformat(), "equity": float(s.cash + s.market_value)} for s in snapshots],
    }


@router.post("/portfolio/positions/{position_id}/close")
def close_position(position_id: int, db: Session = Depends(get_db)) -> dict:
    position = db.get(Position, position_id)
    if position is None or position.status != "open" or position.book != BOOK:
        raise HTTPException(status_code=404, detail="Open paper position not found")
    pnl = paper.close_position(db, position, position_price(position), "manual", utc_now())
    db.commit()
    return {"closed": position_id, "pnl": pnl}


@router.post("/portfolio/orders/{order_id}/cancel")
def cancel_order(order_id: int, db: Session = Depends(get_db)) -> dict:
    order = db.get(PaperOrder, order_id)
    if order is None or order.status != "pending":
        raise HTTPException(status_code=404, detail="Pending order not found")
    order.status = "cancelled"
    order.reason = "cancelled manually"
    db.commit()
    return {"cancelled": order_id}


@router.post("/portfolio/plan")
def plan_now(db: Session = Depends(get_db)) -> dict:
    session = latest_session(db)
    if session is None:
        raise HTTPException(status_code=409, detail="Run analysis first")
    result = paper.plan_entries(db, session)
    paper.snapshot(db, session)
    return {"as_of": session.isoformat(), "summary": result.summary(), "notes": result.notes}


class RiskLimitsIn(BaseModel):
    capital: Decimal = Field(gt=0)
    risk_per_trade_pct: Decimal = Field(gt=0, le=5)
    max_position_pct: Decimal = Field(gt=0, le=100)
    max_open_positions: int = Field(ge=1, le=30)
    daily_loss_limit_pct: Decimal = Field(gt=0, le=50)
    weekly_loss_limit_pct: Decimal = Field(gt=0, le=50)
    max_sector_pct: Decimal = Field(gt=0, le=100)


def _limits_dict(limits) -> dict:
    return {
        "capital": float(limits.capital),
        "risk_per_trade_pct": float(limits.risk_per_trade_pct),
        "max_position_pct": float(limits.max_position_pct),
        "max_open_positions": limits.max_open_positions,
        "daily_loss_limit_pct": float(limits.daily_loss_limit_pct),
        "weekly_loss_limit_pct": float(limits.weekly_loss_limit_pct),
        "max_sector_pct": float(limits.max_sector_pct),
        "kill_switch": limits.kill_switch,
        "updated_at": _iso(limits.updated_at),
    }


@router.get("/risk/limits")
def read_limits(db: Session = Depends(get_db)) -> dict:
    return _limits_dict(get_limits(db))


@router.put("/risk/limits")
def update_limits(body: RiskLimitsIn, db: Session = Depends(get_db)) -> dict:
    limits = get_limits(db)
    for key, value in body.model_dump().items():
        setattr(limits, key, value)
    limits.updated_at = utc_now()
    db.commit()
    return _limits_dict(limits)


class KillSwitchIn(BaseModel):
    on: bool


@router.post("/risk/kill-switch")
def kill_switch(body: KillSwitchIn, db: Session = Depends(get_db)) -> dict:
    limits = get_limits(db)
    limits.kill_switch = body.on
    limits.updated_at = utc_now()
    cancelled = 0
    live_result: dict = {}
    if body.on:
        for order in db.scalars(select(PaperOrder).where(PaperOrder.status == "pending", PaperOrder.side == "BUY")):
            order.status = "cancelled"
            order.reason = "kill switch"
            cancelled += 1
        db.commit()
        from app.api.live import optional_kite
        from app.trading.live import kill_live

        live_result = kill_live(db, optional_kite(db))
    db.commit()
    return {**_limits_dict(limits), "cancelled_orders": cancelled, "live": live_result}


@router.get("/scheduler")
def scheduler_status(db: Session = Depends(get_db)) -> dict:
    return timers.timers(db)


@router.post("/scheduler/{job_id}/run", status_code=202)
def scheduler_run(job_id: str) -> dict:
    if not runner.run_now(job_id):
        raise HTTPException(status_code=404, detail=f"Unknown job {job_id}")
    return {"started": job_id}


@router.post("/paper/end-of-day")
def paper_eod(day: date | None = None, db: Session = Depends(get_db)) -> dict:
    session = day or latest_session(db)
    if session is None:
        raise HTTPException(status_code=409, detail="No market data yet")
    eod = paper.end_of_day(db, session)
    paper.snapshot(db, session)
    return {"as_of": session.isoformat(), "summary": eod.summary()}


@router.post("/paper/monitor")
def paper_monitor(db: Session = Depends(get_db)) -> dict:
    try:
        result = pipeline.monitor_once(db)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"summary": result.summary() if result else "no open positions"}
