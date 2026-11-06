export type KiteStatus = {
  configured: boolean;
  connected: boolean;
  user_id: string | null;
  expires_at: string | null;
  login_url: string | null;
};

export type JobRun = {
  id: number;
  job_name: string;
  status: "running" | "success" | "failed";
  started_at: string;
  finished_at: string | null;
  rows_affected: number | null;
  details: string | null;
  error: string | null;
};

export type InstrumentSummary = {
  id: number;
  symbol: string;
  name: string | null;
  sector: string | null;
  segment: string | null;
  last_date: string | null;
  last_close: number | null;
  change_pct: number | null;
};

export type StockDetail = InstrumentSummary & {
  industry: string | null;
  candles: Record<"day" | "60m", { count: number; first: string | null; last: string | null }>;
};

export type Candle = {
  time: string | number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

export type NewsTag = {
  symbol: string;
  match_type: string;
  sentiment?: number;
  relevance?: number;
  impact?: string | null;
  rationale?: string | null;
};

export type NewsItem = {
  id: number;
  title: string;
  url: string;
  source: string;
  summary: string | null;
  published_at: string | null;
  analyzed: boolean;
  market_sentiment: number | null;
  symbols: NewsTag[];
};

export type LlmUsage = {
  model: string;
  configured: boolean;
  last_24h: { calls: number; cost_usd: number; tokens: number };
  last_30d: { calls: number; cost_usd: number; tokens: number };
};

export type Regime = {
  name: "bull" | "neutral" | "bear" | "volatile" | "unknown";
  as_of: string | null;
  nifty_close: number | null;
  nifty_ema50: number | null;
  nifty_ema200: number | null;
  nifty_rsi: number | null;
  vix: number | null;
  summary: string;
};

export type SignalItem = {
  symbol: string;
  name: string | null;
  sector: string | null;
  as_of: string;
  action: "BUY" | "SELL" | "HOLD";
  score: number;
  technical_score: number | null;
  news_score: number | null;
  regime: string | null;
  entry: number | null;
  stop: number | null;
  target: number | null;
  reward_risk: number | null;
  confidence: number | null;
  rationale: string | null;
  research_verdict: "buy" | "wait" | "avoid" | null;
};

export type SignalList = { as_of: string | null; counts: Partial<Record<SignalItem["action"], number>>; items: SignalItem[] };

export type ResearchReport = {
  as_of: string;
  model: string;
  summary: string;
  bull_case: string[];
  bear_case: string[];
  key_risks: string[];
  verdict: "buy" | "wait" | "avoid" | null;
  conviction: number;
  created_at: string | null;
};

export type StockAnalysis = {
  signal: SignalItem | null;
  indicators: (Record<string, number | null> & { as_of: string }) | null;
  research: ResearchReport | null;
};

export type LinePoint = { time: string; value: number };

export type StrategyParamsShape = {
  name: string;
  model: "score" | "momentum";
  top_n: number;
  exit_rank: number;
  market_filter: boolean;
  sizing: "risk" | "equal";
  slots: number;
  buy_threshold: number;
  sell_threshold: number;
  news_weight: number;
  news_veto: number;
  stop_atr: number;
  target_atr: number;
  max_rsi: number;
  min_traded_value_cr: number;
  max_hold_days: number;
  trail_atr: number;
  entry_regimes: string[];
  regime_adjustment: Record<string, number>;
};

export type BacktestMetrics = {
  start: string;
  end: string;
  final_equity: number;
  total_return_pct: number;
  cagr_pct: number;
  max_drawdown_pct: number;
  sharpe: number;
  sortino: number;
  trades: number;
  win_rate_pct: number;
  avg_win: number;
  avg_loss: number;
  profit_factor: number | null;
  avg_r: number;
  avg_hold_days: number;
  benchmark_cagr_pct: number;
  benchmark_max_drawdown_pct: number;
  exit_reasons: Record<string, number>;
  folds?: {
    train_start: string;
    train_end: string;
    test_start: string;
    test_end: string;
    params: StrategyParamsShape;
    train_metrics: BacktestMetrics;
    test_metrics: BacktestMetrics;
  }[];
  combos_tested?: number;
};

export type BacktestSummary = {
  id: number;
  kind: "single" | "walk_forward";
  strategy: string;
  created_at: string | null;
  start: string;
  end: string;
  cagr_pct: number | null;
  max_drawdown_pct: number | null;
  sharpe: number | null;
  win_rate_pct: number | null;
  trades: number | null;
  benchmark_cagr_pct: number | null;
  params: StrategyParamsShape;
};

export type BacktestDetail = BacktestSummary & {
  metrics: BacktestMetrics;
  equity: { time: string; equity: number; benchmark: number | null }[];
  trades: {
    symbol: string;
    entry_date: string;
    entry_price: number;
    exit_date: string | null;
    exit_price: number | null;
    qty: number;
    pnl: number | null;
    exit_reason: string | null;
  }[];
};

export type ActiveParams = { active: StrategyParamsShape; source: string; defaults: StrategyParamsShape };

export type PaperPosition = {
  id: number;
  symbol: string;
  sector: string | null;
  qty: number;
  entry: number;
  price: number;
  price_at: string | null;
  stop: number | null;
  initial_stop: number | null;
  target: number | null;
  value: number;
  pnl: number;
  pnl_pct: number | null;
  r_multiple: number | null;
  opened_at: string | null;
  closed_at: string | null;
  exit_price: number | null;
  exit_reason: string | null;
  status: string;
};

export type PaperOrder = {
  id: number;
  symbol: string;
  side: "BUY" | "SELL";
  qty: number;
  status: "pending" | "filled" | "cancelled" | "rejected";
  reference: number | null;
  stop: number | null;
  target: number | null;
  filled_price: number | null;
  as_of: string | null;
  reason: string | null;
  created_at: string | null;
};

export type Portfolio = {
  book: string;
  capital: number;
  cash: number;
  invested: number;
  market_value: number;
  equity: number;
  total_return_pct: number;
  realized_pnl: number;
  unrealized_pnl: number;
  reserved_for_orders: number;
  kill_switch: boolean;
  next_session: string;
  positions: PaperPosition[];
  orders: PaperOrder[];
};

export type PortfolioHistory = {
  closed: PaperPosition[];
  stats: { trades: number; win_rate_pct: number | null; realized_pnl: number };
  equity: { time: string; equity: number }[];
};

export type RiskLimits = {
  capital: number;
  risk_per_trade_pct: number;
  max_position_pct: number;
  max_open_positions: number;
  daily_loss_limit_pct: number;
  weekly_loss_limit_pct: number;
  max_sector_pct: number;
  kill_switch: boolean;
  updated_at: string | null;
};

export type JobLastRun = {
  started_at: string | null;
  finished_at: string | null;
  status: "running" | "success" | "failed";
  details: string | null;
  error: string | null;
};

export type SchedulerJob = {
  id: string;
  title: string;
  schedule: string;
  enabled: boolean;
  next_run: string | null;
  last_run: JobLastRun | null;
};

export type DataFreshness = { key: string; label: string; at: string | null; as_of: string | null; job: string | null };

export type SchedulerStatus = {
  now: string;
  market: { open: boolean; trading_day: boolean; opens_at: string | null; closes_at: string | null };
  kite: { login_at: string | null; expires_at: string | null };
  jobs: SchedulerJob[];
  data: DataFreshness[];
};

export type LiveSettings = {
  mode: "paper" | "approve";
  dry_run: boolean;
  live_capital: number;
  max_order_value: number;
  entry_buffer_pct: number;
  max_price_drift_pct: number;
};

export type LiveOrderRecord = {
  id: number;
  symbol: string;
  kind: "entry" | "exit" | "gtt";
  status: string;
  dry_run: boolean;
  kite_order_id: string | null;
  gtt_id: string | null;
  status_message: string | null;
  filled_qty: number | null;
  average_price: number | null;
  payload: Record<string, unknown>;
  created_at: string | null;
  updated_at: string | null;
};

export type Approval = {
  id: number;
  kind: "entry" | "exit";
  symbol: string;
  name: string | null;
  sector: string | null;
  side: "BUY" | "SELL";
  qty: number;
  limit_price: number | null;
  value: number | null;
  stop: number | null;
  target: number | null;
  risk_amount: number | null;
  status: string;
  reason: string | null;
  expires_at: string | null;
  decided_at: string | null;
  score: number | null;
  signal_date: string | null;
  research_verdict: string | null;
  order: LiveOrderRecord | null;
};

export type ApprovalList = { settings: LiveSettings; kite_connected: boolean; items: Approval[] };

export type AccountSummary = {
  now_ist: string;
  market: { open: boolean; trading_day: boolean; next_session: string };
  regime: { name: Regime["name"]; vix: number | null; nifty: number | null };
  mode: { mode: "paper" | "approve"; dry_run: boolean; kill_switch: boolean };
  kite: {
    connected: boolean;
    user_id?: string;
    expires_at?: string;
    error?: string;
    available_cash?: number;
    opening_balance?: number;
    used_margin?: number;
    net?: number;
    holdings_count?: number;
    holdings_value?: number;
    holdings_invested?: number;
    holdings_pnl?: number;
    positions_open?: number;
    today_pnl?: number;
    today_pnl_pct?: number | null;
  };
  paper: {
    equity: number;
    cash: number;
    today_pnl: number;
    today_pnl_pct: number | null;
    total_return_pct: number;
    open_positions: number;
    pending_orders: number;
  };
};
