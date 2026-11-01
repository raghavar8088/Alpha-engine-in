// Crypto Trading: the top ten cryptocurrencies paper traded by the Strategy Factory's and the Strategies
// module's strategies, one $10,000 account per strategy-cryptocurrency pair, on Delta Exchange India's
// perpetuals. Backend: app/services/crypto_trading (engine, views), /api/crypto-trading.
import { apiFetch } from "./api";

const API = "/api/crypto-trading";

export type PairStatus = "eligible" | "failed_validation" | "insufficient_data" | "unsupported" | "error";
export type Library = "factory" | "strategies";
export type DeskStatus = "running" | "paused" | "stopped";

export interface Coin {
  rank: number;
  id: string;
  symbol: string;
  name: string;
  market_cap_usd: number | null;
  price_usd: number | null;
  venue_symbol?: string;
  turnover_24h_usd?: number;
  open_interest_usd?: number;
  history_days?: number;
  verdict: "selected" | "excluded";
  reason?: string;
  contract_value?: number;
  taker_fee?: number;
  funding_interval_s?: number;
  launch_time?: string;
  slippage_bps?: number;
  slippage?: { basis: string; spread_bps?: number };
}

export interface Universe {
  selected: Coin[];
  candidates?: Coin[];
  ranking_source: string;
  venue: string;
  selected_at: string;
  ranking_as_of: string | null;
  screens: Record<string, number>;
  imported_at?: string;
}

export interface Metrics {
  trades: number;
  wins?: number;
  win_rate?: number;
  net_pnl: number;
  gross_profit?: number;
  gross_loss?: number;
  total_costs?: number;
  profit_factor: number | null;
  expectancy?: number;
  avg_r?: number;
  max_drawdown_pct?: number;
  return_pct?: number;
  cagr_pct?: number | null;
  sharpe?: number | null;
  sortino?: number | null;
  largest_win?: number;
  largest_loss?: number;
  max_consecutive_losses?: number;
  exposure_pct?: number;
}

export interface Overview {
  desk: {
    status: DeskStatus;
    since: string | null;
    by: string | null;
    last_action: string | null;
    last_cycle_at: string | null;
    last_cycle: {
      pairs: number;
      deciding: number;
      signals: number;
      opened: number;
      closed: Record<string, number>;
      open: number;
      skips: Record<string, number>;
      ms: number;
    } | null;
    last_reset: { at: string; positions_archived: number } | null;
    switch_on: boolean;
    reset_phrase: string;
  };
  universe: Universe;
  sweep: {
    imported_at?: string;
    pairs?: number;
    strategies?: number;
    counts?: Partial<Record<PairStatus, number>>;
    libraries?: { strategies_registry: number; factory_catalog: number };
    code_version?: string;
    run_on?: string;
  };
  accounts: {
    total: number;
    capital_each: number;
    by_library: Partial<Record<Library, Record<PairStatus, number>>>;
    eligible_grid: Record<string, Record<string, number>>;
  };
  money: {
    accounts?: number;
    cash?: number;
    unrealized?: number;
    realized?: number;
    fees?: number;
    funding?: number;
    trades?: number;
    wins?: number;
    losses?: number;
    halted?: number;
    traded?: number;
  };
  open_positions: number;
  per_coin: Record<string, { open: number; closed: number; realized: number; unrealized: number }>;
  equity_curve: { ts: string; equity: number; capital: number; accounts: number; open: number }[];
  method: Record<string, string>;
}

export interface StrategyRow {
  strategy_id: string;
  library: Library;
  base_id: string;
  name: string;
  family: string;
  sub_family?: string;
  timeframe: string;
  htf: string | null;
  support: "supported" | "adapted" | "unsupported";
  adaptation: string | null;
  unsupported_reason: string | null;
  instrument: string | null;
  rules: {
    hypothesis?: string;
    entry?: string;
    regimes?: string[];
    stop?: string;
    target?: string;
    risk_reward?: number;
    exit?: string;
    sizing?: string;
    params?: Record<string, number | string | boolean>;
    confirmations?: { name: string; params: Record<string, unknown> }[];
    expected_win_rate?: number;
    declared_timeframes?: string[];
  };
}

export interface BacktestRow {
  pair_id: string;
  strategy_id: string;
  name: string;
  library: Library;
  family: string;
  timeframe: string;
  symbol: string;
  coin: string;
  status: PairStatus;
  status_reason: string;
  grade: number | null;
  funding_total?: number;
  no_trade_bar_pct?: number;
  span_days?: number;
  bars_tested?: number;
  slippage_bps?: number;
  overall?: Metrics;
  out_of_sample?: Metrics;
}

export interface BacktestDoc extends BacktestRow {
  in_sample?: Metrics;
  grade_reasons?: string[];
  window_start?: string;
  window_end?: string;
  equity_curve?: [number, number][];
  trades_sample?: { entry_ts: string; exit_ts: string; side: string; entry: number; exit: number; qty: number;
                    net: number; costs: number; r: number; reason: string; bars_held: number }[];
  rejections?: Record<string, number>;
  engine?: string;
  unit_contracts?: number;
  funding_exchanges?: number;
  taker_fee?: number;
  run_at?: string;
  code_version?: string;
}

export interface Position {
  _id: string;
  pair_id: string;
  strategy_id: string;
  library: Library;
  name: string | null;
  timeframe: string;
  symbol: string;
  coin: string;
  side: "BUY" | "SELL";
  direction: "long" | "short";
  contracts: number;
  contract_value: number;
  qty_coin: number;
  entry_px: number;
  entry_mid: number | null;
  entry_basis: string;
  entry_ts: string;
  stop: number | null;
  target: number | null;
  notional_usd: number;
  leverage: number;
  margin_usd: number;
  liq_px: number;
  entry_fee: number;
  funding_paid: number;
  funding_exchanges: number;
  status: "OPEN" | "CLOSED";
  mark: number;
  unrealized_pnl: number;
  max_hold_bars?: number;
  bars_held?: number;
  risk_usd: number | null;
  exit_px?: number;
  exit_ts?: string;
  exit_reason?: string;
  exit_basis?: string;
  exit_fee?: number;
  gross_pnl?: number;
  costs?: number;
  net_pnl?: number;
  r_multiple?: number | null;
  closed_at?: string;
}

export interface Signal {
  at: string;
  pair_id: string;
  strategy_id: string;
  name: string | null;
  library: Library;
  symbol: string;
  coin: string;
  timeframe: string;
  bar_ts: string;
  side: "BUY" | "SELL";
  entry_ref: number | null;
  stop: number | null;
  target: number | null;
  outcome: string;
  position_id?: string;
  fill_px?: number;
  contracts?: number;
  detail?: Record<string, unknown>;
}

export interface AccountRow {
  _id: string;
  strategy_id: string;
  name: string;
  library: Library;
  family: string;
  timeframe: string;
  symbol: string;
  coin: string;
  status: PairStatus;
  status_reason: string;
  grade: number | null;
  eligible: boolean;
  cash: number;
  equity: number | null;
  unrealized_pnl: number | null;
  realized_pnl: number;
  fees: number;
  funding: number;
  trades: number;
  wins: number;
  losses: number;
  max_drawdown_pct: number;
  halt: { kind: string; reason: string; until_day?: string } | null;
  open_position_id: string | null;
  last_trade_at: string | null;
  return_pct: number;
  win_rate: number | null;
  profit_factor: number | null;
  backtest?: { trades: number; net_pnl: number; profit_factor: number | null; oos?: { trades: number; net_pnl: number } };
}

export interface PairDetail {
  backtest: BacktestDoc | null;
  account: (AccountRow & { capital: number; created_at?: string; day_start_equity?: number }) | null;
  strategy: StrategyRow | null;
  positions: Position[];
  equity_curve: [string, number][];
}

const qs = (p: Record<string, string | number | boolean | null | undefined>) => {
  const q = new URLSearchParams();
  Object.entries(p).forEach(([k, v]) => {
    if (v !== null && v !== undefined && v !== "") q.set(k, String(v));
  });
  const s = q.toString();
  return s ? `?${s}` : "";
};

export const fetchOverview = (): Promise<Overview> => apiFetch(`${API}/overview`);
export const fetchUniverse = (): Promise<Universe> => apiFetch(`${API}/universe`);
export const fetchLibrary = (p: Record<string, string | number | undefined>): Promise<{
  total: number; rows: StrategyRow[]; counts: Record<string, Record<string, number>> }> => apiFetch(`${API}/library${qs(p)}`);
export const fetchBacktests = (p: Record<string, string | number | undefined>): Promise<{ total: number; rows: BacktestRow[] }> =>
  apiFetch(`${API}/backtests${qs(p)}`);
export const fetchPair = (id: string): Promise<PairDetail> => apiFetch(`${API}/pair${qs({ id })}`);
export const fetchSignals = async (p: Record<string, string | number | boolean | undefined>): Promise<Signal[]> =>
  (await apiFetch(`${API}/signals${qs(p)}`)).signals ?? [];
export const fetchPositions = async (p: Record<string, string | number | undefined>): Promise<Position[]> =>
  (await apiFetch(`${API}/positions${qs(p)}`)).positions ?? [];
export const fetchAccounts = (p: Record<string, string | number | boolean | undefined>): Promise<{ total: number; rows: AccountRow[] }> =>
  apiFetch(`${API}/accounts${qs(p)}`);

export const controlDesk = (action: "start" | "pause" | "resume") =>
  apiFetch(`${API}/control`, { method: "POST", body: JSON.stringify({ action }) });
export const resetDesk = (confirm: string) =>
  apiFetch(`${API}/reset`, { method: "POST", body: JSON.stringify({ confirm }) });
