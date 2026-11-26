import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.ingest import job_dict, start_or_409
from app.backtest import service
from app.core.db import get_db, get_sessionmaker
from app.core.jobs import track_job
from app.models import BacktestRun, BacktestTrade, DailyCandle, Instrument, JobRun
from app.signals.params import load_active_params, reset_active_params, save_active_params, to_dict
from app.signals.scoring import DEFAULT_PARAMS

router = APIRouter(tags=["backtests"])


def _run_job(run_id: int, mode: str) -> None:
    with get_sessionmaker()() as db:
        job_run = db.get(JobRun, run_id)
        with track_job(db, job_run) as job:
            run = service.run_walk_forward(db) if mode == "walk_forward" else service.run_single(db)
            job.add(run.trades_count)
            job_run.details = f"backtest_id={run.id} cagr={run.cagr} sharpe={run.sharpe} trades={run.trades_count}"


@router.post("/backtests/run", status_code=202)
def run_backtest(
    background: BackgroundTasks,
    mode: str = Query(default="single", pattern="^(single|walk_forward)$"),
    db: Session = Depends(get_db),
) -> dict:
    if db.scalar(select(DailyCandle.instrument_id).limit(1)) is None:
        raise HTTPException(status_code=409, detail="No market data yet: download candles first")
    run = start_or_409(db, f"backtest_{mode}", needs_kite=False)
    background.add_task(_run_job, run.id, mode)
    return job_dict(run)


def _summary(run: BacktestRun) -> dict:
    metrics = json.loads(run.metrics_json or "{}")
    return {
        "id": run.id,
        "kind": run.kind,
        "strategy": run.strategy,
        "created_at": run.created_at.isoformat() + "Z" if run.created_at else None,
        "start": run.start_date.isoformat(),
        "end": run.end_date.isoformat(),
        "cagr_pct": metrics.get("cagr_pct"),
        "max_drawdown_pct": metrics.get("max_drawdown_pct"),
        "sharpe": metrics.get("sharpe"),
        "win_rate_pct": metrics.get("win_rate_pct"),
        "trades": metrics.get("trades"),
        "benchmark_cagr_pct": metrics.get("benchmark_cagr_pct"),
        "params": json.loads(run.params_json),
    }


@router.get("/backtests")
def list_backtests(limit: int = Query(default=30, le=200), db: Session = Depends(get_db)) -> dict:
    runs = db.scalars(select(BacktestRun).order_by(BacktestRun.id.desc()).limit(limit))
    return {"items": [_summary(r) for r in runs]}


def _get(db: Session, run_id: int) -> BacktestRun:
    run = db.get(BacktestRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Backtest not found")
    return run


@router.get("/backtests/{run_id}")
def backtest_detail(run_id: int, db: Session = Depends(get_db)) -> dict:
    run = _get(db, run_id)
    trades = db.execute(
        select(BacktestTrade, Instrument.tradingsymbol)
        .join(Instrument, Instrument.id == BacktestTrade.instrument_id)
        .where(BacktestTrade.run_id == run.id)
        .order_by(BacktestTrade.entry_date.desc())
        .limit(300)
    ).all()
    return {
        **_summary(run),
        "metrics": json.loads(run.metrics_json or "{}"),
        "equity": json.loads(run.equity_json or "[]"),
        "trades": [
            {
                "symbol": symbol,
                "entry_date": t.entry_date.isoformat(),
                "entry_price": float(t.entry_price),
                "exit_date": t.exit_date.isoformat() if t.exit_date else None,
                "exit_price": float(t.exit_price) if t.exit_price is not None else None,
                "qty": t.qty,
                "pnl": float(t.pnl) if t.pnl is not None else None,
                "exit_reason": t.exit_reason,
            }
            for t, symbol in trades
        ],
    }


@router.delete("/backtests/{run_id}", status_code=204)
def delete_backtest(run_id: int, db: Session = Depends(get_db)) -> None:
    _get(db, run_id)
    service.delete_run(db, run_id)


@router.post("/backtests/{run_id}/apply")
def apply_backtest_params(run_id: int, db: Session = Depends(get_db)) -> dict:
    run = _get(db, run_id)
    save_active_params(db, service.run_params(run), f"backtest #{run.id} ({run.kind})")
    return strategy_params(db)


@router.get("/strategy/params")
def strategy_params(db: Session = Depends(get_db)) -> dict:
    params, source = load_active_params(db)
    return {"active": to_dict(params), "source": source or "defaults", "defaults": to_dict(DEFAULT_PARAMS)}


@router.post("/strategy/params/reset")
def reset_strategy_params(db: Session = Depends(get_db)) -> dict:
    reset_active_params(db)
    return strategy_params(db)
