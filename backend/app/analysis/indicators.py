from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from app.models import DailyCandle, IndicatorDaily, Instrument

BENCHMARK = "NIFTY 50"
RS_LOOKBACK = 63
INDICATOR_COLUMNS = (
    "ema20",
    "ema50",
    "ema200",
    "rsi14",
    "macd",
    "macd_signal",
    "adx14",
    "atr14",
    "volume_ratio20",
    "high52w_distance_pct",
    "relative_strength_nifty",
)


def _wilder(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def compute_indicators(candles: pd.DataFrame, benchmark_close: pd.Series | None = None) -> pd.DataFrame:
    df = candles.sort_index()
    close, high, low, volume = df["close"], df["high"], df["low"], df["volume"]
    out = pd.DataFrame(index=df.index)

    for span in (20, 50, 200):
        out[f"ema{span}"] = close.ewm(span=span, adjust=False, min_periods=span).mean()

    delta = close.diff()
    gain = _wilder(delta.clip(lower=0), 14)
    loss = _wilder(-delta.clip(upper=0), 14)
    rs = gain / loss.replace(0, np.nan)
    out["rsi14"] = (100 - 100 / (1 + rs)).where(loss != 0, 100.0).where(gain.notna())

    macd = (
        close.ewm(span=12, adjust=False, min_periods=26).mean()
        - close.ewm(span=26, adjust=False, min_periods=26).mean()
    )
    out["macd"] = macd
    out["macd_signal"] = macd.ewm(span=9, adjust=False, min_periods=9).mean()

    prev_close = close.shift(1)
    true_range = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    atr = _wilder(true_range, 14)
    out["atr14"] = atr

    up, down = high.diff(), -low.diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    plus_di = 100 * _wilder(plus_dm, 14) / atr
    minus_di = 100 * _wilder(minus_dm, 14) / atr
    di_sum = (plus_di + minus_di).replace(0, np.nan)
    out["adx14"] = _wilder((100 * (plus_di - minus_di).abs() / di_sum).fillna(0), 14).where(atr.notna())

    avg_volume = volume.rolling(20, min_periods=20).mean()
    out["volume_ratio20"] = (volume / avg_volume.replace(0, np.nan)).where(avg_volume > 0)

    high52 = high.rolling(252, min_periods=50).max()
    out["high52w_distance_pct"] = (close / high52 - 1) * 100

    if benchmark_close is not None:
        bench = benchmark_close.reindex(df.index).ffill()
        stock_ret = close.pct_change(RS_LOOKBACK, fill_method=None)
        bench_ret = bench.pct_change(RS_LOOKBACK, fill_method=None)
        out["relative_strength_nifty"] = (stock_ret - bench_ret) * 100
    else:
        out["relative_strength_nifty"] = np.nan
    return out


def load_daily_frame(db: Session, instrument_ids: list[int] | None = None, since: date | None = None) -> pd.DataFrame:
    query = select(
        DailyCandle.instrument_id,
        DailyCandle.trade_date,
        DailyCandle.open,
        DailyCandle.high,
        DailyCandle.low,
        DailyCandle.close,
        DailyCandle.volume,
    )
    if instrument_ids is not None:
        query = query.where(DailyCandle.instrument_id.in_(instrument_ids))
    if since is not None:
        query = query.where(DailyCandle.trade_date >= since)
    rows = db.execute(query).all()
    frame = pd.DataFrame(rows, columns=["instrument_id", "trade_date", "open", "high", "low", "close", "volume"])
    for column in ("open", "high", "low", "close"):
        frame[column] = frame[column].astype(float)
    frame["volume"] = frame["volume"].astype(float)
    return frame


@dataclass
class IndicatorResult:
    instruments: int = 0
    inserted: int = 0
    skipped: int = 0


def _rows(instrument_id: int, indicators: pd.DataFrame) -> list[dict]:
    clean = indicators.round(4).astype(object).where(indicators.notna(), None)
    return [
        {"instrument_id": instrument_id, "trade_date": trade_date, **dict(zip(INDICATOR_COLUMNS, values, strict=True))}
        for trade_date, values in zip(clean.index, clean[list(INDICATOR_COLUMNS)].itertuples(index=False), strict=True)
    ]


def update_indicators(
    db: Session,
    full: bool = False,
    on_progress: Callable[[IndicatorResult], None] | None = None,
) -> IndicatorResult:
    instruments = dict(
        db.execute(
            select(Instrument.id, Instrument.tradingsymbol).where(Instrument.is_active, Instrument.in_universe)
        ).all()
    )
    if full:
        db.execute(delete(IndicatorDaily))
        db.commit()
    last_done = dict(
        db.execute(
            select(IndicatorDaily.instrument_id, func.max(IndicatorDaily.trade_date)).group_by(
                IndicatorDaily.instrument_id
            )
        ).all()
    )
    last_candle = dict(
        db.execute(
            select(DailyCandle.instrument_id, func.max(DailyCandle.trade_date)).group_by(DailyCandle.instrument_id)
        ).all()
    )
    stale = [i for i in instruments if i in last_candle and last_done.get(i) != last_candle[i]]
    result = IndicatorResult(instruments=len(instruments), skipped=len(instruments) - len(stale))
    if not stale:
        return result

    benchmark_id = next((i for i, s in instruments.items() if s == BENCHMARK), None)
    ids = stale + ([benchmark_id] if benchmark_id and benchmark_id not in stale else [])
    frame = load_daily_frame(db, ids)
    groups = {key: group.set_index("trade_date") for key, group in frame.groupby("instrument_id")}
    bench_close = groups[benchmark_id]["close"] if benchmark_id in groups else None

    for instrument_id in stale:
        candles = groups.get(instrument_id)
        if candles is None or candles.empty:
            continue
        indicators = compute_indicators(candles, None if instrument_id == benchmark_id else bench_close)
        after = last_done.get(instrument_id)
        if after is not None:
            indicators = indicators[indicators.index > after]
        rows = _rows(instrument_id, indicators)
        for start in range(0, len(rows), 5000):
            db.execute(insert(IndicatorDaily), rows[start : start + 5000])
        db.commit()
        result.inserted += len(rows)
        if on_progress:
            on_progress(result)
    return result


def drop_indicators(db: Session, instrument_id: int) -> None:
    db.execute(delete(IndicatorDaily).where(IndicatorDaily.instrument_id == instrument_id))
