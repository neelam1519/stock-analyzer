import logging
from collections.abc import Callable
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.indicators import update_indicators
from app.backtest.service import run_walk_forward
from app.core.calendar import cached_holidays, is_trading_day, refresh_holidays
from app.core.clock import is_market_hours, now_ist
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.jobs import JobAlreadyRunning, start_job, track_job
from app.ingest.candles import DAILY, HOURLY, ingest_candles
from app.ingest.universe import fetch_nifty500, sync_instruments
from app.kite import service
from app.llm.client import LiteLLMCompleter, LLMNotConfigured
from app.llm.sentiment import analyze_news
from app.models import Instrument, PaperOrder, Position
from app.news.collector import collect_news
from app.news.matcher import build_matcher, seed_aliases
from app.signals.generator import generate_signals
from app.signals.params import load_active_params
from app.signals.research import research_top_picks, shortlist
from app.trading import live, paper

log = logging.getLogger("scheduler")


def run_tracked(name: str, fn: Callable[[Session], str], trading_day_only: bool = False) -> None:
    with get_sessionmaker()() as db:
        if trading_day_only and not is_trading_day(now_ist().date(), cached_holidays(db)):
            return
        try:
            run = start_job(db, name)
        except JobAlreadyRunning:
            log.info("%s already running", name)
            return
        try:
            with track_job(db, run):
                run.details = (fn(db) or "")[:1000]
        except Exception:
            log.exception("%s failed", name)


def news_job(db: Session) -> str:
    seed_aliases(db)
    collected = collect_news(db, build_matcher(db))
    try:
        scored = analyze_news(db, LiteLLMCompleter(db))
        return f"new={collected.inserted} tagged={collected.mapped} scored={scored.scored} calls={scored.calls}"
    except LLMNotConfigured:
        return f"new={collected.inserted} tagged={collected.mapped} llm=not_configured"


def ltp_prices(db: Session, instrument_ids: set[int]) -> dict[int, float]:
    if not instrument_ids:
        return {}
    kite = service.market_client(db)
    rows = db.execute(
        select(Instrument.id, Instrument.exchange, Instrument.tradingsymbol).where(Instrument.id.in_(instrument_ids))
    ).all()
    keys = {f"{exchange}:{symbol}": iid for iid, exchange, symbol in rows}
    quotes = kite.ltp(list(keys))
    return {keys[k]: float(v["last_price"]) for k, v in quotes.items() if k in keys and v.get("last_price")}


def open_fill_job(db: Session) -> str:
    ids = set(db.scalars(select(PaperOrder.instrument_id).where(PaperOrder.status == "pending")))
    if not ids:
        return "no pending orders"
    result = paper.fill_orders(db, ltp_prices(db, ids))
    return "live LTP " + result.summary()


def monitor_once(db: Session) -> paper.PaperResult | None:
    ids = set(db.scalars(select(Position.instrument_id).where(Position.book == paper.BOOK, Position.status == "open")))
    if not ids:
        return None
    return paper.monitor_positions(db, ltp_prices(db, ids))


def live_sync_once(db: Session) -> str | None:
    live.expire_stale(db)
    result = live.sync_live(db, service.market_client(db))
    if result.filled or result.closed or result.failed or result.notes:
        return result.summary() + (" " + "; ".join(result.notes) if result.notes else "")
    return None


def monitor_job() -> None:
    with get_sessionmaker()() as db:
        if not is_trading_day(now_ist().date(), cached_holidays(db)) or not is_market_hours():
            return
        try:
            summary = live_sync_once(db)
            if summary:
                run_tracked("live_sync", lambda _db: summary)
        except (service.KiteNotConnected, service.KiteNotConfigured):
            pass
        except Exception:
            log.exception("live sync failed")
        try:
            result = monitor_once(db)
        except (service.KiteNotConnected, service.KiteNotConfigured):
            return
        except Exception:
            log.exception("monitor failed")
            return
        if result and result.closed:
            run_tracked("paper_monitor", lambda _db: f"intraday exits={result.closed}")


def end_of_day_job(db: Session) -> str:
    today = now_ist().date()
    steps = []
    kite = service.market_client(db)
    daily = ingest_candles(db, kite, DAILY)
    hourly = ingest_candles(db, kite, HOURLY)
    steps.append(f"candles day+{daily.inserted} 60m+{hourly.inserted}")
    update_indicators(db)
    result, regime = generate_signals(db)
    steps.append(f"signals {result.as_of} {regime.name} buy={result.buys}")
    if result.as_of != today:
        steps.append("no candle for today, paper skipped")
        return "; ".join(steps)
    research_day(db, result.as_of)
    eod = paper.end_of_day(db, today)
    plan = paper.plan_entries(db, today)
    paper.snapshot(db, today)
    steps.append(f"paper eod {eod.summary()}; plan {plan.summary()}")
    live_eod = live.live_end_of_day(db, kite, today)
    approvals = live.create_entry_approvals(db, today)
    steps.append(f"live trailed={live_eod.trailed} exit_requests={live_eod.exit_requests} approvals={approvals}")
    return "; ".join(steps)


def research_day(db: Session, as_of: date) -> str:
    try:
        llm = LiteLLMCompleter(db)
    except LLMNotConfigured:
        return "llm not configured"
    params, _ = load_active_params(db)
    limit = get_settings().research_top_n
    symbols = [i.tradingsymbol for i, _ in shortlist(db, as_of, params.name, limit)]
    if not symbols:
        return "no BUY candidates"
    collect_news(db, build_matcher(db), symbols)
    analyze_news(db, llm)
    generate_signals(db, as_of)
    result = research_top_picks(db, llm, as_of, params.name, limit)
    return f"reports={result.reports}"


def weekly_job(db: Session) -> str:
    holidays = refresh_holidays(db, force=True)
    synced = sync_instruments(db, service.market_client(db), fetch_nifty500())
    run = run_walk_forward(db)
    return f"holidays={len(holidays)} instruments={synced} walk_forward=#{run.id} oos_cagr={run.cagr}"
