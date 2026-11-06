from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select

from app.analysis.indicators import compute_indicators, update_indicators
from app.analysis.momentum import momentum_frames, percentile_frame, rank_frame, traded_value_frame
from app.backtest.data import build_market_data
from app.backtest.engine import momentum_mask
from app.backtest.walkforward import MOMENTUM_GRID, grid_for
from app.models import Signal
from app.signals.generator import generate_signals
from app.signals.scoring import DEFAULT_PARAMS, MOMENTUM, MomentumSnapshot, StrategyParams, momentum_decision
from tests.test_signals import seeded

DAYS = 330
DRIFTS = {"ALPHA": 0.0030, "BETA": 0.0018, "GAMMA": 0.0012, "DELTA": -0.0015, "THIN": 0.0035}


def closes(drift: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return 100 * np.exp(np.cumsum(drift + rng.normal(0, 0.004, DAYS)))


def universe():
    days = pd.bdate_range("2025-01-01", periods=DAYS).date
    close = pd.DataFrame({s: closes(d, i) for i, (s, d) in enumerate(DRIFTS.items())}, index=days)
    volume = pd.DataFrame(1e6, index=days, columns=close.columns)
    volume["THIN"] = 10.0
    return close, volume


def test_ranks_strongest_risk_adjusted_trend_first_and_filters_ineligible():
    close, volume = universe()
    frames = momentum_frames(close, traded_value_frame(close, volume))
    ranks = rank_frame(frames.composite).iloc[-1]
    assert ranks["ALPHA"] == 1 and ranks["BETA"] == 2 and ranks["GAMMA"] == 3
    assert np.isnan(ranks["DELTA"]) and np.isnan(ranks["THIN"])
    percentiles = percentile_frame(rank_frame(frames.composite)).iloc[-1]
    assert percentiles["ALPHA"] == pytest.approx(100.0) and percentiles["DELTA"] == 0.0


def snapshot(rank, market_ok=True, eligible=200):
    return MomentumSnapshot(rank, eligible, 90.0 if rank else 0.0, 95.0, 0.4, 0.9, 50.0, market_ok)


def test_momentum_decision_rules():
    buy = momentum_decision(snapshot(3), 100.0, 2.0)
    assert buy.action == "BUY"
    assert buy.stop == pytest.approx(100 - MOMENTUM.stop_atr * 2) and buy.target == pytest.approx(
        100 + MOMENTUM.target_atr * 2
    )
    assert "Momentum rank 3 of 200" in buy.rationale

    assert momentum_decision(snapshot(3, market_ok=False), 100.0, 2.0).action == "HOLD"
    assert momentum_decision(snapshot(3), 100.0, 2.0, news_sentiment=-0.5, news_count=2).action == "HOLD"
    assert momentum_decision(snapshot(MOMENTUM.top_n + 5), 100.0, 2.0).action == "HOLD"
    assert momentum_decision(snapshot(MOMENTUM.exit_rank + 1), 100.0, 2.0).action == "SELL"
    below = momentum_decision(snapshot(None), 90.0, 2.0)
    assert below.action == "SELL" and "Below 200-day average" in below.rationale
    unfiltered = replace(MOMENTUM, market_filter=False)
    assert momentum_decision(snapshot(3, market_ok=False), 100.0, 2.0, params=unfiltered).action == "BUY"


def market_frame():
    close, volume = universe()
    nifty = pd.Series(np.linspace(20000, 26000, DAYS), index=close.index)
    frames = []
    for symbol in [*close.columns, "NIFTY 50"]:
        series = nifty if symbol == "NIFTY 50" else close[symbol]
        df = pd.DataFrame(
            {"open": series, "high": series * 1.01, "low": series * 0.99, "close": series},
            index=close.index,
        )
        df["volume"] = 1e6 if symbol == "NIFTY 50" else volume[symbol]
        merged = df.join(compute_indicators(df, None if symbol == "NIFTY 50" else nifty))
        merged["symbol"] = symbol
        merged["trade_date"] = merged.index
        merged["is_stock"] = symbol != "NIFTY 50"
        frames.append(merged.reset_index(drop=True))
    return pd.concat(frames, ignore_index=True)


def test_backtest_mask_matches_live_decision_every_day():
    data = build_market_data(market_frame(), {})
    total, buys, sells = momentum_mask(data, MOMENTUM)
    eligible = (~np.isnan(data.momentum_rank)).sum(axis=1)
    checked = 0
    for day in range(len(data.dates) - 40, len(data.dates)):
        for col, symbol in enumerate(data.symbols):
            rank = data.momentum_rank[day, col]
            snap = MomentumSnapshot(
                None if np.isnan(rank) else int(rank),
                int(eligible[day]),
                float(total[day, col]),
                None,
                None,
                None,
                None,
                bool(data.market_ok[day]),
            )
            decision = momentum_decision(snap, float(data.close[day, col]), float(data.atr[day, col]))
            assert (decision.action == "BUY") == bool(buys[day, col]), (symbol, day)
            assert (decision.action == "SELL") == bool(sells[day, col]), (symbol, day)
            checked += 1
    assert checked == 40 * len(data.symbols) and buys[-1].sum() == 3


def test_momentum_is_default_and_tunes_its_own_grid():
    assert DEFAULT_PARAMS.model == "momentum" and DEFAULT_PARAMS.name == "momentum_v1"
    assert grid_for(DEFAULT_PARAMS) is MOMENTUM_GRID
    assert grid_for(StrategyParams()) is not MOMENTUM_GRID


def test_generator_writes_momentum_signals(db, settings, monkeypatch):
    seeded(db, monkeypatch)
    update_indicators(db)
    result, _ = generate_signals(db)
    signal = db.scalar(select(Signal))
    assert result.scored == 1 and signal.strategy == "momentum_v1"
    assert signal.action == "SELL" and "Illiquid" in signal.rationale
