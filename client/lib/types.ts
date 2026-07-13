export type MarketStatus = 'OPEN' | 'PRE_OPEN' | 'CLOSED' | 'KILL_SWITCH_ACTIVE'

export interface HealthResponse {
  status: MarketStatus
  time_ist?: string
  trading_day?: boolean
}

// Raw shape from Go engine /api/equity
export interface EquityRaw {
  capital_inr: number
  equity_inr: number
  margin_available_inr: number
  margin_used_inr: number
  margin_utilization_pct: number
  realized_pnl_inr: number
}

// Normalised shape used throughout the frontend
export interface EquityResponse {
  capital: number
  equity: number
  margin_used: number
  margin_available: number
  margin_utilization_pct: number
  pnl: number
}

// Raw trade from Go engine (PascalCase)
export interface TradeRaw {
  ID: string
  Strategy: string
  Underlying: string
  Instrument: string
  Direction: 'LONG' | 'SHORT'
  Strike: number
  Lots: number
  Quantity: number
  EntryPrice: number
  StopLoss: number
  TakeProfit: number
  ExitPrice: number
  ExitReason: string
  EntryAt: string
  ExitAt: string
  Status: 'OPEN' | 'CLOSED'
  GrossPnL: number
  EntryCostINR: number
  ExitCostINR: number
  NetPnL: number
  MarginBlockedINR: number
}

// Normalised trade used throughout the frontend
export interface Trade {
  id: string
  strategy: string
  underlying: string
  instrument: string
  direction: 'LONG' | 'SHORT'
  strike: number
  lots: number
  quantity: number
  entryPrice: number
  stopLoss: number
  takeProfit: number
  exitPrice: number
  exitReason: string
  entryAt: string
  exitAt: string | null
  status: 'OPEN' | 'CLOSED'
  grossPnl: number
  entryCostINR: number
  exitCostINR: number
  netPnl: number
  marginBlockedINR: number
}

// Raw strategy from Go engine
export interface StrategyStatsRaw {
  strategy: string
  status: string
  last_window_sharpe: number
  last_window_winrate: number
}

export interface StrategyStats {
  id: string
  name: string
  timeframe: 'scalping' | 'intraday' | 'swing'
  regime: string
  totalTrades: number
  winRate: number
  netPnl: number
  sharpe: number
  maxDrawdown: number
  status: 'ACTIVE' | 'BLOCKED' | 'INSUFFICIENT_DATA' | 'DEMOTED'
  promotionWindow: number
}

// Raw market from Go engine
export interface MarketDataRaw {
  nifty_spot: number
  banknifty_spot: number
  india_vix: number
  nifty_pcr: number
  banknifty_pcr: number
  nifty_max_pain: number
  banknifty_max_pain: number
  regime?: string
  regime_code?: number
}

export interface MarketData {
  spot: number
  banknifty_spot: number
  vix: number
  pcr: number
  max_pain: number
  regime: string
  regime_code: number
}

export interface StrategyDefinition {
  id: string
  name: string
  timeframe: 'scalping' | 'intraday' | 'swing'
  type: string
  allowedRegimes: string[]
  description: string
  minSLPct: number
  minRR: number
  targetWinRate: number
  instruments: string[]
}

export interface RegimeDefinition {
  code: string
  label: string
  color: string
  sizeMult: number
  description: string
}

// ─── Mock Trading types ───────────────────────────────────────────────────────

export interface MockTradingStatus {
  engine_status: 'MOCK_TRADING_ACTIVE' | 'MARKET_CLOSED' | 'PRE_OPEN_READY' | 'KILL_SWITCH_ACTIVE'
  mock_trading_active: boolean
  market_open: boolean
  pre_open: boolean
  trading_day: boolean
  kill_switch_active: boolean
  time_ist: string
  date_ist: string
  timestamp: string
  market_open_time: string
  market_close_time: string
  next_market_open: string
  session_start: string
  session_end: string
  auto_detection_enabled: boolean
}

export interface MockTradingPortfolio {
  capital_inr: number
  portfolio_value_inr: number
  equity_inr: number
  realized_pnl_inr: number
  unrealized_pnl_inr: number
  total_pnl_inr: number
  daily_pnl_inr: number
  weekly_pnl_inr: number
  monthly_pnl_inr: number
  margin_used_inr: number
  margin_available_inr: number
  margin_utilization_pct: number
  open_positions: number
  total_closed_trades: number
  today_trades: number
  today_wins: number
  kill_switch_active: boolean
}

export interface EquityPoint {
  date: string
  equity_inr: number
  drawdown_pct: number
}

export interface DailyPnLPoint {
  date: string
  pnl_inr: number
  trades: number
  win_rate: number
}

export interface MonthlyReturnPoint {
  month: string
  pnl_inr: number
  return_pct: number
  trades: number
  win_rate: number
}

export interface PnLBucket {
  label: string
  count: number
}

export interface MockTradingAnalytics {
  total_trades: number
  winning_trades: number
  losing_trades: number
  breakeven_trades: number
  win_rate: number
  loss_rate: number
  net_pnl_inr: number
  gross_pnl_inr: number
  total_fees_inr: number
  profit_factor: number
  expectancy_inr: number
  avg_win_inr: number
  avg_loss_inr: number
  risk_reward_ratio: number
  max_drawdown_pct: number
  max_drawdown_inr: number
  sharpe_ratio: number
  sortino_ratio: number
  cagr: number
  recovery_factor: number
  max_consecutive_wins: number
  max_consecutive_losses: number
  avg_hold_minutes: number
  largest_win_inr: number
  largest_loss_inr: number
  equity_curve: EquityPoint[]
  daily_pnl: DailyPnLPoint[]
  monthly_returns: MonthlyReturnPoint[]
  pnl_distribution: PnLBucket[]
}

export interface ValidationFailure {
  Rule: string
  Actual: number
  Target: number
}

export interface ValidationResult {
  Passed: boolean
  Failures: ValidationFailure[]
}

export interface WindowStats {
  Trades: number
  WinRate: number
  Sharpe: number
  ProfitFactor: number
  Expectancy: number
  MaxDrawdown: number
}

export interface StrategyValidationStatus {
  strategy: string
  status: 'PROBATION' | 'PENDING' | 'ACTIVE' | 'DEMOTED'
  mock_trading_approved: boolean
  is_tradeable: boolean
  windows_completed: number
  current_window_progress: number
  trades_needed_for_next_window: number
  last_window?: WindowStats
  validation_result?: ValidationResult
  rejection_reason?: string
}

export interface LeaderboardEntry {
  rank: number
  name: string
  status: string
  mock_trading_approved: boolean
  validation_reason?: string
  total_trades: number
  winning_trades: number
  win_rate: number
  net_pnl_inr: number
  profit_factor: number
  sharpe: number
  max_drawdown_pct: number
  recovery_factor: number
  expectancy_inr: number
  overall_score: number
  windows_completed: number
  current_window_progress: number
  last_validation?: ValidationResult
}

// ─────────────────────────────────────────────────────────────────────────────

export type SortField = 'sharpe' | 'winRate' | 'netPnl' | 'totalTrades'
export type SortDirection = 'asc' | 'desc'

export interface FilterState {
  timeframe: 'all' | 'scalping' | 'intraday' | 'swing'
  regime: string
  status: string
  sortField: SortField
  sortDirection: SortDirection
}

export interface TradeFilter {
  strategy: string
  instrument: string
  direction: string
  status: string
  exitReason: string
  dateFrom: string
  dateTo: string
}
