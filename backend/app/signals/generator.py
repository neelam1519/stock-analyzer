from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

import pandas as pd
from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from app.analysis.indicators import INDICATOR_COLUMNS
from app.analysis.momentum import (
    HISTORY_DAYS,
    LOOKBACKS,
    benchmark_trend,
    momentum_frames,
    percentile_frame,
    rank_frame,
    traded_value_frame,
)
from app.analysis.regime import BENCHMARK, Regime, market_regime
from app.core.clock import IST, to_utc_naive
from app.core.config import get_settings
from app.llm.sentiment import PROMPT_VERSION
from app.models import DailyCandle, IndicatorDaily, Instrument, NewsArticle, NewsSentiment, Signal
from app.signals.params import load_active_params
from app.signals.scoring import MomentumSnapshot, StrategyParams, momentum_decision, score_stock

NEWS_WINDOW_DAYS = 14
NEWS_HALF_LIFE_DAYS = 3.0
TRADED_VALUE_DAYS = 20


@dataclass
class SignalRunResult:
    as_of: date | None
    regime: str
    scored: int = 0
    buys: int = 0
    sells: int = 0


def news_scores(db: Session, as_of: date, model: str) -> dict[int, tuple[float, int]]:
    end = to_utc_naive(datetime.combine(as_of + timedelta(days=1), time(9, 0), IST))
    start = end - timedelta(days=NEWS_WINDOW_DAYS)
    published = func.coalesce(NewsArticle.published_at, NewsArticle.created_at)
    rows = db.execute(
        select(NewsSentiment.instrument_id, NewsSentiment.sentiment, NewsSentiment.relevance, published)
        .join(NewsArticle, NewsArticle.id == NewsSentiment.article_id)
        .where(
            NewsSentiment.model == model,
            NewsSentiment.prompt_version == PROMPT_VERSION,
            NewsSentiment.impact.is_not(None),
            published >= start,
            published < end,
        )
    ).all()
    totals: dict[int, list[float]] = {}
    for instrument_id, sentiment, relevance, when in rows:
        age_days = max(0.0, (end - when).total_seconds() / 86400)
        weight = float(relevance) * 0.5 ** (age_days / NEWS_HALF_LIFE_DAYS)
        bucket = totals.setdefault(instrument_id, [0.0, 0.0, 0])
        bucket[0] += float(sentiment) * weight
        bucket[1] += weight
        bucket[2] += 1
    scores = {}
    for instrument_id, (weighted, weight, count) in totals.items():
        if weight > 0:
            confidence = min(1.0, weight / 1.5)
            scores[instrument_id] = (round(weighted / weight * confidence, 4), int(count))
    return scores


def traded_value_cr(db: Session, as_of: date) -> dict[int, float]:
    since = as_of - timedelta(days=TRADED_VALUE_DAYS * 2)
    rows = db.execute(
        select(DailyCandle.instrument_id, func.avg(DailyCandle.close * DailyCandle.volume))
        .where(DailyCandle.trade_date > since, DailyCandle.trade_date <= as_of)
        .group_by(DailyCandle.instrument_id)
    ).all()
    return {instrument_id: float(value or 0) / 1e7 for instrument_id, value in rows}


def latest_session(db: Session) -> date | None:
    nifty = db.scalar(select(Instrument.id).where(Instrument.tradingsymbol == BENCHMARK))
    return db.scalar(select(func.max(IndicatorDaily.trade_date)).where(IndicatorDaily.instrument_id == nifty))


def _num(value) -> float | None:
    return None if value is None or pd.isna(value) else float(value)


def momentum_snapshots(db: Session, as_of: date) -> dict[int, MomentumSnapshot]:
    nifty = db.scalar(select(Instrument.id).where(Instrument.tradingsymbol == BENCHMARK))
    dates = list(
        reversed(
            db.scalars(
                select(DailyCandle.trade_date)
                .where(DailyCandle.instrument_id == nifty, DailyCandle.trade_date <= as_of)
                .order_by(DailyCandle.trade_date.desc())
                .limit(HISTORY_DAYS)
            ).all()
        )
    )
    if not dates:
        return {}
    rows = db.execute(
        select(DailyCandle.instrument_id, DailyCandle.trade_date, DailyCandle.close, DailyCandle.volume)
        .join(Instrument, Instrument.id == DailyCandle.instrument_id)
        .where(
            DailyCandle.trade_date >= dates[0],
            DailyCandle.trade_date <= as_of,
            (Instrument.id == nifty) | ((Instrument.segment == "NSE") & Instrument.in_universe & Instrument.is_active),
        )
    ).all()
    frame = pd.DataFrame(rows, columns=["instrument_id", "trade_date", "close", "volume"])
    frame[["close", "volume"]] = frame[["close", "volume"]].apply(pd.to_numeric, errors="coerce").astype(float)
    index = pd.Index(dates)
    close = frame.pivot(index="trade_date", columns="instrument_id", values="close").reindex(index)
    volume = frame.pivot(index="trade_date", columns="instrument_id", values="volume").reindex(index)
    market_ok = bool(benchmark_trend(close[nifty]).iloc[-1]) if nifty in close else False
    stocks = [c for c in close.columns if c != nifty]
    frames = momentum_frames(close[stocks], traded_value_frame(close[stocks], volume[stocks]))
    all_ranks = rank_frame(frames.composite)
    ranks = all_ranks.iloc[-1]
    percentiles = percentile_frame(all_ranks).iloc[-1]
    eligible = int(ranks.notna().sum())
    short, long = LOOKBACKS
    return {
        int(iid): MomentumSnapshot(
            rank=None if pd.isna(ranks[iid]) else int(ranks[iid]),
            eligible=eligible,
            percentile=float(percentiles[iid]),
            trend=_num(frames.trend[iid].iloc[-1]),
            return_6m=_num(frames.returns[short][iid].iloc[-1]),
            return_12m=_num(frames.returns[long][iid].iloc[-1]),
            traded_value_cr=_num(frames.traded_value_cr[iid].iloc[-1]),
            market_ok=market_ok,
        )
        for iid in stocks
    }


def generate_signals(
    db: Session, as_of: date | None = None, params: StrategyParams | None = None
) -> tuple[SignalRunResult, Regime]:
    params = params or load_active_params(db)[0]
    as_of = as_of or latest_session(db)
    regime = market_regime(db, as_of)
    result = SignalRunResult(as_of=as_of, regime=regime.name)
    if as_of is None:
        return result, regime

    columns = [getattr(IndicatorDaily, c) for c in INDICATOR_COLUMNS]
    rows = db.execute(
        select(IndicatorDaily.instrument_id, DailyCandle.close, *columns)
        .join(
            DailyCandle,
            (DailyCandle.instrument_id == IndicatorDaily.instrument_id)
            & (DailyCandle.trade_date == IndicatorDaily.trade_date),
        )
        .join(Instrument, Instrument.id == IndicatorDaily.instrument_id)
        .where(
            IndicatorDaily.trade_date == as_of,
            Instrument.segment == "NSE",
            Instrument.in_universe,
            Instrument.is_active,
        )
    ).all()
    news = news_scores(db, as_of, get_settings().llm_model)
    momentum = params.model == "momentum"
    liquidity = {} if momentum else traded_value_cr(db, as_of)
    snapshots = momentum_snapshots(db, as_of) if momentum else {}
    empty = MomentumSnapshot(None, 0, 0.0, None, None, None, None, False)

    db.execute(delete(Signal).where(Signal.as_of_date == as_of, Signal.strategy == params.name))
    records = []
    for row in rows:
        data = dict(zip(["instrument_id", "close", *INDICATOR_COLUMNS], row, strict=True))
        sentiment, count = news.get(data["instrument_id"], (None, 0))
        if momentum:
            breakdown = momentum_decision(
                snapshots.get(data["instrument_id"], empty),
                _num(data["close"]),
                _num(data["atr14"]),
                sentiment,
                count,
                params,
            )
        else:
            breakdown = score_stock(data, regime.name, sentiment, count, liquidity.get(data["instrument_id"]), params)
        if breakdown.action == "BUY" and regime.name not in params.entry_regimes:
            breakdown.action = "HOLD"
            breakdown.entry = breakdown.stop = breakdown.target = None
            breakdown.confidence = 0.0
            breakdown.reasons.append(f"No new entries in {regime.name} regime")
        records.append(
            {
                "instrument_id": data["instrument_id"],
                "as_of_date": as_of,
                "strategy": params.name,
                "action": breakdown.action,
                "score": breakdown.total,
                "technical_score": breakdown.technical,
                "news_score": breakdown.news,
                "fundamental_score": None,
                "regime": regime.name,
                "entry_price": breakdown.entry,
                "stop_loss": breakdown.stop,
                "target": breakdown.target,
                "confidence": breakdown.confidence,
                "rationale": breakdown.rationale[:4000],
            }
        )
        result.buys += breakdown.action == "BUY"
        result.sells += breakdown.action == "SELL"
    for start in range(0, len(records), 1000):
        db.execute(insert(Signal), records[start : start + 1000])
    db.commit()
    result.scored = len(records)
    return result, regime
