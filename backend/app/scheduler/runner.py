import logging
from collections.abc import Callable
from dataclasses import dataclass

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.clock import IST, now_ist, utc_now
from app.scheduler import pipeline

log = logging.getLogger("scheduler")


@dataclass(frozen=True)
class JobSpec:
    id: str
    title: str
    schedule: str
    trigger: CronTrigger
    run: Callable[[], None]
    job_name: str | None = None
    trading_day_only: bool = False
    market_hours_only: bool = False

    @property
    def label(self) -> str:
        return f"{self.title} ({self.schedule})"


def _tracked(name: str, fn, trading_day_only: bool = False):
    return lambda: pipeline.run_tracked(name, fn, trading_day_only)


JOBS = (
    JobSpec(
        "news",
        "Collect news + AI sentiment",
        "hourly at :05, 07:05–22:05",
        CronTrigger(hour="7-22", minute=5, timezone=IST),
        _tracked("ingest_news", pipeline.news_job),
        job_name="ingest_news",
    ),
    JobSpec(
        "open_fill",
        "Fill paper orders at the open",
        "09:16, 09:25, 09:40 on trading days",
        CronTrigger(day_of_week="mon-fri", hour=9, minute="16,25,40", timezone=IST),
        _tracked("paper_open_fill", pipeline.open_fill_job, trading_day_only=True),
        job_name="paper_open_fill",
        trading_day_only=True,
    ),
    JobSpec(
        "monitor",
        "Update prices, check stops and targets",
        "every 2 min, 09:15–15:30",
        CronTrigger(day_of_week="mon-fri", hour="9-15", minute="*/2", timezone=IST),
        pipeline.monitor_job,
        trading_day_only=True,
        market_hours_only=True,
    ),
    JobSpec(
        "end_of_day",
        "Candles → indicators → signals → AI research → paper EOD → next-day orders",
        "15:50 on trading days",
        CronTrigger(day_of_week="mon-fri", hour=15, minute=50, timezone=IST),
        _tracked("end_of_day", pipeline.end_of_day_job, trading_day_only=True),
        job_name="end_of_day",
        trading_day_only=True,
    ),
    JobSpec(
        "weekly",
        "Holidays, NIFTY 500 refresh, walk-forward backtest",
        "Sunday 10:00",
        CronTrigger(day_of_week="sun", hour=10, minute=0, timezone=IST),
        _tracked("weekly_maintenance", pipeline.weekly_job),
        job_name="weekly_maintenance",
    ),
)

_beats: dict[str, dict] = {}


def _with_beat(spec: JobSpec) -> Callable[[], None]:
    def run() -> None:
        started = utc_now()
        try:
            spec.run()
        except Exception as exc:
            _beats[spec.id] = {"started_at": started, "finished_at": utc_now(), "status": "failed", "error": str(exc)}
            raise
        _beats[spec.id] = {"started_at": started, "finished_at": utc_now(), "status": "success", "error": None}

    return run


def last_beat(job_id: str) -> dict | None:
    return _beats.get(job_id)


def is_running() -> bool:
    return _scheduler is not None


_scheduler: BackgroundScheduler | None = None


def start() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    scheduler = BackgroundScheduler(
        timezone=IST, job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 1800}
    )
    for spec in JOBS:
        scheduler.add_job(_with_beat(spec), spec.trigger, id=spec.id, name=spec.label, replace_existing=True)
    scheduler.start()
    _scheduler = scheduler
    log.info("scheduler started with %d jobs", len(JOBS))
    return scheduler


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def run_now(job_id: str) -> bool:
    spec = next((s for s in JOBS if s.id == job_id), None)
    if spec is None:
        return False
    if _scheduler is not None:
        _scheduler.add_job(_with_beat(spec), id=f"{job_id}-manual-{now_ist().timestamp():.0f}", name=f"{spec.label} (manual)")
    else:
        _with_beat(spec)()
    return True
