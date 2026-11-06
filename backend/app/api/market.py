from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.ingest.candles import INTERVALS
from app.models import DailyCandle, IndicatorDaily, Instrument

router = APIRouter(tags=["market"])


def _latest_closes(db: Session, instrument_ids: list[int]) -> dict[int, list[DailyCandle]]:
    if not instrument_ids:
        return {}
    ranked = (
        select(
            DailyCandle.instrument_id,
            DailyCandle.trade_date,
            DailyCandle.close,
            func.row_number()
            .over(partition_by=DailyCandle.instrument_id, order_by=DailyCandle.trade_date.desc())
            .label("rn"),
        )
        .where(DailyCandle.instrument_id.in_(instrument_ids))
        .subquery()
    )
    rows = db.execute(select(ranked).where(ranked.c.rn <= 2).order_by(ranked.c.instrument_id, ranked.c.rn))
    closes: dict[int, list] = {}
    for row in rows:
        closes.setdefault(row.instrument_id, []).append(row)
    return closes


def _instrument_summary(instrument: Instrument, closes: list) -> dict:
    last = closes[0] if closes else None
    prev = closes[1] if len(closes) > 1 else None
    change_pct = float((last.close - prev.close) / prev.close * 100) if last and prev and prev.close else None
    return {
        "id": instrument.id,
        "symbol": instrument.tradingsymbol,
        "name": instrument.name,
        "sector": instrument.sector,
        "segment": instrument.segment,
        "last_date": last.trade_date.isoformat() if last else None,
        "last_close": float(last.close) if last else None,
        "change_pct": round(change_pct, 2) if change_pct is not None else None,
    }


@router.get("/instruments")
def list_instruments(
    q: str | None = None,
    universe: bool = True,
    limit: int = Query(default=600, le=2000),
    db: Session = Depends(get_db),
) -> dict:
    query = select(Instrument).where(Instrument.is_active)
    if universe:
        query = query.where(Instrument.in_universe)
    if q:
        pattern = f"%{q.strip()}%"
        query = query.where(or_(Instrument.tradingsymbol.ilike(pattern), Instrument.name.ilike(pattern)))
    instruments = list(db.scalars(query.order_by(Instrument.tradingsymbol).limit(limit)))
    closes = _latest_closes(db, [i.id for i in instruments])
    return {"items": [_instrument_summary(i, closes.get(i.id, [])) for i in instruments]}


def _get_instrument(db: Session, symbol: str) -> Instrument:
    instrument = db.scalar(select(Instrument).where(Instrument.tradingsymbol == symbol, Instrument.is_active))
    if instrument is None:
        raise HTTPException(status_code=404, detail=f"Unknown symbol {symbol}")
    return instrument


@router.get("/stocks/{symbol}")
def stock_detail(symbol: str, db: Session = Depends(get_db)) -> dict:
    instrument = _get_instrument(db, symbol)
    summary = _instrument_summary(instrument, _latest_closes(db, [instrument.id]).get(instrument.id, []))
    stats = {}
    for name, spec in INTERVALS.items():
        column = getattr(spec.model, spec.key)
        count, first, last = db.execute(
            select(func.count(), func.min(column), func.max(column)).where(spec.model.instrument_id == instrument.id)
        ).one()
        stats[name] = {
            "count": count,
            "first": first.isoformat() if first else None,
            "last": last.isoformat() if last else None,
        }
    return {**summary, "industry": instrument.industry, "candles": stats}


def _chart_time(value) -> str | int:
    if isinstance(value, datetime):
        return int(value.replace(tzinfo=UTC).timestamp())
    return value.isoformat()


@router.get("/stocks/{symbol}/candles")
def stock_candles(
    symbol: str,
    interval: str = Query(default="day", pattern="^(day|60m)$"),
    limit: int = Query(default=750, le=5000),
    db: Session = Depends(get_db),
) -> dict:
    instrument = _get_instrument(db, symbol)
    spec = INTERVALS[interval]
    column = getattr(spec.model, spec.key)
    rows = list(
        db.scalars(
            select(spec.model).where(spec.model.instrument_id == instrument.id).order_by(column.desc()).limit(limit)
        )
    )
    overlays: dict[str, list[dict]] = {}
    if interval == "day" and rows:
        emas = db.execute(
            select(IndicatorDaily.trade_date, IndicatorDaily.ema20, IndicatorDaily.ema50, IndicatorDaily.ema200).where(
                IndicatorDaily.instrument_id == instrument.id, IndicatorDaily.trade_date >= rows[-1].trade_date
            )
        ).all()
        for key in ("ema20", "ema50", "ema200"):
            overlays[key] = [
                {"time": e.trade_date.isoformat(), "value": float(getattr(e, key))}
                for e in sorted(emas)
                if getattr(e, key) is not None
            ]
    return {
        "symbol": instrument.tradingsymbol,
        "interval": interval,
        "overlays": overlays,
        "candles": [
            {
                "time": _chart_time(getattr(row, spec.key)),
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
                "volume": int(row.volume),
            }
            for row in reversed(rows)
        ],
    }
