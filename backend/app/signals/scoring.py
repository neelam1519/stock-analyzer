from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class StrategyParams:
    name: str = "swing_v1"
    model: str = "score"
    buy_threshold: float = 70.0
    sell_threshold: float = 35.0
    news_weight: float = 15.0
    news_veto: float = -0.3
    stop_atr: float = 2.0
    target_atr: float = 4.0
    max_rsi: float = 75.0
    min_traded_value_cr: float = 5.0
    max_hold_days: int = 30
    trail_atr: float = 3.0
    entry_regimes: tuple[str, ...] = ("bull", "neutral", "volatile", "bear")
    regime_adjustment: dict = field(
        default_factory=lambda: {"bull": 0.0, "neutral": -5.0, "volatile": -10.0, "bear": -15.0, "unknown": -10.0}
    )
    top_n: int = 20
    exit_rank: int = 60
    market_filter: bool = False
    sizing: str = "risk"
    slots: int = 8


MOMENTUM = StrategyParams(
    name="momentum_v1",
    model="momentum",
    stop_atr=3.0,
    target_atr=10.0,
    trail_atr=5.0,
    max_hold_days=90,
    top_n=20,
    exit_rank=60,
    market_filter=True,
)
MOMENTUM_V2 = replace(
    MOMENTUM,
    name="momentum_v2",
    sizing="equal",
    slots=10,
    stop_atr=4.0,
    target_atr=100.0,
    max_hold_days=0,
    exit_rank=100,
)
DEFAULT_PARAMS = MOMENTUM_V2


@dataclass
class ScoreBreakdown:
    total: float
    technical: float
    news: float
    regime_adjustment: float
    action: str
    entry: float | None
    stop: float | None
    target: float | None
    confidence: float
    reasons: list[str]

    @property
    def rationale(self) -> str:
        return "; ".join(self.reasons)


def _get(row, key):
    value = row.get(key)
    return None if value is None else float(value)


def technical_score(row: dict) -> tuple[float, list[str]]:
    close, ema20, ema50, ema200 = (_get(row, k) for k in ("close", "ema20", "ema50", "ema200"))
    rsi, macd, macd_signal = _get(row, "rsi14"), _get(row, "macd"), _get(row, "macd_signal")
    adx, volume_ratio = _get(row, "adx14"), _get(row, "volume_ratio20")
    distance, rs = _get(row, "high52w_distance_pct"), _get(row, "relative_strength_nifty")
    score, reasons = 0.0, []

    if None not in (close, ema20, ema50, ema200):
        trend = 8 * (close > ema20) + 8 * (ema20 > ema50) + 8 * (ema50 > ema200) + 6 * (close > ema200)
        score += trend
        if trend == 30:
            reasons.append("Uptrend: close > EMA20 > EMA50 > EMA200")
        elif close < ema50:
            reasons.append("Below EMA50")

    if rsi is not None:
        if 50 <= rsi <= 68:
            score += 12
        elif 40 <= rsi < 50 or 68 < rsi <= 75:
            score += 6
        reasons.append(f"RSI {rsi:.0f}" + (" (overbought)" if rsi > 75 else ""))
    if macd is not None and macd_signal is not None:
        score += 8 * (macd > macd_signal) + 5 * (macd > 0)
        if macd > macd_signal:
            reasons.append("MACD above signal")

    if adx is not None:
        score += min(10.0, max(0.0, (adx - 15) / 15 * 10))
        if adx >= 25:
            reasons.append(f"Strong trend ADX {adx:.0f}")
    if rs is not None:
        score += min(10.0, max(0.0, rs / 15 * 10))
        reasons.append(f"RS {rs:+.1f}% vs NIFTY (3m)")

    if volume_ratio is not None:
        if 1.2 <= volume_ratio <= 3.5:
            score += 10
            reasons.append(f"Volume {volume_ratio:.1f}x avg")
        elif volume_ratio >= 1.0:
            score += 5

    if distance is not None:
        if distance >= -10:
            score += 15
            reasons.append(f"{abs(distance):.0f}% from 52w high")
        elif distance >= -20:
            score += 8
    return min(score, 100.0), reasons


def score_stock(
    row: dict,
    regime: str,
    news_sentiment: float | None = None,
    news_count: int = 0,
    traded_value_cr: float | None = None,
    params: StrategyParams | None = None,
) -> ScoreBreakdown:
    params = params or StrategyParams()
    technical, reasons = technical_score(row)
    news_points = (news_sentiment or 0.0) * params.news_weight
    if news_sentiment is not None and news_count:
        reasons.append(f"News {news_sentiment:+.2f} ({news_count} items)")
    adjustment = params.regime_adjustment.get(regime, -10.0)
    total = max(0.0, min(100.0, technical + news_points + adjustment))

    close, atr = _get(row, "close"), _get(row, "atr14")
    ema50, rsi = _get(row, "ema50"), _get(row, "rsi14")
    macd, macd_signal = _get(row, "macd"), _get(row, "macd_signal")
    liquid = traded_value_cr is None or traded_value_cr >= params.min_traded_value_cr

    vetoed = news_sentiment is not None and news_sentiment <= params.news_veto
    action = "HOLD"
    if (
        not vetoed
        and total >= params.buy_threshold
        and close is not None
        and ema50 is not None
        and close > ema50
        and (rsi is None or rsi < params.max_rsi)
        and atr
        and liquid
    ):
        action = "BUY"
    elif total <= params.sell_threshold or (
        close is not None
        and ema50 is not None
        and close < ema50
        and macd is not None
        and macd_signal is not None
        and macd < macd_signal
    ):
        action = "SELL"
    if vetoed and total >= params.buy_threshold:
        reasons.append("BUY blocked by negative news")
    if not liquid:
        reasons.append(f"Illiquid: ₹{traded_value_cr:.1f} cr/day")

    entry = stop = target = None
    if action == "BUY":
        entry = round(close, 2)
        stop = round(close - params.stop_atr * atr, 2)
        target = round(close + params.target_atr * atr, 2)
    confidence = (
        max(0.0, min(1.0, (total - params.buy_threshold) / (100 - params.buy_threshold))) if action == "BUY" else 0.0
    )
    return ScoreBreakdown(
        round(total, 2),
        round(technical, 2),
        round(news_points, 2),
        adjustment,
        action,
        entry,
        stop,
        target,
        round(confidence, 3),
        reasons,
    )


@dataclass
class MomentumSnapshot:
    rank: int | None
    eligible: int
    percentile: float
    trend: float | None
    return_6m: float | None
    return_12m: float | None
    traded_value_cr: float | None
    market_ok: bool


def momentum_decision(
    snapshot: MomentumSnapshot,
    close: float | None,
    atr: float | None,
    news_sentiment: float | None = None,
    news_count: int = 0,
    params: StrategyParams = MOMENTUM,
) -> ScoreBreakdown:
    reasons: list[str] = []
    rank = snapshot.rank
    if rank is not None:
        reasons.append(f"Momentum rank {rank} of {snapshot.eligible}")
        if snapshot.return_6m is not None and snapshot.return_12m is not None:
            reasons.append(f"6m {snapshot.return_6m * 100:+.0f}%, 12m {snapshot.return_12m * 100:+.0f}%")
        reasons.append("Above 200-day average")
    elif close is not None and snapshot.trend is not None and close <= snapshot.trend:
        reasons.append("Below 200-day average")
    elif snapshot.traded_value_cr is not None and snapshot.traded_value_cr < params.min_traded_value_cr:
        reasons.append(f"Illiquid: ₹{snapshot.traded_value_cr:.1f} cr/day")
    else:
        reasons.append("Not enough history to rank")
    news_points = (news_sentiment or 0.0) * params.news_weight
    if news_sentiment is not None and news_count:
        reasons.append(f"News {news_sentiment:+.2f} ({news_count} items)")

    vetoed = news_sentiment is not None and news_sentiment <= params.news_veto
    leader = rank is not None and rank <= params.top_n
    market_blocked = params.market_filter and not snapshot.market_ok
    action = "HOLD"
    if leader and not vetoed and not market_blocked and close is not None and atr:
        action = "BUY"
    elif rank is None or rank > params.exit_rank:
        action = "SELL"
    if leader and vetoed:
        reasons.append("BUY blocked by negative news")
    if leader and market_blocked:
        reasons.append("No new entries: NIFTY below its 200-day average")

    entry = stop = target = None
    confidence = 0.0
    if action == "BUY" and close is not None and atr and rank is not None:
        entry = round(close, 2)
        stop = round(close - params.stop_atr * atr, 2)
        target = round(close + params.target_atr * atr, 2)
        confidence = round((params.top_n - rank + 1) / params.top_n, 3)
    return ScoreBreakdown(
        round(snapshot.percentile, 2),
        round(snapshot.percentile, 2),
        round(news_points, 2),
        0.0,
        action,
        entry,
        stop,
        target,
        confidence,
        reasons,
    )
