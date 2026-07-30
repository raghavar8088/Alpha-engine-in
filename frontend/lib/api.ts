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

async function apiFetch(path: string, init?: RequestInit) {
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
}

export interface IntradayDeskStatus {
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
  strategy_id: string;
  name: string;
  category: string;
  trades: number;
  win_rate: number;
  net_pnl: number;
  allocated_capital: number | null;
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
