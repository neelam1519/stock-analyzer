from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import create_app
from app.models import PortfolioSnapshot, Trade
from app.trading.summary import kite_figures, paper_figures


def test_kite_figures_combine_holdings_and_positions():
    margins = {
        "net": 12000,
        "available": {"live_balance": 10000, "opening_balance": 11000},
        "utilised": {"debits": 1000},
    }
    holdings = [
        {"quantity": 10, "t1_quantity": 0, "average_price": 100, "last_price": 110, "close_price": 105},
        {"quantity": 0, "t1_quantity": 5, "average_price": 200, "last_price": 190, "close_price": 200},
    ]
    positions = {"day": [{"m2m": 75.0}], "net": [{"quantity": 3}, {"quantity": 0}]}
    figures = kite_figures(margins, holdings, positions)
    assert figures["available_cash"] == 10000 and figures["used_margin"] == 1000
    assert figures["holdings_value"] == pytest.approx(10 * 110 + 5 * 190)
    assert figures["holdings_pnl"] == pytest.approx(100 - 50)
    assert figures["today_pnl"] == pytest.approx(50 - 50 + 75)
    assert figures["positions_open"] == 1
    assert kite_figures({}, [], {})["today_pnl_pct"] is None


def test_paper_today_pnl_uses_previous_snapshot(db, settings):
    db.add(
        PortfolioSnapshot(
            book="paper",
            snapshot_date=date(2026, 11, 4),
            cash=990_000,
            invested=0,
            market_value=0,
            realized_pnl=0,
            unrealized_pnl=0,
        )
    )
    db.commit()
    figures = paper_figures(db, date(2026, 11, 5))
    assert figures["equity"] == 1_000_000 and figures["today_pnl"] == pytest.approx(10_000)
    assert figures["today_pnl_pct"] == pytest.approx(1.01, abs=0.01)


def test_summary_endpoint_without_kite(db, settings):
    db.add(Trade(book="paper", instrument_id=1, side="BUY", qty=1, price=100, fees=0, executed_at=date(2026, 11, 5)))
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    data = TestClient(app).get("/api/account/summary", headers={"X-API-Key": "test-key"}).json()
    assert data["kite"] == {"connected": False}
    assert data["mode"]["mode"] == "paper" and data["mode"]["dry_run"] is True
    assert set(data["market"]) == {"open", "trading_day", "next_session"}
