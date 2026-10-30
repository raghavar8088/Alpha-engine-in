// The auto option-selling desks: Commodity Auto Positions (MCX minis, /api/commodity-auto) and Indian
// Market Option Auto Selling (index options, /api/index-auto). Both run 11 strike distances x 5 account
// sizes per instrument and answer with the same shapes. Backends: app/services/commodity_auto.py and
// app/services/index_auto.py.
import { apiFetch } from "./api";

export type AutoDeskApi = "/api/commodity-auto" | "/api/index-auto";

export interface AutoTotals {
  starting: number;
  equity: number;
  realized: number;
  unrealized: number;
  open: number;
  trades: number;
  wins: number;
}

export interface AutoSummary {
  instruments: string[];
  instrument_info: Record<string, { label: string; sub: string }>;
  strategies: { offset: number; label: string }[];
  sizes: number[];
  accounts: number;
  stop_pct: number;
  per_instrument: Record<string, AutoTotals>;
  market_open: boolean;
  market_label: string;
  entry_label: string;
  switch_on: boolean;
  next_entry_at: string | null;
  last_run: {
    day: string;
    started_at: string | null;
    finished_at: string | null;
    counts: Record<string, number>;
    closed_before: Record<string, number>;
  } | null;
}

export interface AutoLeg {
  strike: number;
  type: "CE" | "PE";
  token: string;
  symbol: string | null;
  entry: number;
  entry_bid: number | null;
  entry_ask: number | null;
  entry_ltp: number | null;
  touch_qty: number | null;
}

export interface AutoPosition {
  id: string;
  account_id: string;
  instrument: string;
  offset: number;
  strategy: string;
  size: number;
  entry_day: string;
  expiry: string;
  atm_strike: number;
  call: AutoLeg;
  put: AutoLeg;
  lots: number;
  qty: number;
  credit: number;
  margin_per_pair: number;
  margin_source: string | null;
  margin_blocked: number;
  allocated: number;
  stop_loss: number;
  entry_fees: number;
  status: "OPEN" | "CLOSED";
  unrealized_pnl: number | null;
  mark: { call: number; put: number; basis: string } | null;
  entry_at: string | null;
  scheduled_exit_at: string | null;
  exit_at: string | null;
  exit_reason: string | null;
  exit_basis: string | null;
  exit: { call: number; put: number } | null;
  gross_pnl: number | null;
  fees: number | null;
  realized_pnl: number | null;
}

export interface AutoAccount {
  account_id: string;
  instrument: string;
  offset: number;
  strategy: string;
  size: number;
  starting_capital: number;
  equity: number;
  available: number;
  margin_used: number;
  realized: number;
  trades: number;
  wins: number;
  fees: number;
  open: AutoPosition | null;
  last_closed: AutoPosition | null;
  last_entry: { day: string; outcome: string | null } | null;
}

// The two backends name their instrument parameter after what it is.
const param = (api: AutoDeskApi) => (api === "/api/index-auto" ? "index" : "commodity");

export async function fetchAutoSummary(api: AutoDeskApi): Promise<AutoSummary> {
  return apiFetch(`${api}/summary`);
}

export async function fetchAutoAccounts(api: AutoDeskApi, instrument: string): Promise<AutoAccount[]> {
  const r = await apiFetch(`${api}/accounts?${param(api)}=${encodeURIComponent(instrument)}`);
  return r.accounts ?? [];
}

export async function fetchAutoTrades(api: AutoDeskApi, instrument: string, size?: number | null, limit = 300): Promise<AutoPosition[]> {
  const q = new URLSearchParams({ [param(api)]: instrument, limit: String(limit) });
  if (size) q.set("size", String(size));
  const r = await apiFetch(`${api}/trades?${q.toString()}`);
  return r.trades ?? [];
}
