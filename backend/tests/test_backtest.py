from dataclasses import replace
from datetime import date

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.analysis.indicators import compute_indicators, update_indicators
from app.backtest.data import build_market_data
from app.backtest.engine import PortfolioConfig, simulate
from app.backtest.service import NoMarketData, run_single, run_walk_forward
from app.backtest.vector import technical_score_frame
from app.backtest.walkforward import fold_windows, stitch
from app.core.db import get_db
from app.main import create_app
from app.models import BacktestTrade, Signal
from app.signals.generator import generate_signals
from app.signals.params import load_active_params, save_active_params
from app.signals.scoring import DEFAULT_PARAMS, StrategyParams, technical_score
from tests.test_signals import seeded


def uptrend(n: int, base: float = 100.0) -> np.ndarray:
    i = np.arange(1, n + 1)
    return base * 1.004**i * (1 + 0.012 * np.sin(i * 1.7))


NO_COST = PortfolioConfig(cost_pct=0, fixed_sell_cost=0, slippage_pct=0, cooldown_days=0)


def market(stock_closes, nifty_closes=None, volume=1e7, gap_day=None, gap_price=None):
    days = pd.bdate_range("2023-01-02", periods=len(stock_closes)).date
    nifty_closes = nifty_closes if nifty_closes is not None else np.linspace(10000, 13000, len(stock_closes))
    frames = []
    for symbol, closes in (("TREND", np.asarray(stock_closes, float)), ("NIFTY 50", np.asarray(nifty_closes, float))):
        df = pd.DataFrame(
            {"open": closes, "high": closes * 1.01, "low": closes * 0.99, "close": closes, "volume": volume}, index=days
        )
        if symbol == "TREND" and gap_day is not None:
            df.iloc[gap_day, df.columns.get_loc("open")] = gap_price
            df.iloc[gap_day, df.columns.get_loc("low")] = gap_price * 0.99
        ind = compute_indicators(df, None if symbol == "NIFTY 50" else pd.Series(nifty_closes, index=days))
        merged = df.join(ind)
        merged["symbol"] = symbol
        merged["trade_date"] = merged.index
        merged["is_stock"] = symbol != "NIFTY 50"
        frames.append(merged.reset_index(drop=True))
    return build_market_data(pd.concat(frames, ignore_index=True), {"TREND": "Tech"})


def test_vector_scores_equal_live_scorer():
    rng = np.random.default_rng(3)
    df = pd.DataFrame(
        {
            k: rng.uniform(lo, hi, 500)
            for k, lo, hi in [
                ("close", 80, 120),
                ("ema20", 80, 120),
                ("ema50", 80, 120),
                ("ema200", 80, 120),
                ("rsi14", 20, 90),
                ("macd", -2, 2),
                ("macd_signal", -2, 2),
                ("adx14", 5, 50),
                ("volume_ratio20", 0.3, 5),
                ("high52w_distance_pct", -40, 0),
                ("relative_strength_nifty", -30, 30),
            ]
        }
    ).mask(rng.random((500, 11)) < 0.1)
    expected = [technical_score({k: None if pd.isna(v) else v for k, v in r.items()})[0] for r in df.to_dict("records")]
    assert np.allclose(technical_score_frame(df).to_numpy(), expected)


def test_uptrend_enters_next_open_and_hits_target():
    closes = np.concatenate([np.full(230, 100.0), uptrend(120)])
    data = market(closes)
    result = simulate(data, StrategyParams(buy_threshold=60, max_hold_days=200, trail_atr=0), NO_COST)
    assert result.trades, "expected at least one trade"
    first = result.trades[0]
    signal_day = list(map(str, data.dates)).index(first.entry_date) - 1
    assert first.entry_price == pytest.approx(data.open[signal_day + 1, 0], abs=0.01)
    assert any(t.exit_reason == "target" and t.r_multiple == pytest.approx(2.0, abs=0.05) for t in result.trades)
    assert result.metrics["final_equity"] > 1_000_000


def test_gap_down_fills_at_open_below_stop():
    closes = np.concatenate([np.full(230, 100.0), uptrend(40), np.full(20, uptrend(40)[-1])])
    base = simulate(market(closes), StrategyParams(buy_threshold=60, trail_atr=0, max_hold_days=200), NO_COST)
    entry_idx = list(map(str, market(closes).dates)).index(base.trades[0].entry_date)
    gap = market(closes, gap_day=entry_idx + 2, gap_price=50.0)
    result = simulate(gap, StrategyParams(buy_threshold=60, trail_atr=0, max_hold_days=200), NO_COST)
    stopped = result.trades[0]
    assert stopped.exit_reason == "stop" and stopped.exit_price == pytest.approx(50.0) and stopped.r_multiple < -1


def test_costs_reduce_pnl_and_regime_gate_blocks_entries():
    closes = np.concatenate([np.full(230, 100.0), uptrend(120)])
    data = market(closes)
    params = StrategyParams(buy_threshold=60, max_hold_days=200, trail_atr=0)
    free = simulate(data, params, NO_COST).metrics["final_equity"]
    costly = simulate(data, params, PortfolioConfig()).metrics["final_equity"]
    assert costly < free
    bear_only = simulate(data, replace(params, entry_regimes=("bear",)), NO_COST)
    assert bear_only.trades == [] and bear_only.metrics["final_equity"] == pytest.approx(1_000_000)


def test_fold_windows_and_stitch_chain_returns():
    dates = np.array(pd.bdate_range("2022-09-01", "2025-03-31").date, dtype="datetime64[D]")
    windows = fold_windows(dates, date(2022, 9, 1), 24, 6)
    assert windows[0] == (date(2022, 9, 1), date(2024, 8, 31), date(2024, 9, 1), date(2025, 2, 28))
    assert windows[-1][2] == date(2025, 3, 1)

    from app.backtest.engine import SimulationResult

    a = SimulationResult(["d1", "d2"], [1_000_000, 1_100_000], [100.0, 110.0])
    b = SimulationResult(["d3", "d4"], [1_000_000, 1_100_000], [200.0, 220.0])
    stitched = stitch([a, b], 1_000_000)
    assert stitched.equity[-1] == pytest.approx(1_210_000)
    assert stitched.benchmark[-1] == pytest.approx(121.0)


def test_active_params_drive_live_signals_and_api(db, settings, monkeypatch):
    seeded(db, monkeypatch)
    update_indicators(db)
    assert load_active_params(db) == (DEFAULT_PARAMS, None)

    save_active_params(db, replace(StrategyParams(), buy_threshold=0, entry_regimes=("bear",)), "test")
    params, source = load_active_params(db)
    assert params.entry_regimes == ("bear",) and source == "test"
    generate_signals(db)
    signal = db.scalar(select(Signal))
    assert signal.action != "BUY"

    run = run_single(db, StrategyParams(buy_threshold=50), start="2025-01-01")
    assert run.kind == "single" and run.trades_count == db.scalar(select(func.count()).select_from(BacktestTrade))

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    headers = {"X-API-Key": "test-key"}
    listing = client.get("/api/backtests", headers=headers).json()["items"]
    assert listing[0]["id"] == run.id
    detail = client.get(f"/api/backtests/{run.id}", headers=headers).json()
    assert detail["equity"] and "cagr_pct" in detail["metrics"]
    applied = client.post(f"/api/backtests/{run.id}/apply", headers=headers).json()
    assert applied["active"]["buy_threshold"] == 50 and applied["source"].startswith(f"backtest #{run.id}")
    assert client.post("/api/strategy/params/reset", headers=headers).json()["source"] == "defaults"


def test_backtest_without_market_data_is_a_clear_error(db, settings):
    with pytest.raises(NoMarketData):
        run_single(db)
    with pytest.raises(NoMarketData):
        run_walk_forward(db)

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    response = TestClient(app).post("/api/backtests/run", headers={"X-API-Key": "test-key"})
    assert response.status_code == 409
    assert "No market data" in response.json()["detail"]
