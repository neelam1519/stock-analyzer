import json
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from kiteconnect.exceptions import InputException
from sqlalchemy import select

from app.core.clock import IST, to_utc_naive, utc_now
from app.core.db import get_db
from app.main import create_app
from app.models import ApprovalItem, DailyCandle, IndicatorDaily, LiveOrder, Position
from app.signals.scoring import DEFAULT_PARAMS
from app.trading import live, paper
from app.trading.live_settings import LiveSettings, save_live_settings
from app.trading.risk import get_limits
from tests.test_paper import DAY, NEXT, setup

AFTER_CLOSE = datetime(2026, 11, 5, 16, 0, tzinfo=IST)
MARKET = datetime(2026, 11, 6, 9, 20, tzinfo=IST)


class FakeTrading:
    def __init__(self, ltp=200.0, cash=500_000.0):
        self.price = ltp
        self.cash = cash
        self.calls: list[tuple] = []
        self.book: dict[str, dict] = {}
        self.gtts: dict[int, dict] = {}

    def ltp(self, instruments):
        return {k: {"last_price": self.price} for k in instruments}

    def margins(self, segment="equity"):
        return {"available": {"live_balance": self.cash}}

    def place_order(self, **payload):
        self.calls.append(("place_order", payload))
        order_id = f"OID{len(self.book) + 1}"
        self.book[order_id] = {"order_id": order_id, "status": "OPEN", "filled_quantity": 0, "average_price": 0}
        return order_id

    def cancel_order(self, variety, order_id):
        self.calls.append(("cancel_order", variety, order_id))

    def orders(self):
        return list(self.book.values())

    def place_gtt(self, **payload):
        self.calls.append(("place_gtt", payload))
        trigger_id = 900 + len(self.gtts)
        self.gtts[trigger_id] = {"status": "active", "orders": payload["orders"]}
        return {"trigger_id": trigger_id}

    def modify_gtt(self, trigger_id, **payload):
        self.calls.append(("modify_gtt", trigger_id, payload))
        return {"trigger_id": trigger_id}

    def get_gtt(self, trigger_id):
        return self.gtts[trigger_id]

    def delete_gtt(self, trigger_id):
        self.calls.append(("delete_gtt", trigger_id))
        self.gtts[trigger_id]["status"] = "deleted"

    def complete(self, order_id, qty, price):
        self.book[order_id].update(status="COMPLETE", filled_quantity=qty, average_price=price)


def approve_mode(db, dry_run=True, **overrides):
    save_live_settings(db, LiveSettings(mode="approve", dry_run=dry_run, **overrides))


def planned(db, monkeypatch, **settings):
    setup(db, monkeypatch)
    paper.plan_entries(db, DAY)
    approve_mode(db, **settings)
    return live.create_entry_approvals(db, DAY, AFTER_CLOSE)


def test_tick_round_and_expiry(db, settings):
    assert live.tick_round(100.01, 0.05, up=True) == 100.05
    assert live.tick_round(100.04, 0.05, up=False) == 100.0
    assert live.next_expiry(db, AFTER_CLOSE) == datetime(2026, 11, 6, 4, 0)


def test_approvals_scale_cap_and_are_idempotent(db, settings, monkeypatch):
    assert planned(db, monkeypatch) == 1
    item = db.scalar(select(ApprovalItem))
    assert item.limit_price == pytest.approx(201.0)
    assert item.qty == 100
    assert item.risk_amount == pytest.approx(100 * 11.0)
    assert live.create_entry_approvals(db, DAY, AFTER_CLOSE) == 0


def test_paper_mode_creates_no_approvals(db, settings, monkeypatch):
    setup(db, monkeypatch)
    paper.plan_entries(db, DAY)
    assert live.create_entry_approvals(db, DAY, AFTER_CLOSE) == 0


def test_dry_run_sends_nothing(db, settings, monkeypatch):
    planned(db, monkeypatch)
    kite = FakeTrading()
    item = live.approve(db, db.scalar(select(ApprovalItem.id)), kite, AFTER_CLOSE)
    record = db.scalar(select(LiveOrder))
    payload = json.loads(record.payload_json)
    assert item.status == "dry_run" and record.dry_run and record.status == "dry_run"
    assert payload == {
        "variety": "amo",
        "exchange": "NSE",
        "tradingsymbol": "RELIANCE",
        "transaction_type": "BUY",
        "quantity": 100,
        "product": "CNC",
        "order_type": "LIMIT",
        "price": 201.0,
        "validity": "DAY",
        "tag": "stkanalyzer",
    }
    assert kite.calls == []
    with pytest.raises(live.ApprovalError, match="already dry_run"):
        live.approve(db, item.id, kite, AFTER_CLOSE)


def test_live_guards(db, settings, monkeypatch):
    planned(db, monkeypatch, dry_run=False)
    item_id = db.scalar(select(ApprovalItem.id))
    with pytest.raises(live.ApprovalError, match="Price moved"):
        live.approve(db, item_id, FakeTrading(ltp=210.0), MARKET)
    with pytest.raises(live.ApprovalError, match="Not enough funds"):
        live.approve(db, item_id, FakeTrading(cash=1000), MARKET)
    with pytest.raises(live.ApprovalError, match="not connected"):
        live.approve(db, item_id, None, MARKET)
    limits = get_limits(db)
    limits.kill_switch = True
    db.commit()
    with pytest.raises(live.ApprovalError, match="Kill switch"):
        live.approve(db, item_id, FakeTrading(), MARKET)
    limits.kill_switch = False
    item = db.get(ApprovalItem, item_id)
    item.expires_at = to_utc_naive(MARKET - timedelta(minutes=1))
    db.commit()
    with pytest.raises(live.ApprovalError, match="expired"):
        live.approve(db, item_id, FakeTrading(), MARKET)


def test_live_entry_fill_gtt_trigger_and_close(db, settings, monkeypatch):
    planned(db, monkeypatch, dry_run=False)
    kite = FakeTrading()
    item = live.approve(db, db.scalar(select(ApprovalItem.id)), kite, MARKET)
    assert item.status == "placed" and kite.calls[0][1]["variety"] == "regular"

    assert live.sync_live(db, kite).filled == 0
    kite.complete("OID1", 100, 200.5)
    result = live.sync_live(db, kite)
    position = db.scalar(select(Position).where(Position.book == "live"))
    assert result.filled == 1 and result.protected == 1 and position.qty == 100
    gtt_call = next(c for c in kite.calls if c[0] == "place_gtt")[1]
    assert gtt_call["trigger_type"] == "two-leg" and gtt_call["trigger_values"] == [190.5, 220.5]
    assert gtt_call["orders"][0]["transaction_type"] == "SELL" and gtt_call["orders"][0]["product"] == "CNC"

    kite.book["SL1"] = {"order_id": "SL1", "status": "COMPLETE", "filled_quantity": 100, "average_price": 190.2}
    kite.gtts[900] = {
        "status": "triggered",
        "orders": [{"price": 188.55, "result": {"order_result": {"order_id": "SL1"}}}, {"price": 220.5}],
    }
    closed = live.sync_live(db, kite)
    db.refresh(position)
    assert closed.closed == 1 and position.status == "closed" and position.exit_reason == "stop"
    assert float(position.exit_price) == pytest.approx(190.2)


def test_exit_approval_deletes_gtt_and_sells(db, settings, monkeypatch):
    planned(db, monkeypatch, dry_run=False)
    kite = FakeTrading()
    live.approve(db, db.scalar(select(ApprovalItem.id)), kite, MARKET)
    kite.complete("OID1", 100, 200.0)
    live.sync_live(db, kite)
    position = db.scalar(select(Position).where(Position.book == "live"))
    assert live.create_exit_approval(db, position, "signal", 205.0, AFTER_CLOSE)
    db.commit()
    exit_item = db.scalar(select(ApprovalItem).where(ApprovalItem.kind == "exit"))
    kite.price = 205.0
    live.approve(db, exit_item.id, kite, MARKET)
    assert ("delete_gtt", 900) in kite.calls
    sell = [c for c in kite.calls if c[0] == "place_order"][-1][1]
    assert sell["transaction_type"] == "SELL" and sell["price"] == pytest.approx(203.95)
    kite.complete("OID2", 100, 204.0)
    live.sync_live(db, kite)
    db.refresh(position)
    assert position.status == "closed" and position.exit_reason == "signal"


def test_live_eod_trails_gtt_and_kill_cancels(db, settings, monkeypatch):
    planned(db, monkeypatch, dry_run=False)
    kite = FakeTrading()
    live.approve(db, db.scalar(select(ApprovalItem.id)), kite, MARKET)
    kite.complete("OID1", 100, 200.0)
    live.sync_live(db, kite)
    position = db.scalar(select(Position).where(Position.book == "live"))
    position.opened_at = datetime(2026, 11, 5, 4, 0)
    db.add(
        DailyCandle(
            instrument_id=position.instrument_id, trade_date=NEXT, open=201, high=215, low=200, close=214, volume=1
        )
    )
    db.add(IndicatorDaily(instrument_id=position.instrument_id, trade_date=NEXT, atr14=2.0))
    db.commit()
    result = live.live_end_of_day(db, kite, NEXT)
    assert result.trailed == 1 and any(c[0] == "modify_gtt" for c in kite.calls)
    assert float(position.stop_loss) == pytest.approx(214.0 - DEFAULT_PARAMS.trail_atr * 2.0)

    paper.plan_entries(db, date(2026, 11, 6))
    db.add(
        ApprovalItem(
            instrument_id=position.instrument_id,
            side="BUY",
            kind="entry",
            qty=1,
            limit_price=1,
            status="pending",
            expires_at=utc_now() + timedelta(hours=1),
        )
    )
    kite.book["OID9"] = {"order_id": "OID9", "status": "OPEN"}
    db.add(
        LiveOrder(
            kind="entry", status="placed", dry_run=False, kite_order_id="OID9", payload_json='{"variety": "regular"}'
        )
    )
    db.commit()
    killed = live.kill_live(db, kite)
    assert killed["cancelled_approvals"] == 1 and killed["cancelled_orders"] == 1
    assert ("cancel_order", "regular", "OID9") in kite.calls


def test_kite_rejection_is_recorded(db, settings, monkeypatch):
    planned(db, monkeypatch, dry_run=False)
    kite = FakeTrading()

    def reject(**payload):
        raise InputException("Static IP not registered")

    kite.place_order = reject
    with pytest.raises(live.ApprovalError, match="Static IP"):
        live.approve(db, db.scalar(select(ApprovalItem.id)), kite, MARKET)
    record = db.scalar(select(LiveOrder))
    assert record.status == "failed" and "Static IP" in record.status_message


def test_settings_api_requires_live_confirmation(db, settings):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    headers = {"X-API-Key": "test-key"}
    body = {
        "mode": "approve",
        "dry_run": False,
        "live_capital": 50000,
        "max_order_value": 10000,
        "entry_buffer_pct": 0.5,
        "max_price_drift_pct": 2,
    }
    assert client.put("/api/trading/settings", headers=headers, json=body).status_code == 409
    saved = client.put("/api/trading/settings", headers=headers, json={**body, "confirm": "LIVE"}).json()
    assert saved["dry_run"] is False and saved["mode"] == "approve"
    assert client.get("/api/approvals", headers=headers).json()["items"] == []


def test_dry_run_records_live_problems_as_warning(db, settings, monkeypatch):
    planned(db, monkeypatch)
    live.approve(db, db.scalar(select(ApprovalItem.id)), FakeTrading(cash=501), AFTER_CLOSE)
    record = db.scalar(select(LiveOrder))
    assert record.status == "dry_run" and "Would be refused live: Not enough funds" in record.status_message
