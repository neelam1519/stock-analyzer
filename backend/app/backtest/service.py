import json
from datetime import date

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.backtest.data import load_market_data
from app.backtest.engine import PortfolioConfig, SimulationResult, simulate
from app.backtest.walkforward import params_from_dict, walk_forward
from app.models import BacktestRun, BacktestTrade, Instrument
from app.signals.params import load_active_params, to_dict
from app.signals.scoring import StrategyParams

DEFAULT_START = "2022-09-01"
EQUITY_POINTS = 400


def downsample(result: SimulationResult) -> list[dict]:
    step = max(1, len(result.dates) // EQUITY_POINTS)
    idx = list(range(0, len(result.dates), step))
    if idx and idx[-1] != len(result.dates) - 1:
        idx.append(len(result.dates) - 1)
    return [{"time": result.dates[i], "equity": result.equity[i], "benchmark": result.benchmark[i]} for i in idx]


def _store(db: Session, kind: str, params: StrategyParams, result: SimulationResult, extra: dict) -> BacktestRun:
    m = result.metrics
    run = BacktestRun(
        strategy=params.name,
        kind=kind,
        params_json=json.dumps(to_dict(params)),
        start_date=date.fromisoformat(m["start"]),
        end_date=date.fromisoformat(m["end"]),
        cagr=m.get("cagr_pct"),
        max_drawdown=m.get("max_drawdown_pct"),
        win_rate=m.get("win_rate_pct"),
        sharpe=m.get("sharpe"),
        trades_count=m.get("trades", 0),
        metrics_json=json.dumps({**m, **extra}),
        equity_json=json.dumps(downsample(result)),
    )
    db.add(run)
    db.flush()
    ids = dict(db.execute(select(Instrument.tradingsymbol, Instrument.id)).all())
    rows = [
        {
            "run_id": run.id,
            "instrument_id": ids[t.symbol],
            "entry_date": date.fromisoformat(t.entry_date),
            "entry_price": t.entry_price,
            "exit_date": date.fromisoformat(t.exit_date),
            "exit_price": t.exit_price,
            "qty": t.qty,
            "pnl": t.pnl,
            "exit_reason": t.exit_reason,
        }
        for t in result.trades
        if t.symbol in ids
    ]
    for start in range(0, len(rows), 1000):
        db.execute(insert(BacktestTrade), rows[start : start + 1000])
    db.commit()
    return run


def run_single(db: Session, params: StrategyParams | None = None, start: str = DEFAULT_START) -> BacktestRun:
    params = params or load_active_params(db)[0]
    data = load_market_data(db)
    result = simulate(data.window(start, data.dates[-1]), params, PortfolioConfig())
    return _store(db, "single", params, result, {"config": PortfolioConfig().__dict__})


def run_walk_forward(db: Session) -> BacktestRun:
    data = load_market_data(db)
    wf = walk_forward(data, load_active_params(db)[0])
    folds = [f.__dict__ for f in wf.folds]
    return _store(
        db,
        "walk_forward",
        wf.recommended,
        wf.oos,
        {
            "folds": folds,
            "combos_tested": wf.combos_tested,
            "stability": wf.stability,
            "config": PortfolioConfig().__dict__,
        },
    )


def run_params(run: BacktestRun) -> StrategyParams:
    return params_from_dict(json.loads(run.params_json))


def delete_run(db: Session, run_id: int) -> None:
    db.execute(delete(BacktestTrade).where(BacktestTrade.run_id == run_id))
    db.execute(delete(BacktestRun).where(BacktestRun.id == run_id))
    db.commit()
