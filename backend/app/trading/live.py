import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any, Protocol

from kiteconnect.exceptions import KiteException
from sqlalchemy import false, select
from sqlalchemy.orm import Session

from app.core.calendar import cached_holidays, is_trading_day, next_trading_day
from app.core.clock import IST, is_market_hours, now_ist, to_utc_naive, utc_now
from app.models import (
    ApprovalItem,
    DailyCandle,
    IndicatorDaily,
    Instrument,
    LiveOrder,
    PaperOrder,
    Position,
    Signal,
    Trade,
)
from app.signals.params import load_active_params
from app.trading.live_settings import load_live_settings
from app.trading.paper import sessions_held
from app.trading.risk import buy_fee, get_limits, sell_fee

BOOK = "live"
TAG = "stkanalyzer"
EXPIRY_TIME = time(9, 30)
OPEN_ORDER_STATES = ("placed", "open")
GTT_TERMINAL = {"cancelled", "deleted", "expired", "disabled", "rejected"}


class TradingClient(Protocol):
    def ltp(self, instruments: list[str]) -> dict[str, dict[str, Any]]: ...
    def place_order(self, **payload) -> str: ...
    def cancel_order(self, variety: str, order_id: str): ...
    def orders(self) -> list[dict[str, Any]]: ...
    def margins(self, segment: str = "equity") -> dict[str, Any]: ...
    def place_gtt(self, **payload) -> dict[str, Any]: ...
    def modify_gtt(self, trigger_id: int, **payload) -> dict[str, Any]: ...
    def get_gtt(self, trigger_id: int) -> dict[str, Any]: ...
    def delete_gtt(self, trigger_id: int) -> dict[str, Any]: ...


class ApprovalError(RuntimeError):
    pass


@dataclass
class SyncResult:
    filled: int = 0
    failed: int = 0
    protected: int = 0
    closed: int = 0
    trailed: int = 0
    exit_requests: int = 0
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"filled={self.filled} failed={self.failed} gtt={self.protected} closed={self.closed} "
            f"trailed={self.trailed} exit_requests={self.exit_requests}"
        )


def _f(value) -> float:
    return float(value) if value is not None else 0.0


def tick_round(price: float, tick: float | None, up: bool) -> float:
    tick = tick or 0.05
    steps = price / tick
    steps = math.ceil(steps - 1e-9) if up else math.floor(steps + 1e-9)
    return round(steps * tick, 2)


def next_expiry(db: Session, now: datetime | None = None) -> datetime:
    now = (now or now_ist()).astimezone(IST)
    holidays = cached_holidays(db)
    day = now.date()
    if not (is_trading_day(day, holidays) and now.time() < EXPIRY_TIME):
        day = next_trading_day(day, holidays)
    return to_utc_naive(datetime.combine(day, EXPIRY_TIME, IST))


def _log(
    db: Session, kind: str, payload: dict, approval_id: int | None, position_id: int | None, dry_run: bool
) -> LiveOrder:
    order = LiveOrder(
        approval_id=approval_id,
        position_id=position_id,
        kind=kind,
        status="pending",
        dry_run=dry_run,
        payload_json=json.dumps(payload, default=str),
        updated_at=utc_now(),
    )
    db.add(order)
    db.flush()
    return order


def create_entry_approvals(db: Session, day: date, now: datetime | None = None) -> int:
    settings = load_live_settings(db)
    if settings.mode != "approve" or get_limits(db).kill_switch:
        return 0
    existing = db.scalar(
        select(ApprovalItem.id)
        .join(Signal, Signal.id == ApprovalItem.signal_id)
        .where(ApprovalItem.kind == "entry", Signal.as_of_date == day)
        .limit(1)
    )
    if existing:
        return 0
    paper_capital = float(get_limits(db).capital) or 1.0
    expires = next_expiry(db, now)
    rows = db.execute(
        select(PaperOrder, Instrument)
        .join(Instrument, Instrument.id == PaperOrder.instrument_id)
        .where(PaperOrder.as_of_date == day, PaperOrder.side == "BUY", PaperOrder.status == "pending")
        .order_by(PaperOrder.id)
    ).all()
    created = 0
    for order, instrument in rows:
        limit = tick_round(
            _f(order.limit_price) * (1 + settings.entry_buffer_pct / 100), _f(instrument.tick_size), up=True
        )
        qty = math.floor(min(order.qty * settings.live_capital / paper_capital, settings.max_order_value / limit))
        if qty < 1:
            continue
        db.add(
            ApprovalItem(
                signal_id=order.signal_id,
                instrument_id=order.instrument_id,
                side="BUY",
                kind="entry",
                qty=qty,
                limit_price=limit,
                stop_loss=order.stop_loss,
                target=order.target,
                risk_amount=round(qty * (limit - _f(order.stop_loss)), 2),
                status="pending",
                expires_at=expires,
                reason=order.reason,
            )
        )
        created += 1
    db.commit()
    return created


def create_exit_approval(
    db: Session, position: Position, reason: str, reference_price: float, now: datetime | None = None
) -> bool:
    exists = db.scalar(
        select(ApprovalItem.id).where(
            ApprovalItem.position_id == position.id, ApprovalItem.kind == "exit", ApprovalItem.status == "pending"
        )
    )
    if exists:
        return False
    db.add(
        ApprovalItem(
            instrument_id=position.instrument_id,
            side="SELL",
            kind="exit",
            position_id=position.id,
            qty=position.qty,
            limit_price=round(reference_price, 2),
            stop_loss=position.stop_loss,
            target=position.target,
            status="pending",
            expires_at=next_expiry(db, now),
            reason=reason,
        )
    )
    return True


def expire_stale(db: Session, now: datetime | None = None) -> int:
    now = now or utc_now()
    count = 0
    for item in db.scalars(
        select(ApprovalItem).where(ApprovalItem.status == "pending", ApprovalItem.expires_at <= now)
    ):
        item.status = "expired"
        item.decided_at = now
        count += 1
    db.commit()
    return count


def _ltp(kite: TradingClient, instrument: Instrument) -> float | None:
    key = f"{instrument.exchange}:{instrument.tradingsymbol}"
    quote = kite.ltp([key]).get(key) or {}
    return float(quote["last_price"]) if quote.get("last_price") else None


def _available_cash(kite: TradingClient) -> float | None:
    margins = kite.margins("equity") or {}
    available = margins.get("available") or {}
    for key in ("live_balance", "cash"):
        if available.get(key) is not None:
            return float(available[key])
    return None


def _order_payload(instrument: Instrument, side: str, qty: int, price: float, market_open: bool) -> dict:
    return {
        "variety": "regular" if market_open else "amo",
        "exchange": instrument.exchange,
        "tradingsymbol": instrument.tradingsymbol,
        "transaction_type": side,
        "quantity": qty,
        "product": "CNC",
        "order_type": "LIMIT",
        "price": price,
        "validity": "DAY",
        "tag": TAG,
    }


def _active_gtt(db: Session, position_id: int) -> LiveOrder | None:
    return db.scalar(
        select(LiveOrder)
        .where(LiveOrder.position_id == position_id, LiveOrder.kind == "gtt", LiveOrder.status == "active")
        .order_by(LiveOrder.id.desc())
    )


def approve(db: Session, item_id: int, kite: TradingClient | None, now: datetime | None = None) -> ApprovalItem:
    settings = load_live_settings(db)
    now_utc = utc_now()
    item = db.get(ApprovalItem, item_id)
    if item is None:
        raise ApprovalError("Approval not found")
    if settings.mode != "approve":
        raise ApprovalError("Trading mode is paper. Switch to approve mode first")
    if get_limits(db).kill_switch:
        raise ApprovalError("Kill switch is on")
    if item.status != "pending":
        raise ApprovalError(f"Approval is already {item.status}")
    if item.expires_at <= now_utc:
        item.status = "expired"
        item.decided_at = now_utc
        db.commit()
        raise ApprovalError("Approval expired")
    if kite is None and not settings.dry_run:
        raise ApprovalError("Kite is not connected. Log in first")

    instrument = db.get(Instrument, item.instrument_id)
    market_open = is_market_hours(now)
    ltp = _ltp(kite, instrument) if kite is not None else None
    position = db.get(Position, item.position_id) if item.position_id else None

    if item.kind == "exit":
        if position is None or position.status != "open" or position.book != BOOK:
            raise ApprovalError("Live position is not open")
        reference = ltp or _f(item.limit_price)
        price = tick_round(reference * (0.995 if market_open else 0.98), _f(instrument.tick_size), up=False)
    else:
        price = _f(item.limit_price)

    problems: list[str] = []
    if item.kind == "entry":
        if ltp is not None and ltp > price * (1 + settings.max_price_drift_pct / 100):
            problems.append(
                f"Price moved to {ltp:.2f}, more than {settings.max_price_drift_pct}% above the {price:.2f} limit"
            )
        value = price * item.qty
        if value > settings.max_order_value * 1.0001:
            problems.append(f"Order value {value:,.0f} exceeds the {settings.max_order_value:,.0f} cap")
        cash = _available_cash(kite) if kite is not None else None
        if cash is not None and cash < value * 1.003:
            problems.append(f"Not enough funds: {cash:,.0f} available, {value:,.0f} needed")
    if problems and not settings.dry_run:
        raise ApprovalError("; ".join(problems))

    payload = _order_payload(instrument, item.side, item.qty, price, market_open)
    record = _log(db, item.kind, payload, item.id, item.position_id, settings.dry_run)
    item.decided_at = now_utc
    if settings.dry_run:
        record.status = "dry_run"
        record.status_message = (
            "Dry run: nothing was sent to Kite"
            + (". Would be refused live: " + "; ".join(problems) if problems else "")
        )[:500]
        item.status = "dry_run"
        db.commit()
        return item

    try:
        if item.kind == "exit" and position is not None:
            gtt = _active_gtt(db, position.id)
            if gtt is not None and gtt.gtt_id:
                kite.delete_gtt(int(gtt.gtt_id))
                gtt.status = "deleted"
                gtt.updated_at = now_utc
        order_id = kite.place_order(**payload)
    except KiteException as exc:
        record.status = "failed"
        record.status_message = str(exc)[:500]
        item.status = "failed"
        db.commit()
        raise ApprovalError(f"Kite rejected the order: {exc}") from exc
    record.kite_order_id = str(order_id)
    record.status = "placed"
    record.response_json = json.dumps({"order_id": order_id})
    item.status = "placed"
    db.commit()
    return item


def reject(db: Session, item_id: int) -> ApprovalItem:
    item = db.get(ApprovalItem, item_id)
    if item is None or item.status != "pending":
        raise ApprovalError("Pending approval not found")
    item.status = "rejected"
    item.decided_at = utc_now()
    db.commit()
    return item


def _record_trade(
    db: Session, position: Position, side: str, qty: int, price: float, when: datetime, ref: str
) -> float:
    value = qty * price
    fees = round(buy_fee(value) if side == "BUY" else sell_fee(value), 2)
    db.add(
        Trade(
            book=BOOK,
            instrument_id=position.instrument_id,
            position_id=position.id,
            side=side,
            qty=qty,
            price=price,
            fees=fees,
            executed_at=when,
            order_ref=ref,
        )
    )
    return fees


def place_protection(
    db: Session, kite: TradingClient, position: Position, instrument: Instrument, ltp: float | None
) -> LiveOrder:
    tick = _f(instrument.tick_size)
    stop = tick_round(_f(position.stop_loss), tick, up=False)
    target = tick_round(_f(position.target), tick, up=True)
    leg = {
        "exchange": instrument.exchange,
        "tradingsymbol": instrument.tradingsymbol,
        "transaction_type": "SELL",
        "quantity": position.qty,
        "order_type": "LIMIT",
        "product": "CNC",
    }
    payload = {
        "trigger_type": "two-leg",
        "tradingsymbol": instrument.tradingsymbol,
        "exchange": instrument.exchange,
        "trigger_values": [stop, target],
        "last_price": ltp or _f(position.avg_price),
        "orders": [{**leg, "price": tick_round(stop * 0.99, tick, up=False)}, {**leg, "price": target}],
    }
    record = _log(db, "gtt", payload, None, position.id, False)
    try:
        response = kite.place_gtt(**payload)
    except KiteException as exc:
        record.status = "failed"
        record.status_message = f"GTT failed, position is unprotected: {exc}"[:500]
        return record
    record.gtt_id = str(response.get("trigger_id"))
    record.status = "active"
    record.response_json = json.dumps(response, default=str)
    return record


def _modify_protection(
    db: Session, kite: TradingClient, position: Position, instrument: Instrument, new_stop: float
) -> bool:
    gtt = _active_gtt(db, position.id)
    if gtt is None or not gtt.gtt_id:
        return False
    payload = json.loads(gtt.payload_json)
    tick = _f(instrument.tick_size)
    stop = tick_round(new_stop, tick, up=False)
    payload["trigger_values"] = [stop, payload["trigger_values"][1]]
    payload["orders"][0]["price"] = tick_round(stop * 0.99, tick, up=False)
    payload["last_price"] = _f(position.last_price) or _f(position.avg_price)
    try:
        kite.modify_gtt(int(gtt.gtt_id), **payload)
    except KiteException as exc:
        gtt.status_message = f"trail update failed: {exc}"[:500]
        return False
    gtt.payload_json = json.dumps(payload, default=str)
    gtt.updated_at = utc_now()
    return True


def _close_live(db: Session, position: Position, price: float, reason: str, when: datetime, ref: str) -> None:
    fees = _record_trade(db, position, "SELL", position.qty, price, when, ref)
    entry_fees = round(buy_fee(_f(position.avg_price) * position.qty), 2)
    position.status = "closed"
    position.closed_at = when
    position.exit_price = price
    position.exit_reason = reason
    position.last_price = price
    position.last_price_at = when
    position.realized_pnl = round((price - _f(position.avg_price)) * position.qty - fees - entry_fees, 2)


def sync_live(db: Session, kite: TradingClient, now: datetime | None = None) -> SyncResult:
    when = utc_now()
    result = SyncResult()
    pending = list(
        db.scalars(
            select(LiveOrder).where(
                LiveOrder.dry_run == false(),
                LiveOrder.kind.in_(("entry", "exit")),
                LiveOrder.status.in_(OPEN_ORDER_STATES),
            )
        )
    )
    gtts = list(db.scalars(select(LiveOrder).where(LiveOrder.kind == "gtt", LiveOrder.status == "active")))
    if not pending and not gtts:
        return result
    book = {str(o.get("order_id")): o for o in kite.orders()}

    for record in pending:
        order = book.get(str(record.kite_order_id))
        if order is None:
            continue
        status = str(order.get("status", "")).upper()
        filled = int(order.get("filled_quantity") or 0)
        average = float(order.get("average_price") or 0)
        record.status_message = (order.get("status_message") or status)[:500]
        record.filled_qty = filled
        record.average_price = average or None
        record.updated_at = when
        done = status == "COMPLETE" or (status in ("CANCELLED", "REJECTED") and filled > 0)
        if not done:
            if status in ("CANCELLED", "REJECTED"):
                record.status = status.lower()
                result.failed += 1
                approval = db.get(ApprovalItem, record.approval_id) if record.approval_id else None
                if approval is not None:
                    approval.status = status.lower()
            else:
                record.status = "open"
            continue
        record.status = "complete" if status == "COMPLETE" else "partial"
        approval = db.get(ApprovalItem, record.approval_id) if record.approval_id else None
        if approval is not None:
            approval.status = "filled"
        instrument = db.get(Instrument, approval.instrument_id if approval else None) if approval else None
        if record.kind == "entry" and approval is not None and instrument is not None:
            signal = db.get(Signal, approval.signal_id) if approval.signal_id else None
            reference = (
                _f(signal.entry_price) if signal is not None and signal.entry_price else _f(approval.limit_price)
            )
            stop_distance = reference - _f(approval.stop_loss)
            target_distance = _f(approval.target) - reference
            position = Position(
                book=BOOK,
                instrument_id=approval.instrument_id,
                signal_id=approval.signal_id,
                qty=filled,
                avg_price=average,
                stop_loss=round(average - stop_distance, 2),
                target=round(average + target_distance, 2),
                initial_stop=round(average - stop_distance, 2),
                highest_close=average,
                last_price=average,
                last_price_at=when,
                status="open",
                opened_at=when,
            )
            db.add(position)
            db.flush()
            record.position_id = position.id
            _record_trade(db, position, "BUY", filled, average, when, f"kite-{record.kite_order_id}")
            protection = place_protection(db, kite, position, instrument, average)
            result.protected += protection.status == "active"
            if protection.status != "active":
                result.notes.append(protection.status_message or "GTT failed")
            result.filled += 1
        elif record.kind == "exit" and record.position_id:
            position = db.get(Position, record.position_id)
            if position is not None and position.status == "open":
                reason = approval.reason if approval is not None and approval.reason else "exit"
                _close_live(db, position, average, reason[:32], when, f"kite-{record.kite_order_id}")
                result.closed += 1

    for gtt in gtts:
        try:
            data = kite.get_gtt(int(gtt.gtt_id))
        except KiteException as exc:
            gtt.status_message = str(exc)[:500]
            continue
        status = str(data.get("status", "")).lower()
        if status == "triggered":
            legs = data.get("orders") or []
            leg_index = next((i for i, leg in enumerate(legs) if leg.get("result")), 0)
            leg = legs[leg_index] if legs else {}
            order_id = str(((leg.get("result") or {}).get("order_result") or {}).get("order_id", ""))
            executed = book.get(order_id, {})
            price = float(executed.get("average_price") or leg.get("price") or 0)
            position = db.get(Position, gtt.position_id) if gtt.position_id else None
            gtt.status = "triggered"
            gtt.updated_at = when
            if position is not None and position.status == "open" and price:
                _close_live(db, position, price, "stop" if leg_index == 0 else "target", when, f"gtt-{gtt.gtt_id}")
                result.closed += 1
        elif status in GTT_TERMINAL:
            gtt.status = status
            gtt.updated_at = when
            result.notes.append(f"GTT {gtt.gtt_id} {status}: position {gtt.position_id} is unprotected")
    db.commit()
    return result


def live_end_of_day(db: Session, kite: TradingClient | None, day: date) -> SyncResult:
    result = SyncResult()
    params, _ = load_active_params(db)
    positions = list(db.scalars(select(Position).where(Position.book == BOOK, Position.status == "open")))
    if not positions:
        return result
    ids = [p.instrument_id for p in positions]
    candles = {
        c.instrument_id: c
        for c in db.scalars(
            select(DailyCandle).where(DailyCandle.trade_date == day, DailyCandle.instrument_id.in_(ids))
        )
    }
    atrs = {
        i.instrument_id: i.atr14
        for i in db.scalars(
            select(IndicatorDaily).where(IndicatorDaily.trade_date == day, IndicatorDaily.instrument_id.in_(ids))
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
        close = float(candle.close)
        position.last_price = close
        position.last_price_at = utc_now()
        position.highest_close = max(_f(position.highest_close), close)
        initial_risk = _f(position.avg_price) - _f(position.initial_stop)
        new_stop = _f(position.stop_loss)
        if initial_risk > 0 and close >= _f(position.avg_price) + initial_risk:
            new_stop = max(new_stop, _f(position.avg_price))
        atr = atrs.get(position.instrument_id)
        if params.trail_atr and atr is not None:
            new_stop = max(new_stop, _f(position.highest_close) - params.trail_atr * float(atr))
        if new_stop > _f(position.stop_loss) + 0.01:
            instrument = db.get(Instrument, position.instrument_id)
            if kite is None or _modify_protection(db, kite, position, instrument, new_stop):
                position.stop_loss = round(new_stop, 2)
                result.trailed += 1
        sessions = sessions_held(db, position.opened_at.date(), day) if position.opened_at else 0
        reason = None
        if sessions >= params.max_hold_days:
            reason = "time"
        elif position.instrument_id in sells:
            reason = "signal"
        if reason and create_exit_approval(db, position, reason, close):
            result.exit_requests += 1
    db.commit()
    return result


def kill_live(db: Session, kite: TradingClient | None) -> dict:
    cancelled_approvals = 0
    for item in db.scalars(select(ApprovalItem).where(ApprovalItem.status == "pending")):
        item.status = "cancelled"
        item.decided_at = utc_now()
        cancelled_approvals += 1
    cancelled_orders = 0
    errors = []
    for record in db.scalars(
        select(LiveOrder).where(
            LiveOrder.kind == "entry", LiveOrder.dry_run == false(), LiveOrder.status.in_(OPEN_ORDER_STATES)
        )
    ):
        if kite is None:
            errors.append(f"order {record.kite_order_id} left open: Kite not connected")
            continue
        try:
            kite.cancel_order(json.loads(record.payload_json).get("variety", "regular"), record.kite_order_id)
            record.status = "cancel_requested"
            cancelled_orders += 1
        except KiteException as exc:
            errors.append(f"order {record.kite_order_id}: {exc}")
    db.commit()
    return {"cancelled_approvals": cancelled_approvals, "cancelled_orders": cancelled_orders, "errors": errors}
