import math
from dataclasses import dataclass, field, replace

import numpy as np

from app.backtest.data import MarketData
from app.signals.scoring import StrategyParams

REGIME_SIZE = {"bull": 1.0, "neutral": 0.75, "volatile": 0.5, "bear": 0.5, "unknown": 0.5}


@dataclass(frozen=True)
class PortfolioConfig:
    capital: float = 1_000_000.0
    risk_per_trade_pct: float = 1.0
    max_positions: int = 8
    max_position_pct: float = 20.0
    max_per_sector: int = 2
    cost_pct: float = 0.12
    fixed_sell_cost: float = 16.0
    slippage_pct: float = 0.05
    cooldown_days: int = 5


@dataclass
class Position:
    col: int
    entry_index: int
    entry_price: float
    qty: int
    stop: float
    target: float
    initial_risk: float
    highest_close: float
    score: float


@dataclass
class TradeRecord:
    symbol: str
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    qty: int
    pnl: float
    return_pct: float
    r_multiple: float
    hold_days: int
    exit_reason: str


@dataclass
class SimulationResult:
    dates: list[str]
    equity: list[float]
    benchmark: list[float]
    trades: list[TradeRecord] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)


def momentum_mask(data: MarketData, params: StrategyParams) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rank = data.momentum_rank
    eligible = ~np.isnan(rank)
    counts = eligible.sum(axis=1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        total = np.where(eligible, 100 * (1 - (rank - 1) / np.maximum(counts, 1)), 0.0)
        buys = eligible & (rank <= params.top_n) & (data.atr > 0) & ~np.isnan(data.close)
        sells = ~(eligible & (rank <= params.exit_rank))
    if params.market_filter:
        buys &= data.market_ok[:, None]
    return total, buys, sells


def buy_mask(data: MarketData, params: StrategyParams) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if params.model == "momentum":
        return momentum_mask(data, params)
    adjustment = np.array([params.regime_adjustment.get(r, -10.0) for r in data.regime])[:, None]
    total = np.clip(data.technical + adjustment, 0, 100)
    with np.errstate(invalid="ignore"):
        buys = (
            (total >= params.buy_threshold)
            & (data.close > data.ema50)
            & (data.rsi < params.max_rsi)
            & (data.atr > 0)
            & (data.traded_value_cr >= params.min_traded_value_cr)
        )
        sells = (total <= params.sell_threshold) | ((data.close < data.ema50) & (data.macd < data.macd_signal))
    allowed = np.isin(data.regime, list(params.entry_regimes))[:, None]
    return np.nan_to_num(total), buys & allowed & ~np.isnan(data.close), sells


def sized_config(config: PortfolioConfig, params: StrategyParams) -> PortfolioConfig:
    if params.sizing != "equal":
        return config
    return replace(config, max_positions=params.slots, max_position_pct=100.0 / params.slots)


def simulate(data: MarketData, params: StrategyParams, config: PortfolioConfig | None = None) -> SimulationResult:
    config = sized_config(config or PortfolioConfig(), params)
    equal_weight = params.sizing == "equal"
    total, buys, sells = buy_mask(data, params)
    n_days = len(data.dates)
    cash = config.capital
    positions: dict[int, Position] = {}
    last_exit: dict[int, int] = {}
    pending_entries: list[tuple[int, float, float]] = []
    pending_exits: set[int] = set()
    equity_curve: list[float] = []
    trades: list[TradeRecord] = []
    cost = config.cost_pct / 100
    slip = config.slippage_pct / 100

    def close_position(col: int, day: int, price: float, reason: str) -> None:
        nonlocal cash
        pos = positions.pop(col)
        fill = price * (1 - slip)
        proceeds = fill * pos.qty
        cash += proceeds - proceeds * cost - config.fixed_sell_cost
        invested = pos.entry_price * pos.qty * (1 + cost)
        pnl = proceeds - proceeds * cost - config.fixed_sell_cost - invested
        trades.append(
            TradeRecord(
                symbol=data.symbols[col],
                entry_date=str(data.dates[pos.entry_index]),
                entry_price=float(round(pos.entry_price, 2)),
                exit_date=str(data.dates[day]),
                exit_price=float(round(fill, 2)),
                qty=pos.qty,
                pnl=float(round(pnl, 2)),
                return_pct=float(round(pnl / invested * 100, 2)),
                r_multiple=float(round((fill - pos.entry_price) / pos.initial_risk, 2)) if pos.initial_risk else 0.0,
                hold_days=day - pos.entry_index,
                exit_reason=reason,
            )
        )
        last_exit[col] = day

    def mark_to_market(day: int) -> float:
        value = cash
        for col, pos in positions.items():
            price = data.close[day, col]
            value += pos.qty * (price if not math.isnan(price) else pos.entry_price)
        return value

    for day in range(n_days):
        for col in sorted(pending_exits):
            if col in positions and not math.isnan(data.open[day, col]):
                close_position(col, day, data.open[day, col], "signal")
        pending_exits.clear()

        for col, risk_budget, signal_atr in pending_entries:
            open_price = data.open[day, col]
            if col in positions or math.isnan(open_price) or len(positions) >= config.max_positions:
                continue
            entry = open_price * (1 + slip)
            stop = entry - params.stop_atr * signal_atr
            target = entry + params.target_atr * signal_atr
            risk_per_share = entry - stop
            if risk_per_share <= 0:
                continue
            equity_now = mark_to_market(max(day - 1, 0))
            qty = math.floor(
                min(
                    risk_budget / risk_per_share,
                    equity_now * config.max_position_pct / 100 / entry,
                    cash / (entry * (1 + cost)),
                )
            )
            if qty <= 0:
                continue
            cash -= entry * qty * (1 + cost)
            positions[col] = Position(
                col, day, entry, qty, stop, target, risk_per_share, entry, total[day - 1, col] if day else 0
            )
        pending_entries.clear()

        for col in list(positions):
            pos = positions[col]
            o, h, low, c = data.open[day, col], data.high[day, col], data.low[day, col], data.close[day, col]
            if math.isnan(c):
                continue
            if low <= pos.stop:
                close_position(col, day, min(o, pos.stop) if day > pos.entry_index else pos.stop, "stop")
                continue
            if h >= pos.target:
                close_position(col, day, max(o, pos.target) if day > pos.entry_index else pos.target, "target")
                continue
            pos.highest_close = max(pos.highest_close, c)
            atr = data.atr[day, col]
            if c >= pos.entry_price + pos.initial_risk:
                pos.stop = max(pos.stop, pos.entry_price)
            if params.trail_atr and not math.isnan(atr):
                pos.stop = max(pos.stop, pos.highest_close - params.trail_atr * atr)
            if params.max_hold_days and day - pos.entry_index >= params.max_hold_days:
                close_position(col, day, c, "time")
                continue
            if sells[day, col]:
                pending_exits.add(col)

        equity = mark_to_market(day)
        equity_curve.append(equity)

        if day + 1 < n_days:
            slots = config.max_positions - len(positions)
            if slots > 0:
                candidates = np.flatnonzero(buys[day])
                candidates = candidates[np.argsort(-total[day, candidates], kind="stable")]
                sector_count: dict[str, int] = {}
                for col in positions:
                    sector_count[data.sectors[col]] = sector_count.get(data.sectors[col], 0) + 1
                size = REGIME_SIZE.get(data.regime[day], 0.5)
                for col in candidates:
                    if slots == 0:
                        break
                    if col in positions or day - last_exit.get(col, -10_000) < config.cooldown_days:
                        continue
                    sector = data.sectors[col]
                    if sector_count.get(sector, 0) >= config.max_per_sector:
                        continue
                    budget = math.inf if equal_weight else equity * config.risk_per_trade_pct / 100 * size
                    pending_entries.append((col, budget, data.atr[day, col]))
                    sector_count[sector] = sector_count.get(sector, 0) + 1
                    slots -= 1

    if n_days:
        for col in list(positions):
            last = data.close[n_days - 1, col]
            close_position(col, n_days - 1, last if not math.isnan(last) else positions[col].entry_price, "end")
        equity_curve[-1] = cash

    result = SimulationResult(
        dates=[str(d) for d in data.dates],
        equity=[round(e, 2) for e in equity_curve],
        benchmark=[round(float(b), 2) if not math.isnan(b) else None for b in data.benchmark],
        trades=trades,
    )
    result.metrics = compute_metrics(result, config.capital)
    return result


def _max_drawdown(values: np.ndarray) -> float:
    if len(values) == 0:
        return 0.0
    peaks = np.maximum.accumulate(values)
    return float(np.min(values / peaks - 1) * 100)


def compute_metrics(result: SimulationResult, capital: float) -> dict:
    equity = np.array(result.equity, dtype=float)
    if len(equity) < 2:
        return {"trades": len(result.trades)}
    years = max(len(equity) / 252, 1 / 252)
    returns = np.diff(equity) / equity[:-1]
    sharpe = float(np.mean(returns) / np.std(returns) * math.sqrt(252)) if np.std(returns) > 0 else 0.0
    downside = returns[returns < 0]
    sortino = (
        float(np.mean(returns) / np.std(downside) * math.sqrt(252)) if len(downside) and np.std(downside) > 0 else 0.0
    )
    pnl = np.array([t.pnl for t in result.trades], dtype=float)
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    bench = np.array([b for b in result.benchmark if b is not None], dtype=float)
    bench_cagr = (bench[-1] / bench[0]) ** (1 / years) - 1 if len(bench) > 1 else 0.0
    cagr = (equity[-1] / capital) ** (1 / years) - 1
    metrics = {
        "start": result.dates[0],
        "end": result.dates[-1],
        "final_equity": round(float(equity[-1]), 2),
        "total_return_pct": round((equity[-1] / capital - 1) * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "max_drawdown_pct": round(_max_drawdown(equity), 2),
        "sharpe": round(sharpe, 2),
        "sortino": round(sortino, 2),
        "trades": len(result.trades),
        "win_rate_pct": round(len(wins) / len(pnl) * 100, 2) if len(pnl) else 0.0,
        "avg_win": round(float(wins.mean()), 2) if len(wins) else 0.0,
        "avg_loss": round(float(losses.mean()), 2) if len(losses) else 0.0,
        "profit_factor": round(float(wins.sum() / -losses.sum()), 2) if len(losses) and losses.sum() < 0 else None,
        "avg_r": round(float(np.mean([t.r_multiple for t in result.trades])), 2) if result.trades else 0.0,
        "avg_hold_days": round(float(np.mean([t.hold_days for t in result.trades])), 1) if result.trades else 0.0,
        "benchmark_cagr_pct": round(bench_cagr * 100, 2),
        "benchmark_max_drawdown_pct": round(_max_drawdown(bench), 2),
        "exit_reasons": {
            r: sum(t.exit_reason == r for t in result.trades) for r in ("stop", "target", "time", "signal", "end")
        },
    }
    return {k: (float(v) if isinstance(v, np.floating) else v) for k, v in metrics.items()}
