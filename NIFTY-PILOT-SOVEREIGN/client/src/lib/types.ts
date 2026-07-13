export interface Trade {
  ID: string;
  Strategy: string;
  Underlying: string;
  Instrument: string;
  Direction: "LONG" | "SHORT";
  Strike: number;
  Lots: number;
  Quantity: number;
  EntryPrice: number;
  StopLoss: number;
  TakeProfit: number;
  ExitPrice?: number;
  ExitReason?: string;
  EntryAt: string;
  ExitAt?: string;
  Status: "OPEN" | "CLOSED";
  GrossPnL: number;
  EntryCostINR: number;
  ExitCostINR: number;
  NetPnL: number;
  MarginBlockedINR: number;
}

export interface EquitySnapshot {
  capital_inr: number;
  realized_pnl_inr: number;
  equity_inr: number;
  margin_used_inr: number;
  margin_available_inr: number;
  margin_utilization_pct: number;
}

export interface HealthSnapshot {
  status: "OPEN" | "CLOSED" | "PRE_OPEN" | "KILL_SWITCH_ACTIVE";
  time_ist: string;
  trading_day: boolean;
}

export interface StrategyStatus {
  strategy: string;
  status: "PROBATION" | "PENDING" | "ACTIVE" | "DEMOTED";
  last_window_sharpe: number;
  last_window_winrate: number;
}

export interface DailyPnLRow {
  date: string;
  pnlINR: number;
  pnlPct: number;
}

export interface MarketSnapshot {
  nifty_spot: number;
  banknifty_spot: number;
  india_vix: number;
  nifty_pcr: number;
  nifty_max_pain: number;
  banknifty_pcr: number;
  banknifty_max_pain: number;
}

export interface GreeksExposure {
  netDelta: number;
  netGamma: number;
  netTheta: number;
  netVega: number;
}

// ─── Mock Trading types ───────────────────────────────────────────────────────

export interface MockTradingStatus {
  engine_status: "MOCK_TRADING_ACTIVE" | "MARKET_CLOSED" | "PRE_OPEN_READY" | "KILL_SWITCH_ACTIVE";
  mock_trading_active: boolean;
  market_open: boolean;
  pre_open: boolean;
  trading_day: boolean;
  kill_switch_active: boolean;
  time_ist: string;
  date_ist: string;
  timestamp: string;
  market_open_time: string;
  market_close_time: string;
  next_market_open: string;
  session_start: string;
  session_end: string;
  auto_detection_enabled: boolean;
}

export interface MockTradingPortfolio {
  capital_inr: number;
  portfolio_value_inr: number;
  equity_inr: number;
  realized_pnl_inr: number;
  unrealized_pnl_inr: number;
  total_pnl_inr: number;
  daily_pnl_inr: number;
  weekly_pnl_inr: number;
  monthly_pnl_inr: number;
  margin_used_inr: number;
  margin_available_inr: number;
  margin_utilization_pct: number;
  open_positions: number;
  total_closed_trades: number;
  today_trades: number;
  today_wins: number;
  kill_switch_active: boolean;
}

export interface EquityPoint {
  date: string;
  equity_inr: number;
  drawdown_pct: number;
}

export interface DailyPnLPoint {
  date: string;
  pnl_inr: number;
  trades: number;
  win_rate: number;
}

export interface MonthlyReturnPoint {
  month: string;
  pnl_inr: number;
  return_pct: number;
  trades: number;
  win_rate: number;
}

export interface PnLBucket {
  label: string;
  count: number;
}

export interface MockTradingAnalytics {
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  breakeven_trades: number;
  win_rate: number;
  loss_rate: number;
  net_pnl_inr: number;
  gross_pnl_inr: number;
  total_fees_inr: number;
  profit_factor: number;
  expectancy_inr: number;
  avg_win_inr: number;
  avg_loss_inr: number;
  risk_reward_ratio: number;
  max_drawdown_pct: number;
  max_drawdown_inr: number;
  sharpe_ratio: number;
  sortino_ratio: number;
  cagr: number;
  recovery_factor: number;
  max_consecutive_wins: number;
  max_consecutive_losses: number;
  avg_hold_minutes: number;
  largest_win_inr: number;
  largest_loss_inr: number;
  equity_curve: EquityPoint[];
  daily_pnl: DailyPnLPoint[];
  monthly_returns: MonthlyReturnPoint[];
  pnl_distribution: PnLBucket[];
}

// ─── Strategy Validation types ────────────────────────────────────────────────

export interface ValidationFailure {
  Rule: string;
  Actual: number;
  Target: number;
}

export interface ValidationResult {
  Passed: boolean;
  Failures: ValidationFailure[];
}

export interface WindowStats {
  Trades: number;
  WinRate: number;
  Sharpe: number;
  ProfitFactor: number;
  Expectancy: number;
  MaxDrawdown: number;
}

export interface StrategyValidationStatus {
  strategy: string;
  status: "PROBATION" | "PENDING" | "ACTIVE" | "DEMOTED";
  mock_trading_approved: boolean;
  is_tradeable: boolean;
  windows_completed: number;
  current_window_progress: number;
  trades_needed_for_next_window: number;
  last_window?: WindowStats;
  validation_result?: ValidationResult;
  rejection_reason?: string;
}

// ─── Strategy Leaderboard types ───────────────────────────────────────────────

export interface LeaderboardEntry {
  rank: number;
  name: string;
  status: string;
  mock_trading_approved: boolean;
  validation_reason?: string;
  total_trades: number;
  winning_trades: number;
  win_rate: number;
  net_pnl_inr: number;
  profit_factor: number;
  sharpe: number;
  max_drawdown_pct: number;
  recovery_factor: number;
  expectancy_inr: number;
  overall_score: number;
  windows_completed: number;
  current_window_progress: number;
  last_validation?: ValidationResult;
}

// ─── Backtest types ───────────────────────────────────────────────────────────

export interface BacktestEquityPoint {
  time: string;
  equity_inr: number;
}

export interface WalkForwardWindow {
  start_trade: number;
  end_trade: number;
  trades: number;
  sharpe: number | null;
  win_rate: number;
  max_drawdown: number;
  profit_factor: number | null;
  avg_win_size_inr: number;
  avg_loss_size_inr: number;
  status: "PASS" | "FAIL" | "INSUFFICIENT_DATA";
}

export interface WalkForwardResult {
  strategy: string;
  total_trades: number;
  window1: WalkForwardWindow;
  window2: WalkForwardWindow;
  promotion_status: "PROMOTED" | "REJECTED" | "INSUFFICIENT_DATA";
  reasoning: string;
  rolling_windows?: RollingWindow[];
  stability_score?: number;
  stability_status?: "STABLE" | "UNSTABLE";
}

export interface RollingWindow {
  window_index: number;
  is_start: string;
  is_end: string;
  oos_start: string;
  oos_end: string;
  is_result: WalkForwardWindow;
  oos_result: WalkForwardWindow;
  promoted: boolean;
}

export interface YearlyBreakdown {
  year: number;
  trades: number;
  gross_pnl_inr: number;
  net_pnl_inr: number;
  win_rate: number;
  sharpe: number;
  max_drawdown: number;
  calmar: number;
}

export interface RegimePerformance {
  strategy: string;
  regime: string;
  trades: number;
  net_pnl_inr: number;
  win_rate: number;
  avg_pnl_inr: number;
}

export interface DrawdownPeriod {
  start: string;
  end: string;
  trough: string;
  drawdown_pct: number;
  duration_days: number;
  recovery_days: number;
}

export interface PerStrategyExtended {
  strategy: string;
  total_trades: number;
  net_pnl_inr: number;
  win_rate: number;
  sharpe: number;
  sortino: number;
  calmar: number;
  omega: number;
  ulcer_index: number;
  max_drawdown: number;
  profit_factor: number;
  avg_win_inr: number;
  avg_loss_inr: number;
  promotion_status: string;
}

export interface MonthlyReturnsRow {
  strategy: string;
  monthly: Record<string, number>;
}

export interface BacktestJobStatus {
  id: string;
  status: "RUNNING" | "DONE" | "ERROR";
  progress: number;
  message?: string;
  error?: string;
  out_dir?: string;
}

export interface BacktestRunSummary {
  id: string;
  status: string;
  progress: number;
  out_dir?: string;
}

export interface BacktestFullResults {
  data_source: string;
  from: string;
  to: string;
  capital_inr: number;
  trades: Trade[];
  equity: BacktestEquityPoint[];
  walk_forward: WalkForwardResult[];
  per_strategy: PerStrategyExtended[];
  yearly_breakdowns: Record<string, YearlyBreakdown[]>;
  regime_performances: Record<string, RegimePerformance[]>;
  correlation_matrix: Record<string, Record<string, number>>;
  monthly_returns_map: Record<string, Record<string, number>>;
  drawdown_periods: DrawdownPeriod[];
}

export interface BacktestConfig {
  years: number;
  from?: string;
  to?: string;
  capital: number;
  instruments: string;
  data_source: string;
  strategies: string[];
  max_concurrent: number;
}
