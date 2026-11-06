from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.models import JobRun

STALE_AFTER = timedelta(hours=2)


class JobAlreadyRunning(RuntimeError):
    pass


class JobHandle:
    def __init__(self, run: JobRun):
        self.run = run
        self.rows = 0

    def add(self, count: int) -> None:
        self.rows += count


def ensure_not_running(db: Session, job_name: str) -> None:
    running = db.scalar(
        select(JobRun.id).where(
            JobRun.job_name == job_name,
            JobRun.status == "running",
            JobRun.started_at > utc_now() - STALE_AFTER,
        )
    )
    if running:
        raise JobAlreadyRunning(job_name)


def start_job(db: Session, job_name: str) -> JobRun:
    ensure_not_running(db, job_name)
    run = JobRun(job_name=job_name, started_at=utc_now(), status="running")
    db.add(run)
    db.commit()
    return run


@contextmanager
def track_job(db: Session, run: JobRun) -> Iterator[JobHandle]:
    handle = JobHandle(run)
    try:
        yield handle
    except Exception as exc:
        db.rollback()
        run.status = "failed"
        run.error = f"{type(exc).__name__}: {exc}"[:4000]
        raise
    else:
        run.status = "success"
    finally:
        run.finished_at = utc_now()
        run.rows_affected = handle.rows
        db.add(run)
        db.commit()
