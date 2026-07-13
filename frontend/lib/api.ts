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
  };
  open_positions: Array<{ key: string; strategy_id: string; timeframe: string; option_type: string; strike: number; entry_premium: number; mark: number; unrealized: number; qty: number; entry_ts: string }>;
  today: { session: string; trades: number; net_pnl: number; peak_capital: number; roi_pct: number | null; wins: number } | null;
}
export interface PreLiveScore {
  key: string; strategy_id: string; timeframe: string; trades: number; wins: number;
  win_rate: number; profit_factor: number | null; expectancy: number; net_pnl: number;
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
