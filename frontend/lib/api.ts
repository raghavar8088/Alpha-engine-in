// Nullish (not ||) so an intentional "" (same-origin, routed through app/api/[...path]
// proxy below) isn't clobbered by the localhost fallback — "" is falsy but not nullish.
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface MarketDataSnapshot {
  symbol: string;
  price: number;
  change: number | null;
  pct_change: number | null;
  volume: number | null;
  updated_at: string;
}

export async function fetchLatestMarketData(): Promise<MarketDataSnapshot[]> {
  const res = await fetch(`${API_URL}/api/market-data/latest`);
  if (!res.ok) throw new Error("Failed to fetch market data");
  return res.json();
}

export interface MarketDataHistoryPoint {
  price: number;
  recorded_at: string;
}

export async function fetchMarketDataHistory(symbol: string, limit = 30): Promise<MarketDataHistoryPoint[]> {
  const res = await fetch(`${API_URL}/api/market-data/${encodeURIComponent(symbol)}/history?limit=${limit}`);
  if (!res.ok) throw new Error("Failed to fetch market data history");
  return res.json();
}

export function marketDataWsUrl(): string {
  const wsBase = API_URL.replace(/^http/, "ws");
  return `${wsBase}/ws/market-data`;
}

export function brokerOrdersWsUrl(): string {
  const wsBase = API_URL.replace(/^http/, "ws");
  return `${wsBase}/ws/broker/orders`;
}

export interface BrokerConnection {
  broker: string;
  client_id: string;
  connected_at: string;
  dhan_name: string | null;
}

// A refresh must re-read the database, not re-serve the short server-side cache that
// makes ordinary loads fast. `refreshing()` raises this flag for the duration of one
// load, and every request started inside it asks the backend to skip its cache.
let FORCE_FRESH = false;

/** Run a loader with cache-bypass on every request it fires. */
export async function refreshing<T>(fn: () => Promise<T>): Promise<T> {
  FORCE_FRESH = true;
  try {
    // The flag is read synchronously as each request is created, so a Promise.all of
    // six fetches all pick it up before the first await resolves.
    return await fn();
  } finally {
    FORCE_FRESH = false;
  }
}

async function apiFetch(path: string, init?: RequestInit) {
  if (FORCE_FRESH) {
    path += `${path.includes("?") ? "&" : "?"}fresh=true`;
  }
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      ...(init?.headers || {}),
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
    },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed: ${res.status}`);
  }
  return res.json();
}

export async function fetchBrokerStatus(): Promise<BrokerConnection | null> {
  return apiFetch("/api/broker/status");
}

export async function connectBroker(accessToken: string): Promise<BrokerConnection> {
  return apiFetch("/api/broker/connect", {
    method: "POST",
    body: JSON.stringify({ access_token: accessToken }),
  });
}

export async function fetchHoldings() {
  return apiFetch("/api/broker/holdings");
}

export async function fetchPositions() {
  return apiFetch("/api/broker/positions");
}

export async function fetchFunds() {
  return apiFetch("/api/broker/funds");
}

export interface PlaceOrderRequest {
  security_id: string;
  exchange_segment: string;
  transaction_type: string;
  quantity: number;
  order_type: string;
  product_type: string;
  price?: number;
  trigger_price?: number;
  paper_trading: boolean;
}

export async function placeOrder(order: PlaceOrderRequest) {
  return apiFetch("/api/broker/orders", {
    method: "POST",
    body: JSON.stringify(order),
  });
}

export async function fetchOrders() {
  return apiFetch("/api/broker/orders");
}

// --- Strategies & Backtesting (roadmap Phases 1-2) ---

export interface ValidationRun {
  symbol: string;
  timeframe: string;
  bar_count: number;
  passed: boolean;
  fail_reasons: string[];
  metrics: Record<string, number | null>;
}

export interface RealMoneyCheck {
  symbol: string;
  timeframe: string;
  ready: boolean;
  consistency: number | null;
  oos_net_profit: number | null;
  oos_total_trades: number | null;
  error: string | null;
}

export interface ValidationSummary {
  status: "pass" | "fail" | "insufficient_data";
  passed: boolean;
  passing_runs: number;
  total_runs: number;
  validated_at: string;
  best_run: ValidationRun | null;
  runs: ValidationRun[];
  real_money: RealMoneyCheck | null;
  real_money_ready: boolean;
}

export interface StrategyInfo {
  strategy_id: string;
  name: string;
  category: string;
  description: string;
  timeframes: string[];
  asset_classes: string[];
  suitable_market: string;
  expected_win_rate: number | null;
  risk_reward: number | null;
  params_schema: { properties?: Record<string, { default?: unknown; type?: string; title?: string }> };
  validation: ValidationSummary | null;
}

export async function fetchStrategies(): Promise<StrategyInfo[]> {
  return apiFetch("/api/strategies");
}

export interface BacktestRequest {
  strategy_id: string;
  symbol: string;
  timeframe: string;
  years?: number;
  initial_capital: number;
  params: Record<string, unknown>;
  walk_forward: boolean;
  monte_carlo: boolean;
}

export interface BacktestSummary {
  id: string;
  strategy_id: string;
  symbol: string;
  timeframe: string;
  start: string;
  end: string;
  bar_count: number;
  created_at: string;
  metrics: Record<string, number | null>;
}

export async function runBacktest(request: BacktestRequest) {
  return apiFetch("/api/backtest", { method: "POST", body: JSON.stringify(request) });
}

export async function fetchBacktests(limit = 20): Promise<BacktestSummary[]> {
  return apiFetch(`/api/backtest?limit=${limit}`);
}

export async function fetchBacktest(id: string) {
  return apiFetch(`/api/backtest/${id}`);
}

// --- Portfolio analytics & risk (roadmap Phase 4) ---

export interface SectorAllocationItem {
  sector: string;
  value: number;
  pct: number;
}

export interface PortfolioAnalytics {
  unrealized_pnl: number;
  unrealized_pnl_holdings: number;
  unrealized_pnl_positions: number;
  realized_pnl_today: number;
  holdings_value: number;
  positions_notional: number;
  capital_allocation: { total_capital: number; cash_available: number; deployed: number };
  exposure_pct: number | null;
  exposure_note: string;
  holdings_pct_of_portfolio: number | null;
  sector_allocation: SectorAllocationItem[];
  beta: number | null;
  alpha_annual_pct: number | null;
  volatility_annual_pct: number | null;
  beta_symbols_used: string[];
  beta_note: string | null;
  computed_at: string;
}

export async function fetchPortfolioAnalytics(): Promise<PortfolioAnalytics> {
  return apiFetch("/api/portfolio/analytics");
}

export interface RiskLimits {
  daily_loss_limit_pct: number;
  max_drawdown_pct: number;
  max_open_positions: number;
  max_exposure_pct: number;
  max_sector_exposure_pct: number;
  max_portfolio_heat_pct: number;
}

export interface RiskStatus {
  total_capital: number;
  day_start_equity: number;
  day_pnl: number;
  day_pnl_pct: number | null;
  open_positions_count: number;
  limits: RiskLimits;
  kill_switch_active: boolean;
  kill_switch_reasons: string[];
  note: string;
}

export async function fetchRiskStatus(): Promise<RiskStatus> {
  return apiFetch("/api/risk/status");
}

export async function fetchRiskConfig(): Promise<RiskLimits> {
  return apiFetch("/api/risk/config");
}

export async function updateRiskConfig(limits: Partial<RiskLimits>): Promise<RiskLimits> {
  return apiFetch("/api/risk/config", { method: "PUT", body: JSON.stringify(limits) });
}

// --- Live strategy engine (roadmap Phase 5) ---

export interface StartRunRequest {
  strategy_id: string;
  symbol: string;
  timeframe: string;
  mode: "HISTORICAL" | "BACKTEST" | "REPLAY" | "SIMULATION" | "PAPER" | "LIVE";
  params?: Record<string, unknown>;
  initial_capital?: number;
  years?: number;
  simulation_bars?: number;
  confirm_live?: boolean;
}

export interface RunSummary {
  run_id: string;
  strategy_id: string;
  symbol: string;
  timeframe: string;
  mode: string;
  status: string;
  started_at: string;
  stopped_at: string | null;
  snapshot: Record<string, any> | null;
}

export interface RunDetail extends RunSummary {
  result: Record<string, any> | null;
  error: string | null;
}

export async function startRun(request: StartRunRequest): Promise<RunDetail> {
  return apiFetch("/api/live/runs", { method: "POST", body: JSON.stringify(request) });
}

export async function fetchRuns(limit = 50): Promise<RunSummary[]> {
  return apiFetch(`/api/live/runs?limit=${limit}`);
}

export async function fetchRun(runId: string): Promise<RunDetail> {
  return apiFetch(`/api/live/runs/${runId}`);
}

export async function stopRun(runId: string): Promise<{ stopped: boolean }> {
  return apiFetch(`/api/live/runs/${runId}/stop`, { method: "POST" });
}

// --- Options analytics (roadmap Phase 7) ---

export interface OptionLeg {
  greeks: { delta: number; theta: number; gamma: number; vega: number; rho?: number };
  implied_volatility: number;
  implied_volatility_source: "broker" | "computed" | null;
  greeks_source: "broker" | "computed" | null;
  last_price: number;
  oi: number;
  previous_close_price: number;
  previous_oi: number;
  volume: number;
  top_bid_price: number;
  top_ask_price: number;
}

export interface OptionStrikeRow {
  strike: number;
  ce: OptionLeg;
  pe: OptionLeg;
}

export interface OptionChain {
  spot: number;
  expiry: string;
  days_to_expiry: number;
  strikes: OptionStrikeRow[];
  pcr_oi: number | null;
  max_pain: number | null;
}

export async function fetchExpiries(symbol: string): Promise<{ symbol: string; expiries: string[] }> {
  return apiFetch(`/api/options/expiries/${symbol}`);
}

export async function fetchOptionChain(symbol: string, expiry: string): Promise<OptionChain> {
  return apiFetch(`/api/options/chain/${symbol}?expiry=${expiry}`);
}

export interface PayoffLegRequest {
  option_type: string;
  strike: number;
  premium: number;
  quantity: number;
  direction: string;
}

export async function fetchPayoff(legs: PayoffLegRequest[], spot?: number, daysToExpiry = 30) {
  return apiFetch("/api/options/payoff", {
    method: "POST",
    body: JSON.stringify({ legs, spot, days_to_expiry: daysToExpiry }),
  });
}

export interface OptionsBacktestRequest {
  strategy_id: string;
  symbol: string;
  timeframe?: string;
  years?: number;
  lot_size?: number;
  quantity_lots?: number;
  dte_days?: number;
  otm_pct?: number;
}

export async function runOptionsBacktest(request: OptionsBacktestRequest) {
  return apiFetch("/api/options/backtest", { method: "POST", body: JSON.stringify(request) });
}

// --- 50-strategy option-buying lab ---

export interface OptionsSweepRequest {
  symbol?: string;
  years?: number;
  min_win_rate?: number;
  min_trades?: number;
  min_expectancy?: number;
  adx_regime?: number | null;
}

export interface SweepEntry {
  strategy_id: string;
  name: string;
  style: string;
  symbol?: string;
  timeframe: string;
  timeframe_native: string;
  data_from?: string;
  data_to?: string;
  metrics?: Record<string, any>;
  structure?: Record<string, any>;
  qualified?: boolean;
  error?: string;
}

export interface OptionsSweep {
  sweep_id: string | null;
  created_at?: string;
  symbol?: string;
  years?: number;
  min_win_rate?: number;
  min_trades?: number;
  pricing_model?: string;
  qualified_count: number;
  strategy_count: number;
  results: SweepEntry[];
}

export async function runOptionsSweep(request: OptionsSweepRequest): Promise<OptionsSweep> {
  return apiFetch("/api/options/backtest-all", { method: "POST", body: JSON.stringify(request) });
}

export async function fetchQualifiedStrategies(): Promise<OptionsSweep> {
  return apiFetch("/api/options/qualified");
}

// --- Option SELLING lab (separate desk, separate gate, separate collection) ---
//
// Kept structurally apart from the buying sweep above rather than sharing its types:
// the two are judged by different rules (selling ignores win rate entirely, buying is
// built on it) and a shared shape would invite rendering them in one leaderboard, which
// would compare strategies held to different standards.

export interface OptionsSellingSweepRequest {
  symbol?: string;
  years?: number;
  min_profit_factor?: number;
  min_trades?: number;
  max_worst_trade_pct_capital?: number;
  max_drawdown_pct?: number;
  naked_min_profit_factor?: number;
  naked_max_worst_trade_pct_capital?: number;
}

export interface SellingGate {
  min_profit_factor: number;
  min_trades: number;
  max_worst_trade_pct_capital: number;
  max_drawdown_pct: number;
  naked_min_profit_factor: number;
  naked_max_worst_trade_pct_capital: number;
  naked_threshold_pct?: number;
}

export interface SellingSweepEntry {
  strategy_id: string;
  name: string;
  style: string;
  timeframe: string;
  suitable_market?: string;
  data_from?: string;
  data_to?: string;
  metrics?: Record<string, any>;
  structure?: Record<string, any>;
  qualified?: boolean;
  naked?: boolean;
  gate_failures?: string[];
  error?: string;
}

export interface OptionsSellingSweep {
  sweep_id: string | null;
  created_at?: string;
  symbol?: string;
  years?: number;
  desk?: string;
  gate?: SellingGate;
  pricing_model?: string;
  margin_model?: string;
  qualified_count: number;
  strategy_count: number;
  results: SellingSweepEntry[];
}

export async function runOptionsSellingSweep(
  request: OptionsSellingSweepRequest,
): Promise<OptionsSellingSweep> {
  return apiFetch("/api/options/selling/backtest-all", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export async function fetchQualifiedSellingStrategies(): Promise<OptionsSellingSweep> {
  return apiFetch("/api/options/selling/qualified");
}

// --- Pre-Live SELLING desk ---
//
// Separate types from the buying desk's, not shared ones. Selling positions are
// multi-leg, carry margin and credit, and can be held for days; a shared type would
// make every selling-specific field optional and let a selling number render on a
// buying page. The two desks must never be confusable.

export interface SellingLeg {
  option_type: "CE" | "PE";
  strike: number;
  sold: boolean;
  security_id: string;
  symbol?: string;
  entry_premium: number;
}

export interface SellingPosition {
  key: string;
  strategy_id: string;
  timeframe: string;
  legs: SellingLeg[];
  structure: string;
  credit: number;
  lots: number;
  qty: number;
  margin: number;
  margin_basis: "defined_risk" | "naked_span" | string;
  expiry: string | null;
  entry_spot: number;
  entry_ts: string;
  mark?: number;
  unrealized?: number;
  updated_at?: string;
}

export interface SellingDeskStatus {
  desk: "selling";
  running: boolean;
  heartbeat: string | null;
  session: string | null;
  universe_size: number;
  universe_source: Record<string, any> | null;
  open_structures: number;
  breaker_tripped: boolean;
  breaker_reason: string | null;
  initial_capital: number;
  realized: number;
  balance: number;
  margin_deployed: number;
  free_margin: number;
  realized_all_time: number;
  unrealized: number;
  credit_at_risk: number;
  sessions_traded: number;
  open_structures_detail: SellingPosition[];
}

export interface SellingScore {
  strategy_id: string;
  trades: number;
  wins: number;
  losses: number;
  net_pnl: number;
  win_rate: number | null;
  profit_factor: number | null;
  allocated_capital?: number;
  updated_at?: string;
}

export interface SellingTrade {
  key: string;
  strategy_id: string;
  timeframe: string;
  legs: SellingLeg[];
  structure: string;
  credit: number;
  exit_cost: number;
  lots: number;
  qty: number;
  margin: number;
  margin_basis: string;
  expiry: string | null;
  entry_ts: string;
  exit_ts: string;
  entry_spot: number;
  exit_spot: number | null;
  exit_reason: string;
  pnl: number;
  held_days: number;
}

export interface SellingEquityPoint {
  ts: string;
  session: string | null;
  equity: number;
  realized: number;
  unrealized: number;
  margin_deployed: number;
  open_structures: number;
}

export interface SellingDay {
  session: string;
  realized_pnl: number;
  unrealized_pnl: number;
  net_pnl: number;
  trades: number;
  open_carried: number;
  margin_deployed: number;
  start_equity: number;
  breaker_tripped: boolean;
  breaker_reason: string | null;
  roi_pct: number;
}

export async function fetchSellingDeskStatus(): Promise<SellingDeskStatus> {
  return apiFetch("/api/prelive-selling/status");
}
export async function fetchSellingDeskLeaderboard(): Promise<SellingScore[]> {
  return apiFetch("/api/prelive-selling/leaderboard");
}
export async function fetchSellingDeskTrades(limit = 100): Promise<SellingTrade[]> {
  return apiFetch(`/api/prelive-selling/trades?limit=${limit}`);
}
export async function fetchSellingDeskEquity(limit = 500): Promise<SellingEquityPoint[]> {
  return apiFetch(`/api/prelive-selling/equity?limit=${limit}`);
}
export async function fetchSellingDeskDaily(limit = 60): Promise<SellingDay[]> {
  return apiFetch(`/api/prelive-selling/daily?limit=${limit}`);
}

// --- Intraday Stocks desk (50-strategy auto-trading equity paper desk, Angel One feed) ---

export interface IntradayPosition {
  position_id: string;
  strategy_id: string;
  strategy_name: string;
  category: string;
  symbol: string;
  display_name: string;
  side: string;
  entry_price: number;
  qty: number;
  capital_deployed: number;
  target: number;
  stoploss: number;
  ltp: number;
  ltp_source: string;
  unrealized_pnl: number;
  pnl_pct: number;
  realized_pnl: number | null;
  exit_price: number | null;
  exit_reason: string | null;
  status: string;
  confidence: number;
  rationale: string;
  max_hold_days: number;
  opened_at: string | null;
  opened_on: string | null;
  closed_at: string | null;
  is_anti?: boolean;
}

export interface IntradayDeskStatus {
  initial_capital: number;
  per_strategy_allocation: number;
  available_cash: number;
  deployed_capital: number;
  realized_pnl: number;
  gross_realized_pnl: number;
  total_fees: number;
  unrealized_pnl: number;
  equity: number;
  roi_pct: number;
  today_roi_pct: number;
  open_positions: number;
  closed_positions: number;
  strategy_count: number;
  heartbeat: string | null;
  last_opened: number | null;
  last_managed: number | null;
  last_notes: string[];
  broker_connected: boolean;
  angel_configured: boolean;
  feed_source: "angel" | "dhan" | "none";
  paused: boolean;
  open_positions_detail: IntradayPosition[];
}

export interface IntradayScore {
  roi_pct?: number;
  fees?: number;
  gross_pnl?: number;
  strategy_id: string;
  name: string;
  category: string;
  trades: number;
  win_rate: number;
  net_pnl: number;
  allocated_capital: number | null;
  is_anti?: boolean;
}

export interface IntradayTrade {
  trade_id: string;
  strategy_id: string;
  strategy_name: string;
  symbol: string;
  side: string;
  entry_price: number;
  exit_price: number;
  qty: number;
  realized_pnl: number;
  exit_reason: string;
  opened_at: string | null;
  closed_at: string | null;
}

export interface IntradayEquityPoint {
  ts: string;
  equity: number;
  realized: number;
  unrealized: number;
  deployed: number;
  open_positions: number;
}

export interface IntradayDay {
  session: string;
  net_pnl: number;
  trades: number;
  wins: number;
  win_rate: number;
}

export async function fetchIntradayStatus(): Promise<IntradayDeskStatus> {
  return apiFetch("/api/intraday-lab/status");
}
export async function fetchIntradayLeaderboard(): Promise<IntradayScore[]> {
  const r = await apiFetch("/api/intraday-lab/leaderboard");
  return r.leaderboard ?? [];
}
export async function fetchIntradayTrades(limit = 100): Promise<IntradayTrade[]> {
  return apiFetch(`/api/intraday-lab/trades?limit=${limit}`);
}

// ---- Live Intraday desk (curated ₹80k shortlist inside Intraday Stocks) ----
export type LiveIntradayBook = "80k" | "30k" | "10k";

export interface DailyRoi {
  date: string;
  trades: number;
  wins: number;
  win_rate: number;
  gross_pnl: number;
  fees: number;
  realized_pnl: number;
  roi_pct: number;
}

export interface LiveIntradaySummary {
  book: LiveIntradayBook;
  books: LiveIntradayBook[];
  initial_capital: number;
  per_strategy_allocation: number;
  position_notional: number;
  available_cash: number;
  deployed_capital: number;
  realized_pnl: number;
  gross_realized_pnl: number;
  total_fees: number;
  unrealized_pnl: number;
  equity: number;
  roi_pct: number;
  today_roi_pct: number;
  open_positions: number;
  closed_positions: number;
  strategy_count: number;
  paused: boolean;
  mode: string;
  today_pnl: number;
  breaker_tripped: boolean;
  daily_loss_limit: number;
  last_run_at: string | null;
  broker_connected: boolean;
  angel_configured: boolean;
}

// Every Live Intraday call is scoped to one book. The books are separate accounts on
// the same eight strategies, so an unscoped call would blend three desks into nonsense.
export async function fetchLiveIntradaySummary(book: LiveIntradayBook = "80k"): Promise<LiveIntradaySummary> {
  return apiFetch(`/api/live-intraday/summary?book=${book}`);
}
export async function fetchLiveIntradayLeaderboard(book: LiveIntradayBook = "80k"): Promise<IntradayScore[]> {
  const r = await apiFetch(`/api/live-intraday/leaderboard?book=${book}`);
  return r.leaderboard ?? [];
}
export async function fetchLiveIntradayPositions(book: LiveIntradayBook = "80k"): Promise<{ positions: IntradayPosition[]; summary: LiveIntradaySummary }> {
  return apiFetch(`/api/live-intraday/positions?book=${book}`);
}
export async function fetchLiveIntradayTrades(limit = 100, book: LiveIntradayBook = "80k"): Promise<IntradayTrade[]> {
  const r = await apiFetch(`/api/live-intraday/trades?limit=${limit}&book=${book}`);
  return r.trades ?? [];
}
export async function fetchLiveIntradayDaily(book: LiveIntradayBook = "80k", limit = 60): Promise<DailyRoi[]> {
  const r = await apiFetch(`/api/live-intraday/daily?book=${book}&limit=${limit}`);
  return r.daily ?? [];
}
export async function fetchIntradayLabDaily(limit = 60): Promise<DailyRoi[]> {
  const r = await apiFetch(`/api/intraday-lab/daily?limit=${limit}`);
  return r.daily ?? [];
}

// ---- Live Trading desk (REAL MONEY twin of Live Intraday; routes real Dhan orders) ----
export interface AngelBrokerPosition {
  symbol: string | null;
  product: string | null;
  net_qty: number;
  buy_avg: number;
  sell_avg: number;
  pnl: number;
  ltp: number;
}

export interface AngelAccount {
  available: boolean;
  reason?: string;
  client_code?: string | null;
  account_name?: string | null;
  available_cash?: number;
  net?: number;
  utilised_margin?: number;
  collateral?: number;
  m2m_realized?: number;
  m2m_unrealized?: number;
  intraday_payin?: number;
  broker_positions?: AngelBrokerPosition[];
  broker_position_count?: number;
}

export interface LiveTradingSummary {
  roi_pct: number;
  account_roi_pct: number | null;
  account_basis: number;
  deployed_roi_pct: number;
  mode: string;                       // "real"
  angel: AngelAccount;
  armed: boolean;
  kill_switch: boolean;
  consecutive_rejects: number;
  max_consecutive_rejects: number;
  disarmed_reason: string | null;
  broker_connected: boolean;
  last_run_at: string | null;
  last_notes: string[];
  initial_capital: number;
  desk_ceiling: number;
  per_strategy_allocation: number;
  position_notional: number;
  available_cash: number;
  deployed_capital: number;
  realized_pnl: number;
  unrealized_pnl: number;
  equity: number;
  open_positions: number;
  closed_positions: number;
  strategy_count: number;
  today_pnl: number;
  breaker_tripped: boolean;
  daily_loss_limit: number;
}

export interface LiveTradingScore {
  strategy_id: string;
  name: string;
  category: string;
  is_anti: boolean;
  trades: number;
  win_rate: number;
  net_pnl: number;
  allocated_capital: number | null;
  enabled: boolean;
}

export interface LiveTradingOpenPosition {
  position_id: string;
  symbol: string;
  strategy_name: string;
  is_anti: boolean;
  side: string;
  qty: number;
  entry_price: number;
  ltp: number | null;
  ltp_source: string | null;
  target: number;
  stoploss: number;
  unrealized_pnl: number;
  pnl_pct: number;
  entry_order_id: string | null;
}

export async function fetchLiveTradingSummary(): Promise<LiveTradingSummary> {
  return apiFetch("/api/live-trading/summary");
}
export async function fetchAngelAccount(force = false): Promise<AngelAccount> {
  return apiFetch(`/api/live-trading/angel-account${force ? "?force=true" : ""}`);
}
export async function fetchLiveTradingLeaderboard(): Promise<LiveTradingScore[]> {
  const r = await apiFetch("/api/live-trading/leaderboard");
  return r.leaderboard ?? [];
}
export async function fetchLiveTradingPositions(): Promise<{ open: LiveTradingOpenPosition[]; summary: LiveTradingSummary }> {
  return apiFetch("/api/live-trading/positions?status=OPEN");
}
export async function setLiveTradingArmed(armed: boolean): Promise<{ summary: LiveTradingSummary }> {
  return apiFetch("/api/live-trading/arm", { method: "POST", body: JSON.stringify({ armed }) });
}
export async function setLiveTradingKillSwitch(active: boolean): Promise<{ summary: LiveTradingSummary }> {
  return apiFetch("/api/live-trading/kill-switch", { method: "POST", body: JSON.stringify({ active }) });
}
export async function setLiveTradingStrategyEnabled(strategyId: string, enabled: boolean): Promise<{ leaderboard: LiveTradingScore[] }> {
  return apiFetch("/api/live-trading/strategy-enabled", { method: "POST", body: JSON.stringify({ strategy_id: strategyId, enabled }) });
}
export async function panicCloseAllLiveTrading(): Promise<{ result: { closed: number; failed: number }; summary: LiveTradingSummary }> {
  return apiFetch("/api/live-trading/panic-close-all", { method: "POST" });
}
export async function fetchIntradayEquity(limit = 500): Promise<IntradayEquityPoint[]> {
  return apiFetch(`/api/intraday-lab/equity?limit=${limit}`);
}
export async function fetchIntradayDaily(limit = 60): Promise<IntradayDay[]> {
  return apiFetch(`/api/intraday-lab/daily?limit=${limit}`);
}

// --- Long-Horizon factor desk (cross-sectional momentum/low-vol/reversal, months-long holds) ---

export interface LongHorizonPosition {
  strategy_id: string;
  strategy_name: string;
  category: string;
  symbol: string;
  entry_price: number;
  qty: number;
  ltp: number;
  unrealized_pnl: number;
  opened_at: string | null;
  max_hold_days: number;
  rationale: string;
}

export interface LongHorizonStatus {
  desk: "long_horizon";
  initial_capital: number;
  realized: number;
  unrealized: number;
  equity: number;
  deployed: number;
  heartbeat: string | null;
  basket_size: number;
  open_positions: number;
  open_positions_detail: LongHorizonPosition[];
  trades_closed: number;
  note?: string;
}

export interface LongHorizonScore {
  strategy_id: string;
  name: string;
  category: string;
  trades: number;
  win_rate: number;
  net_pnl: number;
  allocated_capital: number;
}

export interface LongHorizonTrade {
  trade_id: string;
  strategy_id: string;
  strategy_name: string;
  symbol: string;
  entry_price: number;
  exit_price: number;
  qty: number;
  net_pnl: number;
  costs: number;
  exit_reason: string;
  opened_at: string | null;
  closed_at: string | null;
}

export interface LongHorizonEquityPoint {
  ts: string;
  equity: number;
  realized: number;
  unrealized: number;
  deployed: number;
  open_positions: number;
}

export interface LongHorizonSweepResult {
  strategy_id: string;
  name: string;
  category: string;
  family: string;
  max_hold_days: number;
  train_metrics: Record<string, number | null>;
  test_metrics: Record<string, number | null>;
  qualified: boolean;
  gate_failures: string[];
  test_qualified: boolean;
  test_failures: string[];
  independent: boolean;
  in_basket: boolean;
  duplicate_of?: string;
}

export interface LongHorizonSweep {
  sweep_id: string;
  created_at: string;
  desk: "long_horizon";
  top_k: number;
  universe_size: number;
  train_fraction: number;
  overlap_threshold: number;
  data_from: string | null;
  data_to: string | null;
  strategy_count: number;
  qualified_count: number;
  robust_count: number;
  basket_count: number;
  results: LongHorizonSweepResult[];
}

export async function fetchLongHorizonStatus(): Promise<LongHorizonStatus> {
  return apiFetch("/api/long-horizon/status");
}
export async function fetchLongHorizonLeaderboard(): Promise<LongHorizonScore[]> {
  return apiFetch("/api/long-horizon/leaderboard");
}
export async function fetchLongHorizonTrades(limit = 100): Promise<LongHorizonTrade[]> {
  return apiFetch(`/api/long-horizon/trades?limit=${limit}`);
}
export async function fetchLongHorizonEquity(limit = 500): Promise<LongHorizonEquityPoint[]> {
  return apiFetch(`/api/long-horizon/equity?limit=${limit}`);
}
export async function fetchLongHorizonSweep(): Promise<LongHorizonSweep | null> {
  return apiFetch("/api/long-horizon/sweep");
}
export async function runLongHorizonSweep(): Promise<LongHorizonSweep> {
  return apiFetch("/api/long-horizon/sweep", { method: "POST", body: JSON.stringify({}) });
}
export async function runLongHorizonRebalance(): Promise<{ basket_size: number; rebalanced: number }> {
  return apiFetch("/api/long-horizon/rebalance", { method: "POST" });
}

// --- Trading Calls (Kotak-Neo-style research calls) ---

export type CallSegment = "STOCK" | "FNO" | "COMMODITY";
export type CallStatus = "OPEN" | "PARTIAL_EXIT" | "TARGET_HIT" | "STOPLOSS" | "EXPIRED" | "CLOSED";

export interface TradingCallInstrument {
  symbol: string;
  security_id: string;
  exchange_segment: string;
  lot_size: number;
  expiry: string | null;
  strike: number | null;
  option_type: "CE" | "PE" | null;
}

export interface TradingCall {
  call_id: string;
  segment: CallSegment;
  horizon: "INTRADAY" | "POSITIONAL";
  side: "BUY" | "SELL";
  symbol: string;
  display_name: string;
  instrument: TradingCallInstrument | null;
  entry_price: number;
  ltp: number;
  ltp_source: "dhan_quote" | "last_bar_close" | "model";
  target: number;
  stoploss: number;
  call_expiry_date: string;
  status: CallStatus;
  confidence: number;
  source: { kind: string; strategy_id: string | null; name: string | null; sweep_id?: string };
  rationale: string;
  tags: string[];
  data_as_of: string | null;
  pnl_pct: number | null;
  generated_on: string;
  created_at: string;
  updated_at: string;
  closed_at: string | null;
}

export interface CallSchedulerStatus {
  enabled: boolean;
  slots: string[];
  last_run_at: string | null;
  last_slot: string | null;
  last_created: number | null;
  next_slot: string | null;
}

export interface TradingCallsResponse {
  calls: TradingCall[];
  live_counts: Record<CallSegment, number>;
  scheduler?: CallSchedulerStatus;
}

export async function fetchTradingCalls(segment?: CallSegment, status?: string): Promise<TradingCallsResponse> {
  const params = new URLSearchParams();
  if (segment) params.set("segment", segment);
  if (status) params.set("status", status);
  const qs = params.toString();
  return apiFetch(`/api/trading-calls${qs ? `?${qs}` : ""}`);
}

export interface GenerateCallsResult {
  created: number;
  scanned: number;
  calls: TradingCall[];
  notes: Partial<Record<CallSegment, string>>;
  broker_connected: boolean;
  positions_opened: number;
}

export async function generateTradingCalls(segments?: CallSegment[]): Promise<GenerateCallsResult> {
  return apiFetch("/api/trading-calls/generate", {
    method: "POST",
    body: JSON.stringify(segments ?? null),
  });
}

export async function closeTradingCall(callId: string): Promise<TradingCall> {
  return apiFetch(`/api/trading-calls/${callId}/close`, { method: "POST" });
}

// --- Trading Call Positions (auto-opened paper ledger over Trading Calls) ---

export type CallPositionStatus = "OPEN" | "TARGET_HIT" | "STOPLOSS" | "EXPIRED" | "CLOSED";

export interface TradingCallPosition {
  position_id: string;
  call_id: string;
  segment: CallSegment;
  horizon: "INTRADAY" | "POSITIONAL";
  side: "BUY" | "SELL";
  symbol: string;
  display_name: string;
  instrument: TradingCallInstrument | null;
  entry_price: number;
  lot_size: number;
  lots: number;
  qty: number;
  capital_deployed: number;
  target: number;
  stoploss: number;
  ltp: number;
  ltp_source: "dhan_quote" | "last_bar_close" | "model";
  unrealized_pnl: number;
  pnl_pct: number | null;
  realized_pnl: number | null;
  exit_price: number | null;
  status: CallPositionStatus;
  opened_at: string;
  updated_at: string;
  closed_at: string | null;
}

export interface TradingCallPositionsSummary {
  initial_capital: number;
  available_cash: number;
  deployed_capital: number;
  realized_pnl: number;
  unrealized_pnl: number;
  equity: number;
  open_positions: number;
  closed_positions: number;
}

export interface TradingCallPositionsResponse {
  positions: TradingCallPosition[];
  summary: TradingCallPositionsSummary;
}

export async function fetchTradingCallPositions(
  segment?: CallSegment,
  status?: string,
): Promise<TradingCallPositionsResponse> {
  const params = new URLSearchParams();
  if (segment) params.set("segment", segment);
  if (status) params.set("status", status);
  const qs = params.toString();
  return apiFetch(`/api/trading-calls/positions${qs ? `?${qs}` : ""}`);
}

// --- Intraday Strategy Lab (50-strategy auto-trading paper desk, sub-module of Trading Calls) ---

export type IntradayLabCategory = "scalping" | "momentum" | "mean_reversion" | "swing";

export interface IntradayLabStrategy {
  strategy_id: string;
  name: string;
  category: IntradayLabCategory;
  timeframe: string;
  rationale: string;
  max_hold_days: number;
  risk_pct: number;
  trades: number;
  win_rate: number;
  net_pnl: number;
  allocated_capital: number | null;
}

export interface IntradayLabStrategiesResponse {
  strategies: IntradayLabStrategy[];
  count: number;
}

export async function fetchIntradayLabStrategies(): Promise<IntradayLabStrategiesResponse> {
  return apiFetch("/api/intraday-lab/strategies");
}

export interface IntradayLabLeaderboardRow {
  strategy_id: string;
  name: string;
  category: IntradayLabCategory;
  trades: number;
  win_rate: number;
  net_pnl: number;
  allocated_capital: number | null;
}

export async function fetchIntradayLabLeaderboard(): Promise<{ leaderboard: IntradayLabLeaderboardRow[] }> {
  return apiFetch("/api/intraday-lab/leaderboard");
}

export interface IntradayLabPosition {
  position_id: string;
  strategy_id: string;
  strategy_name: string;
  category: IntradayLabCategory;
  symbol: string;
  display_name: string;
  side: "BUY" | "SELL";
  entry_price: number;
  qty: number;
  capital_deployed: number;
  target: number;
  stoploss: number;
  ltp: number;
  ltp_source: "dhan_quote" | "last_bar_close";
  unrealized_pnl: number;
  pnl_pct: number | null;
  realized_pnl: number | null;
  exit_price: number | null;
  exit_reason: string | null;
  status: "OPEN" | "CLOSED";
  confidence: number;
  rationale: string;
  opened_at: string;
  updated_at: string;
  closed_at: string | null;
}

export async function fetchIntradayLabPositions(
  strategyId?: string,
  status?: string,
): Promise<{ positions: IntradayLabPosition[] }> {
  const params = new URLSearchParams();
  if (strategyId) params.set("strategy_id", strategyId);
  if (status) params.set("status", status);
  const qs = params.toString();
  return apiFetch(`/api/intraday-lab/positions${qs ? `?${qs}` : ""}`);
}

export interface IntradayLabSummary {
  initial_capital: number;
  per_strategy_allocation: number;
  available_cash: number;
  deployed_capital: number;
  realized_pnl: number;
  unrealized_pnl: number;
  equity: number;
  open_positions: number;
  closed_positions: number;
  strategy_count: number;
}

export async function fetchIntradayLabSummary(): Promise<IntradayLabSummary> {
  return apiFetch("/api/intraday-lab/summary");
}

export async function runIntradayLabCycle(): Promise<{ opened: number; managed: number; scanned_symbols: number; notes: string[] }> {
  return apiFetch("/api/intraday-lab/run", { method: "POST" });
}

// --- Manual Positions (user-initiated paper trading desk, NSE + BSE) ---

export interface ManualInstrument {
  symbol: string;
  name: string;
  security_id: string;
  exchange_segment: string;
  lot_size: number;
  tick_size: number;
  asset_class: string;
}

export type ManualProductType = "CNC" | "MTF" | "MARGIN" | "INTRADAY";

export interface ManualAccount {
  account_id: string;
  name: string;
  initial_capital: number;
  created_at: string;
}

export async function fetchManualAccounts(): Promise<ManualAccount[]> {
  const data: { accounts: ManualAccount[] } = await apiFetch("/api/manual-positions/accounts");
  return data.accounts;
}

export async function createManualAccount(name: string, initialCapital?: number): Promise<ManualAccount> {
  return apiFetch("/api/manual-positions/accounts", {
    method: "POST",
    body: JSON.stringify({ name, initial_capital: initialCapital ?? null }),
  });
}

export interface ManualPosition {
  position_id: string;
  account_id: string;
  symbol: string;
  display_name: string;
  instrument: ManualInstrument;
  product_type: ManualProductType;
  side: "BUY";
  quantity: number;
  avg_price: number;
  margin_used: number;
  leverage: number;
  margin_source: "dhan_calculator" | "fallback";
  ltp: number;
  ltp_source: "dhan_quote";
  unrealized_pnl: number;
  pnl_pct: number;
  realized_pnl: number;
  status: "OPEN" | "CLOSED";
  opened_at: string;
  updated_at: string;
  closed_at: string | null;
}

export interface ManualOrder {
  order_id: string;
  symbol: string;
  display_name: string;
  instrument: ManualInstrument;
  transaction_type: "BUY" | "SELL";
  quantity: number;
  order_type: "MARKET" | "LIMIT";
  limit_price: number | null;
  product_type: ManualProductType;
  status: "PENDING" | "FILLED";
  fill_price: number | null;
  margin_used: number | null;
  leverage: number | null;
  placed_at: string;
  updated_at: string;
  filled_at: string | null;
}

export interface ManualPositionsSummary {
  account_id: string;
  initial_capital: number;
  available_cash: number;
  deployed_margin: number;
  realized_pnl: number;
  unrealized_pnl: number;
  total_pnl: number;
  equity: number;
  roi_pct: number;
  open_positions: number;
  closed_positions: number;
  win_rate: number | null;
}

export interface MarginEstimate {
  margin_required: number;
  leverage: number;
  notional_value: number;
  source: "dhan_calculator" | "fallback";
}

export async function searchManualInstruments(q: string): Promise<ManualInstrument[]> {
  if (!q.trim()) return [];
  const data: { results: ManualInstrument[] } = await apiFetch(`/api/manual-positions/search?q=${encodeURIComponent(q)}`);
  return data.results;
}

export async function fetchManualQuote(securityId: string, exchangeSegment: string): Promise<{ ltp: number }> {
  return apiFetch(`/api/manual-positions/quote?security_id=${securityId}&exchange_segment=${exchangeSegment}`);
}

export async function estimateManualMargin(params: {
  security_id: string;
  exchange_segment: string;
  transaction_type: "BUY" | "SELL";
  quantity: number;
  product_type: ManualProductType;
  price: number;
}): Promise<MarginEstimate> {
  const qs = new URLSearchParams(params as unknown as Record<string, string>).toString();
  return apiFetch(`/api/manual-positions/margin?${qs}`);
}

export interface PlaceManualOrderRequest {
  account_id: string;
  security_id: string;
  exchange_segment: string;
  transaction_type: "BUY" | "SELL";
  quantity: number;
  order_type: "MARKET" | "LIMIT";
  product_type: ManualProductType;
  limit_price?: number;
  force_new_position?: boolean;
}

export async function placeManualOrder(payload: PlaceManualOrderRequest): Promise<ManualOrder & { position?: ManualPosition }> {
  return apiFetch("/api/manual-positions/orders", { method: "POST", body: JSON.stringify(payload) });
}

export async function fetchManualPositions(accountId: string, status?: string): Promise<{ positions: ManualPosition[]; summary: ManualPositionsSummary }> {
  const params = new URLSearchParams({ account_id: accountId });
  if (status) params.set("status", status);
  return apiFetch(`/api/manual-positions/positions?${params.toString()}`);
}

export async function fetchManualOrders(accountId: string, status?: string): Promise<{ orders: ManualOrder[] }> {
  const params = new URLSearchParams({ account_id: accountId });
  if (status) params.set("status", status);
  return apiFetch(`/api/manual-positions/orders?${params.toString()}`);
}

export async function cancelManualOrder(accountId: string, orderId: string): Promise<{ cancelled: boolean; order_id: string }> {
  return apiFetch(`/api/manual-positions/orders/${orderId}/cancel`, {
    method: "POST",
    body: JSON.stringify({ account_id: accountId }),
  });
}

export async function exitManualPosition(accountId: string, positionId: string, quantity?: number): Promise<ManualOrder & { position: ManualPosition }> {
  return apiFetch(`/api/manual-positions/positions/${positionId}/exit`, {
    method: "POST",
    body: JSON.stringify({ account_id: accountId, quantity: quantity ?? null }),
  });
}

export async function resetManualPositions(accountId: string): Promise<{ positions_deleted: number; orders_deleted: number; initial_capital: number }> {
  return apiFetch("/api/manual-positions/reset", { method: "POST", body: JSON.stringify({ account_id: accountId }) });
}

// --- F&O Positions (options + futures paper desk, indices + F&O-enabled stocks) ---

export interface FnoUnderlying {
  symbol: string;
  name: string;
  kind: "INDEX" | "EQUITY";
}

export type OptionChainStrike = OptionStrikeRow;

export interface OptionChainResponse extends OptionChain {
  symbol: string;
}

export interface TopMover {
  symbol: string;
  expiry: string;
  strike: number;
  option_type: "CE" | "PE";
  ltp: number;
  change_pct: number;
  volume: number;
  oi: number;
}

export type FnoProductType = "INTRADAY" | "MARGIN";
export type FnoInstrumentKind = "OPTION" | "FUTURE";

export interface FnoInstrument {
  symbol: string;
  security_id: string;
  exchange_segment: string;
  lot_size: number;
  tick_size: number;
  underlying_symbol: string | null;
  expiry: string | null;
  strike: number | null;
  option_type: "CE" | "PE" | null;
}

export interface FnoPosition {
  position_id: string;
  symbol: string;
  display_name: string;
  instrument_kind: FnoInstrumentKind;
  instrument: FnoInstrument;
  product_type: FnoProductType;
  side: "BUY" | "SELL";
  lots: number;
  quantity: number;
  avg_price: number;
  margin_used: number;
  leverage: number;
  margin_source: "dhan_calculator" | "fallback";
  ltp: number;
  ltp_source: "dhan_quote";
  unrealized_pnl: number;
  pnl_pct: number;
  realized_pnl: number;
  status: "OPEN" | "CLOSED";
  opened_at: string;
  updated_at: string;
  closed_at: string | null;
}

export interface FnoOrder {
  order_id: string;
  symbol: string;
  display_name: string;
  instrument_kind: FnoInstrumentKind;
  instrument: FnoInstrument;
  transaction_type: "BUY" | "SELL";
  lots: number;
  quantity: number;
  order_type: "MARKET" | "LIMIT";
  limit_price: number | null;
  product_type: FnoProductType;
  status: "PENDING" | "FILLED";
  fill_price: number | null;
  margin_used: number | null;
  leverage: number | null;
  placed_at: string;
  updated_at: string;
  filled_at: string | null;
}

export interface FnoPositionsSummary extends ManualPositionsSummary {
  // Hedge-aware margin: deployed_margin is the NETTED portfolio (SPAN-lite) figure;
  // standalone_margin is the sum of each leg's own margin; the gap is the benefit.
  standalone_margin?: number;
  margin_benefit?: number;
}

export interface FnoAccount {
  account_id: string;
  name: string;
  initial_capital: number;
  created_at: string;
}

export async function fetchFnoAccounts(): Promise<FnoAccount[]> {
  const data: { accounts: FnoAccount[] } = await apiFetch("/api/fno-positions/accounts");
  return data.accounts;
}

export async function createFnoAccount(name: string, initialCapital?: number): Promise<FnoAccount> {
  return apiFetch("/api/fno-positions/accounts", {
    method: "POST",
    body: JSON.stringify({ name, initial_capital: initialCapital ?? null }),
  });
}

export async function editFnoAccount(
  accountId: string,
  changes: { name?: string; initialCapital?: number },
): Promise<FnoAccount> {
  return apiFetch(`/api/fno-positions/accounts/${accountId}`, {
    method: "PATCH",
    body: JSON.stringify({
      name: changes.name ?? null,
      initial_capital: changes.initialCapital ?? null,
    }),
  });
}

export async function fetchFnoUnderlyings(): Promise<FnoUnderlying[]> {
  const data: { underlyings: FnoUnderlying[] } = await apiFetch("/api/fno-positions/underlyings");
  return data.underlyings;
}

export async function fetchFnoOptionExpiries(symbol: string): Promise<string[]> {
  const data: { expiries: string[] } = await apiFetch(`/api/fno-positions/options/expiries?symbol=${encodeURIComponent(symbol)}`);
  return data.expiries;
}

export async function fetchFnoOptionChain(symbol: string, expiry: string): Promise<OptionChainResponse> {
  return apiFetch(`/api/fno-positions/options/chain?symbol=${encodeURIComponent(symbol)}&expiry=${encodeURIComponent(expiry)}`);
}

export async function fetchFnoFutureExpiries(symbol: string): Promise<string[]> {
  const data: { expiries: string[] } = await apiFetch(`/api/fno-positions/futures/expiries?symbol=${encodeURIComponent(symbol)}`);
  return data.expiries;
}

export async function fetchFnoTopMovers(limit = 10): Promise<{ top_calls: TopMover[]; top_puts: TopMover[] }> {
  return apiFetch(`/api/fno-positions/top-movers?limit=${limit}`);
}

export interface PlaceFnoOrderRequest {
  account_id: string;
  instrument_kind: FnoInstrumentKind;
  symbol: string;
  expiry: string;
  transaction_type: "BUY" | "SELL";
  lots: number;
  order_type: "MARKET" | "LIMIT";
  product_type: FnoProductType;
  strike?: number | null;
  option_type?: "CE" | "PE" | null;
  limit_price?: number;
}

export async function placeFnoOrder(payload: PlaceFnoOrderRequest): Promise<FnoOrder & { position?: FnoPosition }> {
  return apiFetch("/api/fno-positions/orders", { method: "POST", body: JSON.stringify(payload) });
}

export async function fetchFnoPositions(accountId: string, status?: string): Promise<{ positions: FnoPosition[]; summary: FnoPositionsSummary }> {
  const qs = new URLSearchParams({ account_id: accountId });
  if (status) qs.set("status", status);
  return apiFetch(`/api/fno-positions/positions?${qs.toString()}`);
}

export async function fetchFnoOrders(accountId: string, status?: string): Promise<{ orders: FnoOrder[] }> {
  const qs = new URLSearchParams({ account_id: accountId });
  if (status) qs.set("status", status);
  return apiFetch(`/api/fno-positions/orders?${qs.toString()}`);
}

export async function exitFnoPosition(accountId: string, positionId: string, lots?: number): Promise<FnoOrder & { position: FnoPosition }> {
  return apiFetch(`/api/fno-positions/positions/${positionId}/exit`, {
    method: "POST",
    body: JSON.stringify({ account_id: accountId, lots: lots ?? null }),
  });
}

export async function resetFnoPositions(accountId: string): Promise<{ positions_deleted: number; orders_deleted: number; initial_capital: number }> {
  return apiFetch("/api/fno-positions/reset", { method: "POST", body: JSON.stringify({ account_id: accountId }) });
}

export interface FnoBasketLeg {
  instrument_kind?: "OPTION" | "FUTURE";
  symbol: string;
  expiry: string;
  transaction_type: "BUY" | "SELL";
  lots: number;
  strike?: number | null;
  option_type?: "CE" | "PE" | null;
}

export interface FnoBasketMargin {
  margin_required: number;   // combined, netted vs current account positions
  net_premium: number;       // + = credit received, - = debit paid
  available_cash: number;
  affordable: boolean;
  legs: { label: string; side: string; lots: number; qty: number; ltp: number }[];
}

export async function estimateFnoBasketMargin(accountId: string, productType: FnoProductType, legs: FnoBasketLeg[]): Promise<FnoBasketMargin> {
  return apiFetch("/api/fno-positions/basket/margin", {
    method: "POST",
    body: JSON.stringify({ account_id: accountId, product_type: productType, legs }),
  });
}

export async function executeFnoBasket(accountId: string, productType: FnoProductType, legs: FnoBasketLeg[]): Promise<{ filled: number; positions: FnoPosition[]; margin_added: number; net_premium: number }> {
  return apiFetch("/api/fno-positions/basket/execute", {
    method: "POST",
    body: JSON.stringify({ account_id: accountId, product_type: productType, legs }),
  });
}

// --- AI research & trade intelligence (roadmap Phase 6) ---

export interface AIStatus {
  configured: boolean;
  model: string;
  note: string;
}

export async function fetchAIStatus(): Promise<AIStatus> {
  return apiFetch("/api/ai/status");
}

export type AIResult = { status: "ok" | "not_configured" | "no_data"; message?: string } & Record<string, any>;

export async function explainTrade(trade: Record<string, unknown>): Promise<AIResult> {
  return apiFetch("/api/ai/explain-trade", { method: "POST", body: JSON.stringify({ trade }) });
}

export async function fetchStrategyRanking(): Promise<AIResult> {
  return apiFetch("/api/ai/rank-strategies");
}

export async function compareStrategies(strategyIdA: string, strategyIdB: string): Promise<AIResult> {
  return apiFetch("/api/ai/compare-strategies", {
    method: "POST",
    body: JSON.stringify({ strategy_id_a: strategyIdA, strategy_id_b: strategyIdB }),
  });
}

export async function detectUnusualActivity(symbol: string, marketData: Record<string, unknown>): Promise<AIResult> {
  return apiFetch("/api/ai/detect-unusual", { method: "POST", body: JSON.stringify({ symbol, market_data: marketData }) });
}

export async function fetchTradeIdeas(): Promise<AIResult> {
  return apiFetch("/api/ai/trade-ideas");
}

export async function summarizeNews(limit = 20, symbol?: string): Promise<AIResult> {
  return apiFetch("/api/ai/summarize-news", { method: "POST", body: JSON.stringify({ limit, symbol }) });
}

// --- Research feed & vector search (roadmap Phase 6) ---

export interface ResearchSignal {
  id: string;
  symbol: string;
  timeframe: string;
  signal: string;
  confidence: number;
  source: string;
  timestamp: string;
  reasoning: string;
  link: string | null;
}

export async function fetchResearchIdeas(limit = 30, symbol?: string): Promise<ResearchSignal[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (symbol) params.set("symbol", symbol);
  return apiFetch(`/api/research/ideas?${params}`);
}

export async function ingestResearch(): Promise<{ counts: Record<string, number | string> }> {
  return apiFetch("/api/research/ingest", { method: "POST" });
}

export async function fetchVectorStatus(): Promise<{ mode: string }> {
  return apiFetch("/api/research/vector/status");
}

export interface VectorHit {
  id: string;
  score: number;
  payload: Record<string, unknown>;
}

export async function vectorSearch(query: string, collection = "research_signals", limit = 5): Promise<{ mode: string; hits: VectorHit[] }> {
  return apiFetch("/api/research/vector/search", { method: "POST", body: JSON.stringify({ query, collection, limit }) });
}

export async function indexResearchIntoVectorStore(limit = 200): Promise<{ mode?: string; indexed?: number | Record<string, unknown>; status?: string; message?: string }> {
  return apiFetch(`/api/research/vector/index-research?limit=${limit}`, { method: "POST" });
}

// --- Pre-Live paper desk ---

export interface PreLiveUniverseSource {
  sweep_id: string | null;
  created_at: string | null;
  symbol?: string;
  qualified_count?: number;
  fallback?: string;
}
export interface PreLiveStatus {
  engine: {
    status: string; heartbeat?: string; session?: string; open_positions?: number; day_pnl?: number;
    capital_locked?: number; initial_capital?: number; balance?: number; equity?: number;
    available_cash?: number; realized_all_time?: number;
    universe_size?: number; universe_source?: PreLiveUniverseSource | null;
    capital_per_trade?: number; note?: string | null;
    // Only present when heartbeat_watchdog.py has actually run and written them —
    // that script isn't wired into the Docker/Linux deployment yet (Windows-Task-
    // Scheduler-only design), so treat both as possibly absent.
    heartbeat_stale?: boolean; heartbeat_age_seconds?: number | null;
  };
  open_positions: Array<{ key: string; strategy_id: string; timeframe: string; option_type: string; strike: number; entry_premium: number; mark: number; unrealized: number; qty: number; entry_ts: string }>;
  today: { session: string; trades: number; net_pnl: number; peak_capital: number; roi_pct: number | null; wins: number } | null;
}
export interface PreLiveScore {
  key: string; strategy_id: string; timeframe: string; trades: number; wins: number;
  win_rate: number; profit_factor: number | null; expectancy: number; net_pnl: number;
  allocated_capital?: number;
}
export interface PreLiveTrade {
  id: string; strategy_id: string; timeframe: string; option_type: string; strike: number;
  entry_premium: number; exit_premium: number; entry_ts: string; exit_ts: string;
  exit_reason: string; qty: number; pnl: number; session: string;
}
export interface PreLiveDay {
  session: string; trades: number; net_pnl: number; peak_capital: number; roi_pct: number | null; wins: number; cumulative_pnl: number;
}

export async function fetchPreLiveStatus(): Promise<PreLiveStatus> { return apiFetch("/api/prelive/status"); }
export async function fetchPreLiveLeaderboard(): Promise<{ count: number; strategies: PreLiveScore[] }> { return apiFetch("/api/prelive/leaderboard"); }
export async function fetchPreLiveTrades(limit = 100): Promise<{ count: number; trades: PreLiveTrade[] }> { return apiFetch(`/api/prelive/trades?limit=${limit}`); }
export async function fetchPreLiveDaily(limit = 60): Promise<{ count: number; days: PreLiveDay[] }> { return apiFetch(`/api/prelive/daily?limit=${limit}`); }

// --- Watchlist (user-created named lists with live price tracking) ---

export interface WatchlistSymbol {
  symbol: string;
  security_id: string;
  exchange_segment: string;
  added_at: string;
}

export interface Watchlist {
  watchlist_id: string;
  name: string;
  symbols: WatchlistSymbol[];
  created_at: string;
}

export interface WatchlistQuote {
  symbol: string;
  security_id: string;
  exchange_segment: string;
  ltp: number | null;
  change: number | null;
  pct_change: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  prev_close: number | null;
  volume: number | null;
}

export async function searchWatchlistInstruments(q: string): Promise<ManualInstrument[]> {
  if (!q.trim()) return [];
  const data: { results: ManualInstrument[] } = await apiFetch(`/api/watchlist/search?q=${encodeURIComponent(q)}`);
  return data.results;
}

export async function fetchWatchlists(): Promise<{ watchlists: Watchlist[] }> {
  return apiFetch("/api/watchlist");
}

export async function createWatchlist(name: string): Promise<Watchlist> {
  return apiFetch("/api/watchlist", { method: "POST", body: JSON.stringify({ name }) });
}

export async function deleteWatchlist(watchlistId: string): Promise<{ deleted: boolean }> {
  return apiFetch(`/api/watchlist/${watchlistId}`, { method: "DELETE" });
}

export async function addWatchlistSymbol(watchlistId: string, instrument: ManualInstrument): Promise<WatchlistSymbol> {
  return apiFetch(`/api/watchlist/${watchlistId}/symbols`, {
    method: "POST",
    body: JSON.stringify({
      symbol: instrument.symbol,
      security_id: instrument.security_id,
      exchange_segment: instrument.exchange_segment,
    }),
  });
}

export async function removeWatchlistSymbol(watchlistId: string, symbol: string): Promise<{ removed: boolean }> {
  return apiFetch(`/api/watchlist/${watchlistId}/symbols/${encodeURIComponent(symbol)}`, { method: "DELETE" });
}

export async function fetchWatchlistQuotes(watchlistId: string): Promise<{ quotes: WatchlistQuote[] }> {
  return apiFetch(`/api/watchlist/${watchlistId}/quotes`);
}

// --- Chart (TradingView-style candlestick charting, real Dhan OHLCV data) ---

export interface ChartSymbol {
  symbol: string;
  name: string;
  security_id: string;
  exchange_segment: string;
  asset_class: string;
  tick_size: number;
  // Derivatives only — absent on equities/ETFs/indices.
  expiry?: string | null;
  strike?: number | null;
  option_type?: string | null;
  underlying_symbol?: string | null;
  lot_size?: number | null;
}

export interface ChartSymbolInfo {
  symbol: string;
  name: string;
  security_id: string;
  exchange_segment: string;
  asset_class: string;
  pricescale: number;
  timezone: string;
  /** "HHMM-HHMM" IST. MCX runs far later than the equity 0915-1530. */
  session: string;
  supported_resolutions: string[];
  expiry?: string | null;
  strike?: number | null;
  option_type?: string | null;
  underlying_symbol?: string | null;
  lot_size?: number | null;
  is_option?: boolean;
  is_commodity?: boolean;
}

export type ChartResolution = "1" | "5" | "15" | "60" | "D" | "W";

export interface ChartBars {
  s: "ok" | "no_data";
  t?: number[];
  o?: number[];
  h?: number[];
  l?: number[];
  c?: number[];
  v?: number[];
}

export interface ChartTrendPoint {
  time: number;
  price: number;
}

export interface ChartTrend {
  kind: "support" | "resistance";
  p1: ChartTrendPoint;
  p2: ChartTrendPoint;
}

export async function searchChartSymbols(q: string): Promise<ChartSymbol[]> {
  if (!q.trim()) return [];
  const data: { results: ChartSymbol[] } = await apiFetch(`/api/chart/search?q=${encodeURIComponent(q)}`);
  return data.results;
}

export async function resolveChartSymbol(securityId: string, exchangeSegment: string): Promise<ChartSymbolInfo> {
  return apiFetch(`/api/chart/symbol?security_id=${securityId}&exchange_segment=${exchangeSegment}`);
}

export async function fetchChartHistory(
  securityId: string, exchangeSegment: string, resolution: ChartResolution, from: number, to: number,
): Promise<ChartBars> {
  return apiFetch(
    `/api/chart/history?security_id=${securityId}&exchange_segment=${exchangeSegment}&resolution=${resolution}&from=${from}&to=${to}`,
  );
}

export async function fetchChartTrendline(
  securityId: string, exchangeSegment: string, resolution: ChartResolution,
): Promise<{ trend: ChartTrend | null }> {
  return apiFetch(`/api/chart/trendline?security_id=${securityId}&exchange_segment=${exchangeSegment}&resolution=${resolution}`);
}

/** SSE endpoint for live bar updates.
 *
 * Unlike the market-data WebSocket this is plain HTTP, so it works both direct
 * and through the same-origin proxy in `app/api/[...path]/route.ts` — which is
 * the only path available in production, where WebSocket upgrades don't survive
 * the hop. Returns a relative URL in proxy mode, which EventSource resolves
 * against the current origin. */
export function chartStreamUrl(
  securityId: string, exchangeSegment: string, resolution: ChartResolution,
): string {
  return `${API_URL}/api/chart/stream?security_id=${securityId}&exchange_segment=${exchangeSegment}&resolution=${resolution}`;
}

// --- Chart cross-module overlays (Phase 5) ---

export interface ChartPositionOverlay {
  source: "positions" | "fno";
  position_id: string | null;
  symbol: string;
  display_name: string;
  side: string;
  quantity: number;
  /** Average fill. Positions in this app carry no SL/target, so only entry is drawn. */
  entry_price: number;
  ltp: number | null;
  unrealized_pnl: number | null;
  product_type: string | null;
  opened_at: string | null;
}

export interface ChartCallOverlay {
  call_id: string;
  symbol: string;
  display_name: string;
  segment: string;
  side: string;
  horizon: string | null;
  entry_price: number;
  target: number;
  stoploss: number;
  confidence: number | null;
  rationale: string | null;
  created_at: string | null;
}

export interface ChartBacktestRun {
  id: string;
  strategy_id: string;
  symbol: string;
  timeframe: string;
  start: string | null;
  end: string | null;
  created_at: string | null;
  total_return_pct: number | null;
  win_rate: number | null;
  trades: number | null;
}

export interface ChartBacktestTrade {
  entry_ts: string;
  exit_ts: string | null;
  direction: string;
  entry_price: number;
  exit_price: number | null;
  quantity: number;
  pnl: number | null;
  charges: number;
  exit_reason: string;
}

export interface ChartOptionContext {
  available: boolean;
  reason?: string;
  symbol?: string;
  expiry?: string;
  spot?: number;
  days_to_expiry?: number;
  max_pain?: number | null;
  pcr_oi?: number | null;
  top_call_oi?: { strike: number; oi: number }[];
  top_put_oi?: { strike: number; oi: number }[];
}

export async function fetchChartOverlays(
  securityId: string, exchangeSegment: string,
): Promise<{ positions: ChartPositionOverlay[]; calls: ChartCallOverlay[] }> {
  return apiFetch(`/api/chart/overlays?security_id=${securityId}&exchange_segment=${exchangeSegment}`);
}

export async function fetchChartBacktests(symbol: string): Promise<{ runs: ChartBacktestRun[] }> {
  return apiFetch(`/api/chart/backtests?symbol=${encodeURIComponent(symbol)}`);
}

export async function fetchChartBacktestTrades(
  backtestId: string,
): Promise<{ found: boolean; strategy_id: string; trades: ChartBacktestTrade[] }> {
  return apiFetch(`/api/chart/backtests/${backtestId}/trades`);
}

export async function fetchChartOptionContext(symbol: string): Promise<ChartOptionContext> {
  return apiFetch(`/api/chart/option-context?symbol=${encodeURIComponent(symbol)}`);
}

// --- Chart structure & AI explain (Phase 6) ---

export interface ChartZone {
  price: number;
  low: number;
  high: number;
  touches: number;
  last_touch_time: number;
}

export interface ChartChannelLine {
  p1: { time: number; price: number };
  p2: { time: number; price: number };
  slope_per_bar: number;
}

export interface ChartStructure {
  available: boolean;
  reason?: string;
  bars_analyzed?: number;
  last_close?: number | null;
  structure?: { label: string; bias: string };
  support_zones?: ChartZone[];
  resistance_zones?: ChartZone[];
  channel?: { upper: ChartChannelLine | null; lower: ChartChannelLine | null } | null;
  swing_highs?: { time: number; price: number }[];
  swing_lows?: { time: number; price: number }[];
}

export async function fetchChartStructure(
  securityId: string, exchangeSegment: string, resolution: ChartResolution, lookback = 120,
): Promise<ChartStructure> {
  return apiFetch(
    `/api/chart/structure?security_id=${securityId}&exchange_segment=${exchangeSegment}&resolution=${resolution}&lookback=${lookback}`,
  );
}

export interface ChartExplainLevel {
  price: number;
  kind: "support" | "resistance";
  why: string;
}

export interface ChartExplanation {
  status: "ok" | "not_configured";
  message?: string;
  summary?: string;
  trend?: "uptrend" | "downtrend" | "sideways" | "unclear";
  key_observations?: string[];
  levels_to_watch?: ChartExplainLevel[];
  risks?: string[];
  confidence?: number;
}

export async function explainChart(context: Record<string, unknown>): Promise<ChartExplanation> {
  return apiFetch("/api/chart/explain", { method: "POST", body: JSON.stringify(context) });
}

// --- Chart workspace: drawings, layouts, alerts (Phase 7) ---

export type ChartDrawingKind =
  | "trendline" | "horizontal" | "rectangle" | "text" | "fibonacci"
  | "long_position" | "short_position"
  | "ray" | "arrow" | "vertical" | "channel"
  | "polyline" | "brush";

export interface ChartDrawingPoint {
  time: number;
  price: number;
}

export interface ChartDrawing {
  drawing_id: string;
  kind: ChartDrawingKind;
  points: ChartDrawingPoint[];
  text: string | null;
  color: string | null;
  created_at: string | null;
}

export interface ChartLayout {
  layout_id: string;
  name: string;
  resolution: ChartResolution | null;
  indicators: Record<string, unknown>;
  overlays: Record<string, unknown>;
  updated_at: string | null;
}

export interface ChartAlert {
  alert_id: string;
  symbol: string | null;
  display_name: string | null;
  security_id: string;
  exchange_segment: string;
  condition: "crosses_above" | "crosses_below";
  price: number;
  note: string | null;
  status: "ACTIVE" | "TRIGGERED";
  created_at: string | null;
  triggered_at: string | null;
  triggered_price: number | null;
  /** "in_app" until notification-service exists — see chart_workspace.py. */
  delivery: string | null;
}

export async function fetchChartDrawings(
  securityId: string, exchangeSegment: string,
): Promise<{ drawings: ChartDrawing[] }> {
  return apiFetch(`/api/chart/drawings?security_id=${securityId}&exchange_segment=${exchangeSegment}`);
}

export async function saveChartDrawing(
  securityId: string, exchangeSegment: string,
  drawing: { kind: ChartDrawingKind; points: ChartDrawingPoint[]; text?: string; color?: string },
): Promise<ChartDrawing> {
  return apiFetch(
    `/api/chart/drawings?security_id=${securityId}&exchange_segment=${exchangeSegment}`,
    { method: "POST", body: JSON.stringify(drawing) },
  );
}

/** Repositions or restyles a drawing in place. `kind` is fixed at creation. */
export async function updateChartDrawing(
  drawingId: string,
  changes: { points?: ChartDrawingPoint[]; text?: string; color?: string },
): Promise<ChartDrawing> {
  return apiFetch(`/api/chart/drawings/${drawingId}`, {
    method: "PATCH",
    body: JSON.stringify(changes),
  });
}

export async function deleteChartDrawing(drawingId: string): Promise<{ deleted: boolean }> {
  return apiFetch(`/api/chart/drawings/${drawingId}`, { method: "DELETE" });
}

export async function fetchChartLayouts(): Promise<{ layouts: ChartLayout[] }> {
  return apiFetch("/api/chart/layouts");
}

export async function saveChartLayout(layout: {
  name: string; resolution: ChartResolution; indicators: unknown; overlays: unknown;
}): Promise<ChartLayout> {
  return apiFetch("/api/chart/layouts", { method: "POST", body: JSON.stringify(layout) });
}

export async function deleteChartLayout(layoutId: string): Promise<{ deleted: boolean }> {
  return apiFetch(`/api/chart/layouts/${layoutId}`, { method: "DELETE" });
}

export async function fetchChartAlerts(securityId?: string): Promise<{ alerts: ChartAlert[] }> {
  return apiFetch(`/api/chart/alerts${securityId ? `?security_id=${securityId}` : ""}`);
}

export async function createChartAlert(alert: {
  security_id: string; exchange_segment: string; symbol?: string; display_name?: string;
  condition: "crosses_above" | "crosses_below"; price: number; note?: string;
}): Promise<ChartAlert> {
  return apiFetch("/api/chart/alerts", { method: "POST", body: JSON.stringify(alert) });
}

export async function deleteChartAlert(alertId: string): Promise<{ deleted: boolean }> {
  return apiFetch(`/api/chart/alerts/${alertId}`, { method: "DELETE" });
}

export async function evaluateChartAlerts(payload: {
  security_id: string; exchange_segment: string; last_price: number; previous_price: number | null;
}): Promise<{ triggered: ChartAlert[] }> {
  return apiFetch("/api/chart/alerts/evaluate", { method: "POST", body: JSON.stringify(payload) });
}

// --- Telegram Signal Copier ---

export interface TelegramParsedSignal {
  is_trade_idea: boolean;
  action: "BUY" | "SELL" | null;
  symbol: string | null;
  entry: number | null;
  sl: number | null;
  targets: number[];
  confidence: number;
}

export interface TelegramSignal {
  message_id: number;
  raw_text: string;
  received_at: string;
  has_image?: boolean;
  status: "pending" | "parser_not_configured" | "parse_failed" | "not_a_trade_idea" | "parsed_only" | "position_opened" | "execution_failed";
  parsed?: TelegramParsedSignal;
  order_result?: { order_id: string; status: string };
  error?: string;
}

export async function fetchTelegramSignals(limit = 100): Promise<{ signals: TelegramSignal[] }> {
  return apiFetch(`/api/telegram-signals?limit=${limit}`);
}

export function telegramSignalImageUrl(messageId: number): string {
  return `${API_URL}/api/telegram-signals/image/${messageId}`;
}

// ---- Stocks Range (Nifty 50/100/250/500 watch-table with manual buy range) ----
export interface StockRangeRow {
  symbol: string;
  name: string | null;
  belongs_to: string | null;
  sector: string | null;
  ltp: number | null;
  change_1d: number | null;
  change_1d_pct: number | null;
  change_1w: number | null;
  change_1w_pct: number | null;
  stock_trend: string | null;
  sector_trend: string | null;
  buy_price: number | null;
  in_buy_zone: boolean;
  range_move_pct: number | null;
}
export interface StocksRangeUniverse {
  index: string;
  label: string;
  count: number;
  rows: StockRangeRow[];
}
export interface StockSearchResult {
  symbol: string;
  name: string | null;
  sector: string | null;
  belongs_to: string | null;
  tightest_index: string | null;
}
export interface StockRangeSetResult {
  symbol: string;
  buy_price: number;
  previous: number | null;
  pct_diff: number | null;
}

export async function fetchStocksRangeUniverse(index: string): Promise<StocksRangeUniverse> {
  return apiFetch(`/api/stocks-range/universe?index=${encodeURIComponent(index)}`);
}
export async function searchStocksRange(q: string): Promise<StockSearchResult[]> {
  const d = await apiFetch(`/api/stocks-range/search?q=${encodeURIComponent(q)}`);
  return d.results ?? [];
}
export async function getStockRange(symbol: string): Promise<{ symbol: string; buy_price: number | null }> {
  return apiFetch(`/api/stocks-range/range?symbol=${encodeURIComponent(symbol)}`);
}
export async function setStockRange(symbol: string, buyPrice: number): Promise<StockRangeSetResult> {
  return apiFetch(`/api/stocks-range/range`, { method: "POST", body: JSON.stringify({ symbol, buy_price: buyPrice }) });
}

// ---- Bullish Stocks (momentum screener: highs, 9 EMA, MA stack, RSI/MACD, volume) ----
export interface BullishStockRow {
  symbol: string;
  name: string | null;
  sector: string | null;
  belongs_to: string | null;
  fno_enabled: boolean;
  ltp: number;
  change_1d_pct: number | null;
  // indicator values
  ema9_days: number;
  ema9_hold_pct: number;
  sma50: number;
  sma200: number;
  high_52w: number;
  pct_from_52w_high: number;
  all_time_high: number | null;
  all_time_high_date: string | null;
  pct_from_ath: number | null;
  rsi: number | null;
  macd: number | null;
  macd_signal: number | null;
  vol_x_avg: number | null;
  ret_3m: number | null;
  sector_ret_3m: number | null;
  trail_high: number | null;
  // signals
  sig_ema9: boolean;
  sig_ma_stack: boolean;
  sig_near_high: boolean;
  sig_all_time_high: boolean;
  sig_structure: boolean;
  sig_rsi: boolean;
  sig_macd: boolean;
  sig_volume: boolean;
  sig_outperform: boolean;
  score: number;
  max_score: number;
  qualified: boolean;
  // fundamentals (Yahoo, refreshed daily; null when Yahoo has no data for the symbol)
  revenue_growth: number | null;
  earnings_growth: number | null;
  profit_margin: number | null;
  roe: number | null;
  debt_to_equity: number | null;
  held_institutions: number | null;
  held_insiders: number | null;
  analyst_rec: string | null;
  analyst_bullish?: boolean;
  fund_revenue?: boolean;
  fund_earnings?: boolean;
  fund_margin?: boolean;
  fund_debt?: boolean;
  fund_roe?: boolean;
  fund_holding?: boolean;
  fundamental_score: number | null;
  fundamental_max: number;
  fundamentals_known: boolean;
  fundamentally_ok: boolean;
  // trade plan
  entry: number;
  stop_loss: number;
  target: number;
  trail_stop: number;
}
export interface BullishStocksScreen {
  index: string;
  label: string;
  count: number;
  screened: number;
  qualified_only: boolean;
  benchmark: string;
  benchmark_ret_3m: number | null;
  fundamentals_available: boolean;
  fundamentals_graded: number;
  ath_available: number;
  high_window: string;
  unscreened_note: string;
  plan: { stop_pct: number; target_pct: number; trail_pct: number };
  computed_at: string;
  rows: BullishStockRow[];
}

export async function fetchBullishStocks(index: string, all = false): Promise<BullishStocksScreen> {
  return apiFetch(`/api/bullish-stocks/screen?index=${encodeURIComponent(index)}&all=${all ? "true" : "false"}`);
}

// ---- Momentum Trading desk (pre-live gate; paper, ₹10k/strategy, real costs charged) ----
export interface MomentumRegime {
  ok: boolean;
  gate_enabled: boolean;
  benchmark: string;
  close: number | null;
  ma: number | null;
  index_vol: number | null;
  reason: string;
}

export interface MomentumCoverage {
  scanned: number;
  available: number | null;
  note: string | null;
}

export interface MomentumPromotionGate {
  min_trades: number;
  min_profit_factor: number;
  min_win_rate: number;
  max_drawdown_pct: number;
  min_t_stat: number;
}

export interface MomentumSummary {
  initial_capital: number;
  per_strategy_allocation: number;
  position_notional: number;
  max_positions_per_strategy: number;
  available_cash: number;
  deployed_capital: number;
  realized_pnl: number;
  unrealized_pnl: number;
  total_costs: number;
  equity: number;
  open_positions: number;
  closed_positions: number;
  strategy_count: number;
  ready_count: number;
  rejected_count: number;
  pending_count: number;
  paused: boolean;
  mode: string;
  costs_charged: boolean;
  slippage_bps: number;
  promotion_gate: MomentumPromotionGate;
  today_pnl: number;
  breaker_tripped: boolean;
  daily_loss_limit: number;
  daily_loss_pct: number;
  last_run_at: string | null;
  last_notes: string[];
  broker_connected: boolean;
  angel_configured: boolean;
  regime: MomentumRegime;
  coverage: MomentumCoverage | null;
}

export interface MomentumScore {
  strategy_id: string;
  name: string;
  style: string;
  style_label: string;
  horizon: string;
  timeframe: string;
  rationale: string;
  max_hold_days: number;
  trades: number;
  win_rate: number;
  net_pnl: number;
  total_costs: number;
  profit_factor: number | null;
  expectancy: number;
  max_drawdown_pct: number;
  t_stat: number | null;
  return_pct: number;
  allocated_capital: number;
  open_positions: number;
  verdict: "READY" | "REJECTED" | "PENDING";
  verdict_reasons: string[];
}

export interface MomentumPosition {
  position_id: string;
  strategy_id: string;
  strategy_name: string;
  style: string;
  style_label: string;
  horizon: string;
  product: string;
  symbol: string;
  side: string;
  signal_price: number;
  entry_price: number;
  qty: number;
  capital_deployed: number;
  entry_costs: number;
  target: number;
  stoploss: number;
  initial_stop: number;
  trail_mode: string;
  high_water: number;
  ltp: number;
  ltp_source: string;
  unrealized_pnl: number;
  pnl_pct: number;
  realized_pnl: number | null;
  costs: number | null;
  exit_price: number | null;
  exit_reason: string | null;
  status: string;
  rationale: string;
  max_hold_days: number;
  stop_trailed?: boolean;
  opened_at: string;
  opened_on: string;
  closed_at: string | null;
}

export interface MomentumTrade {
  trade_id: string;
  strategy_id: string;
  strategy_name: string;
  style_label: string;
  symbol: string;
  side: string;
  entry_price: number;
  exit_price: number;
  qty: number;
  gross_pnl: number;
  costs: number;
  realized_pnl: number;
  exit_reason: string;
  rationale: string;
  opened_at: string;
  closed_at: string;
}

export interface MomentumCatalogStyle {
  style: string;
  label: string;
  strategies: {
    strategy_id: string;
    name: string;
    horizon: string;
    timeframe: string;
    rationale: string;
    max_hold_days: number;
    params: Record<string, unknown>;
  }[];
}

export async function fetchMomentumSummary(): Promise<MomentumSummary> {
  return apiFetch("/api/momentum/summary");
}
export async function fetchMomentumLeaderboard(): Promise<MomentumScore[]> {
  const r = await apiFetch("/api/momentum/leaderboard");
  return r.leaderboard ?? [];
}
// /positions embeds the capital snapshot only — the regime, heartbeat and cycle notes are
// stitched in from engine state by /summary alone, so they are absent here by design.
export type MomentumCapitalSnapshot = Omit<
  MomentumSummary,
  "regime" | "coverage" | "last_run_at" | "last_notes" | "broker_connected" | "angel_configured"
>;

export async function fetchMomentumPositions(): Promise<{ positions: MomentumPosition[]; open: MomentumPosition[]; summary: MomentumCapitalSnapshot }> {
  return apiFetch("/api/momentum/positions");
}
export async function fetchMomentumTrades(limit = 100): Promise<MomentumTrade[]> {
  const r = await apiFetch(`/api/momentum/trades?limit=${limit}`);
  return r.trades ?? [];
}
export async function fetchMomentumCatalog(): Promise<{ styles: MomentumCatalogStyle[]; total: number }> {
  return apiFetch("/api/momentum/catalog");
}
export async function runMomentumCycle(): Promise<{ opened: number; managed: number; scanned_symbols: number; regime: MomentumRegime; notes: string[] }> {
  return apiFetch("/api/momentum/run", { method: "POST" });
}

// ---- Stock-option Pre-Live desks (paper, single-stock options on live Angel data) ----
export interface StockDeskSummary {
  side: string;
  mode: string;
  strategy_count: number;
  universe: string[];
  timeframe: string;
  per_strategy_capital: number;
  initial_capital: number;
  deployed_capital: number;
  realized_pnl: number;
  unrealized_pnl: number;
  equity: number;
  open_positions: number;
  closed_positions: number;
  last_run_at: string | null;
  last_notes: string[];
  today_pnl: number;
  breaker_tripped: boolean;
  daily_loss_limit: number;
}
export interface StockDeskScore {
  side: string;
  strategy_id: string;
  name: string;
  is_anti: boolean;
  trades: number;
  wins: number;
  win_rate: number;
  net_pnl: number;
  profit_factor: number | null;
  allocated_capital: number | null;
}
export interface StockDeskPosition {
  position_id: string;
  side: string;
  strategy_id: string;
  strategy_name: string;
  is_anti: boolean;
  symbol: string;
  option_type: string;
  expiry: string | null;
  strike: number;
  lot_size: number;
  qty: number;
  structure: string;
  entry_premium: number;
  ltp: number | null;
  capital_deployed: number;
  max_loss?: number;
  credit?: number;
  unrealized_pnl: number;
  realized_pnl: number | null;
  status: string;
}

export async function fetchStockDeskSummary(side: string): Promise<StockDeskSummary> {
  return apiFetch(`/api/stock-desk/${side}/summary`);
}
export async function fetchStockDeskLeaderboard(side: string): Promise<StockDeskScore[]> {
  const r = await apiFetch(`/api/stock-desk/${side}/leaderboard`);
  return r.leaderboard ?? [];
}
export async function fetchStockDeskPositions(side: string): Promise<{ positions: StockDeskPosition[]; summary: StockDeskSummary }> {
  return apiFetch(`/api/stock-desk/${side}/positions?status=OPEN`);
}
export async function runStockDeskCycle(side: string): Promise<{ opened: number; managed: number; notes: string[] }> {
  return apiFetch(`/api/stock-desk/${side}/run`, { method: "POST" });
}

// ---- Zero Hero Trades (expiry-day deep-OTM index option lottery, paper) ----
export interface ZeroHeroSummary {
  mode: string;
  strategy_count: number;
  per_strategy_capital: number;
  initial_capital: number;
  deployed_capital: number;
  realized_pnl: number;
  unrealized_pnl: number;
  equity: number;
  open_positions: number;
  closed_positions: number;
  wins: number;
  win_rate: number;
  expiring_today: string[];
  max_trade_budget: number;
  last_run_at: string | null;
  last_notes: string[];
}
export interface ZeroHeroScore {
  strategy_id: string;
  name: string;
  index: string;
  otm_pct: number;
  max_premium: number;
  window: string;
  window_from: string;
  window_to: string;
  trigger: string;
  target_mult: number;
  trades: number;
  wins: number;
  win_rate: number;
  net_pnl: number;
  profit_factor: number | null;
  expectancy: number;
  best_trade: number;
  capital: number;
}
export interface ZeroHeroPosition {
  position_id: string;
  strategy_id: string;
  strategy_name: string;
  index: string;
  option_type: string;
  strike: number;
  expiry: string;
  lots: number;
  qty: number;
  spot_at_entry: number;
  entry_premium: number;
  ltp: number | null;
  capital_deployed: number;
  target_premium: number;
  stop_premium: number;
  unrealized_pnl: number;
  realized_pnl: number | null;
  exit_premium: number | null;
  exit_reason: string | null;
  status: string;
}
export interface ZeroHeroTrade {
  trade_id: string;
  strategy_name: string;
  index: string;
  option_type: string;
  strike: number;
  qty: number;
  entry_premium: number;
  exit_premium: number;
  multiple: number | null;
  realized_pnl: number;
  exit_reason: string;
  session: string;
}
export interface ZeroHeroSignal {
  signal_id: string;
  ts: string;
  strategy_id: string;
  strategy_name: string;
  index: string;
  option_type: string;
  strike: number;
  spot: number;
  premium: number | null;
  max_premium: number;
  taken: boolean;
  reason: string | null;
}
export interface ZeroHeroDaily {
  session: string;
  net_pnl: number;
  trades: number;
  wins: number;
  win_rate: number;
  best_trade: number;
}

export async function fetchZeroHeroSummary(): Promise<ZeroHeroSummary> {
  return apiFetch("/api/zero-hero/summary");
}
export async function fetchZeroHeroLeaderboard(): Promise<ZeroHeroScore[]> {
  const r = await apiFetch("/api/zero-hero/leaderboard");
  return r.leaderboard ?? [];
}
export async function fetchZeroHeroPositions(status = "OPEN"): Promise<{ positions: ZeroHeroPosition[]; summary: ZeroHeroSummary }> {
  return apiFetch(`/api/zero-hero/positions?status=${status}`);
}
export async function fetchZeroHeroTrades(limit = 300): Promise<ZeroHeroTrade[]> {
  const r = await apiFetch(`/api/zero-hero/trades?limit=${limit}`);
  return r.trades ?? [];
}
export async function fetchZeroHeroSignals(limit = 300): Promise<ZeroHeroSignal[]> {
  const r = await apiFetch(`/api/zero-hero/signals?limit=${limit}`);
  return r.signals ?? [];
}
export async function fetchZeroHeroDaily(limit = 60): Promise<ZeroHeroDaily[]> {
  const r = await apiFetch(`/api/zero-hero/daily?limit=${limit}`);
  return r.daily ?? [];
}

// ---- Buy Low Options (cheap OTM calls on F&O stocks down >4% at the 3 PM check) ----
export interface BuyLowSummary {
  mode: string;
  total_capital: number;
  max_position_cost: number;
  fall_pct: number;
  target_rupees: number;
  stop_rupees: number;
  scan_window: string;
  deployed_capital: number;
  free_capital: number;
  realized_pnl: number;
  unrealized_pnl: number;
  equity: number;
  open_positions: number;
  closed_positions: number;
  wins: number;
  win_rate: number;
  max_concurrent: number;
  last_run_at: string | null;
  last_notes: string[];
}
export interface BuyLowFaller {
  symbol: string;
  ltp: number;
  prev_close: number;
  change_pct: number;
  triggers: boolean;
}
export interface BuyLowPosition {
  position_id: string;
  symbol: string;
  session: string;
  change_pct_at_entry: number;
  spot_at_entry: number;
  option_type: string;
  strike: number;
  expiry: string;
  lot_size: number;
  qty: number;
  entry_premium: number;
  ltp: number | null;
  cost: number;
  target_premium: number;
  stop_premium: number;
  unrealized_pnl: number;
  realized_pnl: number | null;
  exit_premium: number | null;
  exit_reason: string | null;
  status: string;
}
export interface BuyLowTrade {
  trade_id: string;
  symbol: string;
  session: string;
  strike: number;
  change_pct_at_entry: number;
  entry_premium: number;
  exit_premium: number;
  cost: number;
  realized_pnl: number;
  exit_reason: string;
}
export interface BuyLowSignal {
  signal_id: string;
  ts: string;
  symbol: string;
  change_pct: number;
  spot: number;
  strike?: number;
  cost?: number;
  taken: boolean;
  reason: string | null;
}
export interface BuyLowDaily {
  session: string;
  net_pnl: number;
  trades: number;
  wins: number;
  win_rate: number;
}

export async function fetchBuyLowSummary(): Promise<BuyLowSummary> {
  return apiFetch("/api/buy-low/summary");
}
export async function fetchBuyLowFallers(limit = 40): Promise<BuyLowFaller[]> {
  const r = await apiFetch(`/api/buy-low/fallers?limit=${limit}`);
  return r.fallers ?? [];
}
export async function fetchBuyLowPositions(status = "OPEN"): Promise<{ positions: BuyLowPosition[]; summary: BuyLowSummary }> {
  return apiFetch(`/api/buy-low/positions?status=${status}`);
}
export async function fetchBuyLowTrades(limit = 500): Promise<BuyLowTrade[]> {
  const r = await apiFetch(`/api/buy-low/trades?limit=${limit}`);
  return r.trades ?? [];
}
export async function fetchBuyLowSignals(limit = 500): Promise<BuyLowSignal[]> {
  const r = await apiFetch(`/api/buy-low/signals?limit=${limit}`);
  return r.signals ?? [];
}
export async function fetchBuyLowDaily(limit = 60): Promise<BuyLowDaily[]> {
  const r = await apiFetch(`/api/buy-low/daily?limit=${limit}`);
  return r.daily ?? [];
}

export interface BuyLowMover {
  symbol: string;
  ltp: number;
  ref: number;
  ref_date: string;
  change_pct: number;
}
export interface BuyLowScreenerWindow {
  window: string;
  measured_from: string | null;
  covered: number;
  gainers: BuyLowMover[];
  losers: BuyLowMover[];
}
export interface BuyLowUniverseRow {
  symbol: string;
  ltp: number;
  prev_close: number;
  change_1d: number | null;
  ref_1w: number | null;
  change_1w: number | null;
  ref_1m: number | null;
  change_1m: number | null;
  triggers: boolean;
}
export interface BuyLowScreener {
  as_of: string | null;
  universe: number;
  windows: BuyLowScreenerWindow[];
  week_from: string | null;
  month_from: string | null;
  all: BuyLowUniverseRow[];
}

export async function fetchBuyLowScreener(limit = 15): Promise<BuyLowScreener> {
  return apiFetch(`/api/buy-low/screener?limit=${limit}`);
}

// ---- Live Paper Buying (the 5 Pre-Live winners on a Rs50,000 book) ----
export interface LivePaperSummary {
  mode: string;
  underlying: string;
  timeframe: string;
  total_capital: number;
  per_strategy: number;
  strategy_count: number;
  deployed_capital: number;
  realized_pnl: number;
  unrealized_pnl: number;
  equity: number;
  open_positions: number;
  closed_positions: number;
  wins: number;
  win_rate: number;
  market_open: boolean;
  entry_cutoff: string;
  squareoff: string;
  last_run_at: string | null;
  last_notes: string[];
}
export interface LivePaperScore {
  strategy_id: string;
  base_id: string;
  name: string;
  trades: number;
  wins: number;
  win_rate: number;
  net_pnl: number;
  profit_factor: number | null;
  expectancy: number;
  allocated: number;
}
export interface LivePaperPosition {
  position_id: string;
  strategy_id: string;
  strategy_name: string;
  underlying: string;
  option_type: string;
  strike: number;
  expiry: string;
  lots: number;
  qty: number;
  spot_at_entry: number;
  entry_premium: number;
  ltp: number | null;
  cost: number;
  target_premium: number;
  stop_premium: number;
  unrealized_pnl: number;
  realized_pnl: number | null;
  exit_premium: number | null;
  exit_reason: string | null;
  status: string;
  session: string;
}
export interface LivePaperDaily {
  session: string;
  net_pnl: number;
  trades: number;
  wins: number;
  win_rate: number;
}

export async function fetchLivePaperSummary(): Promise<LivePaperSummary> {
  return apiFetch("/api/live-paper/summary");
}
export async function fetchLivePaperLeaderboard(): Promise<LivePaperScore[]> {
  const r = await apiFetch("/api/live-paper/leaderboard");
  return r.leaderboard ?? [];
}
export async function fetchLivePaperPositions(status = "OPEN"): Promise<{ positions: LivePaperPosition[]; summary: LivePaperSummary }> {
  return apiFetch(`/api/live-paper/positions?status=${status}`);
}
export async function fetchLivePaperDaily(limit = 60): Promise<LivePaperDaily[]> {
  const r = await apiFetch(`/api/live-paper/daily?limit=${limit}`);
  return r.daily ?? [];
}

// ---- F&O auto-roll: the daily 3 PM ATM short-straddle roll on one named account ----
export interface FnoAutoRollStatus {
  enabled: boolean;
  account_name: string;
  account_found: boolean;
  account_id: string | null;
  symbol: string;
  lots: number;
  product_type: string;
  roll_time_ist: string;
  grace_minutes: number;
  min_days_to_expiry: number;
  holidays: string[];
  now_ist: string;
  is_trading_day: boolean;
  rolled_today: boolean;
  last_status: string | null;
  last_message: string | null;
  last_run_at: string | null;
  last_rolled_on: string | null;
  recent: {
    roll_id: string;
    status: string;
    trigger: string;
    message: string;
    trading_date: string;
    finished_at: string;
  }[];
}

export interface FnoAutoRollPreview {
  ok: boolean;
  reason: string | null;
  symbol: string;
  lots: number;
  spot: number | null;
  target_expiry: string | null;
  expiry_note: string;
  target_strike: number | null;
  strike_note: string;
  would_close: { position_id: string; display_name: string; side: string; quantity: number }[];
  would_open: string[];
}

export async function fetchFnoAutoRollStatus(): Promise<FnoAutoRollStatus> {
  return apiFetch("/api/fno-positions/auto-roll/status");
}
export async function fetchFnoAutoRollPreview(): Promise<FnoAutoRollPreview> {
  return apiFetch("/api/fno-positions/auto-roll/preview");
}
export async function runFnoAutoRoll(): Promise<{ status: string; message: string }> {
  return apiFetch("/api/fno-positions/auto-roll/run", { method: "POST" });
}

// ---- Momentum Trading (intraday cash equity: long +2%, short -2%) ----
export interface MomentumTradingSummary {
  mode: string;
  enabled: boolean;
  bucket: string;
  buckets: string[];
  universe_size: number;
  total_capital: number;
  position_size: number;
  max_concurrent: number;
  move_pct: number;
  target_pct: number;
  stop_pct: number;
  checkpoints: string[];
  done_today: string[];
  squareoff: string;
  now_ist: string;
  next_due: string | null;
  deployed_capital: number;
  free_capital: number;
  realized_pnl: number;
  unrealized_pnl: number;
  equity: number;
  open_positions: number;
  longs: number;
  shorts: number;
  closed_positions: number;
  wins: number;
  win_rate: number;
}
export interface MomentumTradingPosition {
  position_id: string;
  session: string;
  checkpoint: string;
  symbol: string;
  side: string;
  change_pct_at_entry: number;
  entry_price: number;
  qty: number;
  cost: number;
  ltp: number | null;
  target_price: number;
  stop_price: number;
  unrealized_pnl: number;
  realized_pnl: number | null;
  exit_price: number | null;
  exit_reason: string | null;
  status: string;
}
export interface MomentumTradingCandidate {
  symbol: string;
  change_pct: number;
  ltp: number;
  side: string;
  qty: number;
  cost: number;
  already_open: boolean;
}
export interface MomentumTradingPreview {
  scanned: number;
  candidates: number;
  up: number;
  down: number;
  rows: MomentumTradingCandidate[];
}
export interface MomentumTradingDaily {
  session: string;
  net_pnl: number;
  trades: number;
  wins: number;
  win_rate: number;
}

export async function fetchMomentumTradingSummary(bucket = "top752"): Promise<MomentumTradingSummary> {
  return apiFetch(`/api/momentum-trading/summary?bucket=${bucket}`);
}
export async function fetchMomentumTradingPreview(bucket = "top752"): Promise<MomentumTradingPreview> {
  return apiFetch(`/api/momentum-trading/preview?bucket=${bucket}`);
}
export async function fetchMomentumTradingPositions(status = "OPEN", bucket = "top752"): Promise<{ positions: MomentumTradingPosition[]; summary: MomentumTradingSummary }> {
  return apiFetch(`/api/momentum-trading/positions?status=${status}&bucket=${bucket}`);
}
export async function fetchMomentumTradingDaily(limit = 60, bucket = "top752"): Promise<MomentumTradingDaily[]> {
  const r = await apiFetch(`/api/momentum-trading/daily?limit=${limit}&bucket=${bucket}`);
  return r.daily ?? [];
}


// ── NIFTY 50 Option Scalping ───────────────────────────────────────────────────
// 400 strategies: 50 candle/indicator templates x 8 timeframes, each buying near-expiry
// ATM NIFTY options on its own Rs2,00,000.

export interface NiftyScalpSummary {
  mode: string;
  enabled: boolean;
  initial_capital: number;
  per_strategy_capital: number;
  strategy_count: number;
  deployed_capital: number;
  available_cash: number;
  realized_pnl: number;
  gross_realized_pnl: number;
  total_fees: number;
  unrealized_pnl: number;
  equity: number;
  roi_pct: number;
  today_pnl: number;
  today_roi_pct: number;
  daily_loss_limit: number;
  breaker_tripped: boolean;
  open_positions: number;
  closed_positions: number;
  expiry: string | null;
  last_run_at: string | null;
  last_notes: string[];
}

export interface NiftyScalpScore {
  strategy_id: string;
  name: string;
  template: string;
  family: string;
  timeframe: string;
  style: string;
  trades: number;
  win_rate: number;
  net_pnl: number;
  gross_pnl: number;
  fees: number;
  roi_pct: number;
}

export interface NiftyScalpTimeframe {
  timeframe: string;
  label: string;
  style: string;
  strategies: number;
  capital: number;
  trades: number;
  wins: number;
  win_rate: number;
  net_pnl: number;
  gross_pnl: number;
  fees: number;
  roi_pct: number;
}

export interface NiftyScalpPosition {
  position_id: string;
  strategy_name: string;
  template: string;
  timeframe: string;
  style: string;
  symbol: string;
  option_type: string;
  strike: number;
  expiry: string;
  direction: string;
  lots: number;
  lot_size: number;
  qty: number;
  entry_premium: number;
  ltp: number;
  exit_premium: number | null;
  target_premium: number;
  stop_premium: number;
  capital_deployed: number;
  unrealized_pnl: number;
  realized_pnl: number | null;
  fees: number | null;
  exit_reason: string | null;
  status: string;
}

export interface NiftyScalpSignal {
  ts: string;
  strategy_name: string;
  timeframe: string;
  direction: string;
  spot: number;
  option: string | null;
  premium: number | null;
}

export async function fetchNiftyScalpSummary(): Promise<NiftyScalpSummary> {
  return apiFetch("/api/nifty-scalp/summary");
}
export async function fetchNiftyScalpLeaderboard(timeframe?: string, family?: string): Promise<NiftyScalpScore[]> {
  const q = new URLSearchParams();
  if (timeframe) q.set("timeframe", timeframe);
  if (family) q.set("family", family);
  const r = await apiFetch(`/api/nifty-scalp/leaderboard?${q.toString()}`);
  return r.leaderboard ?? [];
}
export async function fetchNiftyScalpTimeframes(): Promise<NiftyScalpTimeframe[]> {
  const r = await apiFetch("/api/nifty-scalp/timeframes");
  return r.timeframes ?? [];
}
export async function fetchNiftyScalpPositions(status = "OPEN", timeframe?: string): Promise<NiftyScalpPosition[]> {
  const q = timeframe ? `&timeframe=${timeframe}` : "";
  const r = await apiFetch(`/api/nifty-scalp/positions?status=${status}${q}`);
  return r.positions ?? [];
}
export async function fetchNiftyScalpSignals(limit = 150): Promise<NiftyScalpSignal[]> {
  const r = await apiFetch(`/api/nifty-scalp/signals?limit=${limit}`);
  return r.signals ?? [];
}
export async function fetchNiftyScalpDaily(limit = 60): Promise<DailyRoi[]> {
  const r = await apiFetch(`/api/nifty-scalp/daily?limit=${limit}`);
  return r.daily ?? [];
}

// ── NSE volume gainers (feeds the Buy Low screener) ────────────────────────────
// Exchange data Angel does not provide: today's volume against each stock's own 1-week
// and 2-week average, which is what separates a move on ordinary turnover from one
// someone is causing.

export interface NseVolumeRow {
  symbol: string;
  company: string;
  ltp: number | null;
  change_pct: number | null;
  volume: number | null;
  avg_1week_volume: number | null;
  avg_2week_volume: number | null;
  volume_x_1week: number | null;
  volume_x_2week: number | null;
  value_cr: number | null;
}

export interface NseVolume {
  date: string | null;
  count: number;
  ok: boolean;
  error: string | null;
  captured_at?: string | null;
  rows: NseVolumeRow[];
}

export async function fetchNseVolumeGainers(limit = 200): Promise<NseVolume> {
  return apiFetch(`/api/buy-low/nse-volume?limit=${limit}`);
}

// ---- Commodity Trading desk (311 pattern strategies on MCX futures, ₹10L each, paper) ----
export interface CommoditySummary {
  initial_capital: number;
  per_strategy_allocation: number;
  position_notional: number;
  strategy_count: number;
  available_cash: number;
  deployed_capital: number;
  realized_pnl: number;
  unrealized_pnl: number;
  total_costs: number;
  equity: number;
  open_positions: number;
  closed_positions: number;
  ready_count: number;
  rejected_count: number;
  pending_count: number;
  paused: boolean;
  mode: string;
  costs_charged: boolean;
  slippage_bps: number;
  market_open: boolean;
  max_strategies_per_symbol: number;
  promotion_gate: {
    min_trades: number;
    min_profit_factor: number;
    min_win_rate: number;
    max_drawdown_pct: number;
    min_t_stat: number;
  };
  today_pnl: number;
  breaker_tripped: boolean;
  daily_loss_limit: number;
  last_run_at: string | null;
  last_notes: string[];
  last_evaluated: number;
}

export interface CommodityScore {
  strategy_id: string;
  name: string;
  family: string;
  family_label: string;
  template: string;
  timeframe: string;
  trades: number;
  win_rate: number;
  net_pnl: number;
  total_costs: number;
  profit_factor: number | null;
  expectancy: number;
  max_drawdown_pct: number;
  t_stat: number | null;
  return_pct: number;
  allocated_capital: number;
  open_positions: number;
  verdict: "READY" | "REJECTED" | "PENDING";
  verdict_reasons: string[];
}

export interface CommodityPosition {
  position_id: string;
  strategy_name: string;
  family_label: string;
  template: string;
  timeframe: string;
  pattern: string;
  symbol: string;
  display_name: string;
  side: string;
  entry_price: number;
  qty: number;
  capital_deployed: number;
  target: number;
  stoploss: number;
  ltp: number;
  ltp_source: string;
  unrealized_pnl: number;
  pnl_pct: number;
  bars_held: number;
  max_hold_bars: number;
  rationale: string;
  status: string;
  opened_at: string;
}

export interface CommodityTrade {
  trade_id: string;
  strategy_name: string;
  timeframe: string;
  pattern: string;
  symbol: string;
  side: string;
  entry_price: number;
  exit_price: number;
  qty: number;
  gross_pnl: number;
  costs: number;
  realized_pnl: number;
  exit_reason: string;
  closed_at: string;
}

export interface CommodityUniverseRow {
  underlying: string;
  symbol: string;
  expiry: string;
  security_id: string;
  lot_size: number;
  tick_size: number;
  exchange_segment: string;
}

export interface CommodityCoverage {
  symbols: string[];
  native_timeframes: string[];
  derived_timeframes: string[];
  bars: Record<string, Record<string, number>>;
  latest_bar_ist: Record<string, string | null>;
}

export async function fetchCommoditySummary(): Promise<CommoditySummary> {
  return apiFetch("/api/commodity/summary");
}
export async function fetchCommodityLeaderboard(params: { family?: string; timeframe?: string; verdict?: string } = {}): Promise<{ leaderboard: CommodityScore[]; total: number; timeframes: string[] }> {
  const q = new URLSearchParams();
  if (params.family) q.set("family", params.family);
  if (params.timeframe) q.set("timeframe", params.timeframe);
  if (params.verdict) q.set("verdict", params.verdict);
  const s = q.toString();
  return apiFetch(`/api/commodity/leaderboard${s ? `?${s}` : ""}`);
}
export async function fetchCommodityPositions(): Promise<{ positions: CommodityPosition[]; open: CommodityPosition[] }> {
  return apiFetch("/api/commodity/positions");
}
export async function fetchCommodityTrades(limit = 80): Promise<CommodityTrade[]> {
  const r = await apiFetch(`/api/commodity/trades?limit=${limit}`);
  return r.trades ?? [];
}
export async function fetchCommodityUniverse(): Promise<CommodityUniverseRow[]> {
  const r = await apiFetch("/api/commodity/universe");
  return r.universe ?? [];
}
export async function fetchCommodityBars(): Promise<{ coverage: CommodityCoverage }> {
  return apiFetch("/api/commodity/bars");
}
export async function runCommodityCycle(): Promise<{ opened: number; managed: number; evaluated: number; notes: string[] }> {
  return apiFetch("/api/commodity/run", { method: "POST" });
}
export async function refreshCommodityBars(): Promise<{ symbols: number; seconds: number; failed_fetches: number }> {
  return apiFetch("/api/commodity/refresh-bars", { method: "POST" });
}

// ── Swing Trading ──────────────────────────────────────────────────────────────
// You name the buy price; the desk waits for the market to reach it, then manages the
// position to a stop and target you can change at any time.

export interface SwingSummary {
  mode: string;
  enabled: boolean;
  initial_capital: number;
  position_size: number;
  max_positions: number;
  default_sl_pct: number;
  default_tp_pct: number;
  deployed_capital: number;
  available_cash: number;
  realized_pnl: number;
  gross_realized_pnl: number;
  total_fees: number;
  unrealized_pnl: number;
  equity: number;
  roi_pct: number;
  today_pnl: number;
  today_roi_pct: number;
  deployed_roi_pct: number;
  open_positions: number;
  closed_positions: number;
  waiting: number;
  last_run_at: string | null;
}

export interface SwingSearchResult {
  symbol: string;
  name: string;
  angel_token: string;
  angel_exchange: string;
}

export interface SwingWatch {
  watch_id: string;
  symbol: string;
  name: string;
  buy_price: number;
  trigger_side: string;
  ltp: number | null;
  ltp_at_add: number | null;
  sl_pct: number;
  tp_pct: number;
  drift_pct: number;
  max_fill_price: number;
  min_fill_price: number;
  gapped_past: boolean;
  last_gap_pct: number | null;
  stop_price: number;
  target_price: number;
  status: string;
  note: string;
  created_at: string | null;
  triggered_at: string | null;
}

export interface SwingPosition {
  position_id: string;
  symbol: string;
  name: string;
  qty: number;
  buy_price: number;
  entry_price: number;
  slippage: number;
  drifted: boolean;
  drift_pct_actual: number | null;
  drift_pct_allowed: number | null;
  anchor_price: number;
  capital_deployed: number;
  sl_pct: number;
  tp_pct: number;
  stop_price: number;
  target_price: number;
  ltp: number;
  exit_price: number | null;
  unrealized_pnl: number;
  realized_pnl: number | null;
  gross_pnl: number | null;
  fees: number | null;
  exit_reason: string | null;
  status: string;
}

export interface SwingEquityPoint {
  ts: string;
  equity: number;
  realized: number;
  unrealized: number;
  deployed: number;
  roi_pct: number;
  open_positions: number;
}

export interface SwingDay {
  date: string;
  trades: number;
  wins: number;
  win_rate: number;
  gross_pnl: number;
  fees: number;
  realized_pnl: number;
  deployed: number;
  roi_pct: number;
  deployed_roi_pct: number;
}

export async function fetchSwingSummary(): Promise<SwingSummary> {
  return apiFetch("/api/swing/summary");
}
export async function searchSwingStocks(q: string, limit = 25): Promise<SwingSearchResult[]> {
  const r = await apiFetch(`/api/swing/search?q=${encodeURIComponent(q)}&limit=${limit}`);
  return r.results ?? [];
}
export async function fetchSwingWatchlist(status?: string): Promise<SwingWatch[]> {
  const q = status ? `?status=${status}` : "";
  const r = await apiFetch(`/api/swing/watchlist${q}`);
  return r.watchlist ?? [];
}
export async function addSwingWatch(body: {
  symbol: string; buy_price: number; sl_pct?: number; tp_pct?: number;
  drift_pct?: number; note?: string;
}): Promise<SwingWatch> {
  return apiFetch("/api/swing/watch", { method: "POST", body: JSON.stringify(body) });
}
export async function editSwingWatch(
  watchId: string,
  body: { buy_price?: number; sl_pct?: number; tp_pct?: number; drift_pct?: number },
): Promise<SwingWatch> {
  return apiFetch(`/api/swing/watch/${watchId}`, { method: "PATCH", body: JSON.stringify(body) });
}
export async function removeSwingWatch(watchId: string): Promise<{ removed: boolean }> {
  return apiFetch(`/api/swing/watch/${watchId}`, { method: "DELETE" });
}
export async function fetchSwingPositions(status = "OPEN"): Promise<SwingPosition[]> {
  const r = await apiFetch(`/api/swing/positions?status=${status}`);
  return r.positions ?? [];
}
export async function editSwingPosition(
  positionId: string,
  body: { sl_pct?: number; tp_pct?: number; stop_price?: number; target_price?: number },
): Promise<SwingPosition> {
  return apiFetch(`/api/swing/positions/${positionId}`, { method: "PATCH", body: JSON.stringify(body) });
}
export async function fetchSwingEquity(limit = 500): Promise<SwingEquityPoint[]> {
  const r = await apiFetch(`/api/swing/equity?limit=${limit}`);
  return r.equity ?? [];
}
export async function fetchSwingDaily(limit = 90): Promise<SwingDay[]> {
  const r = await apiFetch(`/api/swing/daily?limit=${limit}`);
  return r.daily ?? [];
}


// ── Live Trading history ───────────────────────────────────────────────────────

export interface LiveTradingEquityPoint {
  ts: string;
  equity: number;
  realized: number;
  unrealized: number;
  deployed: number;
  open_positions: number;
}

export interface LiveTradingDay {
  date: string;
  trades: number;
  wins: number;
  win_rate: number;
  realized_pnl: number;
  deployed: number;
  roi_pct: number;
  deployed_roi_pct: number;
}

export async function fetchLiveTradingEquity(limit = 500): Promise<LiveTradingEquityPoint[]> {
  const r = await apiFetch(`/api/live-trading/equity?limit=${limit}`);
  return r.equity ?? [];
}
export async function fetchLiveTradingDaily(limit = 90): Promise<LiveTradingDay[]> {
  const r = await apiFetch(`/api/live-trading/daily?limit=${limit}`);
  return r.daily ?? [];
}


// ── Desk history (shared by every trading module) ──────────────────────────────

export interface DeskHistoryDay {
  date: string;
  trades: number;
  wins: number;
  win_rate: number;
  realized_pnl: number;
  fees: number;
  deployed: number;
  roi_pct: number;
  deployed_roi_pct: number | null;
  deployed_coverage: number;
}

export interface DeskHistory {
  started_on: string | null;
  days_live: number;
  days_traded: number;
  capital: number;
  equity: number;
  realized_pnl: number;
  unrealized_pnl: number;
  total_fees: number;
  trades: number;
  wins: number;
  win_rate: number;
  roi_pct: number;
  deployed_now: number;
  open_positions: number;
  deployed_roi_pct: number | null;
  deployed_total: number;
  deployed_known: boolean;
  deployed_note: string | null;
  avg_per_trading_day: number;
  avg_per_calendar_day: number;
  avg_roi_per_trading_day_pct: number;
  daily: DeskHistoryDay[];
  curve: { ts: string; value: number }[];
  curve_is_derived: boolean;
  account_id?: string;
  account_name?: string;
}

export async function fetchDeskHistory(
  desk: string,
  scope?: string,
  fresh = false,
): Promise<DeskHistory> {
  const q = new URLSearchParams();
  if (scope) q.set("scope", scope);
  if (fresh) q.set("fresh", "true");
  const qs = q.toString();
  return apiFetch(`/api/desk-history/${desk}${qs ? `?${qs}` : ""}`);
}

// ---- Strategy Factory (546 composed strategies, Rs10L paper each) ----
export interface SFSummary {
  strategy_count: number;
  family_counts: Record<string, number>;
  per_strategy_capital: number;
  initial_capital: number;
  deployed_capital: number;
  realized_pnl: number;
  unrealized_pnl: number;
  total_costs: number;
  equity: number;
  open_positions: number;
  closed_positions: number;
  backtest_rows: number;
  grade_counts: Record<string, number>;
  min_grade_to_trade: number;
  require_grade: boolean;
  paused: boolean;
  mode: string;
  costs_charged: boolean;
  slippage_bps: number;
  last_run_at: string | null;
  last_backtest_at: string | null;
  last_notes: string[];
  today_pnl: number;
  breaker_tripped: boolean;
  daily_loss_limit: number;
  markets: Record<string, {
    symbols: number;
    exchange: string;
    cost_model: string;
    backtest_rows: number;
    open_positions: number;
  }>;
  active_sources: string[];
}

export interface SFRow {
  strategy_id: string;
  name: string;
  family: string;
  sub_family: string;
  timeframe: string;
  htf: string | null;
  style: string;
  target_r: number;
  hypothesis: string;
  regimes: string[];
  detector: string;
  grade: number;
  grade_reasons: string[];
  best_symbol: string | null;
  best_source: string | null;
  bt_trades: number;
  bt_win_rate: number;
  bt_profit_factor: number | null;
  bt_expectancy: number;
  bt_avg_r: number;
  bt_net_pnl: number;
  bt_max_dd_pct: number;
  bt_cagr_pct: number | null;
  bt_sharpe: number | null;
  oos_net_pnl: number;
  oos_trades: number;
  paper_trades: number;
  paper_net_pnl: number;
  paper_win_rate: number;
  open_positions: number;
  eligible: boolean;
}

export interface SFRecipe {
  key: string;
  name: string;
  family: string;
  sub_family: string;
  hypothesis: string;
  detector: string;
  target_r: number;
  regimes: string[];
  confirmations: string[];
  intraday_only: boolean;
  uses_htf: boolean;
}

export async function fetchSFSummary(): Promise<SFSummary> {
  return apiFetch("/api/strategy-factory/summary");
}
export async function fetchSFLibrary(p: { family?: string; timeframe?: string; grade?: number } = {}): Promise<{ library: SFRow[]; total: number; timeframes: string[]; families: Record<string, number> }> {
  const q = new URLSearchParams();
  if (p.family) q.set("family", p.family);
  if (p.timeframe) q.set("timeframe", p.timeframe);
  if (p.grade !== undefined) q.set("grade", String(p.grade));
  const s = q.toString();
  return apiFetch(`/api/strategy-factory/library${s ? `?${s}` : ""}`);
}
export async function fetchSFRecipes(): Promise<{ recipes: SFRecipe[]; count: number }> {
  return apiFetch("/api/strategy-factory/recipes");
}
export async function fetchSFStrategy(id: string): Promise<any> {
  return apiFetch(`/api/strategy-factory/strategy/${id}`);
}
export async function fetchSFPositions(): Promise<{ positions: any[]; open: any[] }> {
  return apiFetch("/api/strategy-factory/positions");
}
export async function fetchSFTrades(limit = 100): Promise<any[]> {
  const r = await apiFetch(`/api/strategy-factory/trades?limit=${limit}`);
  return r.trades ?? [];
}
export async function fetchSFSignals(limit = 60): Promise<any[]> {
  const r = await apiFetch(`/api/strategy-factory/signals?limit=${limit}`);
  return r.signals ?? [];
}
export async function runSFBacktest(): Promise<{ started: boolean; note: string }> {
  return apiFetch("/api/strategy-factory/backtest", { method: "POST" });
}
export async function runSFCycle(): Promise<{ opened: number; managed: number; notes: string[] }> {
  return apiFetch("/api/strategy-factory/run", { method: "POST" });
}


// ── Pattern desk (inside Intraday Stocks) ──────────────────────────────────────
// 63 templates x 8 timeframes on NSE equities: 13 geometric chart patterns, 10
// candlestick patterns, 40 indicator/structure rules.

export interface PatternTimeframeCfg {
  key: string;
  label: string;
  style: string;
  target_pct: number;
  stop_pct: number;
  native: boolean;
}

export interface PatternSummary {
  mode: string;
  enabled: boolean;
  initial_capital: number;
  per_strategy_capital: number;
  strategy_count: number;
  template_count: number;
  universe_size: number;
  timeframes: PatternTimeframeCfg[];
  deployed_capital: number;
  available_cash: number;
  realized_pnl: number;
  gross_realized_pnl: number;
  total_fees: number;
  unrealized_pnl: number;
  equity: number;
  roi_pct: number;
  open_positions: number;
  closed_positions: number;
  last_run_at: string | null;
  last_notes: string[];
  last_evaluated: number;
}

export interface PatternScore {
  strategy_id: string;
  name: string;
  template: string;
  family: string;
  timeframe: string;
  style: string;
  trades: number;
  win_rate: number;
  net_pnl: number;
  gross_pnl: number;
  fees: number;
  roi_pct: number;
}

export interface PatternTimeframeStat {
  timeframe: string;
  label: string;
  style: string;
  strategies: number;
  capital: number;
  trades: number;
  wins: number;
  win_rate: number;
  net_pnl: number;
  fees: number;
  roi_pct: number;
}

export interface PatternPosition {
  position_id: string;
  strategy_name: string;
  template: string;
  timeframe: string;
  style: string;
  symbol: string;
  side: string;
  qty: number;
  entry_price: number;
  ltp: number;
  exit_price: number | null;
  target: number;
  stoploss: number;
  capital_deployed: number;
  unrealized_pnl: number;
  realized_pnl: number | null;
  fees: number | null;
  exit_reason: string | null;
  status: string;
}

export async function fetchPatternSummary(): Promise<PatternSummary> {
  return apiFetch("/api/pattern/summary");
}
export async function fetchPatternLeaderboard(timeframe?: string, family?: string): Promise<PatternScore[]> {
  const q = new URLSearchParams();
  if (timeframe) q.set("timeframe", timeframe);
  if (family) q.set("family", family);
  const qs = q.toString();
  const r = await apiFetch(`/api/pattern/leaderboard${qs ? `?${qs}` : ""}`);
  return r.leaderboard ?? [];
}
export async function fetchPatternTimeframes(): Promise<PatternTimeframeStat[]> {
  const r = await apiFetch("/api/pattern/timeframes");
  return r.timeframes ?? [];
}
export async function fetchPatternPositions(status = "OPEN", timeframe?: string): Promise<PatternPosition[]> {
  const q = timeframe ? `&timeframe=${timeframe}` : "";
  const r = await apiFetch(`/api/pattern/positions?status=${status}${q}`);
  return r.positions ?? [];
}

// ── Stock Screener ────────────────────────────────────────────────────────────────
// Momentum across four horizons, sector rotation with drill-down, daily/weekly chart
// patterns, and the intraday/swing/breakout setup shortlists. Every number is computed
// from stored daily bars plus live Angel quotes; NSE and Chartink are enrichment only,
// and the /sources endpoint reports exactly which of them answered.

export interface ScreenerChip { label: string; tier: number; code: string; }

export interface ScreenerMomentumRow {
  rank: number;
  symbol: string;
  name: string | null;
  sector: string;
  belongs_to: string | null;
  ltp: number;
  return_pct: number | null;
  returns: Record<string, number | null>;
  rank_pct: number | null;
  rs_index: number | null;
  rs_sector: number | null;
  consistency: number | null;
  sector_return_pct: number | null;
  volume_x: number | null;
  turnover: number | null;
  delivery_pct: number | null;
  ema9_hold_pct: number | null;
  up_streak: number;
  pct_from_52w_high: number | null;
  pct_from_ath: number | null;
  breakout: { window: number; date: string } | null;
  sessions: number;
  why: ScreenerChip[];
  why_summary: string;
  character: string;
  score: number | null;
  spark: number[];
}

export interface ScreenerCoverage {
  symbols: number; with_history: number; pct: number; sessions_needed: number;
}

export interface ScreenerMomentumBoard {
  index: string; label: string; horizon: string; horizon_label: string;
  benchmark: { symbol: string; available: boolean; returns: Record<string, number | null> };
  coverage: ScreenerCoverage;
  quotes_live: boolean;
  count: number;
  rows: ScreenerMomentumRow[];
}

export interface ScreenerSectorRow {
  sector: string; count: number; thin: boolean;
  returns: Record<string, number | null>;
  breadth: Record<string, number | null>;
  ranks: Record<string, number>;
  rank_change: number | null;
  rotation: string;
  // Keyed by horizon. These used to be a single pair computed on the daily board and
  // reused across every column, which put a one-day leader next to a monthly return.
  leaders: Record<string, { symbol: string; return_pct: number }>;
  laggards: Record<string, { symbol: string; return_pct: number }>;
  rs: Record<string, number | null>;
  volume_x?: number | null;
}

export interface ScreenerSectorBoard {
  count: number; sectors: ScreenerSectorRow[];
  benchmark: Record<string, number | null>;
  horizons: { key: string; label: string }[];
  basis: string;
}

export interface ScreenerContribution {
  symbol: string; name: string | null; return_pct: number;
  weight_pct: number; contribution_pp: number; volume_x: number | null; ltp: number;
}

export interface ScreenerSectorDetail {
  sector: string; horizon: string; horizon_label: string;
  summary: Record<string, any>;
  shape: string; breadth_pct: number; top2_share_pct: number;
  drivers: string[];
  contributions: ScreenerContribution[];
  constituents: (ScreenerMomentumRow & { return_pct: number })[];
  note: string;
}

export interface ScreenerPatternRow {
  symbol: string; sector: string | null;
  pattern: string; template: string; family: string; family_label: string;
  timeframe: string; timeframe_label: string;
  state: "TRIGGERED" | "FORMING";
  side: string; direction: string;
  entry: number; target: number; stoploss: number;
  trigger_level: number | null;
  confidence: number; rationale: string; as_of: string;
  reward_risk: number | null;
}

export interface ScreenerPatternBoard {
  index: string; scanned: number; count: number;
  triggered: number; forming: number;
  weekly_coverage: { symbols: number; with_enough_weekly_bars: number; pct: number; note: string };
  elapsed_s: number;
  catalog: { key: string; label: string; family: string; family_label: string; probeable: boolean }[];
  rows: ScreenerPatternRow[];
}

export interface ScreenerPlan {
  kind: string; label: string; tradable: boolean;
  entry: number; stop: number; target: number;
  stop_pct: number; target_pct: number;
  horizon: string; exit_rule: string; basis: string;
  qty: number; capital_used: number;
  gross_rr: number | null; net_rr: number | null;
  net_reward: number | null; net_risk: number | null;
  cost_win: Record<string, number | string> | null;
  product: string;
  worth_taking: boolean;
  drift_pct?: number; blocked_reason?: string;
  confirming_patterns: { pattern: string; state: string; timeframe: string }[];
}

export interface ScreenerSetupRow {
  symbol: string; name: string | null; sector: string; ltp: number;
  return_pct: number | null; volume_x: number | null; rs_index: number | null;
  sector_return_pct: number | null;
  plan: ScreenerPlan;
  why: ScreenerChip[]; why_summary: string; character: string;
  patterns: { pattern: string; state: string; timeframe: string }[];
}

export interface ScreenerSetupBoard {
  kind: string; index: string; horizon: string;
  universe: number; qualified: number; worth_taking: number; rejected: number;
  capital_per_trade: number; note: string;
  rows: ScreenerSetupRow[];
}

export interface ScreenerSummary {
  index: string; label: string; universe: number;
  advances: number; declines: number; unchanged: number;
  advance_decline_ratio: number | null;
  above_sma20: { pct: number | null; n: number; of: number };
  above_sma50: { pct: number | null; n: number; of: number };
  above_sma200: { pct: number | null; n: number; of: number };
  new_52w_highs: number; new_52w_lows: number;
  above_vwap: { available: boolean; reason: string };
  benchmark: { symbol: string; available: boolean; returns: Record<string, number | null> };
  coverage: Record<string, ScreenerCoverage>;
  quotes_live: boolean;
  market_open: boolean | null;
}

export interface ScreenerSources {
  index: string;
  feeds: {
    name: string; role: string; ok: boolean | null; detail: string;
    coverage?: Record<string, ScreenerCoverage>;
    endpoints?: Record<string, { ok: boolean; error: string | null }>;
    verified?: Record<string, string>;
  }[];
  checked_at: string;
}

export interface ScreenerConfig {
  indices: { key: string; label: string }[];
  default_index: string;
  horizons: { key: string; label: string; sessions: number }[];
  timeframes: { key: string; label: string }[];
  pattern_catalog: { key: string; label: string; family: string; family_label: string; probeable: boolean }[];
  setup_kinds: string[];
  volume_windows: { key: string; label: string; sessions: number }[];
  volume_states: { key: string; label: string; text: string }[];
  paper_families: { key: string; label: string; product: string }[];
  chartink: {
    enabled: boolean;
    presets: { key: string; label: string; why_not_local: string }[];
    named: { slug: string; label: string; why: string; url: string }[];
    verified: Record<string, string>;
    policy: string;
  };
}

export interface ScreenerReason {
  code: string; tier: number; text: string;
  weight: number; value: number | null; unit: string | null;
}

export interface ScreenerDetail {
  symbol: string; name: string | null; sector: string; belongs_to: string | null;
  ltp: number; sessions: number;
  horizons: Record<string, {
    label: string; return_pct: number | null; benchmark_pct: number | null;
    rs_index: number | null; sector_return_pct: number | null; sector_rank: number | null;
    reasons: ScreenerReason[];
    summary: string; character: string;
  }>;
  structure: Record<string, any>;
  patterns: ScreenerPatternRow[];
  trade_plans: ScreenerPlan[];
  narrative: { available: boolean; reason: string };
}

function screenerQs(params: Record<string, string | number | boolean | null | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== null && v !== undefined && v !== "") q.set(k, String(v));
  }
  const s = q.toString();
  return s ? "?" + s : "";
}

export async function fetchScreenerConfig(): Promise<ScreenerConfig> {
  return apiFetch("/api/screener/config");
}
export async function fetchScreenerSummary(index?: string): Promise<ScreenerSummary> {
  return apiFetch("/api/screener/summary" + screenerQs({ index }));
}
export async function fetchScreenerMomentum(
  horizon: string, index?: string, sector?: string, limit = 100, minTurnover?: number,
): Promise<ScreenerMomentumBoard> {
  return apiFetch("/api/screener/momentum" +
    screenerQs({ horizon, index, sector, limit, min_turnover: minTurnover }));
}
export async function fetchScreenerDetail(symbol: string, index?: string): Promise<ScreenerDetail> {
  return apiFetch("/api/screener/momentum/" + encodeURIComponent(symbol) + screenerQs({ index }));
}
export async function fetchScreenerSectors(index?: string, horizon?: string): Promise<ScreenerSectorBoard> {
  return apiFetch("/api/screener/sectors" + screenerQs({ index, horizon }));
}
export async function fetchScreenerSectorDetail(
  sector: string, horizon: string, index?: string,
): Promise<ScreenerSectorDetail> {
  return apiFetch("/api/screener/sectors/" + encodeURIComponent(sector) +
    screenerQs({ horizon, index }));
}
export async function fetchScreenerPatterns(opts: {
  timeframe?: string; pattern?: string; family?: string; state?: string;
  direction?: string; sector?: string; index?: string; limit?: number;
} = {}): Promise<ScreenerPatternBoard> {
  return apiFetch("/api/screener/patterns" + screenerQs(opts as Record<string, string | number>));
}
export async function fetchScreenerSetups(
  kind: string, index?: string, limit = 40,
): Promise<ScreenerSetupBoard> {
  return apiFetch("/api/screener/setups" + screenerQs({ kind, index, limit }));
}
export async function fetchScreenerSources(index?: string): Promise<ScreenerSources> {
  return apiFetch("/api/screener/sources" + screenerQs({ index }));
}
export async function refreshScreener(index?: string): Promise<Record<string, any>> {
  return apiFetch("/api/screener/refresh" + screenerQs({ index }), { method: "POST" });
}

// --- Trending Stocks: LONG-ONLY desk over a user-named basket -----------------
// 678 strategies at Rs10,00,000 paper each, gated by a 1:6 feasibility test and a
// seven-pillar research gate. Every position carries the sentences that justified it.

export interface TSPillar {
  name: string;
  verdict: "supports" | "neutral" | "opposes" | "veto";
  score: number;
  sentence: string;
  facts: Record<string, any>;
}

export interface TSEvidence {
  ok: boolean;
  supports: number;
  required: number;
  score: number;
  vetoes: string[];
  reasons: string[];
  pillars: TSPillar[];
}

export interface TSCoverageCell {
  bars: number;
  first: string | null;
  last: string | null;
  native: boolean;
  derived_from?: string;
  error?: string | null;
}

export interface TSBasketRow {
  symbol: string;
  name: string | null;
  status: "ACTIVE" | "QUARANTINED" | "REMOVED";
  note: string | null;
  quarantine_reason?: string;
  added_at: string | null;
  backfilled_at: string | null;
  backfill: Record<string, number> | null;
  coverage: Record<string, TSCoverageCell>;
  open_positions: number;
}

export interface TSSummary {
  module: string;
  direction: string;
  mode: string;
  strategy_count: number;
  family_counts: Record<string, number>;
  style_counts: Record<string, number>;
  per_strategy_capital: number;
  initial_capital: number;
  deployed_capital: number;
  realized_pnl: number;
  unrealized_pnl: number;
  total_costs: number;
  equity: number;
  open_positions: number;
  closed_positions: number;
  backtest_rows: number;
  validated_rows: number;
  failed_1_6_rr: number;
  grade_counts: Record<string, number>;
  basket: { symbol: string; name: string | null; status: string; quarantine_reason?: string }[];
  basket_size: number;
  gate: {
    min_rr: number;
    min_pillars: number;
    pillars: string[];
    min_grade_to_trade: number;
    require_grade: boolean;
    max_strategies_per_symbol: number;
    max_positions_per_strategy: number;
    max_consecutive_losses: number;
    risk_pct: number;
    slippage_bps: number;
    min_turnover: number;
    entry_cutoff: string;
    squareoff: string;
  };
  costs_charged: boolean;
  paused: boolean;
  market_open: boolean;
  benchmark: string;
  last_run_at: string | null;
  last_backtest_at: string | null;
  last_validation_at: string | null;
  last_notes: string[];
  last_rejections: Record<string, number>;
  breaker_tripped: boolean;
  breaker_reasons: string[];
  today_pnl: number;
  week_pnl: number;
  drawdown_pct: number;
}

export interface TSLibraryRow {
  strategy_id: string;
  name: string;
  family: string;
  sub_family: string;
  timeframe: string;
  htf: string | null;
  style: string;
  target_r: number;
  min_rr: number;
  hypothesis: string;
  regimes: string[];
  detector: string;
  direction: string;
  grade: number | null;
  base_grade: number | null;
  status: string | null;
  grade_reasons: string[];
  failed_rr: boolean;
  failed_rr_label: string | null;
  best_symbol: string | null;
  bt_trades: number;
  bt_win_rate: number;
  bt_profit_factor: number | null;
  bt_expectancy: number;
  bt_avg_r: number;
  bt_net_pnl: number;
  bt_costs: number;
  bt_max_dd_pct: number;
  bt_cagr_pct: number | null;
  bt_sharpe: number | null;
  oos_net_pnl: number;
  oos_trades: number;
  wf_fraction: number | null;
  wf_windows: number | null;
  mc_p5_final: number | null;
  mc_prob_ruin: number | null;
  paper_trades: number;
  paper_net_pnl: number;
  paper_win_rate: number;
  open_positions: number;
  eligible: boolean;
}

export interface TSPosition {
  position_id: string;
  strategy_id: string;
  strategy_name: string;
  family: string;
  timeframe: string;
  style: string;
  symbol: string;
  side: string;
  entry_price: number;
  stoploss: number;
  target: number;
  qty: number;
  risk_amount: number;
  reward_amount: number;
  r_multiple: number;
  min_rr: number;
  capital_deployed: number;
  pattern: string;
  detail: string;
  confirmations: string[];
  regime_primary: string;
  confidence: number;
  reasons: string[];
  evidence: TSEvidence;
  evidence_score: number;
  feasibility: Record<string, any> | null;
  ltp: number;
  unrealized_pnl: number;
  realized_pnl: number | null;
  pnl_pct: number;
  r_now: number | null;
  costs: number | null;
  exit_price: number | null;
  exit_reason: string | null;
  status: string;
  opened_at: string | null;
  closed_at: string | null;
}

export interface TSSignal {
  signal_id: string;
  position_id: string;
  strategy_id: string;
  strategy_name: string;
  symbol: string;
  timeframe: string;
  htf: string | null;
  direction: string;
  entry: number;
  stop: number;
  target: number;
  risk: number;
  reward: number;
  r_multiple: number;
  qty: number;
  capital_allocated: number;
  pattern: string;
  confirmations: string[];
  regime: string;
  confidence: number;
  evidence_score: number;
  pillars_supporting: number;
  reasons: string[];
  created_at: string | null;
}

export interface TSRejections {
  cycles: number;
  totals: Record<string, number>;
  samples: { strategy_id: string; symbol: string; timeframe: string; stage: string; reason: string; detail: string }[];
  backtest_rejection_totals: Record<string, number>;
  legend: Record<string, string>;
}

export async function fetchTSSummary(): Promise<TSSummary> {
  return apiFetch("/api/trending-stocks/summary");
}
export async function fetchTSBasket(): Promise<{ basket: TSBasketRow[]; active: string[]; timeframes: string[]; benchmark: string; native_timeframes: string[]; derived_timeframes: Record<string, string> }> {
  return apiFetch("/api/trending-stocks/basket");
}
export async function addTSSymbol(symbol: string, note?: string): Promise<any> {
  return apiFetch("/api/trending-stocks/basket", {
    method: "POST",
    body: JSON.stringify({ symbol, note: note ?? null }),
  });
}
export async function setTSBasket(raw: string): Promise<any> {
  return apiFetch("/api/trending-stocks/basket/bulk", {
    method: "POST",
    body: JSON.stringify({ symbols: [], raw }),
  });
}
export async function removeTSSymbol(symbol: string): Promise<any> {
  return apiFetch(`/api/trending-stocks/basket/${encodeURIComponent(symbol)}`, { method: "DELETE" });
}
export async function releaseTSSymbol(symbol: string): Promise<any> {
  return apiFetch(`/api/trending-stocks/basket/${encodeURIComponent(symbol)}/release`, { method: "POST" });
}
export async function searchTSInstruments(q: string): Promise<{ results: any[] }> {
  return apiFetch(`/api/trending-stocks/basket/search?q=${encodeURIComponent(q)}`);
}
export async function backfillTSBars(full = true): Promise<any> {
  return apiFetch(`/api/trending-stocks/basket/backfill?full=${full}`, { method: "POST" });
}
export async function fetchTSResearch(symbol: string, timeframe = "1d"): Promise<any> {
  return apiFetch(`/api/trending-stocks/research/${encodeURIComponent(symbol)}?timeframe=${timeframe}`);
}
export async function fetchTSLibrary(p: { family?: string; timeframe?: string; style?: string; grade?: number } = {}): Promise<{ library: TSLibraryRow[]; total: number; timeframes: string[]; families: Record<string, number>; styles: Record<string, number>; strategy_count: number; min_rr: number }> {
  const q = new URLSearchParams();
  if (p.family) q.set("family", p.family);
  if (p.timeframe) q.set("timeframe", p.timeframe);
  if (p.style) q.set("style", p.style);
  if (p.grade !== undefined) q.set("grade", String(p.grade));
  const s = q.toString();
  return apiFetch(`/api/trending-stocks/library${s ? `?${s}` : ""}`);
}
export async function fetchTSRecipes(): Promise<{ recipes: any[]; count: number; excluded: { key: string; why: string }[]; note: string }> {
  return apiFetch("/api/trending-stocks/recipes");
}
export async function fetchTSStrategy(id: string): Promise<any> {
  return apiFetch(`/api/trending-stocks/strategy/${encodeURIComponent(id)}`);
}
export async function fetchTSPositions(status?: string): Promise<{ positions: TSPosition[]; open: TSPosition[]; closed: TSPosition[] }> {
  return apiFetch(`/api/trending-stocks/positions${status ? `?status=${status}` : ""}`);
}
export async function fetchTSSignals(limit = 120): Promise<TSSignal[]> {
  const r = await apiFetch(`/api/trending-stocks/signals?limit=${limit}`);
  return r.signals ?? [];
}
export async function fetchTSRejections(cycles = 20): Promise<TSRejections> {
  return apiFetch(`/api/trending-stocks/rejections?cycles=${cycles}`);
}
export async function runTSBacktest(): Promise<any> {
  return apiFetch("/api/trending-stocks/backtest", { method: "POST", body: JSON.stringify({}) });
}
export async function runTSValidation(): Promise<any> {
  return apiFetch("/api/trending-stocks/validate", { method: "POST", body: JSON.stringify({}) });
}
export async function runTSCycle(): Promise<{ opened: number; managed: number; closed: number; notes: string[] }> {
  return apiFetch("/api/trending-stocks/run", { method: "POST" });
}

// ── Stock Screener: volume, delivery and the paper desk ───────────────────────────

export interface ScreenerTarget {
  target: number | null;
  upside_pct: number | null;
  method: string;
  strength: "strong" | "moderate" | "weak" | "none";
  note: string | null;
}

export interface ScreenerVolumeRow {
  symbol: string; name: string | null; sector: string; ltp: number;
  return_pct: number | null;
  volume_ratio: number; volume: number; volume_baseline: number;
  turnover: number | null;
  delivery_pct: number | null; delivery_avg: number | null; delivery_ratio: number | null;
  trades: number | null;
  state: string; state_label: string; state_text: string;
  price_confirms: boolean;
  delivery_conflict: string | null;
  sector_return_pct: number | null;
  reasons: string[];
  target: ScreenerTarget;
  patterns: { pattern: string; state: string; timeframe: string }[];
}

export interface ScreenerVolumeBoard {
  index: string; label: string; window: string; window_label: string; sessions: number;
  count: number; min_volume_ratio: number;
  by_state: Record<string, number>;
  states: { key: string; label: string; text: string }[];
  delivery_available: boolean; delivery_note: string;
  rows: ScreenerVolumeRow[];
}

export interface ScreenerPaperFamily {
  family: string; label: string; product: string; rank: number;
  trades: number; wins: number; losses: number; win_rate: number | null;
  net_pnl: number; gross_pnl: number; fees: number;
  profit_factor: number | null; expectancy: number | null; avg_r: number | null;
  best: number; worst: number;
  open_positions: number; capital: number; equity: number; roi_pct: number;
}

export interface ScreenerPaperSummary {
  families: ScreenerPaperFamily[];
  ranked: string[];
  total_capital: number; total_net_pnl: number; total_trades: number; total_fees: number;
  per_trade_capital: number; max_open_per_family: number;
  note: string;
  enabled: boolean; squareoff: string;
  last_cycle: string | null; last_opened: number | null; last_closed: number | null;
  max_hold_days: Record<string, number>;
}

export interface ScreenerPaperPosition {
  position_id: string; family: string; symbol: string; name: string | null;
  sector: string | null;
  entry: number; stop: number; target: number; qty: number; capital: number;
  product: string; opened_on: string; opened_at?: string;
  signal_reason: string | null; pattern: string | null;
  net_rr_at_entry: number | null;
  ltp?: number | null;
  unrealised_gross?: number; unrealised_net?: number;
  return_pct?: number; to_target_pct?: number; to_stop_pct?: number;
  exit?: number; exit_reason?: string; closed_on?: string;
  gross_pnl?: number; fees?: number; net_pnl?: number; r_multiple?: number;
}

export interface ScreenerPaperPositions {
  status: string; count: number; rows: ScreenerPaperPosition[];
}

export interface ScreenerDeliveryStatus {
  days_stored: number; latest_date: string | null; symbols_latest: number;
  last_error: string | null; source: string; note: string;
}

export async function fetchScreenerVolume(
  window: string, index?: string, state?: string, limit = 60,
): Promise<ScreenerVolumeBoard> {
  return apiFetch("/api/screener/volume" + screenerQs({ window, index, state, limit }));
}
export async function fetchScreenerPaperSummary(): Promise<ScreenerPaperSummary> {
  return apiFetch("/api/screener/paper/summary");
}
export async function fetchScreenerPaperPositions(
  status = "OPEN", family?: string, limit = 200,
): Promise<ScreenerPaperPositions> {
  return apiFetch("/api/screener/paper/positions" + screenerQs({ status, family, limit }));
}
export async function runScreenerPaperCycle(index?: string): Promise<Record<string, unknown>> {
  return apiFetch("/api/screener/paper/run" + screenerQs({ index }), { method: "POST" });
}
export async function fetchScreenerDelivery(): Promise<ScreenerDeliveryStatus> {
  return apiFetch("/api/screener/delivery");
}
export async function backfillScreenerDelivery(days = 30): Promise<Record<string, unknown>> {
  return apiFetch("/api/screener/delivery/backfill" + screenerQs({ days }), { method: "POST" });
}
export interface ChartinkRow {
  symbol: string; name: string;
  close: number | null; change_pct: number | null; volume: number | null;
}
export interface ChartinkResult {
  ok: boolean;
  rows: ChartinkRow[];
  /** Indices and ETFs the scan matched, removed from `rows`. Returned rather than dropped
   *  silently so a shrinking row count is explained. */
  excluded?: (ChartinkRow & { why: string })[];
  excluded_count?: number;
  error: string | null;
  label?: string; why_not_local?: string;
  slug?: string; url?: string; name?: string; description?: string;
  /** The scan's own clause. Shown, not hidden — a name is not a definition. */
  clause?: string;
  delayed?: boolean;
  behind_mins?: number | null;
  warning?: string;
  fetched_at?: number;
  source?: string;
}
export async function fetchScreenerChartink(scan: string): Promise<ChartinkResult> {
  return apiFetch("/api/screener/chartink" + screenerQs({ scan }));
}
/** Run ANY public Chartink screener. Takes a slug or a full chartink.com URL. */
export async function fetchScreenerChartinkNamed(
  slug: string, fresh = false,
): Promise<ChartinkResult> {
  return apiFetch("/api/screener/chartink/named" + screenerQs({ slug, fresh }));
}

// --- Stock Analysis: ask about named stocks -----------------------------------
// `bias` and `action` are separate on purpose. Where the chart points and whether to buy
// today are different questions; a stock can be in a clean uptrend and still be a poor
// purchase because it is extended or cannot be exited.

export interface AnalysisPillar {
  key: string;
  score: number;
  verdict: "strong" | "ok" | "weak" | "bad" | "unknown";
  note: string;
}
export interface AnalysisRow {
  symbol: string;
  name?: string | null;
  analysed: boolean;
  note?: string;
  screens: string[];
  market_cap_cr: number | null;
  ltp?: number;
  sessions?: number;
  as_of?: string;
  verdict?: {
    score: number; chart_score: number;
    bias: "Bullish" | "Neutral" | "Bearish";
    action: "Buy" | "Watch" | "Avoid";
    action_why: string;
  };
  pillars?: Record<string, AnalysisPillar>;
  returns?: Record<string, number | null>;
  levels?: Record<string, number | null>;
  delivery?: { delivery_pct?: number; delivery_avg?: number; delivery_ratio?: number } | null;
  gate?: { checks: AthGateCheck[]; summary: string } | null;
  patterns?: {
    key: string; label: string; family: string | null; timeframe: string | null;
    state: string; direction: string;
    target?: number; stoploss?: number; reward_risk?: number | null;
  }[];
  next_target?: {
    target: number | null; upside_pct: number | null;
    method: string; strength: string; note?: string;
  } | null;
  plan?: {
    entry: number; stop: number; target: number;
    stop_pct: number; target_pct: number; horizon: string;
    exit_rule: string; basis: string;
    quantity?: number; net_target?: number; net_stop?: number;
    reward_risk?: number | null;
  } | null;
  reasons?: { code: string; tier: number; text: string }[];
}
export interface AnalysisResult {
  count: number;
  analysed: number;
  rows: AnalysisRow[];
  fetch_note?: string | null;
  generated_at?: string;
  sources?: Record<string, string>;
  note?: string;
  error?: string;
}

export async function analyseStocks(
  symbols: string, fresh = false,
): Promise<AnalysisResult> {
  return apiFetch("/api/screener/analyse", {
    method: "POST", body: JSON.stringify({ symbols, fresh }),
  });
}

// --- Analysed Stocks: the all-time-high sweep --------------------------------

export interface AthUniverseRowFull extends AnalysisRow {
  nets: string[];
  from_own_register: boolean;
  stored_ath: number | null;
  stored_ath_date: string | null;
  history_sessions: number | null;
  /** null when there is no stored all-time high to check against — never treated as false. */
  ath_confirmed: boolean | null;
  /** Three real states plus unverified. "At an all-time high", "1% away from one" and
   *  "at a 4-year high while the record still stands 40% above" are different facts. */
  ath_grade: "all_time" | "near_ath" | "multi_year" | "unverified";
  pct_from_ath: number | null;
  ath_basis: string;
}
export interface AthUniverseSnapshot {
  state: "ready" | "running" | "failed" | "never built";
  step?: string;
  progress?: number;
  started_at?: string;
  finished_at?: string;
  seconds?: number;
  count?: number;
  candidates?: number;
  confirmed_ath?: number;
  near_ath?: number;
  buyable?: number;
  rows?: AthUniverseRowFull[];
  note?: string;
  coverage?: {
    chartink_nets: Record<string, { label: string; rows: number; excluded?: number; error: string | null }>;
    chartink_symbols: number;
    own_register_hits: number;
    register_size: number;
    register?: AthRegisterCoverage;
    seeded: { needed: number; seeded: number; left: number; error?: string };
    excluded_non_equity: number;
    excluded?: { symbol: string; name: string; why: string }[];
    blind_spot: string;
  };
}

export interface AthRegisterCoverage {
  universe: number;
  seeded: number;
  missing: number;
  missing_resolvable?: number;
  missing_need_lookup?: number;
  pct?: number;
  note: string;
}
export interface AthExpandStatus {
  state: "ready" | "running" | "failed" | "never run";
  step?: string; progress?: number;
  total?: number; done?: number;
  resolved?: number; seeded?: number; failed?: number;
  seconds?: number; finished_at?: string;
}
export async function fetchAthRegister(): Promise<{
  coverage: AthRegisterCoverage; expand: AthExpandStatus;
}> {
  return apiFetch("/api/screener/ath-universe/register");
}
export async function expandAthRegister(limit?: number): Promise<{
  started: boolean; reason?: string; note?: string;
}> {
  return apiFetch("/api/screener/ath-universe/expand" + (limit ? `?limit=${limit}` : ""),
                  { method: "POST" });
}

export async function fetchAthUniverseSweep(): Promise<AthUniverseSnapshot> {
  return apiFetch("/api/screener/ath-universe");
}
export async function fetchAthUniverseStatus(): Promise<AthUniverseSnapshot> {
  return apiFetch("/api/screener/ath-universe/status");
}
export async function buildAthUniverse(): Promise<{ started: boolean; reason?: string }> {
  return apiFetch("/api/screener/ath-universe/build", { method: "POST" });
}

// --- Instrument search: ranked, typo-tolerant, enriched, app-wide ------------
// Replaces a Mongo $regex built from raw user input, which 500'd on a query of "(" and
// ranked RPOWER above RELIANCE for "reliance".

export interface SearchTradability {
  ok: boolean;
  verdict: "tradable" | "blocked";
  blockers: string[];
  warnings: string[];
}

export interface SearchResult {
  symbol: string;
  name: string;
  broker_name: string;
  sector: string | null;
  indices: string[];
  index_label: string | null;
  security_id: string | null;
  exchange_segment: string;
  angel_token: string | null;
  asset_class: string;
  lot_size: number;
  tradable: boolean;
  ltp: number | null;
  returns: { "1d": number | null; "1w": number | null; "1m": number | null; "6m": number | null } | null;
  turnover: number | null;
  volume_x: number | null;
  pct_from_ath: number | null;
  pct_from_52w_high: number | null;
  up_streak: number | null;
  breakout: string | null;
  sessions: number | null;
  all_time_high: number | null;
  all_time_high_date: string | null;
  above_sma: { "20": boolean | null; "50": boolean | null; "200": boolean | null } | null;
  coverage: string[];
  coverage_note: string;
  tradability: SearchTradability;
  as_of: string | null;
  demotion?: number;
  matched_on?: string;
  why?: string[];
  score?: number;
}

export interface SearchResponse {
  mode: "lexical" | "natural-language" | "trending";
  query?: string;
  results: SearchResult[];
  count: number;
  universe?: number;
  as_of: string | null;
  note?: string;
  sort?: string;
  nl_available?: boolean;
  nl_note?: string;
  filter?: Record<string, any>;
  filter_english?: string;
}

export interface SearchStats {
  instruments: number;
  tradable: number;
  with_clean_name: number;
  with_daily_bars: number;
  aliases: number;
  aliases_dropped: string[];
  trending_pool: number;
  snapshot: { symbols: number; date: string | null; cached: boolean };
  natural_language: {
    enabled: boolean;
    provider: string | null;
    model: string | null;
    configured_providers: string[];
    note: string;
  };
}

export async function searchInstruments(
  q: string,
  opts: { limit?: number; includeUntradable?: boolean } = {},
): Promise<SearchResponse> {
  const p = new URLSearchParams({ q, limit: String(opts.limit ?? 12) });
  if (opts.includeUntradable) p.set("include_untradable", "true");
  return apiFetch(`/api/search/instruments?${p.toString()}`);
}

export async function trendingInstruments(limit = 12, sort: "1d" | "1w" | "1m" | "6m" = "1d"): Promise<SearchResponse> {
  return apiFetch(`/api/search/trending?limit=${limit}&sort=${sort}`);
}

export async function naturalSearch(query: string, limit = 20): Promise<SearchResponse> {
  return apiFetch("/api/search/natural", {
    method: "POST",
    body: JSON.stringify({ query, limit }),
  });
}

export async function resolveInstrument(symbol: string): Promise<SearchResult | { error: string }> {
  return apiFetch(`/api/search/resolve/${encodeURIComponent(symbol)}`);
}

export async function searchStats(): Promise<SearchStats> {
  return apiFetch("/api/search/stats");
}

export async function reindexSearch(): Promise<{ rebuilt: boolean; instruments: number }> {
  return apiFetch("/api/search/reindex", { method: "POST" });
}

// ── Paper Broker: Stock Paper Trading + F&O Paper Trading ─────────────────────────
// One account, two segments. Real Angel One prices, paper money, no order ever reaches
// a broker.

export interface PTContract {
  symbol: string; name: string; security_id: string | null;
  angel_token: string | null; exchange: string; exchange_segment: string | null;
  asset_class: string | null; kind: "EQUITY" | "OPTION" | "FUTURE";
  lot_size: number; tick_size: number;
  expiry: string | null; strike: number | null;
  option_type: string | null; underlying: string | null;
}

export interface PTFunds {
  account_id: string; name: string;
  opening_balance: number; realised_pnl: number; charges_paid: number;
  blocked_margin: number; available_margin: number;
  unrealised_pnl: number; equity: number; net_pnl: number; roi_pct: number;
}

export interface PTOrder {
  order_id: string; account_id: string; segment: string;
  contract: PTContract; symbol: string; token: string;
  transaction_type: "BUY" | "SELL"; quantity: number; filled_quantity: number;
  order_type: string; product: string; validity: string;
  price: number | null; trigger_price: number | null;
  status: string; status_message: string | null;
  fill_price?: number; placed_at: string; filled_at?: string;
  margin_blocked: number;
}

export interface PTPosition {
  position_id: string; segment: string; symbol: string; token: string;
  contract: PTContract; kind: string; underlying: string | null;
  option_type: string | null; strike: number | null; expiry: string | null;
  product: string; quantity: number; avg_price: number; ltp: number | null;
  margin_blocked: number; realised_pnl: number; unrealised_pnl: number;
  pnl_pct: number | null; side: "LONG" | "SHORT"; value: number;
  opened_on: string;
  mtf?: {
    funded_amount: number; leverage: number | null; leverage_source: string | null;
    days_held: number; interest_accrued: number; daily_interest: number;
    pledge_charge: number; estimated_exit_cost: number;
  };
  pnl_after_funding?: number;
}

export interface PTTrade {
  trade_id: string; order_id: string; segment: string; symbol: string;
  transaction_type: string; quantity: number; price: number; product: string;
  order_type: string; value: number; realised_pnl: number; charges: number;
  traded_at: string; traded_on: string;
}

export interface PTHolding {
  symbol: string; token: string; contract: PTContract;
  quantity: number; avg_price: number; ltp: number | null;
  invested: number; current_value: number | null;
  pnl: number | null; pnl_pct: number | null; settled_on: string;
}

export interface PTLedgerEntry {
  entry_id: string; kind: string; amount: number; note: string;
  ref: string | null; date: string; ts: string;
}

export interface PTConfig {
  segments: { key: string; label: string; products: string[] }[];
  order_types: string[];
  validities: string[];
  product_help: Record<string, string>;
  order_type_help: Record<string, string>;
  squareoff: Record<string, string>;
  market_open: boolean;
  engine: Record<string, unknown>;
  fills_note: string;
  mtf: {
    leverage_tiers: { tier: string; leverage: number; margin_pct: number }[];
    default_leverage: number; default_margin_pct: number;
    daily_rate_pct: number; annual_rate_pct: number;
    pledge_charge: number; unpledge_charge: number;
    live_leverage_enabled: boolean; provenance: string; mechanics: string;
  };
}

export interface PTDashboard {
  funds: PTFunds;
  positions: { count: number; unrealised_pnl: number; day_realised: number };
  holdings: { count: number; pnl: number | null; invested: number | null; value: number | null };
  open_orders: number;
  engine: Record<string, unknown>;
}

export interface PTMargin {
  margin: number; method: string; basis: string;
  span: number | null; exposure: number | null; iv?: number | null;
  price: number; contract: PTContract;
  available_margin: number; sufficient: boolean;
  mtf?: {
    leverage: number; margin_pct: number; source: string; tier: string | null;
    funded_amount: number; daily_interest: number;
    daily_rate_pct: number; annual_rate_pct: number;
    pledge_charge: number; unpledge_charge: number;
  };
}

export interface PTChainLeg {
  contract: PTContract; ltp: number | null; oi: number | null;
  volume: number | null; close: number | null; change_pct: number | null;
}

export interface PTChain {
  symbol: string; expiry: string; atm_strike: number | null; lot_size: number;
  count: number; priced: number;
  strikes: { strike: number; CE: PTChainLeg | null; PE: PTChainLeg | null }[];
}

export interface PTContractRef {
  segment: string; symbol: string;
  expiry?: string | null; strike?: number | null;
  option_type?: string | null; instrument_kind?: string;
}

export async function fetchPTConfig(): Promise<PTConfig> {
  return apiFetch("/api/paper-trading/config");
}
export async function fetchPTAccounts(): Promise<{ accounts: { account_id: string; name: string; opening_balance: number }[] }> {
  return apiFetch("/api/paper-trading/accounts");
}
export async function createPTAccount(name: string, capital?: number) {
  return apiFetch("/api/paper-trading/accounts", {
    method: "POST", body: JSON.stringify({ name, capital }),
  });
}
export async function resetPTAccount(accountId: string) {
  return apiFetch(`/api/paper-trading/accounts/${accountId}/reset?confirm=true`, { method: "POST" });
}
export async function fetchPTDashboard(accountId?: string, segment?: string): Promise<PTDashboard> {
  return apiFetch("/api/paper-trading/dashboard" + screenerQs({ account_id: accountId, segment }));
}
export async function searchPTScrips(q: string, segment: string): Promise<{ results: PTContract[] }> {
  return apiFetch("/api/paper-trading/search" + screenerQs({ q, segment }));
}
export async function fetchPTMargin(body: PTContractRef & {
  account_id?: string; transaction_type: string; quantity: number; product: string; price?: number | null;
}): Promise<PTMargin> {
  return apiFetch("/api/paper-trading/margin", { method: "POST", body: JSON.stringify(body) });
}
export async function placePTOrder(body: PTContractRef & {
  account_id?: string; transaction_type: string; quantity: number;
  order_type: string; product: string; validity: string;
  price?: number | null; trigger_price?: number | null;
}): Promise<PTOrder> {
  return apiFetch("/api/paper-trading/orders", { method: "POST", body: JSON.stringify(body) });
}
export async function modifyPTOrder(orderId: string, body: {
  account_id?: string; quantity?: number; price?: number; trigger_price?: number; order_type?: string;
}): Promise<PTOrder> {
  return apiFetch(`/api/paper-trading/orders/${orderId}`, { method: "PUT", body: JSON.stringify(body) });
}
export async function cancelPTOrder(orderId: string, accountId?: string) {
  return apiFetch(`/api/paper-trading/orders/${orderId}` + screenerQs({ account_id: accountId }),
    { method: "DELETE" });
}
export async function fetchPTOrders(accountId?: string, segment?: string, status?: string): Promise<{ count: number; rows: PTOrder[]; open: number }> {
  return apiFetch("/api/paper-trading/orders" + screenerQs({ account_id: accountId, segment, status }));
}
export async function fetchPTTrades(accountId?: string, segment?: string): Promise<{ count: number; rows: PTTrade[]; realised_pnl: number; charges: number }> {
  return apiFetch("/api/paper-trading/trades" + screenerQs({ account_id: accountId, segment }));
}
export async function fetchPTPositions(accountId?: string, segment?: string): Promise<{ count: number; rows: PTPosition[]; unrealised_pnl: number; day_realised: number }> {
  return apiFetch("/api/paper-trading/positions" + screenerQs({ account_id: accountId, segment }));
}
export async function exitPTPosition(positionId: string, accountId?: string, quantity?: number) {
  return apiFetch(`/api/paper-trading/positions/${positionId}/exit` +
    screenerQs({ account_id: accountId, quantity }), { method: "POST" });
}
export async function fetchPTHoldings(accountId?: string): Promise<{ count: number; rows: PTHolding[]; invested: number; current_value: number; pnl: number }> {
  return apiFetch("/api/paper-trading/holdings" + screenerQs({ account_id: accountId }));
}
export async function fetchPTLedger(accountId?: string): Promise<{ count: number; rows: PTLedgerEntry[] }> {
  return apiFetch("/api/paper-trading/ledger" + screenerQs({ account_id: accountId }));
}
export async function fetchPTUnderlyings(): Promise<{ underlyings: { symbol: string; lot_size: number; has_options: boolean; has_futures: boolean }[] }> {
  return apiFetch("/api/paper-trading/fno/underlyings");
}
export async function fetchPTExpiries(symbol: string, kind = "OPTION"): Promise<{ expiries: string[] }> {
  return apiFetch("/api/paper-trading/fno/expiries" + screenerQs({ symbol, kind }));
}
export async function fetchPTChain(symbol: string, expiry: string): Promise<PTChain> {
  return apiFetch("/api/paper-trading/fno/chain" + screenerQs({ symbol, expiry }));
}
export async function runPTTick(): Promise<Record<string, number>> {
  return apiFetch("/api/paper-trading/tick", { method: "POST" });
}

// ── Paper broker: MTF and closed-position cost breakdown ──────────────────────────

export interface PTMtfDetail {
  leverage: number; margin_pct: number; source: string; tier: string | null;
  funded_amount: number; daily_interest: number;
  daily_rate_pct: number; annual_rate_pct: number;
  pledge_charge: number; unpledge_charge: number;
}

export interface PTMtfRateCard {
  leverage_tiers: { tier: string; leverage: number; margin_pct: number }[];
  default_leverage: number; default_margin_pct: number;
  daily_rate_pct: number; annual_rate_pct: number;
  pledge_charge: number; unpledge_charge: number;
  live_leverage_enabled: boolean;
  provenance: string;
  mechanics: string;
}

/** The MTF cost carried on a position while it is open. */
export interface PTPositionMtf {
  funded_amount: number; leverage: number | null; leverage_source: string | null;
  days_held: number; interest_accrued: number; daily_interest: number;
  pledge_charge: number; estimated_exit_cost: number;
}

/** Everything a closed trade cost, itemised. */
export interface PTChargeBreakdown {
  gross_pnl: number;
  statutory: Record<string, number | string> | null;
  mtf: {
    days_held: number; funded_amount: number;
    daily_rate_pct: number; annual_rate_pct: number;
    interest: number; pledge_charge: number; unpledge_charge: number;
    leverage: number | null; leverage_source: string | null; total: number;
  } | null;
  total_charges: number;
  net_pnl: number;
}

export interface PTClosedTrade extends PTTrade {
  charge_breakdown: PTChargeBreakdown | null;
}

export interface PTClosedBook {
  count: number;
  rows: PTClosedTrade[];
  totals: {
    gross_pnl: number; net_pnl: number; total_charges: number;
    statutory_charges: number; mtf_charges: number;
    mtf_interest: number; pledge_charges: number;
  };
  note: string;
}

export async function fetchPTClosed(accountId?: string, segment?: string): Promise<PTClosedBook> {
  return apiFetch("/api/paper-trading/closed" + screenerQs({ account_id: accountId, segment }));
}
export async function fetchPTMtfRateCard(): Promise<PTMtfRateCard> {
  return apiFetch("/api/paper-trading/mtf/rate-card");
}
export async function accruePTMtf(): Promise<{ accrued: number }> {
  return apiFetch("/api/paper-trading/mtf/accrue", { method: "POST" });
}

// ── F&O multi-leg strategy builder ────────────────────────────────────────────────

export interface StrategyPreset {
  key: string; name: string; outlook: string; why: string;
  legs: { offset: number; type: string; side: string; lots: number }[];
}

export interface StrategyLeg {
  strike: number; option_type: string; side: string; lots: number;
}

export interface StrategyAnalysis {
  ok: boolean;
  spot: number; expiry: string | null; days_to_expiry: number; lot_size: number;
  points: { spot: number; pnl: number }[];
  breakevens: number[];
  max_profit: number | null; max_loss: number | null;
  unlimited_profit: boolean; unlimited_loss: boolean; downside_open: boolean;
  scan_range: { low: number; high: number; pct: number };
  net_premium: number; is_debit: boolean;
  greeks: { delta: number; gamma: number; theta: number; vega: number; rho: number };
  per_leg: {
    strike: number; option_type: string; side: string; quantity: number;
    premium: number; label: string; iv: number | null;
    greeks: Record<string, number> | null; note?: string;
  }[];
  unpriced_legs: number;
  margin: { total: number; span: number; exposure: number };
  risk_note: string;
  symbol: string;
  legs: { strike: number; option_type: string; side: string; lots: number; quantity: number; premium: number }[];
  unpriced_strikes: string[];
  available_margin: number;
  affordable: boolean;
}

export async function fetchStrategyPresets(): Promise<{ presets: StrategyPreset[] }> {
  return apiFetch("/api/paper-trading/fno/strategy/presets");
}
export async function analyseStrategy(body: {
  symbol: string; expiry: string; legs: StrategyLeg[]; account_id?: string;
}): Promise<StrategyAnalysis> {
  return apiFetch("/api/paper-trading/fno/strategy/analyse", {
    method: "POST", body: JSON.stringify(body),
  });
}
export async function executeStrategy(body: {
  symbol: string; expiry: string; legs: StrategyLeg[]; account_id?: string;
}): Promise<{
  placed: { leg: string; status: string; message: string | null; fill: number | null }[];
  failed: { leg: string; status: string; message: string | null }[];
  complete: boolean; warning: string | null;
}> {
  return apiFetch("/api/paper-trading/fno/strategy/execute", {
    method: "POST", body: JSON.stringify(body),
  });
}

// ── All Time High Trading ─────────────────────────────────────────────────────────

export interface AthSummary {
  mode: string; enabled: boolean;
  desk_capital: number; per_position: number;
  stop_pct: number; target_pct: number; market_cap_floor_cr: number;
  deployed: number; available: number;
  realised_pnl: number; fees_paid: number; unrealised_pnl: number;
  equity: number; roi_pct: number;
  open_positions: number; max_positions: number;
  closed_trades: number; wins: number; win_rate: number | null;
  target_hits: number; stop_hits: number;
  last_cycle: string | null; last_scanned: number | null;
  market_open: boolean; exit_note: string;
}

export interface AthCoverage {
  mode: string; watchlist_size: number; enforce_market_cap: boolean; mode_note: string;
  market_cap_floor_cr: number; above_market_cap: number;
  angel_quotable: number; with_all_time_high: number;
  tradable: number; missing_highs: number; min_sessions: number;
  note: string; exchange_note: string;
}

export interface AthPosition {
  position_id: string; symbol: string; name: string | null;
  entry: number; quantity: number; cost: number;
  stop: number; target: number; ltp: number | null;
  unrealised_pnl: number; return_pct?: number;
  to_target_pct?: number; to_stop_pct?: number;
  market_cap_cr: number | null; ath_broken: number | null;
  previous_ath_date: string | null; days_held: number; opened_on: string;
  entry_reason?: string | null;
  /** Real-money buy conviction, scored at the CURRENT price. Null if it could not be
   *  computed — which is shown as such, never as a zero. */
  conviction?: AthConviction | null;
  gate_now?: { passed: boolean; summary: string; checks: AthGateCheck[] } | null;
}

export interface AthConviction {
  /** 0-100. NOT a probability of profit — see the label copy on the page. */
  pct: number;
  label: "Strong" | "Good" | "Fair" | "Weak" | "Avoid" | "Unknown";
  headline: string;
  /** One sentence on delivery against the stock's own average, plus median turnover. */
  volume: string;
  confidence: "high" | "medium" | "low" | "none";
  unknown_checks?: number;
  capped: boolean;
  cap_reason: string | null;
}

export interface AthTrade {
  position_id: string; symbol: string; entry: number; exit: number;
  quantity: number; exit_reason: string; return_pct: number;
  gross_pnl: number; fees: number; net_pnl: number;
  days_held: number; opened_on: string; closed_on: string;
}

export interface AthSignal {
  signal_id: string; symbol: string; ltp: number;
  all_time_high: number | null; previous_ath_date: string | null;
  market_cap_cr: number | null; taken: boolean; why: string;
  date: string; ts: string;
}

export interface AthNearHigh {
  symbol: string; name: string; market_cap_cr: number;
  all_time_high: number; ath_date: string | null;
  sessions: number; ltp: number; pct_from_ath: number;
}

export interface AthUniverseRow {
  symbol: string; name: string; market_cap_cr: number;
  all_time_high: number; ath_date: string | null; sessions: number;
}

export async function fetchAthSummary(): Promise<AthSummary> {
  return apiFetch("/api/ath/summary");
}
export async function fetchAthCoverage(): Promise<AthCoverage> {
  return apiFetch("/api/ath/coverage");
}
export async function fetchAthPositions(): Promise<{ count: number; rows: AthPosition[]; unrealised_pnl: number }> {
  return apiFetch("/api/ath/positions");
}
export async function fetchAthTrades(limit = 300): Promise<{ count: number; rows: AthTrade[]; net_pnl: number; fees: number; avg_days_held: number | null }> {
  return apiFetch("/api/ath/trades" + screenerQs({ limit }));
}
export async function fetchAthSignals(limit = 200): Promise<{ count: number; rows: AthSignal[] }> {
  return apiFetch("/api/ath/signals" + screenerQs({ limit }));
}
export async function fetchAthNearHighs(limit = 50): Promise<{ count: number; rows: AthNearHigh[]; universe?: number; priced?: number }> {
  return apiFetch("/api/ath/near-highs" + screenerQs({ limit }));
}
export async function fetchAthUniverse(limit = 500): Promise<{ count: number; rows: AthUniverseRow[] }> {
  return apiFetch("/api/ath/universe" + screenerQs({ limit }));
}
export async function runAthCycle(): Promise<Record<string, unknown>> {
  return apiFetch("/api/ath/run", { method: "POST" });
}
export async function seedAthHighs(limit = 120): Promise<Record<string, unknown>> {
  return apiFetch("/api/ath/seed-highs" + screenerQs({ limit }), { method: "POST" });
}

// ── ATH hand-built watchlist ──────────────────────────────────────────────────────

export interface AthMappedSymbol {
  symbol: string; name: string; status: string; note: string; tradable: boolean;
  market_cap: number | null; market_cap_cr: number | null;
  all_time_high: number | null; ath_date: string | null; sessions: number | null;
}

export interface AthWatchlist {
  symbols: string[];
  mode: string;
  enforce_market_cap: boolean;
  /** The 250-session minimum. Waivable for hand-picked names, on for the screen. */
  enforce_history?: boolean;
  updated_at: string | null;
  count: number;
  tradable: number;
  rows: AthMappedSymbol[];
}

export async function mapAthSymbols(symbols: string | string[]): Promise<{
  count: number; tradable: number; rows: AthMappedSymbol[];
  enforce_market_cap?: boolean; enforce_history?: boolean;
}> {
  return apiFetch("/api/ath/watchlist/map", {
    method: "POST", body: JSON.stringify({ symbols }),
  });
}
export async function fetchAthWatchlist(): Promise<AthWatchlist> {
  return apiFetch("/api/ath/watchlist");
}
export async function saveAthWatchlist(
  symbols: string[], mode?: string, enforce_market_cap?: boolean,
  enforce_history?: boolean,
): Promise<AthWatchlist> {
  return apiFetch("/api/ath/watchlist", {
    method: "POST",
    body: JSON.stringify({ symbols, mode, enforce_market_cap, enforce_history }),
  });
}

export async function enterAllAthWatchlist(symbols?: string[]): Promise<{
  opened: number; already_held?: number; requested?: number;
  skipped?: { symbol: string; why: string }[];
  /** Symbols that never reached the tradable universe, each with the reason. */
  not_eligible?: { symbol: string; status: string; why: string }[];
  capital_left?: number; note?: string; reason?: string;
}> {
  return apiFetch("/api/ath/enter-all?confirm=true", {
    method: "POST", body: JSON.stringify({ symbols: symbols ?? null }),
  });
}

// --- All Time High: the pre-entry gate ---------------------------------------
// Six checks that decide whether the +-20% exit rule is even physically available on a
// given stock. Verdicts are pass / warn / fail / UNKNOWN, and unknown is never folded
// into pass: NSE is the flakiest feed here and an outage must not read as an all-clear.

export interface AthGateCheck {
  key: string;
  label: string;
  verdict: "pass" | "warn" | "fail" | "unknown";
  detail: string;
  value: number | null;
}
export interface AthGateRow {
  symbol: string;
  name: string | null;
  entry: number | null;
  ltp: number | null;
  quantity: number | null;
  unrealised_pnl: number | null;
  entry_reason: string | null;
  opened_on: string | null;
  /** The verdict stored when the position was opened, or null if it predates the gate. */
  gate_at_entry: boolean | null;
  passed: boolean;
  score: number;
  blocked: boolean;
  fail_count: number;
  warn_count: number;
  unknown_count: number;
  summary: string;
  checks: AthGateCheck[];
}
export interface AthGateReport {
  mode: "observe" | "enforce" | "off";
  thresholds: Record<string, unknown> & { note?: string };
  regime: {
    symbol: string | null; last?: number; ma?: number;
    above: boolean | null; distance_pct: number | null; sessions: number;
  };
  surveillance: {
    ok: boolean; bands: number; asm: number; gsm: number;
    errors?: Record<string, string>;
    fetched_at?: string | null; age_hours?: number | null;
    sources?: Record<string, string>;
  };
  open_scored: number;
  open_failing: number;
  open_warning: number;
  open_clean: number;
  rows: AthGateRow[];
  review: {
    buckets: Record<string, {
      trades: number; wins: number; pnl: number; win_rate: number | null;
    }>;
    graded_trades: number;
    verdict: string;
  };
}

export async function fetchAthGate(fresh = false): Promise<AthGateReport> {
  return apiFetch("/api/ath/gate" + (fresh ? "?fresh=true" : ""));
}
export async function setAthGateMode(mode: string): Promise<{ mode: string; note?: string }> {
  return apiFetch("/api/ath/gate/mode", { method: "POST", body: JSON.stringify({ mode }) });
}
export async function refreshAthNse(): Promise<Record<string, unknown>> {
  return apiFetch("/api/ath/gate/refresh-nse", { method: "POST" });
}

// --- Commodity Positions: MCX futures + options paper desk -------------------
// The commodity twin of the F&O Positions client. Priced by Angel (Dhan does not cover
// MCX) and margined locally, both of which the payloads state rather than imply.

export interface CmpAccount {
  account_id: string;
  name: string;
  initial_capital: number;
  created_at: string | null;
  /** The day per-day averages are measured from. Null on accounts made before it existed;
   *  the backend then falls back to the account's creation date. */
  roi_start_date?: string | null;
}

export interface CmpPerformance {
  start_date: string;
  as_of: string;
  days: number;
  trading_days: number;
  initial_capital: number;
  realised_in_window: number;
  unrealised_in_window: number;
  pnl_in_window: number;
  avg_per_day: number;
  avg_per_trading_day: number;
  roi_pct: number | null;
  avg_roi_pct_per_day: number | null;
  opened_in_window: number;
  closed_in_window: number;
  /** Unrealised profit on positions opened BEFORE the window — excluded from it. */
  carried_unrealised: number;
  realised_before_window: number;
  carried_note: string | null;
  note: string;
}

export interface CmpSpec {
  verified: boolean;
  lot_quantity: string;
  price_unit: string;
  multiplier: number;
  spec_source?: string;
  note?: string;
}

export interface CmpUnderlying extends CmpSpec {
  symbol: string;
  futures: number;
  options: number;
  has_options: boolean;
}

export interface CmpFuture extends CmpSpec {
  symbol: string;
  underlying: string;
  expiry: string;
  security_id: string;
  angel_token: string;
  ltp: number | null;
  tick: number;
  contract_value: number | null;
}

export interface CmpChainLeg {
  last_price: number;
  oi: number;
  volume: number;
  iv?: number | null;
  delta?: number | null;
  theta?: number | null;
  vega?: number | null;
  gamma?: number | null;
}

export interface CmpChain extends CmpSpec {
  symbol: string;
  expiry: string;
  spot: number;
  underlying_contract: string | null;
  underlying_expiry: string | null;
  days_to_expiry: number;
  strikes: { strike: number; ce: CmpChainLeg; pe: CmpChainLeg }[];
  strikes_listed: number;
  strikes_shown: number;
  pcr_oi: number | null;
  max_pain: number | null;
  source: string;
  note: string;
}

export interface CmpPosition {
  position_id: string;
  account_id: string;
  symbol: string;
  display_name: string;
  instrument_kind: "OPTION" | "FUTURE";
  underlying_symbol: string;
  instrument: Record<string, any>;
  side: "BUY" | "SELL";
  lots: number;
  quantity: number;
  entry_price: number;
  ltp: number;
  product_type: string;
  margin_used: number;
  contract_value: number;
  unrealized_pnl: number;
  realized_pnl: number;
  status: string;
  opened_at: string | null;
  closed_at: string | null;
}

export interface CmpOrder {
  order_id: string;
  display_name: string;
  instrument_kind: string;
  transaction_type: "BUY" | "SELL";
  lots: number;
  quantity: number;
  order_type: string;
  limit_price: number | null;
  product_type: string;
  status: string;
  fill_price: number | null;
  margin_used: number | null;
  contract_value?: number;
  placed_at: string | null;
}

export interface CmpSummary {
  account: CmpAccount;
  performance?: CmpPerformance;
  initial_capital: number;
  available_cash: number;
  margin_deployed: number;
  contract_exposure: number;
  realized_pnl: number;
  unrealized_pnl: number;
  equity: number;
  open_count: number;
  closed_count: number;
  open_positions: CmpPosition[];
  closed_positions: CmpPosition[];
  exchange: string;
  priced_by: string;
  note: string;
}

export interface CmpMargin {
  margin_required: number;
  span: number;
  exposure: number;
  notional_value: number;
  quantity: number;
  multiplier: number;
  scan_pct: number;
  reference_price: number;
  source: string;
  note: string;
}

export interface CmpSpecCheckRow extends CmpSpec {
  underlying: string;
  price: number;
  contract_value: number;
  plausible: boolean;
}

const cmp = "/api/commodity-positions";

export async function fetchCmpAccounts(): Promise<{ accounts: CmpAccount[] }> {
  return apiFetch(`${cmp}/accounts`);
}
export async function createCmpAccount(name: string, initial_capital?: number): Promise<CmpAccount> {
  return apiFetch(`${cmp}/accounts`, { method: "POST", body: JSON.stringify({ name, initial_capital }) });
}
export async function fetchCmpPerformance(
  id: string, start?: string,
): Promise<CmpPerformance> {
  return apiFetch(`${cmp}/accounts/${id}/performance`
    + (start ? `?start=${encodeURIComponent(start)}` : ""));
}
export async function editCmpAccount(id: string, body: { name?: string; initial_capital?: number; roi_start_date?: string }): Promise<CmpAccount> {
  return apiFetch(`${cmp}/accounts/${id}`, { method: "PATCH", body: JSON.stringify(body) });
}
export async function fetchCmpUnderlyings(): Promise<{ underlyings: CmpUnderlying[]; count: number }> {
  return apiFetch(`${cmp}/underlyings`);
}
export async function fetchCmpFutures(symbol?: string): Promise<{ contracts: CmpFuture[]; count: number; spec_check: CmpSpecCheckRow[] }> {
  return apiFetch(`${cmp}/futures${symbol ? `?symbol=${encodeURIComponent(symbol)}` : ""}`);
}
export async function fetchCmpFutureExpiries(symbol: string): Promise<{ expiries: string[] }> {
  return apiFetch(`${cmp}/futures/expiries?symbol=${encodeURIComponent(symbol)}`);
}
export async function fetchCmpOptionExpiries(symbol: string): Promise<{ expiries: string[] }> {
  return apiFetch(`${cmp}/options/expiries?symbol=${encodeURIComponent(symbol)}`);
}
export async function fetchCmpChain(symbol: string, expiry: string, around = 20): Promise<CmpChain> {
  return apiFetch(`${cmp}/options/chain?symbol=${encodeURIComponent(symbol)}&expiry=${expiry}&around=${around}`);
}
export async function fetchCmpMargin(p: {
  symbol: string; expiry: string; instrument_kind: string; transaction_type: string;
  lots: number; price: number; strike?: number; option_type?: string;
}): Promise<CmpMargin> {
  const q = new URLSearchParams({
    symbol: p.symbol, expiry: p.expiry, instrument_kind: p.instrument_kind,
    transaction_type: p.transaction_type, lots: String(p.lots), price: String(p.price),
  });
  if (p.strike !== undefined) q.set("strike", String(p.strike));
  if (p.option_type) q.set("option_type", p.option_type);
  return apiFetch(`${cmp}/margin?${q.toString()}`);
}
export async function placeCmpOrder(body: {
  account_id: string; instrument_kind: string; symbol: string; expiry: string;
  transaction_type: string; lots: number; order_type: string; product_type: string;
  strike?: number | null; option_type?: string | null; limit_price?: number;
}): Promise<CmpOrder> {
  return apiFetch(`${cmp}/orders`, { method: "POST", body: JSON.stringify(body) });
}
export async function fetchCmpOrders(account_id: string): Promise<{ orders: CmpOrder[] }> {
  return apiFetch(`${cmp}/orders?account_id=${encodeURIComponent(account_id)}`);
}
export async function fetchCmpPositions(account_id: string): Promise<CmpSummary> {
  return apiFetch(`${cmp}/positions?account_id=${encodeURIComponent(account_id)}`);
}
export async function exitCmpPosition(position_id: string, account_id: string, lots?: number): Promise<CmpOrder> {
  return apiFetch(`${cmp}/positions/${position_id}/exit`, {
    method: "POST", body: JSON.stringify({ account_id, lots: lots ?? null }),
  });
}
export interface CmpReopenAtm {
  closed: { contract: string; strike: number; lots: number; side: string;
            exit_price: number; realized: number };
  opened: { contract: string; strike: number; lots: number; side: string;
            entry_price: number };
  future: number;
  strike_moved: number;
  margin_delta: number;
  net_premium: number;
  note: string;
}

/** Close a position and re-open the same contract at today's at-the-money strike.
 *  Same underlying, expiry, option type, side and lots — only the strike moves. */
export async function reopenCmpAtm(position_id: string, account_id: string): Promise<CmpReopenAtm> {
  return apiFetch(
    `${cmp}/positions/${position_id}/reopen-atm?account_id=${encodeURIComponent(account_id)}`,
    { method: "POST" });
}

export interface CmpReopenAtmAll {
  rolled: {
    underlying: string; expiry: string; future: number; legs: number;
    moves: { contract: string; from_strike: number; to_strike: number;
             lots: number; side: string; option_type: string }[];
    closed: { contract: string; exit_price: number }[];
    net_premium: number; margin_added: number;
  }[];
  failed: { underlying: string; expiry: string; reason: string;
            closed: { contract: string; exit_price: number }[] }[];
  skipped: string[];
  legs_rolled: number;
  strikes_changed: number;
  realized: number;
  margin_delta: number;
  note: string;
}

/** Roll open option legs to their at-the-money strike.
 *  Pass `position_ids` to roll only those; omit it to roll the whole book. */
export async function reopenCmpAtmAll(
  account_id: string, position_ids?: string[],
): Promise<CmpReopenAtmAll> {
  return apiFetch(
    `${cmp}/positions/reopen-atm-all?account_id=${encodeURIComponent(account_id)}`,
    { method: "POST", body: JSON.stringify({ position_ids: position_ids ?? null }) });
}

export async function resetCmpAccount(account_id: string): Promise<any> {
  return apiFetch(`${cmp}/reset?account_id=${encodeURIComponent(account_id)}`, { method: "POST" });
}
export async function deleteCmpAccount(account_id: string): Promise<{
  deleted: string; closed_positions_removed: number; orders_removed: number;
}> {
  return apiFetch(`${cmp}/accounts/${encodeURIComponent(account_id)}`, { method: "DELETE" });
}
export async function fetchCmpSpecCheck(): Promise<{ spec_check: CmpSpecCheckRow[]; all_plausible: boolean; note: string }> {
  return apiFetch(`${cmp}/spec-check`);
}
export async function syncCmpInstruments(): Promise<any> {
  return apiFetch(`${cmp}/sync-instruments`, { method: "POST" });
}

// --- Commodity basket orders --------------------------------------------------
// Buy/Sell on a contract adds a LEG; nothing is filled until the basket is placed. The
// estimate is re-run on every change so the capital shown is the number the execute gate
// will actually use.

export interface CmpBasketLeg {
  instrument_kind: "OPTION" | "FUTURE";
  symbol: string;
  expiry: string;
  transaction_type: "BUY" | "SELL";
  lots: number;
  strike?: number | null;
  option_type?: "CE" | "PE" | null;
}

export interface CmpPricedLeg extends CmpSpec {
  label: string;
  symbol: string;
  expiry: string;
  instrument_kind: "OPTION" | "FUTURE";
  strike: number | null;
  option_type: string | null;
  side: "BUY" | "SELL";
  lots: number;
  qty: number;
  ltp: number;
  contract_value: number;
}

export interface CmpBasketEstimate {
  legs: CmpPricedLeg[];
  /** Signed. Negative when the basket hedges an open position and FREES margin. */
  margin_required: number;
  /** How much the basket frees, as a positive number. Zero when it consumes margin. */
  margin_released: number;
  margin_if_legged_separately: number;
  hedge_benefit: number;
  net_premium: number;
  contract_exposure: number;
  available_cash: number;
  cash_after: number;
  affordable: boolean;
  shortfall: number;
  note: string;
}

export async function estimateCmpBasket(account_id: string, legs: CmpBasketLeg[]): Promise<CmpBasketEstimate> {
  return apiFetch(`${cmp}/basket/estimate`, {
    method: "POST",
    body: JSON.stringify({ account_id, legs }),
  });
}

export interface CmpMaxLots {
  max_lots: number;
  margin: number;
  available_cash: number;
  margin_per_lot: number;
  /** Margin at one lot MORE, from the same price snapshot. null when capped. */
  margin_at_next: number | null;
  premium_per_lot: number;
  legs: number;
  reason: string;
}

/** The largest EQUAL lot count this account can carry across these legs.
 *  Lots in the payload are ignored — the server sizes them. */
export async function maxCmpLots(account_id: string, legs: CmpBasketLeg[]): Promise<CmpMaxLots> {
  return apiFetch(`${cmp}/basket/max-lots`, {
    method: "POST",
    body: JSON.stringify({ account_id, legs }),
  });
}

export async function executeCmpBasket(
  account_id: string, legs: CmpBasketLeg[], product_type = "MARGIN",
): Promise<{ filled: number; margin_added: number; net_premium: number; orders: CmpOrder[] }> {
  return apiFetch(`${cmp}/basket/execute`, {
    method: "POST",
    body: JSON.stringify({ account_id, legs, product_type }),
  });
}
