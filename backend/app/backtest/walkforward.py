import itertools
from dataclasses import asdict, dataclass, field, replace
from datetime import date

import numpy as np
import pandas as pd

from app.backtest.data import MarketData
from app.backtest.engine import PortfolioConfig, SimulationResult, TradeRecord, compute_metrics, simulate
from app.signals.scoring import DEFAULT_PARAMS, StrategyParams

ALL_REGIMES = ("bull", "neutral", "volatile", "bear")
GRID = {
    "buy_threshold": (70.0, 75.0, 80.0, 85.0),
    "stop_atr": (1.5, 2.0, 3.0),
    "target_atr": (3.0, 4.0, 6.0),
    "max_hold_days": (15, 30),
    "entry_regimes": (ALL_REGIMES, ("bull", "neutral"), ("bull",)),
}
MOMENTUM_GRID = {
    "top_n": (10, 20),
    "exit_rank": (40, 60),
    "stop_atr": (2.0, 3.0, 4.0),
    "target_atr": (6.0, 10.0),
    "trail_atr": (3.0, 5.0),
    "max_hold_days": (60, 90),
}
MOMENTUM_V2_GRID = {
    "top_n": (10, 20),
    "exit_rank": (60, 100),
    "stop_atr": (3.0, 4.0),
    "trail_atr": (5.0, 6.0),
}
MIN_TRAIN_TRADES = 20


def grid_for(params: StrategyParams) -> dict:
    if params.model != "momentum":
        return GRID
    return MOMENTUM_V2_GRID if params.sizing == "equal" else MOMENTUM_GRID


@dataclass
class Fold:
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    params: dict
    train_metrics: dict
    test_metrics: dict


@dataclass
class WalkForwardResult:
    folds: list[Fold]
    recommended: StrategyParams
    oos: SimulationResult
    combos_tested: int
    stability: dict = field(default_factory=dict)


def params_dict(params: StrategyParams) -> dict:
    data = asdict(params)
    data["entry_regimes"] = list(params.entry_regimes)
    return data


def params_from_dict(data: dict) -> StrategyParams:
    allowed = {f for f in StrategyParams.__dataclass_fields__}
    clean = {k: v for k, v in data.items() if k in allowed}
    if "entry_regimes" in clean:
        clean["entry_regimes"] = tuple(clean["entry_regimes"])
    return StrategyParams(**clean)


def objective(metrics: dict) -> float:
    if metrics.get("trades", 0) < MIN_TRAIN_TRADES:
        return -np.inf
    penalty = max(0.0, -metrics["max_drawdown_pct"] - 25) * 0.05
    return metrics["sharpe"] - penalty


def candidates(base: StrategyParams, grid: dict = GRID) -> list[StrategyParams]:
    keys = list(grid)
    return [
        replace(base, **dict(zip(keys, values, strict=True))) for values in itertools.product(*(grid[k] for k in keys))
    ]


def fold_windows(dates: np.ndarray, warmup_start: date, train_months: int, test_months: int) -> list[tuple]:
    first, last = pd.Timestamp(warmup_start), pd.Timestamp(dates[-1])
    test_start = first + pd.DateOffset(months=train_months)
    windows = []
    while test_start <= last:
        test_end = min(test_start + pd.DateOffset(months=test_months) - pd.Timedelta(days=1), last)
        train_start = test_start - pd.DateOffset(months=train_months)
        windows.append(
            (train_start.date(), (test_start - pd.Timedelta(days=1)).date(), test_start.date(), test_end.date())
        )
        test_start = test_start + pd.DateOffset(months=test_months)
    return windows


def stitch(results: list[SimulationResult], capital: float) -> SimulationResult:
    dates: list[str] = []
    equity: list[float] = []
    bench: list[float | None] = []
    trades: list[TradeRecord] = []
    level = capital
    bench_level = None
    for result in results:
        if not result.equity:
            continue
        first_bench = next((b for b in result.benchmark if b is not None), None)
        fold_base = bench_level if bench_level is not None else first_bench
        for d, e, b in zip(result.dates, result.equity, result.benchmark, strict=True):
            dates.append(d)
            equity.append(round(level * e / capital, 2))
            bench.append(round(fold_base * b / first_bench, 2) if b is not None and first_bench else None)
        level = equity[-1]
        bench_level = next((b for b in reversed(bench) if b is not None), bench_level)
        trades.extend(result.trades)
    stitched = SimulationResult(dates=dates, equity=equity, benchmark=bench, trades=trades)
    stitched.metrics = compute_metrics(stitched, capital)
    return stitched


def walk_forward(
    data: MarketData,
    base: StrategyParams | None = None,
    config: PortfolioConfig | None = None,
    warmup_start: date = date(2022, 9, 1),
    train_months: int = 24,
    test_months: int = 6,
    grid: dict | None = None,
) -> WalkForwardResult:
    base = base or DEFAULT_PARAMS
    grid = grid or grid_for(base)
    config = config or PortfolioConfig()
    combos = candidates(base, grid)
    folds: list[Fold] = []
    tests: list[SimulationResult] = []
    chosen: StrategyParams = base
    for train_start, train_end, test_start, test_end in fold_windows(
        data.dates, warmup_start, train_months, test_months
    ):
        train = data.window(train_start, train_end)
        scored = [(objective(simulate(train, p, config).metrics), p) for p in combos]
        best_score, best = max(scored, key=lambda item: item[0])
        chosen = best if np.isfinite(best_score) else base
        train_result = simulate(train, chosen, config)
        test_result = simulate(data.window(test_start, test_end), chosen, config)
        tests.append(test_result)
        folds.append(
            Fold(
                str(train_start),
                str(train_end),
                str(test_start),
                str(test_end),
                params_dict(chosen),
                train_result.metrics,
                test_result.metrics,
            )
        )
    keys = list(grid)
    stability = {
        key: {k: int(v) for k, v in pd.Series([str(f.params[key]) for f in folds]).value_counts().items()}
        if folds
        else {}
        for key in keys
    }
    return WalkForwardResult(folds, chosen, stitch(tests, config.capital), len(combos), stability)
