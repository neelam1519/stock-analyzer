from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db, get_sessionmaker
from app.core.jobs import JobAlreadyRunning, start_job, track_job
from app.ingest.candles import INTERVALS, ingest_candles
from app.ingest.universe import fetch_nifty500, sync_instruments
from app.kite import service
from app.models import JobRun

router = APIRouter(tags=["ingest"])


def job_dict(run: JobRun) -> dict:
    return {
        "id": run.id,
        "job_name": run.job_name,
        "status": run.status,
        "started_at": run.started_at.isoformat() + "Z",
        "finished_at": run.finished_at.isoformat() + "Z" if run.finished_at else None,
        "rows_affected": run.rows_affected,
        "details": run.details,
        "error": run.error,
    }


def start_or_409(db: Session, name: str, needs_kite: bool = True) -> JobRun:
    if needs_kite:
        try:
            service.market_client(db)
        except (service.KiteNotConnected, service.KiteNotConfigured) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        return start_job(db, name)
    except JobAlreadyRunning as exc:
        raise HTTPException(status_code=409, detail=f"{name} is already running") from exc


def _run_instruments(run_id: int) -> None:
    with get_sessionmaker()() as db:
        run = db.get(JobRun, run_id)
        with track_job(db, run) as job:
            job.add(sync_instruments(db, service.market_client(db), fetch_nifty500()))


def _run_candles(run_id: int, interval: str, symbols: list[str] | None) -> None:
    with get_sessionmaker()() as db:
        run = db.get(JobRun, run_id)
        with track_job(db, run) as job:
            result = ingest_candles(db, service.market_client(db), INTERVALS[interval], symbols)
            job.add(result.inserted)
            run.details = (
                f"instruments={result.instruments} skipped={result.skipped} "
                f"rebuilt={result.rebuilt} failed={result.failed}"
            )


@router.post("/ingest/instruments", status_code=202)
def ingest_instruments(background: BackgroundTasks, db: Session = Depends(get_db)) -> dict:
    run = start_or_409(db, "ingest_instruments")
    background.add_task(_run_instruments, run.id)
    return job_dict(run)


@router.post("/ingest/candles", status_code=202)
def ingest_candles_endpoint(
    background: BackgroundTasks,
    interval: str = Query(default="day", pattern="^(day|60m)$"),
    symbols: list[str] | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    run = start_or_409(db, f"ingest_candles_{interval}")
    background.add_task(_run_candles, run.id, interval, symbols)
    return job_dict(run)


@router.get("/jobs")
def list_jobs(limit: int = Query(default=20, le=200), db: Session = Depends(get_db)) -> dict:
    runs = db.scalars(select(JobRun).order_by(JobRun.started_at.desc()).limit(limit))
    return {"items": [job_dict(run) for run in runs]}
