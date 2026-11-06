from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.api.ingest import job_dict, start_or_409
from app.core.clock import utc_now
from app.core.config import get_settings
from app.core.db import get_db, get_sessionmaker
from app.core.jobs import track_job
from app.llm.client import LiteLLMCompleter, LLMNotConfigured
from app.llm.sentiment import MARKET_SYMBOL, PROMPT_VERSION, analyze_news
from app.models import Instrument, JobRun, LLMCall, NewsArticle, NewsSentiment, NewsSymbolMap
from app.news.collector import collect_news
from app.news.matcher import build_matcher, seed_aliases

router = APIRouter(tags=["news"])


def _run_collect(run_id: int, symbols: list[str] | None) -> None:
    with get_sessionmaker()() as db:
        run = db.get(JobRun, run_id)
        with track_job(db, run) as job:
            seed_aliases(db)
            result = collect_news(db, build_matcher(db), symbols)
            job.add(result.inserted)
            run.details = (
                f"fetched={result.fetched} new={result.inserted} tagged={result.mapped}"
                + (f" errors={','.join(result.errors)}" if result.errors else "")
            )[:1000]


def _run_analyze(run_id: int) -> None:
    with get_sessionmaker()() as db:
        run = db.get(JobRun, run_id)
        with track_job(db, run) as job:
            result = analyze_news(db, LiteLLMCompleter(db))
            job.add(result.scored)
            run.details = (
                f"articles={result.articles} calls={result.calls} scores={result.scored} "
                f"failed_batches={result.failed_batches}"
                + (f" last_error={result.errors[-1]}" if result.errors else "")
            )[:1000]


@router.post("/ingest/news", status_code=202)
def ingest_news(
    background: BackgroundTasks,
    symbols: list[str] | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    run = start_or_409(db, "ingest_news", needs_kite=False)
    background.add_task(_run_collect, run.id, symbols)
    return job_dict(run)


@router.post("/analyze/news", status_code=202)
def analyze_news_endpoint(background: BackgroundTasks, db: Session = Depends(get_db)) -> dict:
    try:
        LiteLLMCompleter(db)
    except LLMNotConfigured as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    run = start_or_409(db, "analyze_news", needs_kite=False)
    background.add_task(_run_analyze, run.id)
    return job_dict(run)


def _iso(value) -> str | None:
    return value.isoformat() + "Z" if value else None


@router.get("/news")
def list_news(
    symbol: str | None = None,
    days: int = Query(default=7, ge=1, le=90),
    tagged_only: bool = False,
    limit: int = Query(default=100, le=500),
    db: Session = Depends(get_db),
) -> dict:
    model = get_settings().llm_model
    published = func.coalesce(NewsArticle.published_at, NewsArticle.created_at)
    query = select(NewsArticle).where(published >= utc_now() - timedelta(days=days))
    if symbol:
        instrument_id = db.scalar(select(Instrument.id).where(Instrument.tradingsymbol == symbol))
        if instrument_id is None:
            raise HTTPException(status_code=404, detail=f"Unknown symbol {symbol}")
        query = query.where(
            exists().where(NewsSymbolMap.article_id == NewsArticle.id, NewsSymbolMap.instrument_id == instrument_id)
        )
    elif tagged_only:
        query = query.where(exists().where(NewsSymbolMap.article_id == NewsArticle.id))
    articles = list(db.scalars(query.order_by(published.desc()).limit(limit)))
    ids = [a.id for a in articles]

    tags: dict[int, dict[str, dict]] = {}
    for article_id, sym, match_type in db.execute(
        select(NewsSymbolMap.article_id, Instrument.tradingsymbol, NewsSymbolMap.match_type)
        .join(Instrument, Instrument.id == NewsSymbolMap.instrument_id)
        .where(NewsSymbolMap.article_id.in_(ids or [-1]))
    ):
        tags.setdefault(article_id, {})[sym] = {"symbol": sym, "match_type": match_type}

    market: dict[int, float] = {}
    for row in db.execute(
        select(NewsSentiment, Instrument.tradingsymbol)
        .join(Instrument, Instrument.id == NewsSentiment.instrument_id)
        .where(
            NewsSentiment.article_id.in_(ids or [-1]),
            NewsSentiment.model == model,
            NewsSentiment.prompt_version == PROMPT_VERSION,
        )
    ):
        score, sym = row
        if sym == MARKET_SYMBOL:
            market[score.article_id] = float(score.sentiment)
            continue
        entry = tags.setdefault(score.article_id, {}).setdefault(sym, {"symbol": sym, "match_type": "llm"})
        entry.update(
            sentiment=float(score.sentiment),
            relevance=float(score.relevance),
            impact=score.impact,
            rationale=score.rationale,
        )

    return {
        "items": [
            {
                "id": a.id,
                "title": a.title,
                "url": a.url,
                "source": a.source,
                "summary": (a.summary or "")[:400] or None,
                "published_at": _iso(a.published_at or a.created_at),
                "analyzed": a.id in market,
                "market_sentiment": market.get(a.id),
                "symbols": sorted(tags.get(a.id, {}).values(), key=lambda t: -(t.get("relevance") or 0)),
            }
            for a in articles
        ]
    }


@router.get("/llm/usage")
def llm_usage(db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    now = utc_now()

    def totals(since):
        calls, cost, tokens = db.execute(
            select(
                func.count(),
                func.coalesce(func.sum(LLMCall.cost_usd), 0),
                func.coalesce(func.sum(LLMCall.prompt_tokens + LLMCall.completion_tokens), 0),
            ).where(LLMCall.created_at >= since)
        ).one()
        return {"calls": calls, "cost_usd": round(float(cost), 4), "tokens": int(tokens)}

    return {
        "model": settings.llm_model,
        "configured": bool(settings.llm_api_key) or settings.llm_provider == "ollama",
        "last_24h": totals(now - timedelta(days=1)),
        "last_30d": totals(now - timedelta(days=30)),
    }
