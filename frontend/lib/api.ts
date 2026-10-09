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

/** How long a GET may take before the page is told it failed. A GET that never answers is
 *  the worst case for a dashboard: no error is thrown, so no banner appears, and every tile
 *  keeps showing its empty default — "₹-", "0 strategies", "IDLE" — which reads exactly like a
 *  real, empty desk. That is what the Intraday Stocks page showed while the backend was
 *  swapping. Writes (POST/PUT/DELETE) get no default timeout: a long-running action such as
 *  a 40-stock fundamental rating must not be cut off half way. Pass `timeoutMs` to override. */
const DEFAULT_GET_TIMEOUT_MS = 60000;

async function apiFetch(path: string, init?: RequestInit & { timeoutMs?: number }) {
  if (FORCE_FRESH) {
    path += `${path.includes("?") ? "&" : "?"}fresh=true`;
  }
  const { timeoutMs: requested, ...rest } = init ?? {};
  const method = (rest.method || "GET").toUpperCase();
  const timeoutMs = requested ?? (method === "GET" ? DEFAULT_GET_TIMEOUT_MS : 0);
  const controller = timeoutMs > 0 && !rest.signal ? new AbortController() : null;
  const timer = controller ? setTimeout(() => controller.abort(), timeoutMs) : null;
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...rest,
      signal: controller?.signal ?? rest.signal,
      headers: {
        ...(rest.headers || {}),
        ...(rest.body ? { "Content-Type": "application/json" } : {}),
      },
    });
  } catch (e) {
    if (controller?.signal.aborted) {
      throw new Error(
        `The server did not answer within ${Math.round(timeoutMs / 1000)}s — it may be overloaded.`,
      );
    }
    throw new Error(`Could not reach the server (${e instanceof Error ? e.message : "network error"}).`);
  } finally {
    if (timer) clearTimeout(timer);
  }
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
  lot_size?: number;
  quantity_lots?: number;
  min_profit_factor?: number;
  min_trades?: number;
  train_fraction?: number;
  validation_fraction?: number;
  purge_days?: number;
  min_validation_trades?: number;
  min_test_trades?: number;
  overlap_threshold?: number;
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
  min_validation_trades?: number;
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
  training_metrics?: Record<string, any>;
  validation_metrics?: Record<string, any>;
  final_test_metrics?: Record<string, any>;
  research_windows?: Record<string, any>;
  structure?: Record<string, any>;
  qualified?: boolean;
  training_qualified?: boolean;
  validation_qualified?: boolean;
  validation_selected?: boolean;
  validation_failures?: string[];
  in_basket?: boolean;
  final_test_sample_sufficient?: boolean;
  final_test_passed?: boolean;
  final_test_failures?: string[];
  final_test_error?: string;
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
  lot_size?: number;
  lot_size_source?: string;
  lot_size_mode?: string;
  train_fraction?: number;
  validation_fraction?: number;
  purge_days?: number;
  min_validation_trades?: number;
  min_test_trades?: number;
  gate?: SellingGate;
  pricing_model?: string;
  fee_model?: string;
  margin_model?: string;
  selection_policy?: string;
  qualified_count: number;
  strategy_count: number;
  robust_count?: number;
  validation_selected_count?: number;
  basket_count?: number;
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
  entry_ltp?: number;
  entry_bid?: number | null;
  entry_ask?: number | null;
  entry_basis?: string;
}

export interface SellingPosition {
  key: string;
  strategy_id: string;
  timeframe: string;
  legs: SellingLeg[];
  structure: string;
  credit: number;
  lots: number;
  lot_size?: number;
  qty: number;
  entry_basis?: string;
  exit_basis?: string;
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
  breaker_scope?: "per_strategy" | "desk_wide";
  strategy_breakers?: Record<string, string>;
  strategy_breaker_count?: number;
  initial_capital: number;
  realized: number;
  balance: number;
  paper_account_realized?: number;
  legacy_realized_unverified?: number;
  mixed_realized_unverified?: number;
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
  lot_size?: number;
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
  gross_pnl?: number;
  charges?: number;
  entry_charges?: number;
  exit_charges?: number;
  execution_model_version?: number;
  pnl_quality?: string;
  entry_basis?: string;
  exit_basis?: string;
  ltp_pnl?: number;
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
  /** null for v2 rules that exit only on their stop, time stop or the close (ORB). */
  target: number | null;
  stoploss: number;
  ltp: number;
  ltp_source: string;
  unrealized_pnl: number;
  pnl_pct: number;
  realized_pnl: number | null;
  exit_price: number | null;
  exit_reason: string | null;
  status: string;
  confidence: number | null;
  rationale: string;
  max_hold_days: number;
  opened_at: string | null;
  opened_on: string | null;
  closed_at: string | null;
  is_anti?: boolean;
  /** v2 tournament only */
  engine?: string;
  timeframe?: string;
  fill_basis?: string;
}

export interface IntradayGate {
  t_threshold: number;
  strategies_tested: number;
  min_trades: number;
  min_profit_factor: number;
  max_drawdown_pct: number;
  note: string;
}

export interface IntradayDeskStatus {
  // Promotion gate. `ready_count` of 0 is the normal, honest state — it means nothing on
  // the board has yet shown an edge distinguishable from luck.
  gate?: IntradayGate;
  ready_count?: number;
  rejected_count?: number;
  pending_count?: number;
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
  // Promotion gate. `verdict` is the only field that answers "is this an edge?" —
  // net_pnl alone cannot, because the top of a 150-strategy board is where luck collects.
  verdict?: "READY" | "REJECTED" | "PENDING";
  verdict_reasons?: string[];
  profit_factor?: number | null;
  expectancy?: number;
  max_drawdown_pct?: number;
  t_stat?: number | null;
  t_threshold?: number;
  strategies_tested?: number;
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
// ---- Intraday tournament v2: walk-forward validation + incubation (Phase 3) ----

export interface V2Metrics {
  trades: number;
  net_pnl: number;
  gross_pnl: number;
  fees: number;
  win_rate: number;
  expectancy: number;
  profit_factor: number | null;
  max_drawdown_pct: number;
  sharpe_annual: number | null;
  t_stat: number | null;
  positive_month_share: number | null;
  months?: Record<string, number>;
  by_reason?: Record<string, number>;
}

export interface V2BacktestResult {
  strategy_id: string;
  name: string;
  family: string;
  timeframe: string;
  kind: string;
  dsr: number | null;
  passed: boolean;
  checks: Record<string, boolean>;
  selection: V2Metrics;
  holdout: V2Metrics;
  full: V2Metrics;
  optimistic_bound?: {
    selection_net: number;
    selection_pf: number | null;
    selection_win_rate: number;
    holdout_net: number;
    ambiguous: boolean;
    note: string;
  } | null;
}

export interface V2BacktestRun {
  run_id: string;
  first_day: string;
  holdout_from: string | null;
  sessions: number;
  selection_sessions: number;
  holdout_sessions: number;
  symbols: number;
  coverage_median: number;
  candidate_trades: number;
  taken_trades: number;
  n_trials: number;
  pbo: { pbo: number | null; combinations: number; median_logit?: number } | null;
  gate: Record<string, number | boolean>;
  passed: string[];
  fill_model: string;
}

export interface V2RegistryEntry {
  strategy_id: string;
  name: string;
  status: "INCUBATING" | "CONFIRMED" | "FAILED";
  registered_at: string | null;
  run_id: string;
  expected: { per_trade_net_mean: number | null; [k: string]: unknown };
  thresholds: { min_trades: number; [k: string]: number };
  forward: { trades?: number; mean?: number; z_vs_expected?: number | null; t?: number | null };
  eligible_for_live?: boolean;
}

export async function fetchV2Backtest(): Promise<{ run: V2BacktestRun | null; results: V2BacktestResult[] }> {
  return apiFetch("/api/intraday-lab/v2/backtest");
}

export async function fetchV2Registry(): Promise<{ strategies: V2RegistryEntry[] }> {
  return apiFetch("/api/intraday-lab/v2/registry");
}

// ---- Intraday ops (Phase 4): alarms + daily edge report ----

export interface OpsAlarm {
  id: string;
  kind: string;
  session: string;
  active: boolean;
  resolved?: boolean;
  count?: number;
  first_at?: string;
  last_at?: string;
  detail?: Record<string, unknown>;
}

export interface EdgeReport {
  date: string;
  desk: { trades: number; gross_pnl: number; fees: number; slippage_est: number; net_pnl: number };
  strategies: {
    strategy_id: string; name: string; trades: number; gross_pnl: number; fees: number;
    slippage_est: number; net_pnl: number; win_rate: number; backtest_per_trade: number | null;
  }[];
  calibration: { strategies_compared: number; median_gap_per_trade: number | null; share_below_backtest: number | null };
  stream_quality: {
    bars_compared?: number;
    close_bp?: { median: number | null; p95: number | null; max?: number | null };
  } | null;
  selection?: {
    expected_move: { rank_ic: number; top20_move_bp: number; all_move_bp: number; lift_top20: number | null; n: number } | null;
    nifty_gap: { forecast_bp: number; call: string; actual_bp: number | null; direction_right?: boolean } | null;
    incubation: { strategy_id: string; status: string; trades: number; forward_mean: number | null;
                  t: number | null; z_vs_expected: number | null; expected_mean: number | null }[];
    slippage_note: string;
  };
}

export async function fetchIntradayAlarms(days = 2): Promise<{ active: OpsAlarm[]; recent: OpsAlarm[] }> {
  return apiFetch(`/api/intraday-ops/alarms?days=${days}`);
}

export async function fetchEdgeReport(date?: string): Promise<EdgeReport | Record<string, never>> {
  return apiFetch(`/api/intraday-ops/edge-report${date ? `?date=${date}` : ""}`);
}

// --- Stock selection: Scanner Board, pre-market brief, evidence (Today's Playbook) ---

/** What a list may be used for, as the 2026-10-02 research found. */
export type EvidenceStatus = "proven" | "candidate" | "context" | "forward";

export interface ScannerRow {
  symbol: string;
  score: number | null;
  value: string;
  side: "LONG" | "SHORT" | null;
  reasons: string[];
  sector: string | null;
  last: number | null;
  chg_pct: number | null;
  expected_move_bp: number | null;
  turnover_cr: number | null;
  variant?: string;
  or_high?: number;
  or_low?: number;
}

export interface ScannerList {
  status: EvidenceStatus;
  use: "where" | "side" | "none";
  title: string;
  evidence: string;
  count: number;
  rows: ScannerRow[];
}

export interface HeldOut {
  days?: number;
  rank_ic?: number;
  ic_positive_days?: number;
  top20_move_bp?: number;
  all_move_bp?: number;
}

export interface ScannerBoard {
  at: string;
  hhmm: string;
  date: string;
  session: string;
  label?: string;
  nifty_chg_pct: number | null;
  sector_chg_pct: Record<string, number>;
  universe: number;
  stocks: number;
  archives_from: string | null;
  preopen: boolean;
  results_today: number;
  model: { trained_at: string; samples: number; oos: Record<string, HeldOut>; y_mean_bp: number;
           variants: Record<string, number> } | null;
  scanners: Record<string, ScannerList>;
  expected_move_all: Record<string, number>;
  or_levels: Record<string, [number, number]>;
}

export interface GapHeldOut {
  sessions: number; from: string; corr: number; mae_bp: number; naive_mae_bp: number;
  direction_hit: number; big_calls: number; big_direction_hit: number | null;
}

export interface GapForecast {
  us_move_bp: number;
  pred_bp: number;
  basis: string;
  call: "gap up" | "gap down" | "flat open";
  confidence: "high" | "moderate" | "low";
  typical_abs_gap_bp: number;
  model: { slope: number; intercept_bp: number; held_out: GapHeldOut };
  provisional?: boolean;
  note?: string;
  made_at?: string;
}

export interface EvidenceEntry {
  status: EvidenceStatus;
  title: string;
  evidence: string;
  predicts?: string;
  use?: string;
}

export interface SelectionEvidence {
  market: Record<string, EvidenceEntry>;
  stock_lists: Record<string, EvidenceEntry>;
  statuses: Record<EvidenceStatus, string>;
}

export interface PositioningRow {
  index_fut_long: number; index_fut_short: number; long_share: number | null; net: number; net_change?: number;
}

export interface SelectionBrief {
  at: string;
  date: string;
  session: string;
  trading_today: boolean;
  closed_reason: string | null;
  global: {
    snapshot_of: string | null;
    series: { key: string; label: string; group: string; session_ret_pct: number | null;
              session_date: string | null; live_chg_pct: number | null; used_for: string }[];
  };
  gap_forecast: GapForecast | null;
  vix: { level: number; prev_close: number; live: boolean; percentile_1y: number;
         regime: "high" | "normal" | "low"; means: string } | null;
  breadth_prev: { session: string; market: { advances: number; declines: number; ratio: number | null };
                  universe: { advances: number; declines: number; ratio: number | null } } | null;
  positioning: ({ session: string } & Record<string, PositioningRow | string>) | null;
  results: { today: { symbol: string; kind: string; at: string | null; source: string }[];
             in_universe_today: string[]; next_7_days: number };
  preopen: { nse_time?: string; stocks?: number; advances?: number; declines?: number;
             universe_movers?: { symbol: string; pchange: number; iep: number; imbalance: number | null }[] } | null;
  expected_day: { universe_expected_move_bp: number; typical_bp: number; ratio: number; as_of: string; note: string } | null;
  stock_bias: { status: EvidenceStatus; rule: string; rows: ScannerRow[] };
  gap_record: { days: { date: string; pred_bp: number | null; call: string | null; actual_bp: number | null }[];
                scored: number; direction_hit: number | null; mae_bp: number | null };
  evidence: SelectionEvidence;
}

export interface SelectionModel {
  model: { weights: Record<string, number[]>; features: Record<string, string[]>; samples: number;
           sessions: number; holdout_sessions: number; oos: Record<string, HeldOut>; y_mean_bp: number;
           trained_at: string; note: string } | null;
  live_record: { days: { date: string; rank_ic: number; top20_move_bp: number; all_move_bp: number;
                         lift_top20: number | null; n: number }[];
                 mean_rank_ic: number | null; mean_lift_top20: number | null };
  gap_model: { series: string; slope: number; intercept_bp: number; sessions: number; corr_all: number;
               held_out: GapHeldOut } | null;
  gap_record: SelectionBrief["gap_record"];
}

export async function fetchSelectionBoard(): Promise<ScannerBoard> {
  return apiFetch(`/api/selection/board`);
}

export async function fetchSelectionBrief(): Promise<SelectionBrief> {
  return apiFetch(`/api/selection/brief`, { timeoutMs: 45000 });
}

export async function fetchSelectionSnapshots(date?: string):
    Promise<{ days: string[]; date: string | null; times: string[]; schedule: string[] }> {
  return apiFetch(`/api/selection/snapshots${date ? `?date=${date}` : ""}`);
}

export async function fetchSelectionSnapshot(date: string, time: string): Promise<ScannerBoard> {
  return apiFetch(`/api/selection/snapshot?date=${date}&time=${encodeURIComponent(time)}`);
}

export async function fetchSelectionModel(): Promise<SelectionModel> {
  return apiFetch(`/api/selection/model`);
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

// --- Intraday Strategy Lab (50-strategy auto-trading paper desk) ---

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
  performance?: CmpPerformance;
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
  /** The day per-day averages are measured from. Null on accounts made before it
   *  existed; the backend then falls back to the account's creation date. */
  roi_start_date?: string | null;
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
  changes: { name?: string; initialCapital?: number; roiStartDate?: string },
): Promise<FnoAccount> {
  return apiFetch(`/api/fno-positions/accounts/${accountId}`, {
    method: "PATCH",
    body: JSON.stringify({
      name: changes.name ?? null,
      initial_capital: changes.initialCapital ?? null,
      roi_start_date: changes.roiStartDate ?? null,
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

export interface FnoMaxLots {
  max_lots: number;
  margin: number;
  margin_at_next: number | null;
  margin_per_lot: number;
  premium_per_lot: number;
  available_cash: number;
  legs: number;
  reason: string;
}

export interface FnoReopenAtm {
  rolled: {
    underlying: string; expiry: string; spot: number; legs: number;
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

/** Delete a paper account. Refuses while it still holds open positions. */
/** Profit since a chosen day for an F&O paper account. Shares the commodity desk's
 *  shape — the two windows answer the same question the same way. */
export async function fetchFnoPerformance(
  accountId: string, start?: string,
): Promise<CmpPerformance> {
  return apiFetch(`/api/fno-positions/accounts/${accountId}/performance`
    + (start ? `?start=${encodeURIComponent(start)}` : ""));
}

export async function deleteFnoAccount(accountId: string): Promise<{
  deleted: string; closed_positions_removed: number; orders_removed: number;
}> {
  return apiFetch(`/api/fno-positions/accounts/${accountId}`, { method: "DELETE" });
}

/** The largest EQUAL lot count this account can carry across these legs. */
export async function maxFnoLots(
  accountId: string, legs: FnoBasketLeg[], productType: FnoProductType = "MARGIN",
): Promise<FnoMaxLots> {
  return apiFetch("/api/fno-positions/basket/max-lots", {
    method: "POST",
    body: JSON.stringify({ account_id: accountId, product_type: productType, legs }),
  });
}

/** Roll open option legs to their at-the-money strike.
 *  Pass `positionIds` to roll only those; omit it to roll the whole book. */
export async function reopenFnoAtm(
  accountId: string, positionIds?: string[],
): Promise<FnoReopenAtm> {
  return apiFetch(
    `/api/fno-positions/positions/reopen-atm-all?account_id=${encodeURIComponent(accountId)}`,
    { method: "POST", body: JSON.stringify({ position_ids: positionIds ?? null }) });
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
  return apiFetch("/api/ai/rank-strategies", { timeoutMs: 120000 });   // waits on an LLM
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
  return apiFetch("/api/ai/trade-ideas", { timeoutMs: 120000 });   // waits on an LLM
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
    capital_per_trade?: number | null; note?: string | null;
    capital_mode?: string; accounts?: number; per_strategy_capital?: number | null; lots_per_position?: number | null;
    weekly_expiry?: string | null; dropped_signals?: Record<string, number>;
    // Only present when heartbeat_watchdog.py has actually run and written them —
    // that script isn't wired into the Docker/Linux deployment yet (Windows-Task-
    // Scheduler-only design), so treat both as possibly absent.
    heartbeat_stale?: boolean; heartbeat_age_seconds?: number | null;
  };
  open_positions: Array<{ key: string; strategy_id: string; timeframe: string; option_type: string; strike: number; entry_premium: number; mark: number; unrealized: number; qty: number; entry_ts: string }>;
  today: { session: string; trades: number; net_pnl: number; peak_capital: number; roi_pct: number | null; wins: number } | null;
}
/** One strategy's research record (2026-10-02: records, not a ranking — no ANTI rows). */
export interface PreLiveScore {
  key: string; strategy_id: string; timeframe: string; trades: number; name?: string | null;
  net_pnl: number; per_trade?: number; win_rate?: number; profit_factor?: number | null;
  t_stat?: number | null; direction_hit?: number | null; direction_n?: number; direction_z?: number | null;
  real_net?: number; real_per_trade?: number; real_basis?: string; dte_mix?: Record<string, number>;
  allocated_capital?: number;
}
export interface PreLiveRecords {
  count: number; strategies: PreLiveScore[]; ranking: boolean; note: string; real_money_basis: string;
  luck: { strategies_with_20_trades: number; expected_t_above_2_by_chance: number; observed_t_above_2: number;
          observed_t_below_minus_2: number; direction_z_above_2: number; reading: string };
  desk: { trades: number; paper_net: number; real_net_estimate: number; direction_hit: number;
          by_days_to_expiry: Record<string, { trades: number; real_per_trade: number }> };
  computed_at: string;
}
export interface OptionHypothesis {
  id: string; name: string; rule: string; status: string; origin?: string;
  expected: Record<string, unknown>; thresholds: Record<string, number>;
  forward: Record<string, unknown>; registered_at: string;
}
export interface VolDeskLeg {
  kind: string; symbol: string; strike: number; lot_size: number; entry_ltp: number; entry_bid: number | null;
  entry_ask: number | null; real_entry: number; exit_ltp?: number; exit_bid?: number | null; real_exit?: number;
}
export interface VolDeskSummary {
  status: { enabled: boolean; last_decision: { _id: string; prediction: number; threshold: number; flagged: boolean } | null;
            last_action: string | null; errors: number; last_error: string | null };
  open: { hypothesis: string; session: string; expiry: string; legs: VolDeskLeg[] }[];
  trades: { hypothesis: string; session: string; expiry: string; paper_pnl: number; real_pnl: number; real_basis: string;
            closed_at: string; legs: VolDeskLeg[] }[];
  decisions: { date: string; prediction: number; threshold: number; flagged: boolean; next_week_expiry: string | null;
               features: Record<string, number> }[];
  H1: { trades: number; real_net: number; paper_net: number };
  H1b: { trades: number; real_net: number; paper_net: number };
}
export interface LabPeriod { trades: number; net_per_trade?: number; direction_hit?: number; direction_t?: number | null }
export interface LabRun {
  run_id: string; seconds: number; data: { from: string; to: string; sessions: number }; pairs: number;
  passed: string[]; pbo: number | null; trials: number; gate: Record<string, number>;
  luck: { strategies: number; direction_t_above_2_expected_by_chance: number; direction_t_above_2_observed: number };
  model: Record<string, unknown>;
  rows: { key: string; explore: LabPeriod; holdout: LabPeriod; dsr: number | null; gate: Record<string, boolean>; passed: boolean }[];
}
export interface RealMoneyReadiness {
  state: { armed: boolean; armed_hypothesis: string | null; kill_switch: boolean; env_enabled: boolean; dry_run: boolean;
           max_lots: number; daily_loss_cap: number; disarmed_reason: string | null };
  hypotheses: { hypothesis: string; name: string; status: string; can_arm: boolean; why_not: string[] }[];
  slippage: { fills: number; mean_slippage_pct: number | null; alarm_at_pct: number; alarm?: boolean };
  recent_orders: Record<string, unknown>[];
  confirm_phrase: string;
  checks: string[];
}
export interface ChainRecorder {
  status: { enabled: boolean; today_rows: number; last_t: string | null; contracts: number; errors: number;
            last_error: string | null; last_ms?: number };
  coverage: { days: number; first?: string | null; last?: string | null; bytes?: number };
  instrument_master: { last_sync: string | null; contracts: number; nifty_expiries: string[]; error: string | null };
}

export async function fetchPreLiveRecords(): Promise<PreLiveRecords> { return apiFetch("/api/prelive/leaderboard"); }
export async function fetchOptionHypotheses(): Promise<{ hypotheses: OptionHypothesis[] }> { return apiFetch("/api/prelive/hypotheses"); }
export async function fetchVolDesk(): Promise<VolDeskSummary> { return apiFetch("/api/prelive/vol-desk"); }
export async function fetchBuyingLab(): Promise<{ run: LabRun | null }> { return apiFetch("/api/prelive/lab"); }
export async function fetchRealMoney(): Promise<RealMoneyReadiness> { return apiFetch("/api/prelive/real-money"); }
export async function fetchChainRecorder(): Promise<ChainRecorder> { return apiFetch("/api/prelive/chain-recorder"); }
export async function armRealMoney(hypothesis: string, confirm: string) {
  return apiFetch("/api/prelive/real-money/arm", { method: "POST", body: JSON.stringify({ hypothesis, confirm }) });
}
export async function disarmRealMoney() { return apiFetch("/api/prelive/real-money/disarm", { method: "POST", body: "{}" }); }
export async function killRealMoney(panic: boolean) {
  return apiFetch("/api/prelive/real-money/kill", { method: "POST", body: JSON.stringify({ active: true, panic }) });
}
export interface PreLiveTrade {
  id: string; strategy_id: string; timeframe: string; option_type: string; strike: number;
  entry_premium: number; exit_premium: number; entry_ts: string; exit_ts: string;
  exit_reason: string; qty: number; pnl: number; session: string;
  // from 2026-10-05: the order book at the fills and the real-money result
  expiry?: string; dte?: number | null; real_entry?: number; real_exit?: number; real_pnl?: number; real_basis?: string;
}
export interface PreLiveDay {
  session: string; trades: number; net_pnl: number; peak_capital: number | null; roi_pct: number | null; wins: number;
  cumulative_pnl: number; real_net?: number; cumulative_real?: number; daily_doc?: boolean;
}

export async function fetchPreLiveStatus(): Promise<PreLiveStatus> { return apiFetch("/api/prelive/status"); }
export async function fetchPreLiveLeaderboard(): Promise<{ count: number; strategies: PreLiveScore[] }> { return apiFetch("/api/prelive/leaderboard"); }
export async function fetchPreLiveTrades(limit = 100): Promise<{ count: number; trades: PreLiveTrade[] }> { return apiFetch(`/api/prelive/trades?limit=${limit}`); }
export async function fetchPreLiveDaily(limit = 60): Promise<{ count: number; days: PreLiveDay[]; sessions_total?: number; total_net?: number; total_real_net?: number }> { return apiFetch(`/api/prelive/daily?limit=${limit}`); }

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
): Promise<{ positions: ChartPositionOverlay[] }> {
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

// ---- Stock Pre-Live Paper Books ------------------------------------------------
// The buying desk's strategies on ONE shared account of Rs 10 lakh or Rs 2 lakh. Same
// signals and same fills as the desk; what differs is that the account can run out of cash
// (a signal it cannot afford is DECLINED, with the reason) and that every close pays real
// Angel One option fees. The desk itself charges nothing, so its P&L is gross.
export type StockBookKey = "10L" | "2L";

export interface StockBookSummary {
  book: StockBookKey;
  books: StockBookKey[];
  label: string;
  book_labels: Record<string, string>;
  book_capitals: Record<string, number>;
  mode: string;
  enabled: boolean;
  parent_side: string;
  capital: number;
  position_cap: number;
  cash: number;
  deployed: number;
  realized_pnl: number;
  unrealized_pnl: number;
  gross_pnl: number;
  fees: number;
  equity: number;
  roi_pct: number;
  open_positions: number;
  closed_positions: number;
  declined: number;
  strategies: number;
}

export interface StockBookScore {
  book: StockBookKey;
  strategy_id: string;
  strategy_name: string | null;
  is_anti: boolean;
  trades: number;
  wins: number;
  win_rate: number;
  net_pnl: number;
  gross_pnl: number;
  fees: number;
  profit_factor: number | null;
  declined: number;
}

export interface StockBookPosition {
  position_id: string;
  book: StockBookKey;
  parent_position_id: string;
  strategy_id: string;
  strategy_name: string | null;
  is_anti: boolean;
  symbol: string;
  option_type: string;
  strike: number;
  expiry: string;
  structure: string | null;
  lots: number;
  lot_size: number;
  qty: number;
  entry_premium: number;
  ltp: number;
  capital_deployed: number;
  unrealized_pnl: number;
  realized_pnl: number | null;
  gross_pnl: number | null;
  fees: number | null;
  exit_premium: number | null;
  exit_reason: string | null;
  status: "OPEN" | "CLOSED" | "DECLINED";
  decline_reason?: string;
  opened_at: string;
  closed_at: string | null;
}

const sbk = "/api/stock-books";

export async function fetchStockBookSummary(book: StockBookKey): Promise<StockBookSummary> {
  return apiFetch(`${sbk}/summary?book=${book}`);
}

export async function fetchStockBookLeaderboard(book: StockBookKey): Promise<StockBookScore[]> {
  const r = await apiFetch(`${sbk}/leaderboard?book=${book}`);
  return r.rows ?? [];
}

export async function fetchStockBookPositions(
  book: StockBookKey,
  status: "OPEN" | "CLOSED" | "DECLINED" | "ALL" = "OPEN",
  limit = 400,
): Promise<StockBookPosition[]> {
  const r = await apiFetch(`${sbk}/positions?book=${book}&status=${status}&limit=${limit}`);
  return r.positions ?? [];
}

// ---- Selling Paper Books ("Paper Trading 01") ----------------------------------
// A picked roster from the NIFTY option-SELLING desk on ONE account. The book follows the
// desk's own fills, pays real option fees on every leg, and declines - with the reason - any
// entry on a structure's own expiry day, any second copy of an identical position, and
// anything the account cannot afford. ANTI picks BUY the structure the original sells.
export interface SellingBookSummary {
  book: string;
  books: string[];
  book_labels: Record<string, string>;
  label: string;
  mode: string;
  enabled: boolean;
  capital: number;
  pnl_model_version?: number;
  selection_status?: string;
  fill_model?: string;
  notes?: string[];
  position_cap: number;
  cash: number;
  deployed: number;
  realized_pnl: number;
  unrealized_pnl: number;
  gross_pnl: number;
  fees: number;
  legacy_realized_pnl?: number;
  legacy_unrealized_pnl?: number;
  legacy_fees?: number;
  legacy_open_positions?: number;
  legacy_closed_positions?: number;
  equity: number;
  model_equity?: number;
  roi_pct: number;
  open_positions: number;
  closed_positions: number;
  declined: number;
  declined_by_reason: { expiry_day: number; duplicate: number; money: number };
  rules: { skip_expiry_day_entries: boolean; one_copy_per_structure: boolean };
  started_at: string | null;
  last_run_at: string | null;
  roster: { pick: string; base_strategy_id: string; direction: "SHORT" | "LONG" }[];
}

export interface SellingBookPick {
  pick: string;
  base_strategy_id: string;
  direction: "SHORT" | "LONG";
  trades: number;
  wins: number;
  win_rate: number | null;
  profit_factor: number | null;
  gross_pnl: number;
  fees: number;
  net_pnl: number;
  open: number;
  unrealized_pnl: number;
  legacy_trades?: number;
  legacy_open?: number;
  legacy_net_pnl?: number;
  declined_expiry_day: number;
  declined_duplicate: number;
  declined_money: number;
}

export interface SellingBookPosition {
  position_id: string;
  book: string;
  pick: string;
  base_strategy_id: string;
  direction: "SHORT" | "LONG";
  structure: string;
  expiry: string;
  credit: number;
  parent_credit?: number;
  pnl_model_version?: number;
  entry_quote_quality?: string;
  quote_quality?: string;
  lots: number;
  lot_size: number;
  qty: number;
  capital: number;
  mark: number | null;
  unrealized_pnl: number;
  realized_pnl: number | null;
  gross_pnl: number | null;
  fees: number | null;
  exit_cost: number | null;
  exit_reason: string | null;
  status: "OPEN" | "CLOSED" | "DECLINED";
  decline_reason: string | null;
  opened_at: string | null;
  closed_at: string | null;
}

const slb = "/api/selling-books";

export async function fetchSellingBookSummary(book: string): Promise<SellingBookSummary> {
  return apiFetch(`${slb}/summary?book=${book}`);
}

export async function fetchSellingBookLeaderboard(book: string): Promise<SellingBookPick[]> {
  const r = await apiFetch(`${slb}/leaderboard?book=${book}`);
  return r.rows ?? [];
}

export async function fetchSellingBookPositions(
  book: string,
  status: "OPEN" | "CLOSED" | "DECLINED" | "ALL" = "OPEN",
  limit = 400,
): Promise<SellingBookPosition[]> {
  const r = await apiFetch(`${slb}/positions?book=${book}&status=${status}&limit=${limit}`);
  return r.positions ?? [];
}

export async function runStockBooksCycle(): Promise<{
  opened: number; closed: number; declined: number; marked: number; notes: string[];
}> {
  return apiFetch(`${sbk}/run`, { method: "POST" });
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

// ---- Live Paper Buying (the 5 Pre-Live winners on a Rs50,000 book) ----
export type LivePaperBook = "50k" | "2L";

export interface LivePaperSummary {
  book: LivePaperBook;
  books: LivePaperBook[];
  label: string;
  mode: string;
  underlying: string;
  timeframe: string;
  timeframes: string[];
  total_capital: number;
  /** null: the books are a shared pool, there is no per-strategy slice. */
  per_strategy: number | null;
  sizing: string;
  free_cash: number;
  total_pnl: number;
  realized_pct: number;
  unrealized_pct: number;
  total_pct: number;
  costs_charged: boolean;
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
  /** 2026-10-02: new entries need a CONFIRMED hypothesis verdict; none exists, so the books
   *  are paused and only keep their record. */
  paused_by_gate?: boolean;
  gate_required?: boolean;
  selection_basis?: string;
  costs_from?: string;
}
export interface LivePaperScore {
  strategy_id: string;
  base_id: string;
  name: string;
  /** Pre-Live tournament rank — also the capital priority when a book is short. */
  rank: number;
  timeframe: string;
  open_positions: number;
  unrealized_pnl: number;
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

export async function fetchLivePaperSummary(book: LivePaperBook = "50k"): Promise<LivePaperSummary> {
  return apiFetch(`/api/live-paper/summary?book=${book}`);
}
export async function fetchLivePaperLeaderboard(book: LivePaperBook = "50k"): Promise<LivePaperScore[]> {
  const r = await apiFetch(`/api/live-paper/leaderboard?book=${book}`);
  return r.leaderboard ?? [];
}
export async function fetchLivePaperPositions(
  status = "OPEN",
  book: LivePaperBook = "50k",
): Promise<{ positions: LivePaperPosition[]; summary: LivePaperSummary }> {
  return apiFetch(`/api/live-paper/positions?status=${status}&book=${book}`);
}
export async function fetchLivePaperDaily(limit = 60, book: LivePaperBook = "50k"): Promise<LivePaperDaily[]> {
  const r = await apiFetch(`/api/live-paper/daily?limit=${limit}&book=${book}`);
  return r.daily ?? [];
}

// ---- F&O auto-roll: the daily 3 PM ATM short-straddle roll on one named account ----
export interface FnoAutoRollStatus {
  enabled: boolean;
  account_name: string;
  account_found: boolean;
  account_id: string | null;
  /** The account actually being traded — may differ from account_name on a prefix bind. */
  matched_account_name?: string | null;
  matched_by?: "id" | "exact" | "prefix" | "ambiguous" | "none";
  binding_note?: string | null;
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

// ── the Rs 2 lakh paper book on that desk ──────────────────────────────────────
// A hand-picked roster of the SAME strategies sharing ONE book. The desk above gives
// every strategy its own Rs 2 lakh, so nothing there ever competes for cash; here it
// does, and that is the number this tab exists to show.

export interface NiftyScalpPaperSummary {
  mode: string;
  enabled: boolean;
  book_capital: number;
  roster_size: number;
  slice_per_strategy: number;
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
  one_lot_over_slice: boolean;
  max_concurrent: number | null;
  today_pnl: number;
  daily_loss_limit: number;
  breaker_tripped: boolean;
  note: string;
}

export interface NiftyScalpPaperRosterRow {
  strategy_id: string;
  name: string;
  template: string;
  family: string;
  timeframe: string;
  style: string;
  slice: number;
  trades: number;
  win_rate: number;
  net_pnl: number;
  gross_pnl: number;
  fees: number;
  roi_pct: number;
  /** The same strategy's record on the parent desk — the record that got it picked. */
  desk_trades: number;
  desk_net_pnl: number;
  desk_roi_pct: number;
}

export async function fetchNiftyScalpPaperSummary(): Promise<NiftyScalpPaperSummary> {
  return apiFetch("/api/nifty-scalp/paper/summary");
}
export async function fetchNiftyScalpPaperRoster(): Promise<NiftyScalpPaperRosterRow[]> {
  const r = await apiFetch("/api/nifty-scalp/paper/roster");
  return r.roster ?? [];
}
export async function fetchNiftyScalpPaperPositions(status = "OPEN"): Promise<NiftyScalpPosition[]> {
  const r = await apiFetch(`/api/nifty-scalp/paper/positions?status=${status}`);
  return r.positions ?? [];
}
export async function fetchNiftyScalpPaperDaily(limit = 60): Promise<DailyRoi[]> {
  const r = await apiFetch(`/api/nifty-scalp/paper/daily?limit=${limit}`);
  return r.daily ?? [];
}
export async function setNiftyScalpPaperRoster(
  strategy_ids: string[],
): Promise<{ strategy_ids: string[]; count: number; unknown: string[] }> {
  return apiFetch("/api/nifty-scalp/paper/roster", {
    method: "PUT",
    body: JSON.stringify({ strategy_ids }),
  });
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
// --- Commodity: per-contract leaderboards ------------------------------------
// The main board blends all eight underlyings. These recompute the stats AND re-run the
// promotion gate on one contract's trades alone, so a verdict here means "clears the gate
// on THIS contract" rather than on a book dominated by the metals.

export interface CommodityScriptRow {
  symbol: string;
  strategies_traded: number;
  closed_trades: number;
  open_positions: number;
  realised_pnl: number;
  unrealised_pnl: number;
  net_pnl: number;
  deployed: number;
  total_costs: number;
  ready: number;
  rejected: number;
  pending: number;
  profitable: number;
}
export interface CommodityScriptOverview {
  rows: CommodityScriptRow[];
  gate: Record<string, number>;
  note: string;
}
export interface CommodityScriptBoard {
  symbol: string;
  rows: (CommodityScore & { symbol: string })[];
  totals: CommodityScriptRow;
  available: string[];
  total?: number;
  note?: string;
  error?: string;
  timeframes?: string[];
}

export async function fetchCommodityScripts(fresh = false): Promise<CommodityScriptOverview> {
  return apiFetch(`/api/commodity/scripts${fresh ? "?fresh=true" : ""}`);
}
export async function fetchCommodityScriptBoard(
  symbol: string,
  params: { family?: string; timeframe?: string; verdict?: string } = {},
): Promise<CommodityScriptBoard> {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) q.set(k, v);
  const s = q.toString();
  return apiFetch(`/api/commodity/scripts/${encodeURIComponent(symbol)}${s ? `?${s}` : ""}`);
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

// --- Commodity upgrade (2026-10-03): honest records, MCX market rules, Lab, hypotheses,
// the HC1 trend book and the locked real-money executor. The desk no longer promotes
// anything; these are records, and the Lab is the only door.

export interface CmdRecordRow {
  key: unknown;
  trades: number;
  net_bp: number;
  net_t: number | null;
  net_ci95: [number, number] | null;
  raw_bp: number;
  raw_t: number | null;
  direction_hit: number | null;
  win_rate: number | null;
  net_pnl: number;
  real_trades: number;
  real_bp: number | null;
}
export interface CmdStrategyRecord extends CmdRecordRow {
  strategy_id: string;
  name: string;
  template: string;
  timeframe: string;
  family: string;
  family_label: string;
  retired: boolean;
}
export interface CmdRecords {
  desk: { all: CmdRecordRow | null; not_void: CmdRecordRow | null; honest: CmdRecordRow | null };
  by_fill_basis: CmdRecordRow[];
  by_timeframe: CmdRecordRow[];
  by_timeframe_all: CmdRecordRow[];
  by_contract: CmdRecordRow[];
  by_family: CmdRecordRow[];
  strategies: CmdStrategyRecord[];
  luck: { strategies_judged: number; min_trades: number; t_above_2: number; t_below_minus_2: number;
          expected_by_chance_each_tail: number; positive: number; note: string };
  labels: Record<string, number | string>;
  retired_timeframes: string[];
  definitions: Record<string, string>;
}
export async function fetchCommodityRecords(fresh = false): Promise<CmdRecords> {
  return apiFetch(`/api/commodity/records${fresh ? "?fresh=true" : ""}`);
}

export interface CmdContractRule {
  underlying: string;
  settlement: string;
  exit_days: number;
  trading: string | null;
  contracts: { symbol: string; expiry: string; trading_days_left: number; in_exit_window: boolean; tradable: boolean }[];
}
export interface CmdMarket {
  calendar: {
    now_ist: string; session: string | null; open: boolean; close_today: string; us_daylight_saving: boolean;
    today_holiday: { name: string; morning_closed: boolean; evening_closed: boolean } | null;
    list_covers_through: string; list_expired: boolean;
    upcoming_holidays: { date: string; name: string; morning_closed: boolean; evening_closed: boolean }[];
  };
  contracts: CmdContractRule[];
  spreads_30d: { underlying: string; samples: number; median_bp: number; p90_bp: number; half_spread_bp: number }[];
  stale_after_min: number;
  curve_recorder: { documents: number; first_date: string | null; trading_days_recorded: number; next_slot: string;
                    next_at: string; error: string | null; underlyings: string[] };
}
export async function fetchCommodityMarket(): Promise<CmdMarket> {
  return apiFetch("/api/commodity/market");
}

export interface CmdPeriod { months?: number; ann_ret_pct?: number; sharpe?: number | null; t?: number | null; max_dd_pct?: number }
export interface CmdLabCandidate {
  key: string; kind: "trend" | "pattern"; rule?: string; series?: string; template?: string; name?: string;
  legs: string[]; explore: CmdPeriod; heldout: CmdPeriod; dsr: number | null;
  alpha: { alpha_ann_pct?: number; beta?: number; alpha_t?: number | null };
  benchmark_heldout_sharpe: number | null; feasible_legs: number; passes_history: boolean; reasons: string[];
}
export interface CmdLabRun {
  at: string; n_trials_registry: number; pbo: { pbo: number | null; combinations?: number; trials?: number };
  data_span: Record<string, [string, string, number]>; book_capital: number;
  benchmark: { name: string; heldout: CmdPeriod; explore: CmdPeriod };
  feasibility: Record<string, { vol_60d: number | null; target_notional: number; feasible: boolean;
                                vehicle: { contract: string; price: number; lot_value: number; lots: number } | null }>;
  candidates: CmdLabCandidate[]; passed_history: string[]; verdict_counts: Record<string, number>;
  gate: { dsr_min: number; pbo_max: number; alpha_t_min: number; min_feasible_legs: number; incubation_sessions: number };
}
export interface CmdLabVerdict { key: string; kind: string; verdict: string; reasons: string[]; dsr: number | null; summary: string }
export async function fetchCommodityLab(): Promise<{ run: CmdLabRun | null; verdicts: CmdLabVerdict[] }> {
  return apiFetch("/api/commodity/lab");
}
export async function runCommodityLab(): Promise<{ started: boolean; note: string }> {
  return apiFetch("/api/commodity/lab/run", { method: "POST" });
}

export interface CmdHypothesis {
  id: string; name: string; status: string; rule: string; test?: string; prior?: Record<string, unknown>;
  thresholds?: Record<string, unknown>; expectation?: string; verdict_reason?: string; decision_date?: string;
  forward?: Record<string, unknown> | null; registered_at?: string; evaluated_at?: string; book?: string;
}
export async function fetchCommodityHypotheses(): Promise<{ hypotheses: CmdHypothesis[] }> {
  return apiFetch("/api/commodity/hypotheses");
}

export interface CmdTrendBook {
  book: string; capital: number; start_date: string; vehicles: Record<string, string>;
  legs: { commodity: string; side: string | null; lots: number; contract: string; expiry: string; avg_price: number;
          mark?: number; unrealized_pnl?: number; realized_pnl: number; fees: number; multiplier: number }[];
  equity: { date: string; equity: number; realized: number; fees: number; unrealized: number }[];
  trades: { trade_id: string; commodity: string; contract: string; side: string; lots: number; price: number;
            spread_bp: number | null; fees: number; purpose: string; at: string; realized_pnl?: number }[];
  state: { last_targets?: { legs: Record<string, { side: string; lots: number; contract: string; price: number | null;
                                                   notional: number; vol_60d: number; ret_12m: number;
                                                   not_held_reason: string | null }>;
                            stress: { worst_day_loss: number; worst_day_pct: number | null; margin: number; ok: boolean } };
           rebalanced_month?: string; last_notes?: string[]; last_mark?: { equity: number } };
}
export async function fetchCommodityTrendBook(): Promise<CmdTrendBook> {
  return apiFetch("/api/commodity/trend-book");
}

export interface CmdRealMoney {
  state: { armed: boolean; armed_for: string | null; kill_switch: boolean; env_enabled: boolean; dry_run: boolean;
           qty_verified: boolean; max_order_notional: number; daily_loss_cap: number; disarmed_reason: string | null };
  strategies: { strategy: string; name: string; status: string; can_arm: boolean; why_not: string[] }[];
  recent_orders: { strategy: string; purpose: string; status: string; tradingsymbol: string; side: string; lots: number;
                   ref_price: number; at: string; refused?: string[] | null }[];
  checks: string[];
  confirm_phrase: string;
}
export async function fetchCommodityRealMoney(): Promise<CmdRealMoney> {
  return apiFetch("/api/commodity/real-money");
}
export async function setCommodityKillSwitch(active: boolean): Promise<unknown> {
  return apiFetch("/api/commodity/real-money/kill", { method: "POST", body: JSON.stringify({ active }) });
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
  /** Set only when the rows come from an expired scan being refreshed behind the request. */
  stale_s?: number;
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
    named: { slug: string; label: string; why: string; url: string; group?: string }[];
    named_groups?: string[];
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
  /** True once the contract has stopped trading. Its `ltp` is then a settlement value,
   *  not a live quote, and `price_basis` says where that number came from. */
  expired?: boolean;
  price_basis?: string;
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
  /** On an exit: how the fill price was arrived at — a live quote, or, for a contract
   *  closed after expiry, the settlement basis. */
  exit_basis?: string;
}

export interface CmpSummary {
  account: CmpAccount;
  performance?: CmpPerformance;
  /** The mark-to-market pass outlived the read's wait budget and is finishing in the
   *  background: these marks are the previous ones. Ask again shortly, with fresh=true. */
  marks_refreshing?: boolean;
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

/** What one lot of an underlying costs and controls — for the order ticket. Priced per
 *  underlying, so the page multiplies by the lot count client-side. */
export interface CmpSizing {
  symbol: string;
  price: number | null;
  price_contract?: string | null;
  one_lot_value: number | null;
  /** Estimated margin for one FUTURES lot, at the measured broker rate. */
  margin_per_lot_est: number | null;
  /** The same for one SOLD OPTION lot, which costs ~1.2x a future on the same commodity.
   *  Both are quoted because this ticket places either from the same box. */
  margin_per_lot_short_option_est?: number | null;
  margin_rate?: number;
  margin_rate_short_option?: number;
  capital: number | null;
  available_cash: number | null;
  lots_at_1x_capital: number | null;
  lot_quantity: string;
  price_unit: string;
  multiplier: number;
  verified: boolean;
  note: string;
}

const cmp = "/api/commodity-positions";

export async function fetchCmpSizing(symbol: string, accountId?: string): Promise<CmpSizing> {
  const q = accountId ? `&account_id=${encodeURIComponent(accountId)}` : "";
  return apiFetch(`${cmp}/sizing?symbol=${encodeURIComponent(symbol)}${q}`);
}

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
export async function fetchCmpPositions(account_id: string, fresh = false): Promise<CmpSummary> {
  // fresh=true skips the backend's 20 s response cache - needed for the quick re-ask after
  // `marks_refreshing`, which would otherwise be answered with the same stale body.
  return apiFetch(
    `${cmp}/positions?account_id=${encodeURIComponent(account_id)}${fresh ? "&fresh=true" : ""}`);
}

/** Everything the Commodity Positions page needs to first paint, in one request - see
 *  `bootstrap_endpoint`. Each part has the shape its own endpoint returns; a part that
 *  failed is null with its reason, and the page then fetches that part on its own. */
export interface CmpBootstrap {
  accounts: CmpAccount[];
  account_id: string | null;
  underlyings: CmpUnderlying[];
  symbol: string | null;
  option_expiries: string[];
  future_expiries: string[];
  expiry: string | null;
  chain: CmpChain | null;
  chain_error: string | null;
  positions: CmpSummary | null;
  positions_error: string | null;
  sizing: {
    account_id: string; symbol: string; expiry: string; strike: number;
    sell: CmpMaxLots | null; buy: CmpMaxLots | null;
  } | null;
}

export async function fetchCmpBootstrap(p: {
  account_id?: string; symbol?: string; expiry?: string; with_chain?: boolean;
} = {}): Promise<CmpBootstrap> {
  const q = new URLSearchParams();
  if (p.account_id) q.set("account_id", p.account_id);
  if (p.symbol) q.set("symbol", p.symbol);
  if (p.expiry) q.set("expiry", p.expiry);
  if (p.with_chain) q.set("with_chain", "true");
  const qs = q.toString();
  return apiFetch(`${cmp}/bootstrap${qs ? `?${qs}` : ""}`);
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
  /** What the leg CONTROLS: a future at its own price, an option at its STRIKE. */
  contract_value: number;
  /** What the leg is WORTH right now — premium x quantity. On a sold option this is a
   *  small fraction of `contract_value`; they were once the same field. */
  premium_value?: number;
}

export interface CmpBasketEstimate {
  legs: CmpPricedLeg[];
  /** Signed. Negative when the basket hedges an open position and FREES margin. */
  margin_required: number;
  /** Where the margin figure came from: "angel" (the broker's own calculator, the same
   *  figure its app shows) or "measured[:why]" (rates measured from the broker on
   *  2026-10-09, used when it could not be asked — throttled, unreachable, the contract
   *  unmapped, or its answer not believable). Shown on the page, never implied: the local
   *  model this replaced was 8.2x too light on short MCX options and nothing on screen
   *  said which model had produced the number. */
  margin_source?: string;
  /** How much the basket frees, as a positive number. Zero when it consumes margin. */
  margin_released: number;
  /** Each leg's own margin at the measured rates, summed. */
  margin_if_legged_separately: number;
  /** Always 0 now. SPAN nets almost nothing across the baskets this desk trades — 0% on
   *  a straddle, 1.8% on a vertical — so the gap between the two numbers above is
   *  calibration drift, not a saving anyone earned. The old model claimed Rs 69,181 of it
   *  on a straddle that in fact nets nothing. */
  hedge_benefit: number;
  net_premium: number;
  /** Notional controlled, with opposing option sides netted per expiry — a short
   *  straddle finishes long or short the underlying, never both. */
  contract_exposure: number;
  /** The plain sum of every leg, before that netting. */
  contract_exposure_gross?: number;
  /** The basket's premium value, which is what `contract_exposure` used to report. */
  premium_value?: number;
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
  /** Margin at one lot MORE, projected from `margin_per_lot`. Margin is exactly linear in
   *  size, so this needs no extra broker call. null when capped. */
  margin_at_next: number | null;
  /** Where the margin figure came from: "angel" (the broker's own calculator, the same
   *  figure its app shows) or "measured[:why]" (rates measured from the broker on
   *  2026-10-09, used when it could not be asked — throttled, unreachable, the contract
   *  unmapped, or its answer not believable). Shown on the page, never implied: the local
   *  model this replaced was 8.2x too light on short MCX options and nothing on screen
   *  said which model had produced the number. */
  margin_source?: string;
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

// ---- Pre-Live Commodity Trading -----------------------------------------------
// The graduation desk above the 311-pattern paper desk: only patterns that already
// cleared that desk's promotion gate trade here, in WHOLE MCX lots sized against margin,
// on a Rs 1,00,000 book per CONTRACT. The engine ships OFF and every contract has its own
// switch. Still paper — no order reaches a broker from this module.
const cpl = "/api/commodity-prelive";

export interface CommodityPreliveSummary {
  enabled: boolean;
  admission_mode: "per_script" | "blended";
  enabled_at: string | null;
  disabled_reason: string | null;
  last_run_at: string | null;
  last_opened: number;
  last_managed: number;
  last_evaluated: number;
  last_notes: string[];
  script_capital: number;
  scripts: string[];
  active_scripts: string[];
  script_count: number;
  active_script_count: number;
  initial_capital: number;
  capital_switched_on: number;
  equity: number;
  realized_pnl: number;
  unrealized_pnl: number;
  margin_deployed: number;
  available_margin: number;
  total_costs: number;
  open_positions: number;
  closed_positions: number;
  admitted_total: number;
  /** Set while admission comes only from the Commodity Lab and nothing is confirmed. */
  paused_reason?: string | null;
  admission_source?: string;
  admitted_by_script: Record<string, number>;
  admission_counts: {
    per_script: Record<string, number>;
    per_script_total: number;
    blended_per_contract: number;
    blended_total: number;
  };
  ready_count: number;
  rejected_count: number;
  pending_count: number;
  mode: string;
  costs_charged: boolean;
  sizing: string;
  slippage_bps: number;
  market_open: boolean;
  max_positions_per_script: number;
  lots_per_trade: number;
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
  breaker_base: number;
}

export interface CommodityPreliveScript {
  symbol: string;
  enabled: boolean;
  contract: string;
  expiry: string;
  capital: number;
  ltp: number | null;
  ltp_source: string | null;
  multiplier: number;
  lot_quantity: string | null;
  price_unit: string | null;
  spec_verified: boolean;
  lot_notional: number;
  margin_per_lot: number;
  margin_pct: number;
  lots_per_book: number;
  lots_fundable_now: number;
  tradable: boolean;
  unpriced: boolean;
  afford_note: string | null;
  admitted_strategies: number;
  realized_pnl: number;
  unrealized_pnl: number;
  net_pnl: number;
  return_pct: number;
  margin_deployed: number;
  available_margin: number;
  equity: number;
  open_positions: number;
  closed_positions: number;
}

export interface CommodityPreliveScripts {
  rows: CommodityPreliveScript[];
  script_capital: number;
  max_positions_per_script: number;
  lots_per_trade: number;
  admission_mode: string;
  tradable_count: number;
  note: string;
}

export interface CommodityPreliveScore {
  strategy_id: string;
  symbol: string;
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
  open_positions: number;
  unrealized_pnl: number;
  verdict: "READY" | "REJECTED" | "PENDING";
  verdict_reasons: string[];
  still_admitted: boolean;
  admitted_because: string | null;
}

export interface CommodityPreliveBoard {
  rows: CommodityPreliveScore[];
  symbol: string | null;
  total: number;
  shown: number;
  admission_mode: string;
  gate: Record<string, number>;
  note: string;
}

export interface CommodityPrelivePosition {
  position_id: string;
  strategy_id: string;
  strategy_name: string;
  family_label: string;
  timeframe: string;
  pattern: string;
  symbol: string;
  display_name: string;
  side: string;
  entry_price: number;
  lots: number;
  multiplier: number;
  qty: number;
  notional: number;
  margin_used: number;
  target: number;
  stoploss: number;
  ltp: number;
  unrealized_pnl: number;
  pnl_pct: number;
  return_on_margin_pct: number;
  bars_held: number;
  max_hold_bars: number;
  rationale: string;
  admitted_because: string | null;
  status: string;
  opened_at: string;
}

export interface CommodityPreliveTrade {
  trade_id: string;
  strategy_name: string;
  timeframe: string;
  pattern: string;
  symbol: string;
  side: string;
  entry_price: number;
  exit_price: number;
  lots: number;
  qty: number;
  margin_used: number;
  gross_pnl: number;
  costs: number;
  realized_pnl: number;
  return_on_margin_pct: number;
  exit_reason: string;
  closed_at: string;
}

export async function fetchCommodityPreliveSummary(): Promise<CommodityPreliveSummary> {
  return apiFetch(`${cpl}/summary`);
}

export async function fetchCommodityPreliveScripts(fresh = false): Promise<CommodityPreliveScripts> {
  return apiFetch(`${cpl}/scripts${fresh ? "?fresh=true" : ""}`);
}

export async function fetchCommodityPreliveBoard(params: {
  symbol?: string;
  family?: string;
  timeframe?: string;
  verdict?: string;
  limit?: number;
} = {}): Promise<CommodityPreliveBoard> {
  const q = new URLSearchParams();
  if (params.symbol) q.set("symbol", params.symbol);
  if (params.family) q.set("family", params.family);
  if (params.timeframe) q.set("timeframe", params.timeframe);
  if (params.verdict) q.set("verdict", params.verdict);
  if (params.limit) q.set("limit", String(params.limit));
  const qs = q.toString();
  return apiFetch(`${cpl}/leaderboard${qs ? `?${qs}` : ""}`);
}

export async function fetchCommodityPrelivePositions(symbol?: string): Promise<{
  positions: CommodityPrelivePosition[];
  open: CommodityPrelivePosition[];
}> {
  return apiFetch(`${cpl}/positions${symbol ? `?symbol=${encodeURIComponent(symbol)}` : ""}`);
}

export async function fetchCommodityPreliveTrades(limit = 60, symbol?: string): Promise<CommodityPreliveTrade[]> {
  const q = new URLSearchParams({ limit: String(limit) });
  if (symbol) q.set("symbol", symbol);
  const r = await apiFetch(`${cpl}/trades?${q.toString()}`);
  return r.trades ?? [];
}

export async function setCommodityPreliveEngine(enabled: boolean, reason?: string) {
  return apiFetch(`${cpl}/engine`, {
    method: "POST",
    body: JSON.stringify({ enabled, reason: reason ?? null }),
  });
}

export async function setCommodityPreliveScript(symbol: string, enabled: boolean) {
  return apiFetch(`${cpl}/script-enabled`, {
    method: "POST",
    body: JSON.stringify({ symbol, enabled }),
  });
}

export async function setCommodityPreliveAllScripts(enabled: boolean) {
  return apiFetch(`${cpl}/scripts-enabled`, {
    method: "POST",
    body: JSON.stringify({ enabled }),
  });
}

export async function setCommodityPreliveAdmissionMode(mode: "per_script" | "blended") {
  return apiFetch(`${cpl}/admission-mode`, {
    method: "POST",
    body: JSON.stringify({ mode }),
  });
}

export async function runCommodityPreliveCycle() {
  return apiFetch(`${cpl}/run`, { method: "POST" });
}

export async function closeAllCommodityPrelive(symbol?: string) {
  return apiFetch(`${cpl}/close-all${symbol ? `?symbol=${encodeURIComponent(symbol)}` : ""}`, {
    method: "POST",
  });
}

// ---- Pattern Paper Books (the pattern shortlist at ₹50k and ₹2 lakh) -----------
// Two paper books running the SAME eight shortlisted pattern strategies, differing only
// in capital. They mirror the 548-strategy pattern desk's fills rather than re-scanning,
// so any difference between them is caused by ACCOUNT SIZE and nothing else.
const pbk = "/api/pattern-books";

export type PatternBookKey = "50k" | "2L";

export interface PatternBookSummary {
  book: PatternBookKey;
  books: PatternBookKey[];
  label: string;
  book_capitals: Record<string, number>;
  book_labels: Record<string, string>;
  mode: string;
  enabled: boolean;
  desk_capital: number;
  strategies: number;
  per_strategy_allocation: number;
  equity: number;
  realized_pnl: number;
  unrealized_pnl: number;
  gross_pnl: number;
  fees: number;
  deployed: number;
  available_cash: number;
  open_positions: number;
  closed_positions: number;
  roi_pct: number;
  skipped_unaffordable: number;
  last_skip: string | null;
  last_run_at: string | null;
  source: string;
}

export interface PatternBookScore {
  strategy_id: string;
  name: string;
  template: string;
  family: string;
  timeframe: string;
  style: string;
  allocation: number;
  trades: number;
  win_rate: number;
  gross_pnl: number;
  fees: number;
  net_pnl: number;
  roi_pct: number;
  open_positions: number;
}

export interface PatternBookPosition {
  position_id: string;
  book: PatternBookKey;
  parent_position_id: string;
  strategy_id: string;
  strategy_name: string;
  template: string;
  family: string;
  timeframe: string;
  style: string;
  symbol: string;
  side: string;
  entry_price: number;
  qty: number;
  capital_deployed: number;
  allocation: number;
  target: number | null;
  stoploss: number | null;
  ltp: number;
  unrealized_pnl: number;
  realized_pnl: number | null;
  gross_pnl: number | null;
  fees: number | null;
  exit_price: number | null;
  exit_reason: string | null;
  status: "OPEN" | "CLOSED" | "DECLINED";
  decline_reason?: string | null;
  opened_at: string;
  closed_at: string | null;
}

export interface PatternBookTrade {
  trade_id: string;
  book: PatternBookKey;
  strategy_name: string;
  template: string;
  timeframe: string;
  symbol: string;
  side: string;
  entry_price: number;
  exit_price: number;
  qty: number;
  gross_pnl: number;
  fees: number;
  realized_pnl: number;
  exit_reason: string | null;
  closed_at: string;
}

export async function fetchPatternBookSummary(book: PatternBookKey): Promise<PatternBookSummary> {
  return apiFetch(`${pbk}/summary?book=${book}`);
}

export async function fetchPatternBookLeaderboard(book: PatternBookKey): Promise<{
  book: PatternBookKey;
  rows: PatternBookScore[];
  total: number;
  per_strategy_allocation: number;
  note: string;
}> {
  return apiFetch(`${pbk}/leaderboard?book=${book}`);
}

export async function fetchPatternBookPositions(
  book: PatternBookKey,
  status: "OPEN" | "CLOSED" | "ALL" = "OPEN",
): Promise<PatternBookPosition[]> {
  const r = await apiFetch(`${pbk}/positions?book=${book}&status=${status}`);
  return r.positions ?? [];
}

export async function fetchPatternBookTrades(
  book: PatternBookKey,
  limit = 60,
): Promise<PatternBookTrade[]> {
  const r = await apiFetch(`${pbk}/trades?book=${book}&limit=${limit}`);
  return r.trades ?? [];
}

export async function runPatternBooksCycle() {
  return apiFetch(`${pbk}/run`, { method: "POST" });
}

// ---- Module ON/OFF switches ---------------------------------------------------
// Turning a module OFF stops its scheduler cycle, which is where it both fetches market
// data and places paper trades — so both stop together. Positions already open are left
// untouched and are NOT managed while it is off.
export interface ModuleSwitch {
  module: string;
  label: string;
  href: string;
  enabled: boolean;
  // Main Control adds these. Optional so the older /api/modules response still types.
  group?: string;
  api_prefixes?: string[];
  has_api?: boolean;
  // True where OTHER pages read this module's API, so OFF reaches past its own page.
  shared?: boolean;
  note?: string;
  // How many requests this switch has actually refused since the backend started. This is
  // the proof the toggle does something; it resets on restart.
  blocked_requests?: number;
  last_blocked?: string;
}

export interface ModuleSwitches {
  modules: ModuleSwitch[];
  total: number;
  on: number;
  off: number;
  note: string;
  groups?: string[];
  blocked_total?: number;
  api_prefixes_controlled?: number;
}

// ---- Main Control -------------------------------------------------------------
// The same switches as /api/modules, but this endpoint reports the whole app (every module,
// grouped as the sidebar groups them) and the blocked-request counters. OFF here stops the
// module's scheduler AND makes its API refuse anything that would call the broker or write a
// document; plain reads of stored rows still answer, so the page renders frozen numbers
// rather than an error.
const mc = "/api/main-control";

export async function fetchMainControl(): Promise<ModuleSwitches> {
  return apiFetch(mc);
}

export async function setMainControlModule(
  module: string,
  enabled: boolean,
): Promise<ModuleSwitches> {
  return apiFetch(`${mc}/toggle`, {
    method: "POST",
    body: JSON.stringify({ module, enabled }),
  });
}

export async function setMainControlBulk(
  modules: Record<string, boolean>,
): Promise<ModuleSwitches> {
  return apiFetch(`${mc}/bulk`, { method: "POST", body: JSON.stringify({ modules }) });
}

export async function setMainControlAll(enabled: boolean): Promise<ModuleSwitches> {
  return apiFetch(`${mc}/all`, { method: "POST", body: JSON.stringify({ enabled }) });
}

// "Only this one works" in a single call: this module ON, every other module OFF.
export async function setMainControlOnly(module: string): Promise<ModuleSwitches> {
  return apiFetch(`${mc}/only`, { method: "POST", body: JSON.stringify({ module }) });
}

export async function resetMainControlCounts(): Promise<ModuleSwitches> {
  return apiFetch(`${mc}/reset-counts`, { method: "POST" });
}

export interface ModuleResolution {
  path: string;
  method: string;
  module: string | null;
  label: string | null;
  enabled: boolean;
  counts_as_work: boolean;
  would_block: boolean;
  reason: string;
}

// Ask the backend which module owns a path and whether it would be blocked right now —
// so a switch can be checked rather than trusted.
export async function resolveModulePath(
  path: string,
  method = "GET",
): Promise<ModuleResolution> {
  return apiFetch(`${mc}/resolve?path=${encodeURIComponent(path)}&method=${method}`);
}

export async function fetchModuleSwitches(): Promise<ModuleSwitches> {
  return apiFetch("/api/modules");
}

export async function setModuleSwitch(module: string, enabled: boolean): Promise<ModuleSwitches> {
  return apiFetch("/api/modules/toggle", {
    method: "POST",
    body: JSON.stringify({ module, enabled }),
  });
}

export async function setAllModuleSwitches(enabled: boolean): Promise<ModuleSwitches> {
  return apiFetch("/api/modules/all", {
    method: "POST",
    body: JSON.stringify({ enabled }),
  });
}

// ---- Fundamental Rating (screener.in fundamentals, scored 1-10) ----
export type RatingBand = "strong" | "good" | "mixed" | "weak" | "poor" | "unknown";

export interface RatingPillar {
  pillar: string;
  label: string;
  score: number;
  weight: number;
  effective_weight?: number;
  reason: string;
  inputs: Record<string, unknown>;
}

export interface SkippedPillar {
  pillar: string;
  label: string;
  weight: number;
  why: string;
}

export interface ResultSignal {
  label: string;
  value: string;
  detail: string;
  tone: "good" | "bad" | "neutral";
}

/** Whether the LATEST quarter is strong — a separate read from the 1-10 business score. */
export interface ResultsStrength {
  rated: boolean;
  score: number | null;
  verdict: string;
  band: RatingBand;
  grade: string;
  grade_key: GradeKey;
  tier: string;
  headline: string;
  signals: ResultSignal[];
  latest_quarter?: string;
  comparison_quarter?: string;
  previous_quarter?: string;
  sales_qoq?: number | null;
  one_off_flag?: boolean;
  one_off_note?: string | null;
  coverage?: number;
}

/** The multi-year P&L record, graded on the same nine-tier scale. */
export interface PnlStrength {
  rated: boolean;
  score: number | null;
  verdict?: string;
  grade: string;
  grade_key: GradeKey;
  tier: string;
  headline: string;
  signals: ResultSignal[];
  years?: number;
  first_year?: string | null;
  last_year?: string | null;
  one_off_flag?: boolean;
  one_off_note?: string | null;
  coverage?: number;
}

/** The screener.in tables themselves, shaped for direct rendering. */
export interface Statements {
  quarters: Record<string, (number | null)[]>;
  quarters_periods: string[];
  profit_loss: Record<string, (number | null)[]>;
  profit_loss_periods: string[];
  ranges: Record<string, Record<string, number | null>>;
}

export interface FundamentalRating {
  symbol: string;
  name: string | null;
  sector?: string | null;
  industry?: string | null;
  rated: boolean;
  score: number | null;
  verdict: string;
  band: RatingBand;
  is_lender?: boolean;
  coverage: number;
  pillars: RatingPillar[];
  skipped: SkippedPillar[];
  summary: string;
  price?: number | null;
  market_cap_cr?: number | null;
  pe?: number | null;
  roce?: number | null;
  screener_pros?: string[];
  screener_cons?: string[];
  basis?: string;
  source_url?: string;
  data_missing?: string[];
  from_cache?: boolean;
  rated_at?: string;
  /** A few sentences about the company's fundamentals, composed server-side. */
  brief?: string;
  /** The brief plus the identifying facts and source — what the Copy button copies. */
  copy_text?: string;
  /** Just the name, score and the three grades — what the header Copy button copies. */
  headline_text?: string;
  /** Rich-text versions, so a paste carries the grade's emphasis. */
  copy_html?: string;
  headline_html?: string;
  results?: ResultsStrength;
  pnl?: PnlStrength;
  statements?: Statements;
  grade: string;
  grade_key: GradeKey;
  tier?: string;
}

export interface RateResponse {
  ratings: FundamentalRating[];
  failures: { symbol: string; error: string }[];
  requested: number;
  rated: number;
  truncated: string[];
  note: string | null;
}

export interface RatingMethodology {
  pillars: { pillar: string; label: string; weight: number }[];
  bands: { from: number; to: number; verdict: string; band: RatingBand }[];
  source: string;
  cache_hours: number;
  max_symbols: number;
  notes: string[];
}

export async function rateFundamentals(symbols: string, force = false): Promise<RateResponse> {
  return apiFetch("/api/fundamentals/rate", {
    method: "POST",
    body: JSON.stringify({ symbols, force }),
  });
}

export async function fetchFundamentalDetail(
  symbol: string,
  force = false,
): Promise<FundamentalRating & { fundamentals: Record<string, unknown> }> {
  return apiFetch(`/api/fundamentals/${encodeURIComponent(symbol)}${force ? "?force=true" : ""}`);
}

export async function fetchRecentRatings(limit = 50): Promise<{ ratings: FundamentalRating[]; count: number }> {
  return apiFetch(`/api/fundamentals/recent?limit=${limit}`);
}

export async function fetchRatingMethodology(): Promise<RatingMethodology> {
  return apiFetch("/api/fundamentals/methodology");
}

// ---- Fundamental Rating: the nine-tier grade + the index/sector scanner ----
export type GradeKey =
  | "worst" | "below-average" | "average" | "above-average" | "good"
  | "very-good" | "excellent" | "extraordinary" | "explosive" | "unrated";

/** Worst -> best. Drives legend order and the filter list. */
export const GRADE_ORDER: GradeKey[] = [
  "worst", "below-average", "average", "above-average", "good",
  "very-good", "excellent", "extraordinary", "explosive",
];

export const GRADE_COLOR: Record<GradeKey, string> = {
  worst: "#b3261e",
  "below-average": "#d4443c",
  average: "#c98a10",
  "above-average": "#9a9412",
  good: "#6a9c1a",
  "very-good": "#3f9c34",
  excellent: "#1a9c5b",
  extraordinary: "#0e8f8f",
  explosive: "#7d34dc",
  unrated: "#8a8a99",
};

export interface GradeTier {
  tier: string;
  grade_key: GradeKey;
  grade: string;
  from: number;
  to: number;
}

/** A stock as the picker lists it — one flat row per company. */
export interface UniverseStock {
  symbol: string;
  name: string | null;
  nse_sector: string | null;
  sector: string | null;
  industry: string | null;
  indices: string[];
  score: number | null;
  grade: string;
  grade_key: GradeKey;
  verdict: string;
  coverage: number | null;
  is_lender?: boolean;
  results_score: number | null;
  results_grade: string | null;
  results_grade_key: GradeKey | null;
  latest_quarter: string | null;
  pnl_score: number | null;
  pnl_grade: string | null;
  pnl_grade_key: GradeKey | null;
  price: number | null;
  market_cap_cr: number | null;
  pe: number | null;
  roce: number | null;
  summary: string | null;
  source_url?: string;
  rated_at?: string;
}

export interface ScanScope {
  type: "index" | "sector" | "watchlist";
  key: string;
  label: string;
}

export interface ScanScopes {
  indices: { key: string; label: string; count: number }[];
  sectors: { key: string; label: string; count: number }[];
  watchlists?: { key: string; label: string; count: number }[];
  rated_stored: number;
}

export interface ScanStatus {
  running: boolean;
  status: "idle" | "running" | "cooling" | "done" | "cancelled" | "cancelling";
  scope: ScanScope | null;
  total: number;
  done: number;
  ok: number;
  failed: number;
  failures: { symbol: string; error: string }[];
  current?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  note?: string;
}

export async function fetchScanScopes(): Promise<ScanScopes> {
  return apiFetch("/api/fundamentals/universe/scopes");
}

export async function fetchScanStatus(): Promise<ScanStatus> {
  return apiFetch("/api/fundamentals/universe/scan/status");
}

export async function startUniverseScan(
  type: "index" | "sector" | "watchlist",
  key: string,
  force = false,
): Promise<{ started: boolean; reason?: string; scope?: ScanScope }> {
  return apiFetch("/api/fundamentals/universe/scan", {
    method: "POST",
    body: JSON.stringify({ type, key, force }),
  });
}

export async function cancelUniverseScan(): Promise<{ cancelling: boolean }> {
  return apiFetch("/api/fundamentals/universe/scan/cancel", { method: "POST" });
}

export interface UniverseFilters {
  index?: string;
  sector?: string;
  minScore?: number;
  minResults?: number;
  minPnl?: number;
  grades?: GradeKey[];
  search?: string;
  sort?: string;
}

export async function fetchUniverseStocks(
  f: UniverseFilters = {},
): Promise<{ stocks: UniverseStock[]; count: number; sort: string }> {
  const p = new URLSearchParams();
  if (f.index) p.set("index", f.index);
  if (f.sector) p.set("sector", f.sector);
  if (f.minScore !== undefined) p.set("min_score", String(f.minScore));
  if (f.minResults !== undefined) p.set("min_results", String(f.minResults));
  if (f.minPnl !== undefined) p.set("min_pnl", String(f.minPnl));
  if (f.grades?.length) p.set("grades", f.grades.join(","));
  if (f.search) p.set("search", f.search);
  if (f.sort) p.set("sort", f.sort);
  const qs = p.toString();
  return apiFetch(`/api/fundamentals/universe/stocks${qs ? `?${qs}` : ""}`);
}

// ---- Fundamental Rating: watchlists + the paper book that tests the grades ----
export interface FundWatchlist {
  name: string;
  symbols: string[];
  count: number;
  updated_at?: string;
}

/** One grade tier's slice of the book — the answer to "how did the explosive stocks do". */
export interface TierPerformance {
  grade_key: GradeKey;
  grade: string | null;
  stocks: number;
  invested: number;
  value: number;
  pnl: number;
  avg_return_pct: number;
  win_rate: number;
  winners: number;
  best: { symbol: string; return_pct: number } | null;
  worst: { symbol: string; return_pct: number } | null;
  day_pnl?: number | null;
  day_return_pct?: number | null;
}

export interface BookPosition {
  symbol: string;
  name: string | null;
  qty: number;
  buy_price: number;
  ltp: number | null;
  invested: number;
  cash_left: number;
  value: number;
  unrealized_pnl: number;
  return_pct: number;
  grade_at_entry: string | null;
  grade_key_at_entry: GradeKey | null;
  score_at_entry: number | null;
  sector: string | null;
  opened_on: string;
}

export interface PaperBook {
  book: string;
  funded: boolean;
  note?: string;
  stocks?: number;
  allocated?: number;
  invested?: number;
  cash_left?: number;
  value?: number;
  pnl?: number;
  return_pct?: number;
  winners?: number;
  losers?: number;
  win_rate?: number;
  positions: BookPosition[];
  tiers: TierPerformance[];
  marked_at?: string | null;
}

export interface BookDay {
  session: string;
  value: number;
  invested: number;
  pnl: number;
  return_pct: number;
  stocks: number;
  win_rate: number;
  day_pnl: number | null;
  day_return_pct: number | null;
  tiers: TierPerformance[];
  movers: {
    best: { symbol: string; return_pct: number } | null;
    worst: { symbol: string; return_pct: number } | null;
  };
}

export async function fetchFundWatchlists(): Promise<{ watchlists: FundWatchlist[] }> {
  return apiFetch("/api/fundamentals/watchlists");
}

export async function saveFundWatchlist(name: string, symbols: string): Promise<FundWatchlist> {
  return apiFetch("/api/fundamentals/watchlists", {
    method: "POST",
    body: JSON.stringify({ name, symbols }),
  });
}

export async function deleteFundWatchlist(name: string): Promise<{ deleted: number }> {
  return apiFetch(`/api/fundamentals/watchlists/${encodeURIComponent(name)}`, {
    method: "DELETE",
  });
}

export async function fundWatchlist(
  name: string,
  perStock = 100000,
): Promise<{ opened: number; already_held: number; skipped?: { symbol: string; reason: string }[] }> {
  return apiFetch(`/api/fundamentals/watchlists/${encodeURIComponent(name)}/fund`, {
    method: "POST",
    body: JSON.stringify({ per_stock: perStock }),
  });
}

export async function fetchPaperBook(name: string, refresh = false): Promise<PaperBook> {
  return apiFetch(
    `/api/fundamentals/watchlists/${encodeURIComponent(name)}/book${refresh ? "?refresh=true" : ""}`,
  );
}

export async function fetchBookDaily(
  name: string,
  limit = 120,
): Promise<{ book: string; days: BookDay[]; count: number }> {
  return apiFetch(
    `/api/fundamentals/watchlists/${encodeURIComponent(name)}/daily?limit=${limit}`,
  );
}

export async function snapshotBook(name: string): Promise<{ written: boolean; reason?: string }> {
  return apiFetch(`/api/fundamentals/watchlists/${encodeURIComponent(name)}/snapshot`, {
    method: "POST",
  });
}

// ---- Natural Gas Paper Trading (Rs 2 lakh on two picked NATGASMINI strategies) ----
export interface NatGasSummary {
  book: string;
  label: string;
  symbol: string;
  enabled: boolean;
  capital: number;
  equity: number;
  realized_pnl: number;
  unrealized_pnl: number;
  total_pnl: number;
  realized_pct: number;
  unrealized_pct: number;
  total_pct: number;
  today_pnl: number;
  today_pct: number;
  margin_deployed: number;
  available_margin: number;
  total_costs: number;
  open_positions: number;
  closed_positions: number;
  win_rate: number;
  daily_loss_limit: number;
  breaker_tripped: boolean;
  market_open: boolean;
  last_run_at: string | null;
  last_opened: number;
  last_managed: number;
  last_notes: string[];
  roster: { template: string; timeframe: string }[];
}

export interface NatGasStrategy {
  template: string;
  name: string;
  timeframe: string;
  family: string;
  family_label: string;
  trades: number;
  win_rate: number;
  profit_factor: number | null;
  expectancy: number;
  max_drawdown_pct: number;
  t_stat: number | null;
  total_costs: number;
  realized_pnl: number;
  unrealized_pnl: number;
  open_positions: number;
  verdict: string;
  verdict_reasons: string[];
}

export interface NatGasPosition {
  position_id: string;
  strategy_name: string;
  timeframe: string;
  pattern: string | null;
  side: "BUY" | "SELL";
  lots: number;
  qty: number;
  entry_price: number;
  exit_price: number | null;
  ltp: number | null;
  target: number;
  stoploss: number;
  margin_used: number;
  unrealized_pnl: number | null;
  realized_pnl: number | null;
  costs: number | null;
  return_on_margin_pct: number | null;
  exit_reason: string | null;
  status: string;
  opened_at: string;
  closed_at: string | null;
}

const ngb = "/api/natgas-book";
export async function fetchNatGasSummary(): Promise<NatGasSummary> {
  return apiFetch(`${ngb}/summary`);
}
export async function fetchNatGasStrategies(): Promise<{ strategies: NatGasStrategy[] }> {
  return apiFetch(`${ngb}/strategies`);
}
export async function fetchNatGasPositions(status: "OPEN" | "CLOSED"): Promise<{ positions: NatGasPosition[] }> {
  return apiFetch(`${ngb}/positions?status=${status}`);
}
export async function toggleNatGasBook(enabled: boolean): Promise<NatGasSummary> {
  return apiFetch(`${ngb}/toggle`, { method: "POST", body: JSON.stringify({ enabled }) });
}
export async function runNatGasCycle(): Promise<{ opened: number; managed: number; notes: string[] }> {
  return apiFetch(`${ngb}/run`, { method: "POST" });
}
export async function closeAllNatGas(): Promise<{ closed: number; net_pnl: number }> {
  return apiFetch(`${ngb}/close-all`, { method: "POST" });
}

// ---- Gold Desk (MCX gold futures + Delta gold perpetuals, one book each) ----
export type GoldVenueKey = "mcx" | "delta";

export interface GoldSummary {
  venue: GoldVenueKey;
  label: string;
  currency: "INR" | "USD";
  unit_label: string;
  quote_note: string;
  symbols: string[];
  tradable_symbols: string[];
  enabled: boolean;
  capital: number;
  equity: number;
  realized_pnl: number;
  unrealized_pnl: number;
  total_pnl: number;
  realized_pct: number;
  unrealized_pct: number;
  total_pct: number;
  today_pnl: number;
  today_pct: number;
  margin_deployed: number;
  available_margin: number;
  total_costs: number;
  open_positions: number;
  closed_positions: number;
  win_rate: number;
  daily_loss_limit: number;
  breaker_tripped: boolean;
  book_floor: number;
  book_floor_pct: number;
  floor_reached: boolean;
  market_open: boolean;
  max_positions: number;
  slippage_bps: number;
  max_hold_bars: number;
  strategy_count: number;
  stream_count: number;
  fee_note: string;
  last_run_at: string | null;
  last_opened: number;
  last_managed: number;
  last_evaluated: number;
  last_notes: string[];
}

export interface GoldStrategy {
  template: string;
  timeframe: string;
  symbol: string;
  name: string;
  family: string;
  family_label: string;
  trades: number;
  win_rate: number;
  profit_factor: number | null;
  expectancy: number;
  max_drawdown_pct: number;
  t_stat: number | null;
  total_costs: number;
  realized_pnl: number;
  unrealized_pnl: number;
  open_positions: number;
  verdict: string;
  verdict_reasons: string[];
}

export interface GoldPosition {
  position_id: string;
  venue: GoldVenueKey;
  currency: string;
  strategy_name: string;
  timeframe: string;
  pattern: string | null;
  symbol: string;
  side: "BUY" | "SELL";
  units: number;
  unit_label: string;
  qty: number;
  entry_price: number;
  exit_price: number | null;
  ltp: number | null;
  target: number;
  stoploss: number;
  notional: number;
  margin_used: number;
  unrealized_pnl: number | null;
  realized_pnl: number | null;
  costs: number | null;
  return_on_margin_pct: number | null;
  exit_reason: string | null;
  status: string;
  rationale: string | null;
  bars_held: number;
  max_hold_bars: number;
  opened_at: string;
  closed_at: string | null;
}

export interface GoldBasis {
  mcx?: {
    symbol: string; price: number; source: string; quote: string;
    per_gram_inr: number; per_oz_inr: number;
  };
  delta?: {
    prices: Record<string, number>; quote: string; source: string; token_basis_usd: number;
  };
  implied?: {
    note: string;
    usd_inr_used?: number;
    delta_per_oz_inr?: number;
    mcx_per_oz_inr?: number;
    premium_pct?: number;
  };
}

export interface GoldCoverage {
  venue?: string;
  symbols?: string[];
  bars?: Record<string, Record<string, number>>;
  last_bar_at?: Record<string, string | null>;
  latest_bar_ist?: Record<string, string | null>;
  last_refresh?: Record<string, unknown>;
}

const gd = "/api/gold-desk";
export async function fetchGoldVenues(): Promise<{ venues: GoldSummary[] }> {
  return apiFetch(`${gd}/venues`);
}
export async function fetchGoldSummary(venue: GoldVenueKey): Promise<GoldSummary> {
  return apiFetch(`${gd}/summary?venue=${venue}`);
}
export async function fetchGoldStrategies(venue: GoldVenueKey): Promise<{ strategies: GoldStrategy[] }> {
  return apiFetch(`${gd}/strategies?venue=${venue}`);
}
export async function fetchGoldPositions(
  venue: GoldVenueKey,
  status: "OPEN" | "CLOSED",
): Promise<{ positions: GoldPosition[] }> {
  return apiFetch(`${gd}/positions?venue=${venue}&status=${status}`);
}
export async function fetchGoldBasis(): Promise<GoldBasis> {
  return apiFetch(`${gd}/basis`);
}
export async function fetchGoldCoverage(venue: GoldVenueKey): Promise<GoldCoverage> {
  return apiFetch(`${gd}/coverage?venue=${venue}`);
}
export async function toggleGoldDesk(venue: GoldVenueKey, enabled: boolean): Promise<GoldSummary> {
  return apiFetch(`${gd}/toggle?venue=${venue}`, { method: "POST", body: JSON.stringify({ enabled }) });
}
export async function runGoldCycle(
  venue: GoldVenueKey,
): Promise<{ venue: string; opened: number; managed: number; evaluated: number; notes: string[] }> {
  return apiFetch(`${gd}/run?venue=${venue}`, { method: "POST" });
}
export async function closeAllGold(venue: GoldVenueKey): Promise<{ closed: number; net_pnl: number }> {
  return apiFetch(`${gd}/close-all?venue=${venue}`, { method: "POST" });
}
