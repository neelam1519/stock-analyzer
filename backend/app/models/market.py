from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, String, Unicode, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Price, Score

SCHEMA = "mkt"


class Instrument(Base):
    __tablename__ = "instruments"
    __table_args__ = (UniqueConstraint("exchange", "tradingsymbol"), {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instrument_token: Mapped[int] = mapped_column(BigInteger, unique=True)
    exchange_token: Mapped[int | None] = mapped_column(BigInteger)
    tradingsymbol: Mapped[str] = mapped_column(String(64))
    name: Mapped[str | None] = mapped_column(Unicode(256))
    exchange: Mapped[str] = mapped_column(String(16))
    segment: Mapped[str | None] = mapped_column(String(32))
    instrument_type: Mapped[str | None] = mapped_column(String(16))
    sector: Mapped[str | None] = mapped_column(Unicode(128))
    industry: Mapped[str | None] = mapped_column(Unicode(128))
    lot_size: Mapped[int] = mapped_column(Integer, default=1)
    tick_size: Mapped[Decimal | None] = mapped_column(Price)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    in_universe: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.sysutcdatetime())


class SymbolAlias(Base):
    __tablename__ = "symbol_aliases"
    __table_args__ = {"schema": SCHEMA}

    instrument_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.instruments.id"), primary_key=True)
    alias: Mapped[str] = mapped_column(Unicode(128), primary_key=True)


class DailyCandle(Base):
    __tablename__ = "daily_candles"
    __table_args__ = {"schema": SCHEMA}

    instrument_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.instruments.id"), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[Decimal] = mapped_column(Price)
    high: Mapped[Decimal] = mapped_column(Price)
    low: Mapped[Decimal] = mapped_column(Price)
    close: Mapped[Decimal] = mapped_column(Price)
    volume: Mapped[int] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(16), default="kite")


class IntradayCandle60m(Base):
    __tablename__ = "intraday_candles_60m"
    __table_args__ = {"schema": SCHEMA}

    instrument_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.instruments.id"), primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, primary_key=True)
    open: Mapped[Decimal] = mapped_column(Price)
    high: Mapped[Decimal] = mapped_column(Price)
    low: Mapped[Decimal] = mapped_column(Price)
    close: Mapped[Decimal] = mapped_column(Price)
    volume: Mapped[int] = mapped_column(BigInteger)


class IndicatorDaily(Base):
    __tablename__ = "indicators_daily"
    __table_args__ = {"schema": SCHEMA}

    instrument_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.instruments.id"), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    ema20: Mapped[Decimal | None] = mapped_column(Price)
    ema50: Mapped[Decimal | None] = mapped_column(Price)
    ema200: Mapped[Decimal | None] = mapped_column(Price)
    rsi14: Mapped[Decimal | None] = mapped_column(Score)
    macd: Mapped[Decimal | None] = mapped_column(Price)
    macd_signal: Mapped[Decimal | None] = mapped_column(Price)
    adx14: Mapped[Decimal | None] = mapped_column(Score)
    atr14: Mapped[Decimal | None] = mapped_column(Price)
    volume_ratio20: Mapped[Decimal | None] = mapped_column(Score)
    high52w_distance_pct: Mapped[Decimal | None] = mapped_column(Score)
    relative_strength_nifty: Mapped[Decimal | None] = mapped_column(Score)


class CorporateAction(Base):
    __tablename__ = "corporate_actions"
    __table_args__ = (UniqueConstraint("instrument_id", "ex_date", "action_type"), {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.instruments.id"))
    ex_date: Mapped[date] = mapped_column(Date)
    action_type: Mapped[str] = mapped_column(String(32))
    details: Mapped[str | None] = mapped_column(Unicode(512))
