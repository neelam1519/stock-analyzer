import json
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.api.portfolio import _iso, _position_dict
from app.core.config import get_settings
from app.core.db import get_db
from app.kite import service
from app.models import ApprovalItem, Instrument, LiveOrder, Position, ResearchReport, Signal
from app.trading import live
from app.trading.live_settings import MODES, load_live_settings, save_live_settings

router = APIRouter(tags=["live"])


def optional_kite(db: Session):
    try:
        return service.market_client(db)
    except (service.KiteNotConnected, service.KiteNotConfigured):
        return None


class LiveSettingsIn(BaseModel):
    mode: str
    dry_run: bool
    live_capital: float = Field(gt=0)
    max_order_value: float = Field(gt=0)
    entry_buffer_pct: float = Field(ge=0, le=3)
    max_price_drift_pct: float = Field(gt=0, le=10)
    confirm: str | None = None


@router.get("/trading/settings")
def read_trading_settings(db: Session = Depends(get_db)) -> dict:
    return asdict(load_live_settings(db))


@router.put("/trading/settings")
def update_trading_settings(body: LiveSettingsIn, db: Session = Depends(get_db)) -> dict:
    if body.mode not in MODES:
        raise HTTPException(status_code=422, detail=f"mode must be one of {MODES}")
    current = load_live_settings(db)
    if current.dry_run and not body.dry_run and body.confirm != "LIVE":
        raise HTTPException(status_code=409, detail="Type LIVE to confirm switching off dry run")
    settings = current
    for key, value in body.model_dump(exclude={"confirm"}).items():
        setattr(settings, key, value)
    return asdict(save_live_settings(db, settings))


def _approval_dict(
    item: ApprovalItem, instrument: Instrument, signal: Signal | None, verdict: str | None, order: LiveOrder | None
) -> dict:
    price = float(item.limit_price) if item.limit_price is not None else None
    return {
        "id": item.id,
        "kind": item.kind,
        "symbol": instrument.tradingsymbol,
        "name": instrument.name,
        "sector": instrument.sector,
        "side": item.side,
        "qty": item.qty,
        "limit_price": price,
        "value": round(price * item.qty, 2) if price else None,
        "stop": float(item.stop_loss) if item.stop_loss is not None else None,
        "target": float(item.target) if item.target is not None else None,
        "risk_amount": float(item.risk_amount) if item.risk_amount is not None else None,
        "status": item.status,
        "reason": item.reason,
        "expires_at": _iso(item.expires_at),
        "decided_at": _iso(item.decided_at),
        "score": float(signal.score) if signal is not None else None,
        "signal_date": signal.as_of_date.isoformat() if signal is not None else None,
        "research_verdict": verdict,
        "order": _order_dict(order, instrument.tradingsymbol) if order is not None else None,
    }


def _order_dict(order: LiveOrder, symbol: str) -> dict:
    return {
        "id": order.id,
        "symbol": symbol,
        "kind": order.kind,
        "status": order.status,
        "dry_run": order.dry_run,
        "kite_order_id": order.kite_order_id,
        "gtt_id": order.gtt_id,
        "status_message": order.status_message,
        "filled_qty": order.filled_qty,
        "average_price": float(order.average_price) if order.average_price is not None else None,
        "payload": json.loads(order.payload_json),
        "created_at": _iso(order.created_at),
        "updated_at": _iso(order.updated_at),
    }


@router.get("/approvals")
def list_approvals(
    status: str = Query(default="pending", pattern="^(pending|all)$"),
    limit: int = Query(default=100, le=500),
    db: Session = Depends(get_db),
) -> dict:
    live.expire_stale(db)
    query = (
        select(ApprovalItem, Instrument, Signal, ResearchReport.verdict)
        .join(Instrument, Instrument.id == ApprovalItem.instrument_id)
        .outerjoin(Signal, Signal.id == ApprovalItem.signal_id)
        .outerjoin(
            ResearchReport,
            and_(
                ResearchReport.instrument_id == ApprovalItem.instrument_id,
                ResearchReport.as_of_date == Signal.as_of_date,
                ResearchReport.model == get_settings().llm_model,
            ),
        )
    )
    if status == "pending":
        query = query.where(ApprovalItem.status == "pending")
    rows = db.execute(query.order_by(ApprovalItem.id.desc()).limit(limit)).all()
    orders = {
        o.approval_id: o
        for o in db.scalars(
            select(LiveOrder).where(LiveOrder.approval_id.in_([r[0].id for r in rows] or [-1])).order_by(LiveOrder.id)
        )
    }
    return {
        "settings": asdict(load_live_settings(db)),
        "kite_connected": service.active_session(db) is not None,
        "items": [_approval_dict(item, inst, sig, verdict, orders.get(item.id)) for item, inst, sig, verdict in rows],
    }


@router.post("/approvals/{item_id}/approve")
def approve_item(item_id: int, db: Session = Depends(get_db)) -> dict:
    try:
        item = live.approve(db, item_id, optional_kite(db))
    except live.ApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (service.KiteNotConnected, service.KiteNotConfigured) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    order = db.scalar(select(LiveOrder).where(LiveOrder.approval_id == item.id).order_by(LiveOrder.id.desc()))
    instrument = db.get(Instrument, item.instrument_id)
    return _approval_dict(item, instrument, db.get(Signal, item.signal_id) if item.signal_id else None, None, order)


@router.post("/approvals/{item_id}/reject")
def reject_item(item_id: int, db: Session = Depends(get_db)) -> dict:
    try:
        item = live.reject(db, item_id)
    except live.ApprovalError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"id": item.id, "status": item.status}


@router.post("/approvals/create")
def create_approvals_now(db: Session = Depends(get_db)) -> dict:
    from app.signals.generator import latest_session

    day = latest_session(db)
    if day is None:
        raise HTTPException(status_code=409, detail="No signals yet")
    if load_live_settings(db).mode != "approve":
        raise HTTPException(status_code=409, detail="Switch trading mode to approve first")
    return {"as_of": day.isoformat(), "created": live.create_entry_approvals(db, day)}


@router.get("/live/orders")
def live_orders(limit: int = Query(default=100, le=500), db: Session = Depends(get_db)) -> dict:
    orders = list(db.scalars(select(LiveOrder).order_by(LiveOrder.id.desc()).limit(limit)))
    items = []
    for order in orders:
        instrument_id = None
        if order.approval_id:
            approval = db.get(ApprovalItem, order.approval_id)
            instrument_id = approval.instrument_id if approval else None
        if instrument_id is None and order.position_id:
            position = db.get(Position, order.position_id)
            instrument_id = position.instrument_id if position else None
        instrument = db.get(Instrument, instrument_id) if instrument_id else None
        items.append(_order_dict(order, instrument.tradingsymbol if instrument else "?"))
    return {"items": items}


@router.get("/live/positions")
def live_positions(db: Session = Depends(get_db)) -> dict:
    rows = db.execute(
        select(Position, Instrument)
        .join(Instrument, Instrument.id == Position.instrument_id)
        .where(Position.book == live.BOOK)
        .order_by(Position.status.desc(), Position.opened_at.desc())
        .limit(200)
    ).all()
    return {"items": [_position_dict(p, i) for p, i in rows]}


@router.post("/live/sync")
def live_sync(db: Session = Depends(get_db)) -> dict:
    kite = optional_kite(db)
    if kite is None:
        raise HTTPException(status_code=409, detail="Kite is not connected")
    result = live.sync_live(db, kite)
    return {"summary": result.summary(), "notes": result.notes}
