from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SCHEMAS = ("mkt", "res", "trd", "app")


def upgrade() -> None:
    for schema in SCHEMAS:
        op.execute(f"IF SCHEMA_ID('{schema}') IS NULL EXEC('CREATE SCHEMA [{schema}]')")
    op.create_table('app_settings',
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('value', sa.UnicodeText(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(sysutcdatetime())'), nullable=False),
    sa.PrimaryKeyConstraint('key', name=op.f('pk_app_settings')),
    schema='app'
    )
    op.create_table('job_runs',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('job_name', sa.String(length=64), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=False),
    sa.Column('finished_at', sa.DateTime(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('rows_affected', sa.Integer(), nullable=True),
    sa.Column('error', sa.UnicodeText(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_job_runs')),
    schema='app'
    )
    op.create_index(op.f('ix_job_runs_job_name'), 'job_runs', ['job_name'], unique=False, schema='app')
    op.create_table('kite_sessions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('access_token_enc', sa.String(length=1024), nullable=False),
    sa.Column('login_time', sa.DateTime(), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(sysutcdatetime())'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_kite_sessions')),
    schema='app'
    )
    op.create_index(op.f('ix_kite_sessions_expires_at'), 'kite_sessions', ['expires_at'], unique=False, schema='app')
    op.create_table('llm_calls',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('model', sa.String(length=128), nullable=False),
    sa.Column('purpose', sa.String(length=64), nullable=False),
    sa.Column('prompt_tokens', sa.Integer(), nullable=False),
    sa.Column('completion_tokens', sa.Integer(), nullable=False),
    sa.Column('cost_usd', sa.Numeric(precision=12, scale=6), nullable=False),
    sa.Column('latency_ms', sa.Integer(), nullable=True),
    sa.Column('success', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(sysutcdatetime())'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_llm_calls')),
    schema='app'
    )
    op.create_table('instruments',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('instrument_token', sa.BigInteger(), nullable=False),
    sa.Column('exchange_token', sa.BigInteger(), nullable=True),
    sa.Column('tradingsymbol', sa.String(length=64), nullable=False),
    sa.Column('name', sa.Unicode(length=256), nullable=True),
    sa.Column('exchange', sa.String(length=16), nullable=False),
    sa.Column('segment', sa.String(length=32), nullable=True),
    sa.Column('instrument_type', sa.String(length=16), nullable=True),
    sa.Column('sector', sa.Unicode(length=128), nullable=True),
    sa.Column('industry', sa.Unicode(length=128), nullable=True),
    sa.Column('lot_size', sa.Integer(), nullable=False),
    sa.Column('tick_size', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('in_universe', sa.Boolean(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(sysutcdatetime())'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_instruments')),
    sa.UniqueConstraint('exchange', 'tradingsymbol', name=op.f('uq_instruments_exchange_tradingsymbol')),
    sa.UniqueConstraint('instrument_token', name=op.f('uq_instruments_instrument_token')),
    schema='mkt'
    )
    op.create_table('backtest_runs',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('strategy', sa.String(length=64), nullable=False),
    sa.Column('params_json', sa.UnicodeText(), nullable=False),
    sa.Column('start_date', sa.Date(), nullable=False),
    sa.Column('end_date', sa.Date(), nullable=False),
    sa.Column('cagr', sa.Numeric(precision=9, scale=4), nullable=True),
    sa.Column('max_drawdown', sa.Numeric(precision=9, scale=4), nullable=True),
    sa.Column('win_rate', sa.Numeric(precision=9, scale=4), nullable=True),
    sa.Column('sharpe', sa.Numeric(precision=9, scale=4), nullable=True),
    sa.Column('trades_count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(sysutcdatetime())'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_backtest_runs')),
    schema='res'
    )
    op.create_table('news_articles',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('url_hash', sa.String(length=64), nullable=False),
    sa.Column('url', sa.String(length=2048), nullable=False),
    sa.Column('source', sa.String(length=64), nullable=False),
    sa.Column('title', sa.Unicode(length=1024), nullable=False),
    sa.Column('summary', sa.UnicodeText(), nullable=True),
    sa.Column('published_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(sysutcdatetime())'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_news_articles')),
    sa.UniqueConstraint('url_hash', name=op.f('uq_news_articles_url_hash')),
    schema='res'
    )
    op.create_index(op.f('ix_news_articles_published_at'), 'news_articles', ['published_at'], unique=False, schema='res')
    op.create_table('portfolio_snapshots',
    sa.Column('book', sa.String(length=8), nullable=False),
    sa.Column('snapshot_date', sa.Date(), nullable=False),
    sa.Column('cash', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('invested', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('market_value', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('realized_pnl', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('unrealized_pnl', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.PrimaryKeyConstraint('book', 'snapshot_date', name=op.f('pk_portfolio_snapshots')),
    schema='trd'
    )
    op.create_table('risk_limits',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('capital', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('risk_per_trade_pct', sa.Numeric(precision=9, scale=4), nullable=False),
    sa.Column('max_position_pct', sa.Numeric(precision=9, scale=4), nullable=False),
    sa.Column('max_open_positions', sa.Integer(), nullable=False),
    sa.Column('daily_loss_limit_pct', sa.Numeric(precision=9, scale=4), nullable=False),
    sa.Column('weekly_loss_limit_pct', sa.Numeric(precision=9, scale=4), nullable=False),
    sa.Column('max_sector_pct', sa.Numeric(precision=9, scale=4), nullable=False),
    sa.Column('kill_switch', sa.Boolean(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_risk_limits')),
    schema='trd'
    )
    op.create_table('corporate_actions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('instrument_id', sa.Integer(), nullable=False),
    sa.Column('ex_date', sa.Date(), nullable=False),
    sa.Column('action_type', sa.String(length=32), nullable=False),
    sa.Column('details', sa.Unicode(length=512), nullable=True),
    sa.ForeignKeyConstraint(['instrument_id'], ['mkt.instruments.id'], name=op.f('fk_corporate_actions_instrument_id_instruments')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_corporate_actions')),
    sa.UniqueConstraint('instrument_id', 'ex_date', 'action_type', name=op.f('uq_corporate_actions_instrument_id_ex_date_action_type')),
    schema='mkt'
    )
    op.create_table('daily_candles',
    sa.Column('instrument_id', sa.Integer(), nullable=False),
    sa.Column('trade_date', sa.Date(), nullable=False),
    sa.Column('open', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('high', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('low', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('close', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('volume', sa.BigInteger(), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.ForeignKeyConstraint(['instrument_id'], ['mkt.instruments.id'], name=op.f('fk_daily_candles_instrument_id_instruments')),
    sa.PrimaryKeyConstraint('instrument_id', 'trade_date', name=op.f('pk_daily_candles')),
    schema='mkt'
    )
    op.create_table('indicators_daily',
    sa.Column('instrument_id', sa.Integer(), nullable=False),
    sa.Column('trade_date', sa.Date(), nullable=False),
    sa.Column('ema20', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('ema50', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('ema200', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('rsi14', sa.Numeric(precision=9, scale=4), nullable=True),
    sa.Column('macd', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('macd_signal', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('adx14', sa.Numeric(precision=9, scale=4), nullable=True),
    sa.Column('atr14', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('volume_ratio20', sa.Numeric(precision=9, scale=4), nullable=True),
    sa.Column('high52w_distance_pct', sa.Numeric(precision=9, scale=4), nullable=True),
    sa.Column('relative_strength_nifty', sa.Numeric(precision=9, scale=4), nullable=True),
    sa.ForeignKeyConstraint(['instrument_id'], ['mkt.instruments.id'], name=op.f('fk_indicators_daily_instrument_id_instruments')),
    sa.PrimaryKeyConstraint('instrument_id', 'trade_date', name=op.f('pk_indicators_daily')),
    schema='mkt'
    )
    op.create_table('intraday_candles_60m',
    sa.Column('instrument_id', sa.Integer(), nullable=False),
    sa.Column('ts', sa.DateTime(), nullable=False),
    sa.Column('open', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('high', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('low', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('close', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('volume', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['instrument_id'], ['mkt.instruments.id'], name=op.f('fk_intraday_candles_60m_instrument_id_instruments')),
    sa.PrimaryKeyConstraint('instrument_id', 'ts', name=op.f('pk_intraday_candles_60m')),
    schema='mkt'
    )
    op.create_table('symbol_aliases',
    sa.Column('instrument_id', sa.Integer(), nullable=False),
    sa.Column('alias', sa.Unicode(length=128), nullable=False),
    sa.ForeignKeyConstraint(['instrument_id'], ['mkt.instruments.id'], name=op.f('fk_symbol_aliases_instrument_id_instruments')),
    sa.PrimaryKeyConstraint('instrument_id', 'alias', name=op.f('pk_symbol_aliases')),
    schema='mkt'
    )
    op.create_table('backtest_trades',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('run_id', sa.Integer(), nullable=False),
    sa.Column('instrument_id', sa.Integer(), nullable=False),
    sa.Column('entry_date', sa.Date(), nullable=False),
    sa.Column('entry_price', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('exit_date', sa.Date(), nullable=True),
    sa.Column('exit_price', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('qty', sa.Integer(), nullable=False),
    sa.Column('pnl', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('exit_reason', sa.String(length=32), nullable=True),
    sa.ForeignKeyConstraint(['instrument_id'], ['mkt.instruments.id'], name=op.f('fk_backtest_trades_instrument_id_instruments')),
    sa.ForeignKeyConstraint(['run_id'], ['res.backtest_runs.id'], name=op.f('fk_backtest_trades_run_id_backtest_runs')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_backtest_trades')),
    schema='res'
    )
    op.create_index(op.f('ix_backtest_trades_run_id'), 'backtest_trades', ['run_id'], unique=False, schema='res')
    op.create_table('fundamentals_quarterly',
    sa.Column('instrument_id', sa.Integer(), nullable=False),
    sa.Column('period_end', sa.Date(), nullable=False),
    sa.Column('revenue', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('net_profit', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('eps', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('roe', sa.Numeric(precision=9, scale=4), nullable=True),
    sa.Column('debt_to_equity', sa.Numeric(precision=9, scale=4), nullable=True),
    sa.Column('pe', sa.Numeric(precision=9, scale=4), nullable=True),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.ForeignKeyConstraint(['instrument_id'], ['mkt.instruments.id'], name=op.f('fk_fundamentals_quarterly_instrument_id_instruments')),
    sa.PrimaryKeyConstraint('instrument_id', 'period_end', name=op.f('pk_fundamentals_quarterly')),
    schema='res'
    )
    op.create_table('news_sentiment',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('article_id', sa.BigInteger(), nullable=False),
    sa.Column('instrument_id', sa.Integer(), nullable=False),
    sa.Column('model', sa.String(length=128), nullable=False),
    sa.Column('prompt_version', sa.String(length=16), nullable=False),
    sa.Column('sentiment', sa.Numeric(precision=9, scale=4), nullable=False),
    sa.Column('relevance', sa.Numeric(precision=9, scale=4), nullable=False),
    sa.Column('impact', sa.String(length=16), nullable=True),
    sa.Column('rationale', sa.UnicodeText(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(sysutcdatetime())'), nullable=False),
    sa.ForeignKeyConstraint(['article_id'], ['res.news_articles.id'], name=op.f('fk_news_sentiment_article_id_news_articles')),
    sa.ForeignKeyConstraint(['instrument_id'], ['mkt.instruments.id'], name=op.f('fk_news_sentiment_instrument_id_instruments')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_news_sentiment')),
    sa.UniqueConstraint('article_id', 'instrument_id', 'model', 'prompt_version', name=op.f('uq_news_sentiment_article_id_instrument_id_model_prompt_version')),
    schema='res'
    )
    op.create_table('news_symbol_map',
    sa.Column('article_id', sa.BigInteger(), nullable=False),
    sa.Column('instrument_id', sa.Integer(), nullable=False),
    sa.Column('match_type', sa.String(length=16), nullable=False),
    sa.ForeignKeyConstraint(['article_id'], ['res.news_articles.id'], name=op.f('fk_news_symbol_map_article_id_news_articles')),
    sa.ForeignKeyConstraint(['instrument_id'], ['mkt.instruments.id'], name=op.f('fk_news_symbol_map_instrument_id_instruments')),
    sa.PrimaryKeyConstraint('article_id', 'instrument_id', name=op.f('pk_news_symbol_map')),
    schema='res'
    )
    op.create_table('research_reports',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('instrument_id', sa.Integer(), nullable=False),
    sa.Column('as_of_date', sa.Date(), nullable=False),
    sa.Column('model', sa.String(length=128), nullable=False),
    sa.Column('summary', sa.UnicodeText(), nullable=False),
    sa.Column('bull_case', sa.UnicodeText(), nullable=True),
    sa.Column('bear_case', sa.UnicodeText(), nullable=True),
    sa.Column('score', sa.Numeric(precision=9, scale=4), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(sysutcdatetime())'), nullable=False),
    sa.ForeignKeyConstraint(['instrument_id'], ['mkt.instruments.id'], name=op.f('fk_research_reports_instrument_id_instruments')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_research_reports')),
    schema='res'
    )
    op.create_index(op.f('ix_research_reports_instrument_id'), 'research_reports', ['instrument_id'], unique=False, schema='res')
    op.create_table('signals',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('instrument_id', sa.Integer(), nullable=False),
    sa.Column('as_of_date', sa.Date(), nullable=False),
    sa.Column('strategy', sa.String(length=64), nullable=False),
    sa.Column('action', sa.String(length=8), nullable=False),
    sa.Column('score', sa.Numeric(precision=9, scale=4), nullable=False),
    sa.Column('technical_score', sa.Numeric(precision=9, scale=4), nullable=True),
    sa.Column('news_score', sa.Numeric(precision=9, scale=4), nullable=True),
    sa.Column('fundamental_score', sa.Numeric(precision=9, scale=4), nullable=True),
    sa.Column('regime', sa.String(length=16), nullable=True),
    sa.Column('entry_price', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('stop_loss', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('target', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('confidence', sa.Numeric(precision=9, scale=4), nullable=True),
    sa.Column('rationale', sa.UnicodeText(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(sysutcdatetime())'), nullable=False),
    sa.ForeignKeyConstraint(['instrument_id'], ['mkt.instruments.id'], name=op.f('fk_signals_instrument_id_instruments')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_signals')),
    sa.UniqueConstraint('instrument_id', 'as_of_date', 'strategy', name=op.f('uq_signals_instrument_id_as_of_date_strategy')),
    schema='res'
    )
    op.create_index(op.f('ix_signals_as_of_date'), 'signals', ['as_of_date'], unique=False, schema='res')
    op.create_table('approval_queue',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('signal_id', sa.BigInteger(), nullable=True),
    sa.Column('instrument_id', sa.Integer(), nullable=False),
    sa.Column('side', sa.String(length=4), nullable=False),
    sa.Column('qty', sa.Integer(), nullable=False),
    sa.Column('limit_price', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('stop_loss', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('target', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('risk_amount', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('decided_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(sysutcdatetime())'), nullable=False),
    sa.ForeignKeyConstraint(['instrument_id'], ['mkt.instruments.id'], name=op.f('fk_approval_queue_instrument_id_instruments')),
    sa.ForeignKeyConstraint(['signal_id'], ['res.signals.id'], name=op.f('fk_approval_queue_signal_id_signals')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_approval_queue')),
    schema='trd'
    )
    op.create_index(op.f('ix_approval_queue_status'), 'approval_queue', ['status'], unique=False, schema='trd')
    op.create_table('paper_orders',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('instrument_id', sa.Integer(), nullable=False),
    sa.Column('signal_id', sa.BigInteger(), nullable=True),
    sa.Column('side', sa.String(length=4), nullable=False),
    sa.Column('qty', sa.Integer(), nullable=False),
    sa.Column('order_type', sa.String(length=8), nullable=False),
    sa.Column('limit_price', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('filled_price', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('filled_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(sysutcdatetime())'), nullable=False),
    sa.ForeignKeyConstraint(['instrument_id'], ['mkt.instruments.id'], name=op.f('fk_paper_orders_instrument_id_instruments')),
    sa.ForeignKeyConstraint(['signal_id'], ['res.signals.id'], name=op.f('fk_paper_orders_signal_id_signals')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_paper_orders')),
    schema='trd'
    )
    op.create_index(op.f('ix_paper_orders_status'), 'paper_orders', ['status'], unique=False, schema='trd')
    op.create_table('positions',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('book', sa.String(length=8), nullable=False),
    sa.Column('instrument_id', sa.Integer(), nullable=False),
    sa.Column('signal_id', sa.BigInteger(), nullable=True),
    sa.Column('qty', sa.Integer(), nullable=False),
    sa.Column('avg_price', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('stop_loss', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('target', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('opened_at', sa.DateTime(), nullable=False),
    sa.Column('closed_at', sa.DateTime(), nullable=True),
    sa.Column('exit_price', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('realized_pnl', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.ForeignKeyConstraint(['instrument_id'], ['mkt.instruments.id'], name=op.f('fk_positions_instrument_id_instruments')),
    sa.ForeignKeyConstraint(['signal_id'], ['res.signals.id'], name=op.f('fk_positions_signal_id_signals')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_positions')),
    schema='trd'
    )
    op.create_index(op.f('ix_positions_book'), 'positions', ['book'], unique=False, schema='trd')
    op.create_index(op.f('ix_positions_status'), 'positions', ['status'], unique=False, schema='trd')
    op.create_table('live_orders',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('approval_id', sa.BigInteger(), nullable=False),
    sa.Column('kite_order_id', sa.String(length=64), nullable=True),
    sa.Column('gtt_id', sa.String(length=64), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('dry_run', sa.Boolean(), nullable=False),
    sa.Column('payload_json', sa.UnicodeText(), nullable=False),
    sa.Column('response_json', sa.UnicodeText(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(sysutcdatetime())'), nullable=False),
    sa.ForeignKeyConstraint(['approval_id'], ['trd.approval_queue.id'], name=op.f('fk_live_orders_approval_id_approval_queue')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_live_orders')),
    schema='trd'
    )
    op.create_index(op.f('ix_live_orders_kite_order_id'), 'live_orders', ['kite_order_id'], unique=False, schema='trd')
    op.create_table('trades',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('book', sa.String(length=8), nullable=False),
    sa.Column('instrument_id', sa.Integer(), nullable=False),
    sa.Column('position_id', sa.BigInteger(), nullable=True),
    sa.Column('side', sa.String(length=4), nullable=False),
    sa.Column('qty', sa.Integer(), nullable=False),
    sa.Column('price', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('fees', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('executed_at', sa.DateTime(), nullable=False),
    sa.Column('order_ref', sa.String(length=64), nullable=True),
    sa.ForeignKeyConstraint(['instrument_id'], ['mkt.instruments.id'], name=op.f('fk_trades_instrument_id_instruments')),
    sa.ForeignKeyConstraint(['position_id'], ['trd.positions.id'], name=op.f('fk_trades_position_id_positions')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_trades')),
    schema='trd'
    )
    op.create_index(op.f('ix_trades_book'), 'trades', ['book'], unique=False, schema='trd')


def downgrade() -> None:
    op.drop_index(op.f('ix_trades_book'), table_name='trades', schema='trd')
    op.drop_table('trades', schema='trd')
    op.drop_index(op.f('ix_live_orders_kite_order_id'), table_name='live_orders', schema='trd')
    op.drop_table('live_orders', schema='trd')
    op.drop_index(op.f('ix_positions_status'), table_name='positions', schema='trd')
    op.drop_index(op.f('ix_positions_book'), table_name='positions', schema='trd')
    op.drop_table('positions', schema='trd')
    op.drop_index(op.f('ix_paper_orders_status'), table_name='paper_orders', schema='trd')
    op.drop_table('paper_orders', schema='trd')
    op.drop_index(op.f('ix_approval_queue_status'), table_name='approval_queue', schema='trd')
    op.drop_table('approval_queue', schema='trd')
    op.drop_index(op.f('ix_signals_as_of_date'), table_name='signals', schema='res')
    op.drop_table('signals', schema='res')
    op.drop_index(op.f('ix_research_reports_instrument_id'), table_name='research_reports', schema='res')
    op.drop_table('research_reports', schema='res')
    op.drop_table('news_symbol_map', schema='res')
    op.drop_table('news_sentiment', schema='res')
    op.drop_table('fundamentals_quarterly', schema='res')
    op.drop_index(op.f('ix_backtest_trades_run_id'), table_name='backtest_trades', schema='res')
    op.drop_table('backtest_trades', schema='res')
    op.drop_table('symbol_aliases', schema='mkt')
    op.drop_table('intraday_candles_60m', schema='mkt')
    op.drop_table('indicators_daily', schema='mkt')
    op.drop_table('daily_candles', schema='mkt')
    op.drop_table('corporate_actions', schema='mkt')
    op.drop_table('risk_limits', schema='trd')
    op.drop_table('portfolio_snapshots', schema='trd')
    op.drop_index(op.f('ix_news_articles_published_at'), table_name='news_articles', schema='res')
    op.drop_table('news_articles', schema='res')
    op.drop_table('backtest_runs', schema='res')
    op.drop_table('instruments', schema='mkt')
    op.drop_table('llm_calls', schema='app')
    op.drop_index(op.f('ix_kite_sessions_expires_at'), table_name='kite_sessions', schema='app')
    op.drop_table('kite_sessions', schema='app')
    op.drop_index(op.f('ix_job_runs_job_name'), table_name='job_runs', schema='app')
    op.drop_table('job_runs', schema='app')
    op.drop_table('app_settings', schema='app')
    for schema in reversed(SCHEMAS):
        op.execute(f"IF SCHEMA_ID('{schema}') IS NOT NULL EXEC('DROP SCHEMA [{schema}]')")
