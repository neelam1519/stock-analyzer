from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.analysis.indicators import INDICATOR_COLUMNS, update_indicators
from app.analysis.regime import market_regime
from app.api.ingest import job_dict, start_or_409
from app.core.config import get_settings
from app.core.db import get_db, get_sessionmaker
from app.core.jobs import track_job
from app.llm.client import LiteLLMCompleter, LLMNotConfigured
from app.llm.sentiment import analyze_news
from app.models import IndicatorDaily, Instrument, JobRun, ResearchReport, Signal
from app.news.collector import collect_news
from app.news.matcher import build_matcher
from app.signals.generator import generate_signals, latest_session
from app.signals.params import load_active_params
from app.signals.research import report_dict, research_top_picks, shortlist

router = APIRouter(tags=["signals"])


def _strategy(db: Session) -> str:
    return load_active_params(db)[0].name


def _run_analysis(run_id: int) -> None:
    with get_sessionmaker()() as db:
        run = db.get(JobRun, run_id)
        with track_job(db, run) as job:
            indicators = update_indicators(db)
            result, regime = generate_signals(db)
            job.add(indicators.inserted + result.scored)
            run.details = (
                f"indicators_new={indicators.inserted} as_of={result.as_of} regime={regime.name} "
                f"scored={result.scored} buy={result.buys} sell={result.sells}"
            )


def _run_research(run_id: int, limit: int) -> None:
    with get_sessionmaker()() as db:
        run = db.get(JobRun, run_id)
        with track_job(db, run) as job:
            as_of = latest_session(db)
            llm = LiteLLMCompleter(db)
            symbols = [i.tradingsymbol for i, _ in shortlist(db, as_of, _strategy(db), limit)]
            news = collect_news(db, build_matcher(db), symbols)
            scored = analyze_news(db, llm)
            generate_signals(db, as_of)
            result = research_top_picks(db, llm, as_of, _strategy(db), limit)
            job.add(result.reports)
            run.details = (
                f"picks={','.join(result.shortlisted)} news_new={news.inserted} news_scored={scored.scored} "
                f"reports={result.reports} failed={result.failed}"
                + (f" last_error={result.errors[-1]}" if result.errors else "")
            )[:1000]


@router.post("/analysis/run", status_code=202)
def run_analysis(background: BackgroundTasks, db: Session = Depends(get_db)) -> dict:
    run = start_or_409(db, "run_analysis", needs_kite=False)
    background.add_task(_run_analysis, run.id)
    return job_dict(run)


@router.post("/research/run", status_code=202)
def run_research(
    background: BackgroundTasks, limit: int = Query(default=10, ge=1, le=25), db: Session = Depends(get_db)
) -> dict:
    try:
        LiteLLMCompleter(db)
    except LLMNotConfigured as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if latest_session(db) is None:
        raise HTTPException(status_code=409, detail="Run analysis first")
    run = start_or_409(db, "research_top", needs_kite=False)
    background.add_task(_run_research, run.id, limit)
    return job_dict(run)


@router.get("/market/regime")
def regime(db: Session = Depends(get_db)) -> dict:
    return market_regime(db).as_dict()


def _num(value) -> float | None:
    return float(value) if value is not None else None


def _signal_dict(signal: Signal, instrument: Instrument, report: ResearchReport | None = None) -> dict:
    entry, stop, target = _num(signal.entry_price), _num(signal.stop_loss), _num(signal.target)
    reward_risk = round((target - entry) / (entry - stop), 2) if entry and stop and target and entry > stop else None
    return {
        "symbol": instrument.tradingsymbol,
        "name": instrument.name,
        "sector": instrument.sector,
        "as_of": signal.as_of_date.isoformat(),
        "action": signal.action,
        "score": _num(signal.score),
        "technical_score": _num(signal.technical_score),
        "news_score": _num(signal.news_score),
        "regime": signal.regime,
        "entry": entry,
        "stop": stop,
        "target": target,
        "reward_risk": reward_risk,
        "confidence": _num(signal.confidence),
        "rationale": signal.rationale,
        "research_verdict": report.verdict if report else None,
    }


@router.get("/signals")
def list_signals(
    as_of: date | None = None,
    action: str | None = Query(default=None, pattern="^(BUY|SELL|HOLD)$"),
    limit: int = Query(default=100, le=600),
    db: Session = Depends(get_db),
) -> dict:
    strategy = _strategy(db)
    as_of = as_of or db.scalar(select(func.max(Signal.as_of_date)).where(Signal.strategy == strategy))
    if as_of is None:
        return {"as_of": None, "counts": {}, "items": []}
    model = get_settings().llm_model
    base = and_(Signal.as_of_date == as_of, Signal.strategy == strategy)
    counts = dict(db.execute(select(Signal.action, func.count()).where(base).group_by(Signal.action)).all())
    query = (
        select(Signal, Instrument, ResearchReport)
        .join(Instrument, Instrument.id == Signal.instrument_id)
        .outerjoin(
            ResearchReport,
            and_(
                ResearchReport.instrument_id == Signal.instrument_id,
                ResearchReport.as_of_date == Signal.as_of_date,
                ResearchReport.model == model,
            ),
        )
        .where(base)
    )
    if action:
        query = query.where(Signal.action == action)
    order = Signal.score.asc() if action == "SELL" else Signal.score.desc()
    rows = db.execute(query.order_by(order, Instrument.tradingsymbol).limit(limit)).all()
    return {
        "as_of": as_of.isoformat(),
        "counts": counts,
        "items": [_signal_dict(signal, instrument, report) for signal, instrument, report in rows],
    }


@router.get("/stocks/{symbol}/analysis")
def stock_analysis(symbol: str, db: Session = Depends(get_db)) -> dict:
    instrument = db.scalar(select(Instrument).where(Instrument.tradingsymbol == symbol))
    if instrument is None:
        raise HTTPException(status_code=404, detail=f"Unknown symbol {symbol}")
    signal = db.scalar(
        select(Signal)
        .where(Signal.instrument_id == instrument.id, Signal.strategy == _strategy(db))
        .order_by(Signal.as_of_date.desc())
        .limit(1)
    )
    indicator = db.scalar(
        select(IndicatorDaily)
        .where(IndicatorDaily.instrument_id == instrument.id)
        .order_by(IndicatorDaily.trade_date.desc())
        .limit(1)
    )
    report = db.scalar(
        select(ResearchReport)
        .where(ResearchReport.instrument_id == instrument.id, ResearchReport.model == get_settings().llm_model)
        .order_by(ResearchReport.as_of_date.desc(), ResearchReport.created_at.desc())
        .limit(1)
    )
    return {
        "signal": _signal_dict(signal, instrument) if signal else None,
        "indicators": (
            {"as_of": indicator.trade_date.isoformat(), **{c: _num(getattr(indicator, c)) for c in INDICATOR_COLUMNS}}
            if indicator
            else None
        ),
        "research": report_dict(report) if report else None,
    }
