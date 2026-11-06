from dataclasses import asdict, dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DailyCandle, IndicatorDaily, Instrument

BENCHMARK = "NIFTY 50"
VIX = "INDIA VIX"


@dataclass(frozen=True)
class Regime:
    name: str
    as_of: date | None
    nifty_close: float | None
    nifty_ema50: float | None
    nifty_ema200: float | None
    nifty_rsi: float | None
    vix: float | None
    summary: str

    def as_dict(self) -> dict:
        data = asdict(self)
        data["as_of"] = self.as_of.isoformat() if self.as_of else None
        return data


def classify(close: float, ema50: float, ema200: float, vix: float | None) -> str:
    if vix is not None and vix >= 22:
        return "volatile"
    if close > ema200 and ema50 > ema200 and close > ema50:
        return "bull"
    if close < ema200 and ema50 < ema200:
        return "bear"
    return "neutral"


SUMMARIES = {
    "bull": "NIFTY is above its 50 and 200-day EMAs. Full position sizing for BUY signals.",
    "neutral": "NIFTY trend is mixed. Signals need a higher score and positions are smaller.",
    "bear": "NIFTY is below its 200-day EMA. Only the strongest setups qualify.",
    "volatile": "India VIX is elevated. Fewer entries and wider stops.",
    "unknown": "Not enough NIFTY 50 history to judge the market.",
}


def market_regime(db: Session, as_of: date | None = None) -> Regime:
    ids = dict(
        db.execute(
            select(Instrument.tradingsymbol, Instrument.id).where(Instrument.tradingsymbol.in_([BENCHMARK, VIX]))
        ).all()
    )
    nifty_id = ids.get(BENCHMARK)
    query = (
        select(IndicatorDaily, DailyCandle.close)
        .join(
            DailyCandle,
            (DailyCandle.instrument_id == IndicatorDaily.instrument_id)
            & (DailyCandle.trade_date == IndicatorDaily.trade_date),
        )
        .where(IndicatorDaily.instrument_id == nifty_id)
    )
    if as_of:
        query = query.where(IndicatorDaily.trade_date <= as_of)
    row = db.execute(query.order_by(IndicatorDaily.trade_date.desc()).limit(1)).first()
    if row is None or row[0].ema200 is None:
        return Regime("unknown", None, None, None, None, None, None, SUMMARIES["unknown"])
    ind, close = row
    vix_query = select(DailyCandle.close).where(
        DailyCandle.instrument_id == ids.get(VIX), DailyCandle.trade_date <= ind.trade_date
    )
    vix = db.scalar(vix_query.order_by(DailyCandle.trade_date.desc()).limit(1))
    vix_value = float(vix) if vix is not None else None
    name = classify(float(close), float(ind.ema50), float(ind.ema200), vix_value)
    return Regime(
        name,
        ind.trade_date,
        float(close),
        float(ind.ema50),
        float(ind.ema200),
        float(ind.rsi14) if ind.rsi14 is not None else None,
        vix_value,
        SUMMARIES[name],
    )
