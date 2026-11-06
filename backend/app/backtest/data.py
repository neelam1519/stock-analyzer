from dataclasses import dataclass

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.indicators import INDICATOR_COLUMNS
from app.analysis.momentum import benchmark_trend, momentum_frames, rank_frame, traded_value_frame
from app.analysis.regime import BENCHMARK, VIX
from app.backtest.vector import regime_series, technical_score_frame
from app.models import DailyCandle, IndicatorDaily, Instrument

LIQUIDITY_WINDOW = 27


@dataclass
class MarketData:
    dates: np.ndarray
    symbols: list[str]
    sectors: list[str]
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    atr: np.ndarray
    ema50: np.ndarray
    rsi: np.ndarray
    macd: np.ndarray
    macd_signal: np.ndarray
    technical: np.ndarray
    traded_value_cr: np.ndarray
    regime: np.ndarray
    benchmark: np.ndarray
    momentum_rank: np.ndarray
    market_ok: np.ndarray

    def window(self, start, end) -> "MarketData":
        mask = (self.dates >= np.datetime64(start)) & (self.dates <= np.datetime64(end))
        fields = {
            k: (v[mask] if isinstance(v, np.ndarray) and v.shape[:1] == self.dates.shape else v)
            for k, v in self.__dict__.items()
        }
        return MarketData(**fields)


def build_market_data(
    frame: pd.DataFrame, sectors: dict[str, str], benchmark_symbol: str = BENCHMARK, vix_symbol: str = VIX
) -> MarketData:
    frame = frame.copy()
    frame["technical"] = technical_score_frame(frame)
    frame["traded_value_cr"] = (frame["close"] * frame["volume"]).groupby(frame["symbol"]).transform(
        lambda s: s.rolling(LIQUIDITY_WINDOW, min_periods=10).mean()
    ) / 1e7
    nifty = frame[frame["symbol"] == benchmark_symbol].set_index("trade_date").sort_index()
    vix = frame[frame["symbol"] == vix_symbol].set_index("trade_date")["close"].sort_index()
    regimes = regime_series(nifty, vix if not vix.empty else None)
    stocks = frame[~frame["symbol"].isin([benchmark_symbol, vix_symbol]) & frame["is_stock"]]
    dates = np.array(sorted(nifty.index), dtype="datetime64[D]")
    symbols = sorted(stocks["symbol"].unique())

    def matrix(column: str) -> np.ndarray:
        pivot = stocks.pivot(index="trade_date", columns="symbol", values=column)
        pivot.index = pd.to_datetime(pivot.index)
        return pivot.reindex(index=pd.to_datetime(dates), columns=symbols).to_numpy(dtype=float)

    regime = regimes.reindex(pd.Index(dates.astype(object))).fillna("unknown").to_numpy()
    bench = nifty["close"].reindex(pd.Index(dates.astype(object))).to_numpy(dtype=float)
    close = pd.DataFrame(matrix("close"))
    frames = momentum_frames(close, traded_value_frame(close, pd.DataFrame(matrix("volume"))))
    return MarketData(
        dates=dates,
        symbols=symbols,
        sectors=[sectors.get(s) or "Other" for s in symbols],
        open=matrix("open"),
        high=matrix("high"),
        low=matrix("low"),
        close=matrix("close"),
        atr=matrix("atr14"),
        ema50=matrix("ema50"),
        rsi=matrix("rsi14"),
        macd=matrix("macd"),
        macd_signal=matrix("macd_signal"),
        technical=matrix("technical"),
        traded_value_cr=matrix("traded_value_cr"),
        regime=regime,
        benchmark=bench,
        momentum_rank=rank_frame(frames.composite).to_numpy(dtype=float),
        market_ok=benchmark_trend(pd.Series(bench)).to_numpy(dtype=bool),
    )


def load_market_data(db: Session) -> MarketData:
    columns = [getattr(IndicatorDaily, c) for c in INDICATOR_COLUMNS]
    rows = db.execute(
        select(
            Instrument.tradingsymbol,
            Instrument.segment,
            DailyCandle.trade_date,
            DailyCandle.open,
            DailyCandle.high,
            DailyCandle.low,
            DailyCandle.close,
            DailyCandle.volume,
            *columns,
        )
        .join(Instrument, Instrument.id == DailyCandle.instrument_id)
        .outerjoin(
            IndicatorDaily,
            (IndicatorDaily.instrument_id == DailyCandle.instrument_id)
            & (IndicatorDaily.trade_date == DailyCandle.trade_date),
        )
        .where(Instrument.in_universe, Instrument.is_active)
    ).all()
    names = ["symbol", "segment", "trade_date", "open", "high", "low", "close", "volume", *INDICATOR_COLUMNS]
    frame = pd.DataFrame(rows, columns=names)
    for column in names[3:]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype(float)
    frame["is_stock"] = frame["segment"] == "NSE"
    sectors = dict(db.execute(select(Instrument.tradingsymbol, Instrument.sector).where(Instrument.in_universe)).all())
    return build_market_data(frame.drop(columns=["segment"]), sectors)
