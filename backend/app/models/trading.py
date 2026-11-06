from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, String, Unicode, UnicodeText
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, BigId, CreatedAtMixin, Money, Price, Score

SCHEMA = "trd"
INSTRUMENT_FK = "mkt.instruments.id"
SIGNAL_FK = "res.signals.id"


class PaperOrder(CreatedAtMixin, Base):
    __tablename__ = "paper_orders"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey(INSTRUMENT_FK))
    signal_id: Mapped[int | None] = mapped_column(ForeignKey(SIGNAL_FK))
    side: Mapped[str] = mapped_column(String(4))
    qty: Mapped[int] = mapped_column(Integer)
    order_type: Mapped[str] = mapped_column(String(8))
    limit_price: Mapped[Decimal | None] = mapped_column(Price)
    status: Mapped[str] = mapped_column(String(16), index=True)
    filled_price: Mapped[Decimal | None] = mapped_column(Price)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime)
    as_of_date: Mapped[date | None] = mapped_column(Date)
    stop_loss: Mapped[Decimal | None] = mapped_column(Price)
    target: Mapped[Decimal | None] = mapped_column(Price)
    position_id: Mapped[int | None] = mapped_column(BigInteger)
    reason: Mapped[str | None] = mapped_column(String(200))


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    book: Mapped[str] = mapped_column(String(8), index=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey(INSTRUMENT_FK))
    signal_id: Mapped[int | None] = mapped_column(ForeignKey(SIGNAL_FK))
    qty: Mapped[int] = mapped_column(Integer)
    avg_price: Mapped[Decimal] = mapped_column(Price)
    stop_loss: Mapped[Decimal | None] = mapped_column(Price)
    target: Mapped[Decimal | None] = mapped_column(Price)
    status: Mapped[str] = mapped_column(String(16), index=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    exit_price: Mapped[Decimal | None] = mapped_column(Price)
    realized_pnl: Mapped[Decimal | None] = mapped_column(Money)
    initial_stop: Mapped[Decimal | None] = mapped_column(Price)
    highest_close: Mapped[Decimal | None] = mapped_column(Price)
    last_price: Mapped[Decimal | None] = mapped_column(Price)
    last_price_at: Mapped[datetime | None] = mapped_column(DateTime)
    exit_reason: Mapped[str | None] = mapped_column(String(32))


class ApprovalItem(CreatedAtMixin, Base):
    __tablename__ = "approval_queue"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    signal_id: Mapped[int | None] = mapped_column(ForeignKey(SIGNAL_FK))
    instrument_id: Mapped[int] = mapped_column(ForeignKey(INSTRUMENT_FK))
    side: Mapped[str] = mapped_column(String(4))
    qty: Mapped[int] = mapped_column(Integer)
    limit_price: Mapped[Decimal] = mapped_column(Price)
    stop_loss: Mapped[Decimal | None] = mapped_column(Price)
    target: Mapped[Decimal | None] = mapped_column(Price)
    risk_amount: Mapped[Decimal | None] = mapped_column(Money)
    status: Mapped[str] = mapped_column(String(16), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    kind: Mapped[str | None] = mapped_column(String(8))
    position_id: Mapped[int | None] = mapped_column(BigInteger)
    reason: Mapped[str | None] = mapped_column(Unicode(300))


class LiveOrder(CreatedAtMixin, Base):
    __tablename__ = "live_orders"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    approval_id: Mapped[int | None] = mapped_column(ForeignKey(f"{SCHEMA}.approval_queue.id"))
    kite_order_id: Mapped[str | None] = mapped_column(String(64), index=True)
    gtt_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True)
    payload_json: Mapped[str] = mapped_column(UnicodeText)
    response_json: Mapped[str | None] = mapped_column(UnicodeText)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    kind: Mapped[str | None] = mapped_column(String(16))
    position_id: Mapped[int | None] = mapped_column(BigInteger)
    status_message: Mapped[str | None] = mapped_column(Unicode(500))
    filled_qty: Mapped[int | None] = mapped_column(Integer)
    average_price: Mapped[Decimal | None] = mapped_column(Price)


class Trade(Base):
    __tablename__ = "trades"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    book: Mapped[str] = mapped_column(String(8), index=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey(INSTRUMENT_FK))
    position_id: Mapped[int | None] = mapped_column(ForeignKey(f"{SCHEMA}.positions.id"))
    side: Mapped[str] = mapped_column(String(4))
    qty: Mapped[int] = mapped_column(Integer)
    price: Mapped[Decimal] = mapped_column(Price)
    fees: Mapped[Decimal] = mapped_column(Money, default=0)
    executed_at: Mapped[datetime] = mapped_column(DateTime)
    order_ref: Mapped[str | None] = mapped_column(String(64))


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"
    __table_args__ = {"schema": SCHEMA}

    book: Mapped[str] = mapped_column(String(8), primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date, primary_key=True)
    cash: Mapped[Decimal] = mapped_column(Money)
    invested: Mapped[Decimal] = mapped_column(Money)
    market_value: Mapped[Decimal] = mapped_column(Money)
    realized_pnl: Mapped[Decimal] = mapped_column(Money)
    unrealized_pnl: Mapped[Decimal] = mapped_column(Money)


class RiskLimits(Base):
    __tablename__ = "risk_limits"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    capital: Mapped[Decimal] = mapped_column(Money)
    risk_per_trade_pct: Mapped[Decimal] = mapped_column(Score)
    max_position_pct: Mapped[Decimal] = mapped_column(Score)
    max_open_positions: Mapped[int] = mapped_column(Integer)
    daily_loss_limit_pct: Mapped[Decimal] = mapped_column(Score)
    weekly_loss_limit_pct: Mapped[Decimal] = mapped_column(Score)
    max_sector_pct: Mapped[Decimal] = mapped_column(Score)
    kill_switch: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)
