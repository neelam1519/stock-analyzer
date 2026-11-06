import json
from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.analysis.indicators import compute_indicators, update_indicators
from app.analysis.regime import classify, market_regime
from app.core.clock import IST
from app.core.db import get_db
from app.ingest.candles import DAILY, ingest_candles
from app.ingest.universe import sync_instruments
from app.main import create_app
from app.models import IndicatorDaily, ResearchReport, Signal
from app.signals.generator import generate_signals
from app.signals.params import save_active_params
from app.signals.research import research_top_picks
from app.signals.scoring import StrategyParams, score_stock
from tests.fakes import FakeKite, instrument_rows
from tests.test_ingest import UNIVERSE

STRONG = {
    "close": 110,
    "ema20": 105,
    "ema50": 100,
    "ema200": 90,
    "rsi14": 62,
    "macd": 1.2,
    "macd_signal": 0.8,
    "adx14": 28,
    "volume_ratio20": 1.6,
    "high52w_distance_pct": -3,
    "relative_strength_nifty": 12,
    "atr14": 2.5,
}
WEAK = {
    "close": 80,
    "ema20": 85,
    "ema50": 90,
    "ema200": 95,
    "rsi14": 35,
    "macd": -1.0,
    "macd_signal": -0.5,
    "adx14": 30,
    "volume_ratio20": 0.8,
    "high52w_distance_pct": -35,
    "relative_strength_nifty": -10,
    "atr14": 2.0,
}


def frame(values, volume=1000.0):
    idx = pd.date_range("2024-01-01", periods=len(values), freq="B").date
    close = pd.Series(values, index=idx, dtype=float)
    return pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": volume}, index=idx
    )


def test_indicators_match_known_properties():
    flat = compute_indicators(frame([100.0] * 260))
    last = flat.iloc[-1]
    assert last["ema20"] == pytest.approx(100) and last["ema200"] == pytest.approx(100)
    assert last["atr14"] == pytest.approx(2.0)
    assert last["macd"] == pytest.approx(0)
    assert last["high52w_distance_pct"] == pytest.approx(100 / 101 * 100 - 100)

    rising = compute_indicators(frame(np.arange(100, 360, dtype=float)))
    assert rising["rsi14"].iloc[-1] == pytest.approx(100)
    assert rising["adx14"].iloc[-1] > 50
    assert pd.isna(rising["ema200"].iloc[198]) and not pd.isna(rising["ema200"].iloc[199])

    alternating = compute_indicators(frame([100.0, 102.0] * 60))
    assert alternating["rsi14"].iloc[-1] == pytest.approx(50, abs=5)


def test_relative_strength_vs_benchmark():
    stock = frame(np.linspace(100, 130, 120))
    bench = frame(np.linspace(100, 110, 120))["close"]
    rs = compute_indicators(stock, bench)["relative_strength_nifty"].iloc[-1]
    assert rs > 0


def test_regime_classification():
    assert classify(110, 105, 100, 14) == "bull"
    assert classify(90, 95, 100, 14) == "bear"
    assert classify(102, 98, 100, 14) == "neutral"
    assert classify(110, 105, 100, 25) == "volatile"


def test_score_stock_buy_sell_and_vetoes():
    buy = score_stock(STRONG, "bull", 0.4, 3, 50)
    assert buy.action == "BUY" and buy.stop == 105.0 and buy.target == 120.0
    assert "Uptrend" in buy.rationale

    assert score_stock(WEAK, "bull").action == "SELL"
    assert score_stock(STRONG, "bull", -0.5, 2, 50).action == "HOLD"
    assert score_stock(STRONG, "bull", None, 0, 1.0).action == "HOLD"
    assert score_stock({**STRONG, "rsi14": 80}, "bull").action == "HOLD"
    assert score_stock(STRONG, "bear").total < score_stock(STRONG, "bull").total


def seeded(db, monkeypatch):
    monkeypatch.setenv("DAILY_HISTORY_DAYS", "500")
    from app.core import config

    config.get_settings.cache_clear()
    kite = FakeKite(instrument_rows())
    sync_instruments(db, kite, UNIVERSE)
    reliance_token = 1
    closes = {}
    for i, day in enumerate(pd.bdate_range("2025-06-01", "2026-11-05").date):
        closes[(reliance_token, day)] = 100 + i * 0.5
        closes[(256265, day)] = 20000 + i * 5
    kite.closes = closes
    ingest_candles(db, kite, DAILY, now=datetime(2026, 11, 5, 18, 0, tzinfo=IST))


def test_pipeline_generates_signals_and_is_incremental(db, settings, monkeypatch):
    seeded(db, monkeypatch)
    save_active_params(db, StrategyParams(), "test")
    first = update_indicators(db)
    assert first.inserted == db.scalar(select(func.count()).select_from(IndicatorDaily))
    assert update_indicators(db).inserted == 0

    regime = market_regime(db)
    assert regime.name == "bull" and regime.as_of == date(2026, 11, 5)

    result, _ = generate_signals(db)
    assert result.scored == 1
    signal = db.scalar(select(Signal))
    assert signal.as_of_date == date(2026, 11, 5) and signal.action in {"BUY", "HOLD"}
    generate_signals(db)
    assert db.scalar(select(func.count()).select_from(Signal)) == 1


class FakeResearchLLM:
    model = "gemini/gemini-3.5-flash-lite"

    def complete_json(self, system, user, purpose):
        context = json.loads(user)
        return {
            "summary": f"{context['symbol']} trend intact.",
            "bull_case": ["Above all EMAs"],
            "bear_case": ["Extended"],
            "key_risks": ["Results next week"],
            "verdict": "WAIT",
            "conviction": 1.4,
        }


def test_research_reports_and_api(db, settings, monkeypatch):
    seeded(db, monkeypatch)
    save_active_params(db, StrategyParams(), "test")
    update_indicators(db)
    generate_signals(db)
    signal = db.scalar(select(Signal))
    signal.action = "BUY"
    db.commit()

    result = research_top_picks(db, FakeResearchLLM(), signal.as_of_date)
    assert result.reports == 1 and result.shortlisted == ["RELIANCE"]
    report = db.scalar(select(ResearchReport))
    assert report.verdict == "wait" and float(report.score) == 100.0

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    headers = {"X-API-Key": "test-key"}
    listing = client.get("/api/signals?action=BUY", headers=headers).json()
    assert listing["items"][0]["symbol"] == "RELIANCE"
    assert listing["items"][0]["research_verdict"] == "wait"
    analysis = client.get("/api/stocks/RELIANCE/analysis", headers=headers).json()
    assert analysis["research"]["key_risks"] == ["Results next week"]
    assert analysis["indicators"]["ema20"] is not None
    assert client.get("/api/market/regime", headers=headers).json()["name"] == "bull"
    candles = client.get("/api/stocks/RELIANCE/candles?interval=day&limit=30", headers=headers).json()
    assert len(candles["overlays"]["ema20"]) == 30
