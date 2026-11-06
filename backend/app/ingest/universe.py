import csv
import io
from dataclasses import dataclass

import httpx
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.kite.service import MarketDataClient
from app.models import Instrument

NIFTY500_URLS = (
    "https://archives.nseindia.com/content/indices/ind_nifty500list.csv",
    "https://niftyindices.com/IndexConstituent/ind_nifty500list.csv",
)
BENCHMARK_INDICES = ("NIFTY 50", "NIFTY 500", "INDIA VIX", "NIFTY BANK")
HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh) stock-analyzer", "Accept": "text/csv"}


@dataclass(frozen=True)
class Constituent:
    symbol: str
    name: str
    industry: str


def parse_constituents(text: str) -> list[Constituent]:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    return [
        Constituent(row["Symbol"].strip(), row["Company Name"].strip(), row["Industry"].strip())
        for row in reader
        if row.get("Symbol") and row.get("Series", "EQ").strip() == "EQ"
    ]


def fetch_nifty500() -> list[Constituent]:
    errors = []
    for url in NIFTY500_URLS:
        try:
            response = httpx.get(url, headers=HTTP_HEADERS, timeout=30, follow_redirects=True)
            response.raise_for_status()
            constituents = parse_constituents(response.text)
            if len(constituents) > 400:
                return constituents
            errors.append(f"{url}: only {len(constituents)} rows")
        except httpx.HTTPError as exc:
            errors.append(f"{url}: {exc}")
    raise RuntimeError("Could not download NIFTY 500 list: " + "; ".join(errors))


def is_tracked(row: dict) -> bool:
    return row.get("segment") == "INDICES" or (row.get("segment") == "NSE" and row.get("instrument_type") == "EQ")


def sync_instruments(db: Session, kite: MarketDataClient, constituents: list[Constituent]) -> int:
    universe = {c.symbol: c for c in constituents}
    rows = [row for row in kite.instruments("NSE") if is_tracked(row)]
    existing = {i.instrument_token: i for i in db.scalars(select(Instrument))}
    seen: set[int] = set()
    now = utc_now()

    for row in rows:
        token = int(row["instrument_token"])
        seen.add(token)
        symbol = row["tradingsymbol"]
        member = universe.get(symbol) if row["segment"] == "NSE" else None
        instrument = existing.get(token) or Instrument(instrument_token=token)
        instrument.exchange_token = int(row["exchange_token"]) if row.get("exchange_token") else None
        instrument.tradingsymbol = symbol
        instrument.name = (member.name if member else row.get("name")) or symbol
        instrument.exchange = row.get("exchange") or "NSE"
        instrument.segment = row["segment"]
        instrument.instrument_type = row.get("instrument_type")
        instrument.industry = member.industry if member else instrument.industry
        instrument.sector = member.industry if member else instrument.sector
        instrument.lot_size = int(row.get("lot_size") or 1)
        instrument.tick_size = row.get("tick_size")
        instrument.is_active = True
        instrument.in_universe = bool(member) or (row["segment"] == "INDICES" and symbol in BENCHMARK_INDICES)
        instrument.updated_at = now
        db.add(instrument)

    missing = [token for token in existing if token not in seen]
    if missing:
        for start in range(0, len(missing), 1000):
            db.execute(
                update(Instrument)
                .where(Instrument.instrument_token.in_(missing[start : start + 1000]))
                .values(is_active=False, in_universe=False, updated_at=now)
            )
    db.commit()
    return len(rows)
