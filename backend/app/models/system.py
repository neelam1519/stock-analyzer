from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, Unicode, UnicodeText, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, BigId, CreatedAtMixin

SCHEMA = "app"


class KiteSession(CreatedAtMixin, Base):
    __tablename__ = "kite_sessions"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(32))
    access_token_enc: Mapped[str] = mapped_column(String(1024))
    login_time: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class AppSetting(Base):
    __tablename__ = "app_settings"
    __table_args__ = {"schema": SCHEMA}

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(UnicodeText)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.sysutcdatetime())


class JobRun(Base):
    __tablename__ = "job_runs"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    job_name: Mapped[str] = mapped_column(String(64), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(16))
    rows_affected: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[str | None] = mapped_column(Unicode(1000))
    error: Mapped[str | None] = mapped_column(UnicodeText)


class LLMCall(CreatedAtMixin, Base):
    __tablename__ = "llm_calls"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    model: Mapped[str] = mapped_column(String(128))
    purpose: Mapped[str] = mapped_column(String(64))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
