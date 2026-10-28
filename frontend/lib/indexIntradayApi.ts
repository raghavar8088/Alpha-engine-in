/** Indian Index Intraday — the module's API client.
 *
 * Kept in its own file so this module never edits the shared lib/api.ts. The fetch helper mirrors
 * api.ts's apiFetch exactly: the same base URL, `fresh=true` on every request made during a manual
 * refresh (so it skips the server's short GET cache), a 60 s limit on GETs (a GET that never
 * answers must surface as an error, not as an empty desk), and the server's `detail` as the
 * error message.
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const BASE = "/api/index-intraday";
const GET_TIMEOUT_MS = 60000;

let FORCE_FRESH = false;

/** Run a loader with the server's GET cache bypassed for every request it fires. */
export async function freshII<T>(fn: () => Promise<T>): Promise<T> {
  FORCE_FRESH = true;
  try {
    return await fn();
  } finally {
    FORCE_FRESH = false;
  }
}

async function iiFetch<T>(path: string, init?: RequestInit & { timeoutMs?: number }): Promise<T> {
  let url = `${BASE}${path}`;
  if (FORCE_FRESH) url += `${url.includes("?") ? "&" : "?"}fresh=true`;
  const { timeoutMs: requested, ...rest } = init ?? {};
  const method = (rest.method || "GET").toUpperCase();
  const timeoutMs = requested ?? (method === "GET" ? GET_TIMEOUT_MS : 0);
  const controller = timeoutMs > 0 && !rest.signal ? new AbortController() : null;
  const timer = controller ? setTimeout(() => controller.abort(), timeoutMs) : null;
  let res: Response;
  try {
    res = await fetch(`${API_URL}${url}`, {
      ...rest,
      signal: controller?.signal ?? rest.signal,
      headers: { ...(rest.headers || {}), ...(rest.body ? { "Content-Type": "application/json" } : {}) },
    });
  } catch (e) {
    if (controller?.signal.aborted) {
      throw new Error(`The server did not answer within ${Math.round(timeoutMs / 1000)}s — it may be overloaded.`);
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

const post = <T>(path: string, body: unknown, timeoutMs?: number) =>
  iiFetch<T>(path, { method: "POST", body: JSON.stringify(body), timeoutMs });

// ── types ─────────────────────────────────────────────────────────────────────────

export type IIStatus = "Experimental" | "Backtested" | "Validated" | "Paper Trading Approved";
export type IIModel = "etf" | "index";
export type IIParams = Record<string, string | number>;

export interface IIInstrument {
  symbol: string;
  label: string;
  exchange: string;
  kind: "index" | "vix" | "etf";
  tracks: string | null;
  ltp: number | null;
  prev_close: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  change_pct: number | null;
  ticked_s_ago: number | null;
  // indexes only: the cash route a real account would trade
  etf?: string | null;
  slip_bp?: number;
  fee_rt_bp?: number;
  all_in_rt_bp?: number;
  etf_minute_value_lakh?: number | null;
  etf_order_cap?: number;
  tradable?: boolean;
}

export interface IIFeed {
  connected: boolean;
  connected_for_s: number;
  reconnects: number;
  messages: number;
  seconds_since_message: number | null;
  ticking: string[];
  last_error: string | null;
}

export interface IIOverview {
  at: string;
  session: string;
  instruments: IIInstrument[];
  feed: IIFeed;
  entry_window: string;
  square_off: string;
}

export interface IIResearch {
  generated: string;
  trials: number;
  trials_100_trades: number;
  effective_trials: number;
  luck_sharpe: number;
  validated: number;
  periods: { selection: string; validation: string; holdout: string };
  costs: string;
  history_starts: Record<string, string>;
  no_data: number;
  statuses: IIStatus[];
  verdict: string;
}

export interface IIStats {
  trades?: number | null;
  days?: number | null;
  trades_per_day?: number | null;
  win_rate?: number | null;
  mean_net_bp?: number | null;
  mean_gross_bp?: number | null;
  t_trade?: number | null;
  profit_factor?: number | null;
  expectancy_bp?: number | null;
  avg_win_bp?: number | null;
  avg_loss_bp?: number | null;
  rr?: number | null;
  total_bp?: number | null;
  ann_bp?: number | null;
  sharpe?: number | null;
  sortino?: number | null;
  max_dd_bp?: number | null;
  months_positive?: number | null;
  avg_month_bp?: number | null;
  years_positive?: number | null;
  years?: number | null;
  skew?: number | null;
  kurt?: number | null;
}

export interface IIStage3 {
  nb_median_sharpe: number | null;
  breadth_pos: number | null;
  breadth_tested: number | null;
  wf_bp: number | null;
  idx_2023_net_bp: number | null;
  idx_2023_trades: number | null;
  etf_2023_net_bp: number | null;
  etf_2023_gross_bp: number | null;
  etf_2023_trades: number | null;
  mc_p_losing_year: number | null;
  mc_median_year_bp: number | null;
  mc_p5_year_bp: number | null;
  mc_dd95_bp: number | null;
}

export interface IIStrategy {
  id: string;
  key: string;
  family: string;
  family_label: string;
  params: IIParams;
  exit: string;
  exit_label: string;
  index: string;
  round: number;
  status: IIStatus;
  stage1: boolean;
  stage2: boolean;
  failed: string | null;
  sel: IIStats;
  val: IIStats;
  sv: IIStats;
  dsr: number | null;
  dsr_raw: number | null;
  stage3?: IIStage3;
  monthly?: [string, number][];
}

export interface IIFamily {
  family: string;
  label: string;
  variants: number;
  stage1: number;
  stage2: number;
  best_sv_sharpe: number | null;
  best: { id: string; index: string; exit: string; params: IIParams; net_bp: number | null; failed: string | null } | null;
}

export interface IIDeployment {
  sid: string;
  key: string;
  family: string;
  params: IIParams;
  exit: string;
  index: string;
  model: IIModel;
  status: IIStatus;
  added_at: string;
  /** Strategy Factory deployments only */
  name?: string;
  grade?: number | null;
}

export interface IIRiskConfig {
  capital: number;
  risk_per_trade_pct: number;
  max_position_pct: number;
  max_daily_loss_pct: number;
  max_trades_per_day: number;
  max_concurrent: number;
  max_drawdown_pct: number;
  loss_streak: number;
  streak_cooldown_min: number;
  cooldown_after_exit_min: number;
  entry_from: string;
  entry_until: string;
  square_off: string;
  emergency_stop: boolean;
}

export interface IIDayState {
  day: string;
  trades: number;
  realized: number;
  loss_streak: number;
  paused_until: string | null;
  halted: boolean;
  peak_equity: number;
}

export interface IIAccount {
  capital: number;
  realized: number;
  unrealized: number;
  equity: number;
  open_positions: number;
}

export interface IIPosition {
  sid: string;
  key: string;
  family: string;
  params: IIParams;
  exit: string;
  index: string;
  model: IIModel;
  instrument: string;
  status: "OPEN" | "CLOSED";
  side: 1 | -1;
  day: string;
  entry_min: number;
  entry_time: string;
  entry_kind: string;
  entry_raw: number;
  fill: number;
  units: number;
  notional: number;
  stop: number | null;
  target: number | null;
  trail: number | null;
  best: number;
  next_min: number;
  sizing: string;
  unrealized: number;
  mark: number;
  research_status: IIStatus | null;
  opened_at: string;
  /** Strategy Factory positions only: the strategy and the setup that fired */
  name?: string;
  grade?: number | null;
  signal?: IISFSignal | null;
}

export interface IITrade {
  sid: string;
  key: string;
  family: string;
  index: string;
  model: IIModel;
  instrument: string;
  side: 1 | -1;
  units: number;
  day: string;
  entry_min: number;
  exit_min: number;
  entry_time: string;
  exit_time: string;
  entry: number;
  exit: number;
  entry_kind: string;
  exit_reason: string;
  exit_basis: string;
  gross: number;
  costs: number;
  net: number;
  net_bp: number | null;
  notional: number;
  stop: number | null;
  target: number | null;
  sizing: string | null;
  research_status: IIStatus | null;
  closed_at: string;
  /** Strategy Factory trades only */
  name?: string;
  grade?: number | null;
  signal?: IISFSignal | null;
}

export interface IITerminal {
  account: IIAccount;
  risk: IIRiskConfig;
  day: IIDayState;
  open_positions: IIPosition[];
  today_trades: IITrade[];
  deployments: IIDeployment[];
  engine: { last_tick: string | null; notes: string[]; last_opened: number; last_closed: number };
}

export interface IIEvent {
  at: string;
  kind: string;
  text: string;
  sid?: string;
  family?: string;
}

export interface IIEquityPoint {
  at: string;
  equity: number;
  realized: number;
  unrealized: number;
  open: number;
}

export interface IIReport {
  day: string;
  trades: number;
  wins: number;
  gross: number;
  costs: number;
  net: number;
  by_strategy: {
    sid: string;
    key: string;
    index: string;
    model: IIModel;
    trades: number;
    wins: number;
    gross: number;
    costs: number;
    net: number;
  }[];
  exit_reasons: Record<string, number>;
  history_appended?: Record<string, unknown>;
}

export interface IIBacktestTrade {
  day: string;
  side: 1 | -1;
  entry_min: number;
  exit_min: number;
  entry: number;
  exit: number;
  reason: string;
  gross_bp: number;
  net_bp: number;
}

export interface IIBacktest {
  family: string;
  params: IIParams;
  exit: string;
  index: string;
  start: string | null;
  end: string | null;
  days: number;
  costs: { fee_rt_bp: number; slip_bp_a_side: number; scale: number; basis: "measured" | "research" };
  stats: IIStats;
  exit_reasons: Record<string, number>;
  equity_bp: [string, number][];
  drawdown_bp: [string, number][];
  trades: IIBacktestTrade[];
  note: string;
  /** Strategy Factory runs only */
  sid?: string;
  name?: string;
  rejections?: Record<string, number>;
  volume_from?: string | null;
}

export interface IIBacktestRequest {
  sid?: string;
  family?: string;
  params?: IIParams;
  exit?: string;
  index?: string;
  start?: string;
  end?: string;
  cost_scale?: number;
  cost_basis?: "measured" | "research";
}

// ── calls ─────────────────────────────────────────────────────────────────────────

export const fetchIIOverview = () => iiFetch<IIOverview>("/overview");
export const fetchIIResearch = () => iiFetch<IIResearch>("/research");
export const fetchIIFamilies = () => iiFetch<{ families: IIFamily[] }>("/families");

export function fetchIIStrategies(q: {
  index?: string;
  family?: string;
  status?: string;
  min_trades?: number;
  stage?: number;
  sort?: string;
  limit?: number;
}) {
  const sp = new URLSearchParams();
  Object.entries(q).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  });
  return iiFetch<{ strategies: IIStrategy[]; matched: number }>(`/strategies?${sp.toString()}`);
}

export const fetchIIStrategy = (sid: string) => iiFetch<IIStrategy>(`/strategies/${encodeURIComponent(sid)}`);
export const fetchIIDeployments = () => iiFetch<{ deployments: IIDeployment[] }>("/deployments");
export const setIIDeployment = (sid: string, enabled: boolean, model: IIModel) =>
  post<{ deployments: IIDeployment[] }>("/deployments", { sid, enabled, model });
export const fetchIITerminal = () => iiFetch<IITerminal>("/terminal");

export function fetchIIJournal(q: { sid?: string; day?: string; limit?: number } = {}) {
  const sp = new URLSearchParams();
  Object.entries(q).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  });
  return iiFetch<{ trades: IITrade[] }>(`/journal${sp.toString() ? `?${sp}` : ""}`);
}

export const fetchIIEquity = (limit = 2000) => iiFetch<{ equity: IIEquityPoint[] }>(`/equity?limit=${limit}`);
export const fetchIIEvents = (limit = 200) => iiFetch<{ events: IIEvent[] }>(`/events?limit=${limit}`);
export const fetchIIReport = (day?: string) => iiFetch<IIReport>(`/report${day ? `?day=${day}` : ""}`);
export const fetchIIRisk = () => iiFetch<{ config: IIRiskConfig; day: IIDayState; account: IIAccount }>("/risk");
export const saveIIRisk = (values: Partial<IIRiskConfig>) => post<{ config: IIRiskConfig }>("/risk", values);
export const setIIEmergency = (on: boolean) =>
  post<{ emergency_stop: boolean; closed?: number }>("/risk/emergency", { on });
export const resetIIHalt = () => post<{ day: IIDayState }>("/risk/reset-halt", {});
/** A Lab run can take a while (it loads up to four years of minutes): give it two minutes. */
export const runIIBacktest = (req: IIBacktestRequest) => post<IIBacktest>("/backtest", req, 120000);
export const runIITick = () => post<{ opened: number; closed: number; notes: string[] }>("/run", {});

// ── the Strategy Factory's strategies, traded intraday here (ids like SF0123-NIFTY) ──────────────

export type IISFFamily = "chart" | "candlestick" | "structure" | "indicator" | "hybrid";
export type IISFTimeframe = "1m" | "5m" | "15m" | "30m" | "45m" | "1h" | "4h" | "1d";

export interface IISFSignal {
  pattern: string;
  detail: string;
  confidence: number;
  regime: string;
  confirmations: string[];
  stop_basis: string;
  target_basis: string;
  r_multiple: number;
  bar: string;
  timeframe: string;
}

export interface IISFStats {
  trades?: number | null;
  trades_per_day?: number | null;
  win_rate?: number | null;
  mean_net_bp?: number | null;
  mean_gross_bp?: number | null;
  t_trade?: number | null;
  profit_factor?: number | null;
  total_bp?: number | null;
  ann_bp?: number | null;
  sharpe?: number | null;
  max_dd_bp?: number | null;
  months_positive?: number | null;
  years_positive?: number | null;
  years?: number | null;
}

export interface IISFStrategy {
  id: string;
  index: string;
  etf: string | null;
  sf: string;
  name: string;
  recipe: string;
  hypothesis_name: string;
  family: IISFFamily;
  family_label: string;
  sub_family: string;
  timeframe: IISFTimeframe;
  htf: string | null;
  detector: string;
  hypothesis: string;
  confirmations: string[];
  regimes: string[];
  target_r: number;
  style: string;
  volume_dependent: boolean;
  max_trades_a_day: number;
  max_hold_min: number;
  lookback_bars: number;
  status: IIStatus;
  grade: number | null;
  grade_reasons: string[];
  failed: string | null;
  all: IISFStats;
  is: IISFStats;
  oos: IISFStats;
  dsr: number | null;
  exits: Record<string, number>;
  rejections: Record<string, number>;
  monthly?: { start: string | null; bp: number[] };
  deployed?: IIModel | null;
}

export interface IISFHeader {
  generated: string | null;
  round: string | null;
  indexes: string[] | null;
  strategies_per_index: number | null;
  trials: number | null;
  periods: { in_sample: string[]; out_of_sample: string[]; holdout: string } | null;
  costs: Record<string, { fee_rt_bp: number; slip_bp_a_side: number; etf: string | null }> | null;
  grade_counts: Record<string, number> | null;
  hypotheses: number;
  timeframes: IISFTimeframe[];
  families: Record<IISFFamily, string>;
  all_indexes: string[];
  distribution: {
    index: string;
    grades: Record<string, number>;
    ungraded: number;
    families: Record<string, number>;
    strategies: number;
    covered: boolean;
  };
}

export interface IISFHypothesis {
  key: string;
  name: string;
  family: IISFFamily;
  family_label: string;
  sub_family: string;
  hypothesis: string;
  detector: string;
  target_r: number;
  regimes: string[];
  confirmations: string[];
  intraday_only: boolean;
  uses_htf: boolean;
  timeframes: { timeframe: IISFTimeframe; id: string; grade: number | null; trades: number | null; total_bp: number | null;
                sharpe: number | null }[];
  best: { timeframe: IISFTimeframe; id: string; grade: number | null; sharpe: number | null } | null;
}

export interface IISFActivity {
  deployments: IIDeployment[];
  open_positions: IIPosition[];
  trades: IITrade[];
  events: IIEvent[];
}

export const fetchIISFHeader = (index: string) => iiFetch<IISFHeader>(`/factory?index=${encodeURIComponent(index)}`);

export function fetchIISFStrategies(q: {
  index: string;
  family?: string;
  timeframe?: string;
  grade?: string;
  sort?: string;
  q?: string;
  limit?: number;
  offset?: number;
}) {
  const sp = new URLSearchParams();
  Object.entries(q).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  });
  return iiFetch<{ strategies: IISFStrategy[]; matched: number }>(`/factory/strategies?${sp.toString()}`);
}

export const fetchIISFStrategy = (sid: string) =>
  iiFetch<IISFStrategy>(`/factory/strategies/${encodeURIComponent(sid)}`);
export const fetchIISFHypotheses = (index: string) =>
  iiFetch<{ index: string; hypotheses: IISFHypothesis[] }>(`/factory/hypotheses?index=${encodeURIComponent(index)}`);
export const fetchIISFActivity = (limit = 100) => iiFetch<IISFActivity>(`/factory/activity?limit=${limit}`);
/** A Strategy Factory id: SF0001..SF0546 on an index, e.g. SF0123-NIFTY. */
export const isSFId = (sid: string) => /^SF\d{4}-[A-Z0-9]+$/.test(sid.trim());
