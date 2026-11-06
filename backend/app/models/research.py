from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Unicode, UnicodeText, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, BigId, CreatedAtMixin, Money, Price, Score

SCHEMA = "res"
INSTRUMENT_FK = "mkt.instruments.id"


class NewsArticle(CreatedAtMixin, Base):
    __tablename__ = "news_articles"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    url_hash: Mapped[str] = mapped_column(String(64), unique=True)
    url: Mapped[str] = mapped_column(String(2048))
    source: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(Unicode(1024))
    summary: Mapped[str | None] = mapped_column(UnicodeText)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)


class NewsSymbolMap(Base):
    __tablename__ = "news_symbol_map"
    __table_args__ = {"schema": SCHEMA}

    article_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.news_articles.id"), primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey(INSTRUMENT_FK), primary_key=True)
    match_type: Mapped[str] = mapped_column(String(16))


class NewsSentiment(CreatedAtMixin, Base):
    __tablename__ = "news_sentiment"
    __table_args__ = (
        UniqueConstraint("article_id", "instrument_id", "model", "prompt_version"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.news_articles.id"))
    instrument_id: Mapped[int] = mapped_column(ForeignKey(INSTRUMENT_FK))
    model: Mapped[str] = mapped_column(String(128))
    prompt_version: Mapped[str] = mapped_column(String(16))
    sentiment: Mapped[Decimal] = mapped_column(Score)
    relevance: Mapped[Decimal] = mapped_column(Score)
    impact: Mapped[str | None] = mapped_column(String(16))
    rationale: Mapped[str | None] = mapped_column(UnicodeText)


class FundamentalsQuarterly(Base):
    __tablename__ = "fundamentals_quarterly"
    __table_args__ = {"schema": SCHEMA}

    instrument_id: Mapped[int] = mapped_column(ForeignKey(INSTRUMENT_FK), primary_key=True)
    period_end: Mapped[date] = mapped_column(Date, primary_key=True)
    revenue: Mapped[Decimal | None] = mapped_column(Money)
    net_profit: Mapped[Decimal | None] = mapped_column(Money)
    eps: Mapped[Decimal | None] = mapped_column(Price)
    roe: Mapped[Decimal | None] = mapped_column(Score)
    debt_to_equity: Mapped[Decimal | None] = mapped_column(Score)
    pe: Mapped[Decimal | None] = mapped_column(Score)
    source: Mapped[str] = mapped_column(String(32))


class ResearchReport(CreatedAtMixin, Base):
    __tablename__ = "research_reports"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey(INSTRUMENT_FK), index=True)
    as_of_date: Mapped[date] = mapped_column(Date)
    model: Mapped[str] = mapped_column(String(128))
    summary: Mapped[str] = mapped_column(UnicodeText)
    bull_case: Mapped[str | None] = mapped_column(UnicodeText)
    bear_case: Mapped[str | None] = mapped_column(UnicodeText)
    key_risks: Mapped[str | None] = mapped_column(UnicodeText)
    verdict: Mapped[str | None] = mapped_column(String(8))
    prompt_version: Mapped[str | None] = mapped_column(String(16))
    score: Mapped[Decimal | None] = mapped_column(Score)


class Signal(CreatedAtMixin, Base):
    __tablename__ = "signals"
    __table_args__ = (UniqueConstraint("instrument_id", "as_of_date", "strategy"), {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey(INSTRUMENT_FK))
    as_of_date: Mapped[date] = mapped_column(Date, index=True)
    strategy: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(8))
    score: Mapped[Decimal] = mapped_column(Score)
    technical_score: Mapped[Decimal | None] = mapped_column(Score)
    news_score: Mapped[Decimal | None] = mapped_column(Score)
    fundamental_score: Mapped[Decimal | None] = mapped_column(Score)
    regime: Mapped[str | None] = mapped_column(String(16))
    entry_price: Mapped[Decimal | None] = mapped_column(Price)
    stop_loss: Mapped[Decimal | None] = mapped_column(Price)
    target: Mapped[Decimal | None] = mapped_column(Price)
    confidence: Mapped[Decimal | None] = mapped_column(Score)
    rationale: Mapped[str | None] = mapped_column(UnicodeText)


class BacktestRun(CreatedAtMixin, Base):
    __tablename__ = "backtest_runs"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str | None] = mapped_column(String(16))
    metrics_json: Mapped[str | None] = mapped_column(UnicodeText)
    equity_json: Mapped[str | None] = mapped_column(UnicodeText)
    params_json: Mapped[str] = mapped_column(UnicodeText)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    cagr: Mapped[Decimal | None] = mapped_column(Score)
    max_drawdown: Mapped[Decimal | None] = mapped_column(Score)
    win_rate: Mapped[Decimal | None] = mapped_column(Score)
    sharpe: Mapped[Decimal | None] = mapped_column(Score)
    trades_count: Mapped[int] = mapped_column(Integer, default=0)


class BacktestTrade(Base):
    __tablename__ = "backtest_trades"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.backtest_runs.id"), index=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey(INSTRUMENT_FK))
    entry_date: Mapped[date] = mapped_column(Date)
    entry_price: Mapped[Decimal] = mapped_column(Price)
    exit_date: Mapped[date | None] = mapped_column(Date)
    exit_price: Mapped[Decimal | None] = mapped_column(Price)
    qty: Mapped[int] = mapped_column(Integer)
    pnl: Mapped[Decimal | None] = mapped_column(Money)
    exit_reason: Mapped[str | None] = mapped_column(String(32))
