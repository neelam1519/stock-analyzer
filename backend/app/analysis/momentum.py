import math
from dataclasses import dataclass

import pandas as pd

LOOKBACKS = (126, 252)
SKIP_DAYS = 5
TREND_DAYS = 200
TREND_MIN_PERIODS = 150
LIQUIDITY_DAYS = 27
LIQUIDITY_MIN_PERIODS = 10
MIN_TRADED_VALUE_CR = 5.0
FFILL_LIMIT = 5
HISTORY_DAYS = max(LOOKBACKS) + SKIP_DAYS + 20


@dataclass
class MomentumFrames:
    composite: pd.DataFrame
    trend: pd.DataFrame
    returns: dict[int, pd.DataFrame]
    traded_value_cr: pd.DataFrame


def _zscore(frame: pd.DataFrame) -> pd.DataFrame:
    spread = frame.std(axis=1).where(lambda std: std > 0).fillna(1.0)
    return frame.sub(frame.mean(axis=1), axis=0).div(spread, axis=0)


def traded_value_frame(close: pd.DataFrame, volume: pd.DataFrame) -> pd.DataFrame:
    return (close * volume).rolling(LIQUIDITY_DAYS, min_periods=LIQUIDITY_MIN_PERIODS).mean() / 1e7


def momentum_frames(close: pd.DataFrame, traded_value_cr: pd.DataFrame) -> MomentumFrames:
    close = close.ffill(limit=FFILL_LIMIT)
    daily = close.pct_change(fill_method=None)
    trend = close.rolling(TREND_DAYS, min_periods=TREND_MIN_PERIODS).mean()
    eligible = (traded_value_cr >= MIN_TRADED_VALUE_CR) & (close > trend)
    risk_adjusted, returns = [], {}
    for lookback in LOOKBACKS:
        change = close.shift(SKIP_DAYS) / close.shift(lookback) - 1
        volatility = daily.rolling(lookback, min_periods=int(lookback * 0.7)).std() * math.sqrt(252)
        score = change / volatility
        eligible &= score.notna()
        risk_adjusted.append(score)
        returns[lookback] = change
    zscores = [_zscore(score.where(eligible)) for score in risk_adjusted]
    total = zscores[0]
    for frame in zscores[1:]:
        total = total + frame
    composite = (total / len(zscores)).where(eligible)
    return MomentumFrames(composite, trend, returns, traded_value_cr)


def rank_frame(composite: pd.DataFrame) -> pd.DataFrame:
    return composite.rank(axis=1, ascending=False, method="first")


def percentile_frame(ranks: pd.DataFrame) -> pd.DataFrame:
    count = ranks.count(axis=1)
    return (100 * (1 - (ranks - 1).div(count, axis=0))).where(ranks.notna(), 0.0)


def benchmark_trend(close: pd.Series) -> pd.Series:
    close = close.ffill(limit=FFILL_LIMIT)
    return close > close.rolling(TREND_DAYS, min_periods=TREND_MIN_PERIODS).mean()
