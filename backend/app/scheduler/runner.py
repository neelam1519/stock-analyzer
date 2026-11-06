import logging
from dataclasses import dataclass

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.clock import IST, now_ist
from app.scheduler import pipeline

log = logging.getLogger("scheduler")


@dataclass(frozen=True)
class JobSpec:
    id: str
    label: str
    trigger: CronTrigger
    run: object


def _tracked(name: str, fn, trading_day_only: bool = False):
    return lambda: pipeline.run_tracked(name, fn, trading_day_only)


JOBS = (
    JobSpec(
        "news",
        "Collect news + AI sentiment (hourly 07:00–22:00)",
        CronTrigger(hour="7-22", minute=5, timezone=IST),
        _tracked("ingest_news", pipeline.news_job),
    ),
    JobSpec(
        "open_fill",
        "Fill paper orders at the open via Kite LTP (09:16, 09:25, 09:40)",
        CronTrigger(day_of_week="mon-fri", hour=9, minute="16,25,40", timezone=IST),
        _tracked("paper_open_fill", pipeline.open_fill_job, trading_day_only=True),
    ),
    JobSpec(
        "monitor",
        "Check stops and targets via Kite LTP (every 2 min in market hours)",
        CronTrigger(day_of_week="mon-fri", hour="9-15", minute="*/2", timezone=IST),
        pipeline.monitor_job,
    ),
    JobSpec(
        "end_of_day",
        "Candles → indicators → signals → AI research → paper EOD → next-day orders (15:50)",
        CronTrigger(day_of_week="mon-fri", hour=15, minute=50, timezone=IST),
        _tracked("end_of_day", pipeline.end_of_day_job, trading_day_only=True),
    ),
    JobSpec(
        "weekly",
        "Holidays, NIFTY 500 refresh, walk-forward backtest (Sun 10:00)",
        CronTrigger(day_of_week="sun", hour=10, minute=0, timezone=IST),
        _tracked("weekly_maintenance", pipeline.weekly_job),
    ),
)

_scheduler: BackgroundScheduler | None = None


def start() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    scheduler = BackgroundScheduler(
        timezone=IST, job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 1800}
    )
    for spec in JOBS:
        scheduler.add_job(spec.run, spec.trigger, id=spec.id, name=spec.label, replace_existing=True)
    scheduler.start()
    _scheduler = scheduler
    log.info("scheduler started with %d jobs", len(JOBS))
    return scheduler


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def status() -> list[dict]:
    jobs = {job.id: job for job in _scheduler.get_jobs()} if _scheduler else {}
    return [
        {
            "id": spec.id,
            "label": spec.label,
            "enabled": spec.id in jobs,
            "next_run": jobs[spec.id].next_run_time.isoformat()
            if spec.id in jobs and jobs[spec.id].next_run_time
            else None,
        }
        for spec in JOBS
    ]


def run_now(job_id: str) -> bool:
    spec = next((s for s in JOBS if s.id == job_id), None)
    if spec is None:
        return False
    if _scheduler is not None:
        _scheduler.add_job(spec.run, id=f"{job_id}-manual-{now_ist().timestamp():.0f}", name=f"{spec.label} (manual)")
    else:
        spec.run()
    return True
