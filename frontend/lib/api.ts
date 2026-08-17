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
