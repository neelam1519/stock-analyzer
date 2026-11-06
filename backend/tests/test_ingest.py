from datetime import date, datetime

from sqlalchemy import func, select

from app.core.clock import IST, kite_token_expiry, last_completed_session
from app.ingest.candles import DAILY, HOURLY, chunks, fetch_window, ingest_candles, needs_rebuild
from app.ingest.universe import Constituent, parse_constituents, sync_instruments
from app.models import DailyCandle, Instrument, IntradayCandle60m
from tests.fakes import FakeKite, instrument_rows

UNIVERSE = [Constituent("RELIANCE", "Reliance Industries Ltd.", "Oil Gas & Consumable Fuels")]
THURSDAY_EVENING = datetime(2026, 11, 5, 18, 0, tzinfo=IST)


def setup_universe(db, kite):
    sync_instruments(db, kite, UNIVERSE)
    return db.scalar(select(Instrument).where(Instrument.tradingsymbol == "RELIANCE"))


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def test_kite_token_expires_at_next_6am_ist():
    assert kite_token_expiry(datetime(2026, 11, 5, 9, 0, tzinfo=IST)) == datetime(2026, 11, 6, 0, 30)
    assert kite_token_expiry(datetime(2026, 11, 5, 5, 0, tzinfo=IST)) == datetime(2026, 11, 5, 0, 30)


def test_last_completed_session_handles_intraday_and_weekends():
    assert last_completed_session(datetime(2026, 11, 5, 11, 0, tzinfo=IST)) == date(2026, 11, 4)
    assert last_completed_session(THURSDAY_EVENING) == date(2026, 11, 5)
    assert last_completed_session(datetime(2026, 11, 8, 12, 0, tzinfo=IST)) == date(2026, 11, 6)


def test_fetch_window_and_chunks():
    assert fetch_window(date(2026, 11, 5), date(2026, 11, 5), 100) is None
    assert fetch_window(None, date(2026, 11, 5), 10) == (date(2026, 10, 26), date(2026, 11, 5))
    assert fetch_window(date(2026, 11, 1), date(2026, 11, 5), 10) == (date(2026, 10, 25), date(2026, 11, 5))
    parts = list(chunks(date(2026, 1, 1), date(2026, 1, 10), 4))
    assert parts == [
        (date(2026, 1, 1), date(2026, 1, 4)),
        (date(2026, 1, 5), date(2026, 1, 8)),
        (date(2026, 1, 9), date(2026, 1, 10)),
    ]


def test_needs_rebuild_detects_adjusted_history():
    assert not needs_rebuild({1: 100.0}, {1: 100.2})
    assert needs_rebuild({1: 100.0}, {1: 50.0})


def test_parse_constituents_reads_nse_csv():
    text = "﻿Company Name,Industry,Symbol,Series,ISIN Code\nABB India Ltd.,Capital Goods,ABB,EQ,INE117A01022\n"
    assert parse_constituents(text) == [Constituent("ABB", "ABB India Ltd.", "Capital Goods")]


def test_sync_instruments_marks_universe_and_benchmarks(db):
    kite = FakeKite(instrument_rows())
    assert sync_instruments(db, kite, UNIVERSE) == 3
    rows = {i.tradingsymbol: i for i in db.scalars(select(Instrument))}
    assert set(rows) == {"RELIANCE", "TINYCO", "NIFTY 50"}
    assert rows["RELIANCE"].in_universe and rows["RELIANCE"].sector == "Oil Gas & Consumable Fuels"
    assert rows["NIFTY 50"].in_universe
    assert not rows["TINYCO"].in_universe

    kite._instruments = [r for r in instrument_rows() if r["tradingsymbol"] != "TINYCO"]
    sync_instruments(db, kite, UNIVERSE)
    db.expire_all()
    assert not db.scalar(select(Instrument).where(Instrument.tradingsymbol == "TINYCO")).is_active


def test_daily_ingest_is_incremental(db, settings, monkeypatch):
    monkeypatch.setenv("DAILY_HISTORY_DAYS", "30")
    from app.core import config

    config.get_settings.cache_clear()
    kite = FakeKite(instrument_rows())
    setup_universe(db, kite)

    first = ingest_candles(db, kite, DAILY, now=THURSDAY_EVENING)
    stored = count(db, DailyCandle)
    assert first.inserted == stored > 0
    assert db.scalar(select(func.max(DailyCandle.trade_date))) == date(2026, 11, 5)

    kite.calls.clear()
    second = ingest_candles(db, kite, DAILY, now=THURSDAY_EVENING)
    assert second.inserted == 0
    assert kite.calls == []

    friday = datetime(2026, 11, 6, 18, 0, tzinfo=IST)
    third = ingest_candles(db, kite, DAILY, now=friday)
    assert third.inserted == 2
    assert count(db, DailyCandle) == stored + 2


def test_daily_ingest_rebuilds_after_split(db, settings, monkeypatch):
    monkeypatch.setenv("DAILY_HISTORY_DAYS", "30")
    from app.core import config

    config.get_settings.cache_clear()
    kite = FakeKite(instrument_rows())
    reliance = setup_universe(db, kite)
    ingest_candles(db, kite, DAILY, symbols=["RELIANCE"], now=THURSDAY_EVENING)
    before = count(db, DailyCandle)

    kite.closes = {(reliance.instrument_token, day.trade_date): 50.0 for day in db.scalars(select(DailyCandle))}
    result = ingest_candles(db, kite, DAILY, symbols=["RELIANCE"], now=datetime(2026, 11, 6, 18, 0, tzinfo=IST))
    assert result.rebuilt == 1
    closes = set(db.scalars(select(DailyCandle.close).where(DailyCandle.trade_date < date(2026, 11, 6))))
    assert closes == {50.0}
    assert count(db, DailyCandle) >= before


def test_hourly_ingest_skips_incomplete_candle(db, settings, monkeypatch):
    monkeypatch.setenv("INTRADAY_HISTORY_DAYS", "3")
    from app.core import config

    config.get_settings.cache_clear()
    kite = FakeKite(instrument_rows())
    setup_universe(db, kite)
    midday = datetime(2026, 11, 5, 12, 0, tzinfo=IST)
    ingest_candles(db, kite, HOURLY, now=midday)
    latest = db.scalar(select(func.max(IntradayCandle60m.ts)))
    assert latest == datetime(2026, 11, 5, 10, 15)
    indices = db.scalar(
        select(func.count()).select_from(IntradayCandle60m).join(Instrument).where(Instrument.segment == "INDICES")
    )
    assert indices == 0

    kite.calls.clear()
    ingest_candles(db, kite, HOURLY, now=datetime(2026, 11, 5, 12, 30, tzinfo=IST))
    assert kite.calls == []
