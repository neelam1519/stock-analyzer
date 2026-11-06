from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from app.core.clock import IST, MARKET_CLOSE, is_weekday, last_completed_session, now_ist
from app.core.config import get_settings
from app.kite.service import KiteNotConnected, MarketDataClient
from app.models import DailyCandle, IndicatorDaily, Instrument, IntradayCandle60m

OVERLAP_DAYS = 7
ADJUSTMENT_TOLERANCE = 0.005


@dataclass(frozen=True)
class IntervalSpec:
    name: str
    kite_interval: str
    model: type
    key: str
    max_days_per_call: int
    history_days: Callable[[], int]


DAILY = IntervalSpec("day", "day", DailyCandle, "trade_date", 1900, lambda: get_settings().daily_history_days)
HOURLY = IntervalSpec("60m", "60minute", IntradayCandle60m, "ts", 390, lambda: get_settings().intraday_history_days)
INTERVALS = {spec.name: spec for spec in (DAILY, HOURLY)}


@dataclass
class IngestResult:
    instruments: int = 0
    skipped: int = 0
    inserted: int = 0
    rebuilt: int = 0
    failed: int = 0


def fetch_window(last_stored: date | None, end: date, history_days: int) -> tuple[date, date] | None:
    if last_stored is not None and last_stored >= end:
        return None
    start = last_stored - timedelta(days=OVERLAP_DAYS) if last_stored else end - timedelta(days=history_days)
    return start, end


def chunks(start: date, end: date, max_days: int) -> Iterable[tuple[date, date]]:
    cursor = start
    while cursor <= end:
        stop = min(cursor + timedelta(days=max_days - 1), end)
        yield cursor, stop
        cursor = stop + timedelta(days=1)


def candle_key(spec: IntervalSpec, raw: datetime | date) -> date | datetime:
    if spec is DAILY:
        return raw.astimezone(IST).date() if isinstance(raw, datetime) and raw.tzinfo else _as_date(raw)
    moment = raw.astimezone(IST) if raw.tzinfo else raw
    return moment.replace(tzinfo=None)


def _as_date(raw: datetime | date) -> date:
    return raw.date() if isinstance(raw, datetime) else raw


def is_complete(spec: IntervalSpec, key: date | datetime, now: datetime) -> bool:
    if spec is DAILY:
        return key <= last_completed_session(now)
    candle_end = key + timedelta(minutes=60)
    session_close = datetime.combine(key.date(), MARKET_CLOSE)
    return min(candle_end, session_close) <= now.astimezone(IST).replace(tzinfo=None)


def latest_complete_hourly(now: datetime) -> datetime:
    day = now.astimezone(IST).date()
    while True:
        if is_weekday(day):
            slots = [datetime.combine(day, time(9, 15)) + timedelta(hours=h) for h in range(7)]
            done = [slot for slot in slots if is_complete(HOURLY, slot, now)]
            if done:
                return done[-1]
        day -= timedelta(days=1)


def call_range(spec: IntervalSpec, start: date, stop: date) -> tuple[date | datetime, date | datetime]:
    if spec is DAILY:
        return start, stop
    return datetime.combine(start, time.min), datetime.combine(stop, time(23, 59, 59))


def needs_rebuild(stored: dict, fetched: dict) -> bool:
    for key, close in fetched.items():
        previous = stored.get(key)
        if previous and abs(close - previous) / previous > ADJUSTMENT_TOLERANCE:
            return True
    return False


def last_stored_keys(db: Session, spec: IntervalSpec) -> dict[int, date | datetime]:
    column = getattr(spec.model, spec.key)
    rows = db.execute(select(spec.model.instrument_id, func.max(column)).group_by(spec.model.instrument_id))
    return {instrument_id: last for instrument_id, last in rows}


def ingest_instrument(
    db: Session,
    kite: MarketDataClient,
    spec: IntervalSpec,
    instrument: Instrument,
    last_stored: date | datetime | None,
    now: datetime,
) -> tuple[int, bool]:
    end = now.astimezone(IST).date()
    last_day = _as_date(last_stored) if last_stored is not None else None
    if spec is DAILY:
        end = last_completed_session(now)
    elif last_stored is not None and last_stored >= latest_complete_hourly(now):
        return 0, False
    window = fetch_window(last_day, end, spec.history_days())
    if window is None:
        return 0, False

    fetched = {}
    for start, stop in chunks(*window, spec.max_days_per_call):
        call_start, call_stop = call_range(spec, start, stop)
        for candle in kite.historical_data(instrument.instrument_token, call_start, call_stop, spec.kite_interval):
            key = candle_key(spec, candle["date"])
            if is_complete(spec, key, now):
                fetched[key] = candle

    column = getattr(spec.model, spec.key)
    overlap = {k: float(c["close"]) for k, c in fetched.items() if last_stored is not None and k <= last_stored}
    if overlap:
        stored = dict(
            db.execute(
                select(column, spec.model.close).where(
                    spec.model.instrument_id == instrument.id, column.in_(list(overlap))
                )
            ).all()
        )
        if needs_rebuild({k: float(v) for k, v in stored.items()}, overlap):
            db.execute(delete(spec.model).where(spec.model.instrument_id == instrument.id))
            if spec is DAILY:
                db.execute(delete(IndicatorDaily).where(IndicatorDaily.instrument_id == instrument.id))
            db.commit()
            inserted, _ = ingest_instrument(db, kite, spec, instrument, None, now)
            return inserted, True

    rows = [
        {
            "instrument_id": instrument.id,
            spec.key: key,
            "open": candle["open"],
            "high": candle["high"],
            "low": candle["low"],
            "close": candle["close"],
            "volume": int(candle.get("volume") or 0),
        }
        for key, candle in sorted(fetched.items())
        if last_stored is None or key > last_stored
    ]
    if rows:
        db.execute(insert(spec.model), rows)
        db.commit()
    return len(rows), False


def ingest_candles(
    db: Session,
    kite: MarketDataClient,
    spec: IntervalSpec,
    symbols: list[str] | None = None,
    now: datetime | None = None,
    on_progress: Callable[[IngestResult], None] | None = None,
) -> IngestResult:
    now = now or now_ist()
    query = select(Instrument).where(Instrument.is_active, Instrument.in_universe)
    if symbols:
        query = query.where(Instrument.tradingsymbol.in_(symbols))
    if spec is HOURLY:
        query = query.where(Instrument.segment != "INDICES")
    instruments = list(db.scalars(query.order_by(Instrument.tradingsymbol)))
    last_keys = last_stored_keys(db, spec)
    result = IngestResult(instruments=len(instruments))

    for instrument in instruments:
        try:
            inserted, rebuilt = ingest_instrument(db, kite, spec, instrument, last_keys.get(instrument.id), now)
        except KiteNotConnected:
            raise
        except Exception:
            db.rollback()
            result.failed += 1
            if result.failed > 25 and result.failed > result.instruments // 5:
                raise
            continue
        result.inserted += inserted
        result.rebuilt += int(rebuilt)
        result.skipped += int(inserted == 0 and not rebuilt)
        if on_progress:
            on_progress(result)
    return result
