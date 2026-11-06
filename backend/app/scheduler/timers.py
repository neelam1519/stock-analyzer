from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.calendar import cached_holidays, is_trading_day, next_trading_day
from app.core.clock import IST, MARKET_CLOSE, MARKET_OPEN, now_ist
from app.models import (
    BacktestRun,
    DailyCandle,
    JobRun,
    KiteSession,
    NewsArticle,
    NewsSentiment,
    Position,
    ResearchReport,
    Signal,
)
from app.scheduler import runner
from app.scheduler.runner import JobSpec

MAX_STEPS = 500


def iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def in_market_hours(moment: datetime) -> bool:
    return MARKET_OPEN <= moment.astimezone(IST).time() <= MARKET_CLOSE


def next_fire(spec: JobSpec, now: datetime, holidays: set[date]) -> datetime | None:
    moment = spec.trigger.get_next_fire_time(None, now)
    for _ in range(MAX_STEPS):
        if moment is None:
            return None
        local = moment.astimezone(IST)
        if spec.trading_day_only and not is_trading_day(local.date(), holidays):
            moment = spec.trigger.get_next_fire_time(
                None, datetime.combine(local.date() + timedelta(days=1), time(0), IST)
            )
            continue
        if spec.market_hours_only and not in_market_hours(local):
            moment = spec.trigger.get_next_fire_time(moment, moment + timedelta(seconds=1))
            continue
        return moment
    return None


def market_window(now: datetime, holidays: set[date]) -> dict:
    now = now.astimezone(IST)
    day = now.date()
    trading = is_trading_day(day, holidays)
    opens = datetime.combine(day, MARKET_OPEN, IST)
    closes = datetime.combine(day, MARKET_CLOSE, IST)
    if trading and opens <= now <= closes:
        return {"open": True, "trading_day": True, "opens_at": None, "closes_at": iso_utc(closes)}
    next_day = day if trading and now < opens else next_trading_day(day, holidays)
    return {
        "open": False,
        "trading_day": trading,
        "opens_at": iso_utc(datetime.combine(next_day, MARKET_OPEN, IST)),
        "closes_at": None,
    }


def _run_dict(run: JobRun | None) -> dict | None:
    if run is None:
        return None
    return {
        "started_at": iso_utc(run.started_at),
        "finished_at": iso_utc(run.finished_at),
        "status": run.status,
        "details": run.details,
        "error": (run.error or "")[:300] or None,
    }


def _beat_dict(beat: dict | None) -> dict | None:
    if beat is None:
        return None
    return {
        "started_at": iso_utc(beat["started_at"]),
        "finished_at": iso_utc(beat["finished_at"]),
        "status": beat["status"],
        "details": None,
        "error": beat["error"],
    }


def last_run(db: Session, spec: JobSpec) -> dict | None:
    if spec.job_name is None:
        return _beat_dict(runner.last_beat(spec.id))
    run = db.scalar(select(JobRun).where(JobRun.job_name == spec.job_name).order_by(JobRun.started_at.desc()).limit(1))
    return _run_dict(run)


def jobs(db: Session, now: datetime, holidays: set[date]) -> list[dict]:
    enabled = runner.is_running()
    return [
        {
            "id": spec.id,
            "title": spec.title,
            "schedule": spec.schedule,
            "enabled": enabled,
            "next_run": iso_utc(next_fire(spec, now, holidays)) if enabled else None,
            "last_run": last_run(db, spec),
        }
        for spec in runner.JOBS
    ]


def freshness(db: Session) -> list[dict]:
    candle_day = db.scalar(select(func.max(DailyCandle.trade_date)))
    signal_day = db.scalar(select(func.max(Signal.as_of_date)))
    items = [
        (
            "prices",
            "Live prices of open positions",
            db.scalar(select(func.max(Position.last_price_at)).where(Position.status == "open")),
            None,
            "monitor",
        ),
        ("news", "News articles", db.scalar(select(func.max(NewsArticle.created_at))), None, "news"),
        ("sentiment", "News AI sentiment", db.scalar(select(func.max(NewsSentiment.created_at))), None, "news"),
        ("candles", "Daily candles", None, candle_day, "end_of_day"),
        ("signals", "Signals", db.scalar(select(func.max(Signal.created_at))), signal_day, "end_of_day"),
        ("research", "AI research", db.scalar(select(func.max(ResearchReport.created_at))), None, "end_of_day"),
        ("backtest", "Walk-forward backtest", db.scalar(select(func.max(BacktestRun.created_at))), None, "weekly"),
    ]
    return [
        {
            "key": key,
            "label": label,
            "at": iso_utc(at),
            "as_of": as_of.isoformat() if as_of else None,
            "job": job,
        }
        for key, label, at, as_of, job in items
    ]


def kite(db: Session) -> dict:
    session = db.scalar(select(KiteSession).order_by(KiteSession.login_time.desc(), KiteSession.id.desc()))
    if session is None:
        return {"login_at": None, "expires_at": None}
    return {"login_at": iso_utc(session.login_time), "expires_at": iso_utc(session.expires_at)}


def timers(db: Session, now: datetime | None = None) -> dict:
    now = (now or now_ist()).astimezone(IST)
    holidays = cached_holidays(db)
    return {
        "now": iso_utc(now),
        "market": market_window(now, holidays),
        "kite": kite(db),
        "jobs": jobs(db, now, holidays),
        "data": freshness(db),
    }
