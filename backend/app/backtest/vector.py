import numpy as np
import pandas as pd

from app.analysis.regime import classify


def technical_score_frame(df: pd.DataFrame) -> pd.Series:
    c, e20, e50, e200 = df["close"], df["ema20"], df["ema50"], df["ema200"]
    rsi, macd, sig = df["rsi14"], df["macd"], df["macd_signal"]
    adx, vol, dist, rs = df["adx14"], df["volume_ratio20"], df["high52w_distance_pct"], df["relative_strength_nifty"]

    has_trend = c.notna() & e20.notna() & e50.notna() & e200.notna()
    trend = 8.0 * (c > e20) + 8.0 * (e20 > e50) + 8.0 * (e50 > e200) + 6.0 * (c > e200)
    score = trend.where(has_trend, 0.0)

    rsi_pts = np.select(
        [(rsi >= 50) & (rsi <= 68), ((rsi >= 40) & (rsi < 50)) | ((rsi > 68) & (rsi <= 75))], [12.0, 6.0], 0.0
    )
    score = score + rsi_pts

    has_macd = macd.notna() & sig.notna()
    score = score + (8.0 * (macd > sig) + 5.0 * (macd > 0)).where(has_macd, 0.0)

    score = score + ((adx - 15) / 15 * 10).clip(0, 10).fillna(0.0)
    score = score + (rs / 15 * 10).clip(0, 10).fillna(0.0)
    score = score + np.select([(vol >= 1.2) & (vol <= 3.5), vol >= 1.0], [10.0, 5.0], 0.0)
    score = score + np.select([dist >= -10, dist >= -20], [15.0, 8.0], 0.0)
    return score.clip(upper=100.0)


def regime_series(nifty: pd.DataFrame, vix_close: pd.Series | None) -> pd.Series:
    vix = vix_close.reindex(nifty.index).ffill() if vix_close is not None else pd.Series(np.nan, index=nifty.index)
    names = []
    for date, row in nifty.iterrows():
        if pd.isna(row["ema200"]) or pd.isna(row["ema50"]):
            names.append("unknown")
            continue
        v = vix.get(date)
        names.append(classify(row["close"], row["ema50"], row["ema200"], None if pd.isna(v) else float(v)))
    return pd.Series(names, index=nifty.index)
