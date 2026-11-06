import json
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.analysis.regime import Regime, market_regime
from app.core.clock import utc_now
from app.core.config import get_settings
from app.llm.client import JSONCompleter, LLMResponseError
from app.llm.sentiment import PROMPT_VERSION as NEWS_PROMPT_VERSION
from app.models import DailyCandle, IndicatorDaily, Instrument, NewsArticle, NewsSentiment, ResearchReport, Signal

RESEARCH_PROMPT_VERSION = "r1"
VERDICTS = {"buy", "wait", "avoid"}

SYSTEM_PROMPT = """You are a disciplined swing-trading analyst for Indian equities on NSE (holding period 1-6 weeks).
You get one stock's technical snapshot, the quant signal, the market regime and recent scored news.
Write a short, sober research note. Never invent facts, numbers or events that are not in the input.
If the news is thin, say so. Weigh event risk (results, regulatory issues, promoter actions) heavily.
Reply with JSON only:
{"summary":"2-3 sentences","bull_case":["..."],"bear_case":["..."],"key_risks":["..."],"verdict":"buy|wait|avoid","conviction":0.0}
conviction is 0.0-1.0 for the verdict. Use "wait" when the setup is good but timing or event risk argues for patience."""


@dataclass
class ResearchResult:
    shortlisted: list[str] = field(default_factory=list)
    reports: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def shortlist(db: Session, as_of: date, strategy: str, limit: int) -> list[tuple[Instrument, Signal]]:
    return list(
        db.execute(
            select(Instrument, Signal)
            .join(Signal, Signal.instrument_id == Instrument.id)
            .where(Signal.as_of_date == as_of, Signal.strategy == strategy, Signal.action == "BUY")
            .order_by(Signal.score.desc())
            .limit(limit)
        ).all()
    )


def _context(db: Session, instrument: Instrument, signal: Signal, regime: Regime, model: str) -> dict:
    ind = db.get(IndicatorDaily, (instrument.id, signal.as_of_date))
    closes = list(
        db.scalars(
            select(DailyCandle.close)
            .where(DailyCandle.instrument_id == instrument.id, DailyCandle.trade_date <= signal.as_of_date)
            .order_by(DailyCandle.trade_date.desc())
            .limit(61)
        )
    )
    change = {
        label: round((float(closes[0]) / float(closes[n]) - 1) * 100, 2)
        for label, n in (("5d", 5), ("20d", 20), ("60d", 60))
        if len(closes) > n
    }
    news = db.execute(
        select(
            NewsArticle.title,
            NewsArticle.source,
            NewsArticle.published_at,
            NewsSentiment.sentiment,
            NewsSentiment.rationale,
        )
        .join(NewsSentiment, NewsSentiment.article_id == NewsArticle.id)
        .where(
            NewsSentiment.instrument_id == instrument.id,
            NewsSentiment.model == model,
            NewsSentiment.prompt_version == NEWS_PROMPT_VERSION,
            NewsArticle.published_at >= utc_now() - timedelta(days=21),
        )
        .order_by(NewsArticle.published_at.desc())
        .limit(12)
    ).all()
    indicators = {}
    if ind is not None:
        for key in (
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
        ):
            value = getattr(ind, key)
            indicators[key] = round(float(value), 2) if value is not None else None
    return {
        "symbol": instrument.tradingsymbol,
        "company": instrument.name,
        "sector": instrument.sector,
        "as_of": signal.as_of_date.isoformat(),
        "last_close": float(closes[0]) if closes else None,
        "price_change_pct": change,
        "indicators": indicators,
        "signal": {
            "score": float(signal.score),
            "technical": float(signal.technical_score or 0),
            "news_points": float(signal.news_score or 0),
            "entry": float(signal.entry_price) if signal.entry_price else None,
            "stop": float(signal.stop_loss) if signal.stop_loss else None,
            "target": float(signal.target) if signal.target else None,
            "rationale": signal.rationale,
        },
        "market_regime": {"name": regime.name, "summary": regime.summary, "vix": regime.vix},
        "news": [
            {
                "title": n.title,
                "source": n.source,
                "date": n.published_at.date().isoformat() if n.published_at else None,
                "sentiment": float(n.sentiment),
                "note": n.rationale,
            }
            for n in news
        ],
    }


def _as_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(v)[:300] for v in value if v][:6]
    return [str(value)[:300]] if value else []


def write_report(
    db: Session, llm: JSONCompleter, instrument: Instrument, signal: Signal, regime: Regime
) -> ResearchReport:
    context = _context(db, instrument, signal, regime, get_settings().llm_model)
    payload = llm.complete_json(SYSTEM_PROMPT, json.dumps(context, ensure_ascii=False), "research_report")
    verdict = str(payload.get("verdict", "")).lower()
    if verdict not in VERDICTS or not payload.get("summary"):
        raise LLMResponseError("Research reply missing verdict or summary")
    try:
        conviction = max(0.0, min(1.0, float(payload.get("conviction", 0))))
    except (TypeError, ValueError):
        conviction = 0.0
    db.execute(
        delete(ResearchReport).where(
            ResearchReport.instrument_id == instrument.id,
            ResearchReport.as_of_date == signal.as_of_date,
            ResearchReport.model == llm.model,
        )
    )
    report = ResearchReport(
        instrument_id=instrument.id,
        as_of_date=signal.as_of_date,
        model=llm.model,
        summary=str(payload["summary"])[:4000],
        bull_case=json.dumps(_as_list(payload.get("bull_case")), ensure_ascii=False),
        bear_case=json.dumps(_as_list(payload.get("bear_case")), ensure_ascii=False),
        key_risks=json.dumps(_as_list(payload.get("key_risks")), ensure_ascii=False),
        verdict=verdict,
        prompt_version=RESEARCH_PROMPT_VERSION,
        score=round(conviction * 100, 2),
    )
    db.add(report)
    db.commit()
    return report


def research_top_picks(
    db: Session, llm: JSONCompleter, as_of: date, strategy: str = "swing_v1", limit: int = 10
) -> ResearchResult:
    regime = market_regime(db, as_of)
    result = ResearchResult()
    for instrument, signal in shortlist(db, as_of, strategy, limit):
        result.shortlisted.append(instrument.tradingsymbol)
        try:
            write_report(db, llm, instrument, signal, regime)
            result.reports += 1
        except (LLMResponseError, ValueError) as exc:
            db.rollback()
            result.failed += 1
            result.errors.append(f"{instrument.tradingsymbol}: {str(exc)[:150]}")
    return result


def report_dict(report: ResearchReport) -> dict:
    return {
        "as_of": report.as_of_date.isoformat(),
        "model": report.model,
        "summary": report.summary,
        "bull_case": json.loads(report.bull_case or "[]"),
        "bear_case": json.loads(report.bear_case or "[]"),
        "key_risks": json.loads(report.key_risks or "[]"),
        "verdict": report.verdict,
        "conviction": float(report.score or 0) / 100,
        "created_at": report.created_at.isoformat() + "Z" if report.created_at else None,
    }
