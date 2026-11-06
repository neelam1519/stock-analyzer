from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.analysis.indicators import update_indicators
from app.core.calendar import is_trading_day, next_trading_day, parse_holidays
from app.core.db import get_db
from app.main import create_app
from app.models import DailyCandle, Instrument, PaperOrder, PortfolioSnapshot, Position, Signal, Trade
from app.signals.scoring import DEFAULT_PARAMS
from app.trading import paper
from app.trading.risk import account, get_limits
from tests.test_signals import seeded

DAY = date(2026, 11, 5)
NEXT = date(2026, 11, 6)
WHEN = datetime(2026, 11, 5, 4, 0)


def setup(db, monkeypatch, entry=200.0, stop=190.0, target=220.0, regime="bull"):
    seeded(db, monkeypatch)
    update_indicators(db)
    reliance = db.scalar(select(Instrument).where(Instrument.tradingsymbol == "RELIANCE"))
    reliance.sector = "Energy"
    db.add(
        Signal(
            instrument_id=reliance.id,
            as_of_date=DAY,
            strategy=DEFAULT_PARAMS.name,
            action="BUY",
            score=90,
            regime=regime,
            entry_price=entry,
            stop_loss=stop,
            target=target,
            confidence=0.5,
            rationale="test",
        )
    )
    db.commit()
    return reliance


def add_candle(db, instrument_id, day, o, h, low, c):
    db.add(DailyCandle(instrument_id=instrument_id, trade_date=day, open=o, high=h, low=low, close=c, volume=1000))
    db.commit()


def test_holiday_calendar():
    holidays = set(
        map(date.fromisoformat, parse_holidays({"CM": [{"tradingDate": "06-Nov-2026"}, {"tradingDate": "bad"}]}))
    )
    assert holidays == {NEXT}
    assert not is_trading_day(NEXT, holidays) and not is_trading_day(date(2026, 11, 7), holidays)
    assert next_trading_day(DAY, holidays) == date(2026, 11, 9)


def test_plan_sizes_by_risk_and_is_idempotent(db, settings, monkeypatch):
    setup(db, monkeypatch)
    result = paper.plan_entries(db, DAY)
    order = db.scalar(select(PaperOrder))
    assert result.planned == 1 and order.status == "pending"
    assert order.qty == 1000
    assert paper.plan_entries(db, DAY).notes == ["entries already planned for this session"]


def test_kill_switch_and_regime_sizing(db, settings, monkeypatch):
    setup(db, monkeypatch, regime="neutral")
    limits = get_limits(db)
    limits.kill_switch = True
    db.commit()
    assert paper.plan_entries(db, DAY).rejected == 1
    db.query(PaperOrder).delete()
    limits.kill_switch = False
    db.commit()
    paper.plan_entries(db, DAY)
    assert db.scalar(select(PaperOrder)).qty == 750


def test_fill_then_target_and_cash_accounting(db, settings, monkeypatch):
    reliance = setup(db, monkeypatch)
    paper.plan_entries(db, DAY)
    fill = paper.fill_orders(db, {reliance.id: 201.0}, WHEN)
    position = db.scalar(select(Position))
    assert fill.filled == 1 and position.status == "open"
    assert float(position.avg_price) == pytest.approx(201.1, abs=0.01)
    assert float(position.stop_loss) == pytest.approx(191.1, abs=0.01)

    paper.monitor_positions(db, {reliance.id: 225.0}, WHEN)
    db.refresh(position)
    assert position.status == "closed" and position.exit_reason == "target"
    acct = account(db)
    assert acct.open_positions == 0
    assert acct.cash == pytest.approx(1_000_000 + float(position.realized_pnl), abs=0.05)
    assert db.scalar(select(Trade.side).where(Trade.side == "SELL")) == "SELL"


def test_gap_up_cancels_order(db, settings, monkeypatch):
    reliance = setup(db, monkeypatch)
    paper.plan_entries(db, DAY)
    result = paper.fill_orders(db, {reliance.id: 210.0}, WHEN)
    assert result.cancelled == 1 and db.scalar(select(Position)) is None


def test_end_of_day_fallback_fill_trailing_and_sell_exit(db, settings, monkeypatch):
    reliance = setup(db, monkeypatch)
    paper.plan_entries(db, DAY)
    add_candle(db, reliance.id, NEXT, 200.0, 216.0, 199.0, 215.0)
    result = paper.end_of_day(db, NEXT, datetime(2026, 11, 6, 10, 0))
    position = db.scalar(select(Position))
    assert result.filled == 1 and position.status == "open"
    assert float(position.stop_loss) >= float(position.avg_price)

    db.add(Signal(instrument_id=reliance.id, as_of_date=NEXT, strategy=DEFAULT_PARAMS.name, action="SELL", score=20))
    db.commit()
    paper.end_of_day(db, NEXT, datetime(2026, 11, 6, 10, 0))
    exit_order = db.scalar(select(PaperOrder).where(PaperOrder.side == "SELL"))
    assert exit_order.status == "pending" and exit_order.position_id == position.id

    paper.fill_orders(db, {reliance.id: 214.0}, datetime(2026, 11, 9, 4, 0))
    db.refresh(position)
    assert position.status == "closed" and position.exit_reason == "signal"


def test_eod_stop_with_gap_fills_at_open(db, settings, monkeypatch):
    reliance = setup(db, monkeypatch)
    paper.plan_entries(db, DAY)
    paper.fill_orders(db, {reliance.id: 200.0}, WHEN)
    add_candle(db, reliance.id, NEXT, 180.0, 182.0, 175.0, 178.0)
    paper.end_of_day(db, NEXT, datetime(2026, 11, 6, 10, 0))
    position = db.scalar(select(Position))
    assert position.exit_reason == "stop" and float(position.exit_price) == pytest.approx(180.0 * 0.9995, abs=0.01)


def test_daily_loss_limit_blocks_entries(db, settings, monkeypatch):
    setup(db, monkeypatch)
    db.add(
        PortfolioSnapshot(
            book="paper",
            snapshot_date=date(2026, 11, 4),
            cash=1_030_000,
            invested=0,
            market_value=0,
            realized_pnl=0,
            unrealized_pnl=0,
        )
    )
    db.commit()
    result = paper.plan_entries(db, DAY)
    order = db.scalar(select(PaperOrder))
    assert result.rejected == 1 and "daily loss limit" in order.reason


def test_portfolio_api_and_kill_switch(db, settings, monkeypatch):
    reliance = setup(db, monkeypatch)
    paper.plan_entries(db, DAY)
    paper.fill_orders(db, {reliance.id: 200.0}, WHEN)
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    headers = {"X-API-Key": "test-key"}
    data = client.get("/api/portfolio", headers=headers).json()
    assert data["positions"][0]["symbol"] == "RELIANCE" and data["equity"] < 1_000_000
    position_id = data["positions"][0]["id"]
    assert client.post(f"/api/portfolio/positions/{position_id}/close", headers=headers).status_code == 200
    assert client.get("/api/portfolio/history", headers=headers).json()["stats"]["trades"] == 1
    limits = client.put(
        "/api/risk/limits",
        headers=headers,
        json={
            "capital": 500000,
            "risk_per_trade_pct": 0.5,
            "max_position_pct": 10,
            "max_open_positions": 5,
            "daily_loss_limit_pct": 2,
            "weekly_loss_limit_pct": 5,
            "max_sector_pct": 30,
        },
    ).json()
    assert limits["capital"] == 500000
    assert client.post("/api/risk/kill-switch", headers=headers, json={"on": True}).json()["kill_switch"] is True
