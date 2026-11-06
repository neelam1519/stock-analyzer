import json
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.core.config import get_settings
from app.llm.client import JSONCompleter, LLMResponseError
from app.models import Instrument, NewsArticle, NewsSentiment, NewsSymbolMap

PROMPT_VERSION = "v1"
MARKET_SYMBOL = "NIFTY 50"
IMPACTS = {"low", "medium", "high"}

SYSTEM_PROMPT = """You are an equity research analyst covering Indian stocks listed on NSE.
For each news item, judge the likely price impact over the next 1-4 weeks, which is a swing-trading horizon.
Score only the candidate symbols given for that item, and never invent symbols.
sentiment: -1.0 (very bearish) to 1.0 (very bullish), 0 when neutral or unclear.
relevance: 0.0 (mentioned in passing) to 1.0 (the news is mainly about this company).
impact: "low", "medium" or "high" expected price effect.
rationale: at most 25 words, factual, no hype.
Also score the overall Indian equity market for each item (sentiment and relevance; relevance is low for single-company news).
Routine filings with no business impact get sentiment 0 and low relevance.
Reply with JSON only:
{"results":[{"id":<item id>,"market":{"sentiment":0.0,"relevance":0.0},"stocks":[{"symbol":"","sentiment":0.0,"relevance":0.0,"impact":"low","rationale":""}]}]}"""


@dataclass
class AnalyzeResult:
    articles: int = 0
    scored: int = 0
    calls: int = 0
    failed_batches: int = 0
    errors: list[str] = field(default_factory=list)


def _clamp(value, low: float, high: float) -> float:
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return 0.0


def pending_articles(db: Session, model: str, limit: int) -> list[NewsArticle]:
    since = utc_now() - timedelta(days=get_settings().news_lookback_days)
    analyzed = exists().where(
        NewsSentiment.article_id == NewsArticle.id,
        NewsSentiment.model == model,
        NewsSentiment.prompt_version == PROMPT_VERSION,
    )
    mapped = exists().where(NewsSymbolMap.article_id == NewsArticle.id)
    published = func.coalesce(NewsArticle.published_at, NewsArticle.created_at)
    base = select(NewsArticle).where(~analyzed, published >= since)
    with_symbols = list(db.scalars(base.where(mapped).order_by(published.desc()).limit(limit)))
    remaining = limit - len(with_symbols)
    general = list(db.scalars(base.where(~mapped).order_by(published.desc()).limit(remaining))) if remaining > 0 else []
    return with_symbols + general


def build_prompt(articles: list[NewsArticle], candidates: dict[int, list[str]]) -> str:
    items = [
        {
            "id": a.id,
            "source": a.source,
            "title": a.title,
            "summary": (a.summary or "")[:600],
            "candidates": candidates.get(a.id, []),
        }
        for a in articles
    ]
    return json.dumps({"items": items}, ensure_ascii=False)


def store_scores(
    db: Session,
    payload: dict,
    articles: list[NewsArticle],
    candidates: dict[int, list[str]],
    symbol_ids: dict[str, int],
    market_id: int,
    model: str,
) -> int:
    by_id = {a.id: a for a in articles}
    stored = 0
    seen: set[int] = set()
    for result in payload.get("results", []):
        try:
            article_id = int(result.get("id"))
        except (TypeError, ValueError):
            continue
        if article_id not in by_id or article_id in seen:
            continue
        seen.add(article_id)
        allowed = set(candidates.get(article_id, []))
        market = result.get("market") or {}
        db.add(
            NewsSentiment(
                article_id=article_id,
                instrument_id=market_id,
                model=model,
                prompt_version=PROMPT_VERSION,
                sentiment=_clamp(market.get("sentiment"), -1, 1),
                relevance=_clamp(market.get("relevance"), 0, 1),
                impact=None,
                rationale=None,
            )
        )
        stored += 1
        written: set[int] = {market_id}
        for stock in result.get("stocks") or []:
            symbol = str(stock.get("symbol", "")).strip().upper()
            instrument_id = symbol_ids.get(symbol)
            if symbol not in allowed or instrument_id is None or instrument_id in written:
                continue
            written.add(instrument_id)
            impact = str(stock.get("impact", "")).lower()
            db.add(
                NewsSentiment(
                    article_id=article_id,
                    instrument_id=instrument_id,
                    model=model,
                    prompt_version=PROMPT_VERSION,
                    sentiment=_clamp(stock.get("sentiment"), -1, 1),
                    relevance=_clamp(stock.get("relevance"), 0, 1),
                    impact=impact if impact in IMPACTS else None,
                    rationale=str(stock.get("rationale") or "")[:500] or None,
                )
            )
            stored += 1
    db.commit()
    return stored


def _complete_with_retry(llm: JSONCompleter, prompt: str, result: AnalyzeResult, attempts: int = 2) -> dict:
    for attempt in range(attempts):
        result.calls += 1
        try:
            return llm.complete_json(SYSTEM_PROMPT, prompt, "news_sentiment")
        except (LLMResponseError, ValueError):
            if attempt == attempts - 1:
                raise
    raise LLMResponseError("unreachable")


def analyze_news(db: Session, llm: JSONCompleter, limit: int | None = None) -> AnalyzeResult:
    settings = get_settings()
    articles = pending_articles(db, llm.model, limit or settings.llm_max_articles_per_run)
    result = AnalyzeResult(articles=len(articles))
    if not articles:
        return result

    market_id = db.scalar(select(Instrument.id).where(Instrument.tradingsymbol == MARKET_SYMBOL))
    if market_id is None:
        raise RuntimeError("NIFTY 50 instrument missing, sync instruments first")
    symbol_ids = {s.upper(): i for s, i in db.execute(select(Instrument.tradingsymbol, Instrument.id)).all()}
    candidates: dict[int, list[str]] = {}
    rows = db.execute(
        select(NewsSymbolMap.article_id, Instrument.tradingsymbol)
        .join(Instrument, Instrument.id == NewsSymbolMap.instrument_id)
        .where(NewsSymbolMap.article_id.in_([a.id for a in articles]))
    )
    for article_id, symbol in rows:
        candidates.setdefault(article_id, []).append(symbol)

    size = max(1, settings.llm_batch_size)
    for start in range(0, len(articles), size):
        batch = articles[start : start + size]
        try:
            payload = _complete_with_retry(llm, build_prompt(batch, candidates), result)
            result.scored += store_scores(db, payload, batch, candidates, symbol_ids, market_id, llm.model)
        except (LLMResponseError, ValueError) as exc:
            db.rollback()
            result.failed_batches += 1
            result.errors.append(str(exc)[:200])
        except Exception as exc:
            db.rollback()
            result.failed_batches += 1
            result.errors.append(f"{type(exc).__name__}: {str(exc)[:200]}")
            if result.failed_batches >= 3 and result.scored == 0:
                raise
    return result
