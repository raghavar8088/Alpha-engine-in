// Commodity Auto Positions (2026-10-30): 220 paper accounts selling an MCX option strangle every
// evening on the four minis. Backend: app/services/commodity_auto.py, /api/commodity-auto.
import { apiFetch } from "./api";

export type CautoCommodity = "NATGASMINI" | "CRUDEOILM" | "GOLDM" | "SILVERM";

export interface CautoTotals {
  starting: number;
  equity: number;
  realized: number;
  unrealized: number;
  open: number;
  trades: number;
  wins: number;
}

export interface CautoSummary {
  commodities: CautoCommodity[];
  strategies: { offset: number; label: string }[];
  sizes: number[];
  accounts: number;
  stop_pct: number;
  per_commodity: Record<CautoCommodity, CautoTotals>;
  mcx_open: boolean;
  switch_on: boolean;
  next_entry_at: string | null;
  last_run: {
    day: string;
    started_at: string | null;
    finished_at: string | null;
    counts: Record<string, number>;
    closed_before: Record<string, number>;
  } | null;
  store: string;
}

export interface CautoLeg {
  strike: number;
  type: "CE" | "PE";
  token: string;
  symbol: string;
  entry: number;
  entry_bid: number | null;
  entry_ask: number | null;
  entry_ltp: number | null;
  touch_qty: number | null;
}

export interface CautoPosition {
  id: string;
  account_id: string;
  commodity: CautoCommodity;
  offset: number;
  strategy: string;
  size: number;
  entry_day: string;
  expiry: string;
  future_at_entry: number;
  atm_strike: number;
  call: CautoLeg;
  put: CautoLeg;
  lots: number;
  multiplier: number;
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
  updated_at: string | null;
}

export interface CautoAccount {
  account_id: string;
  commodity: CautoCommodity;
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
  open: CautoPosition | null;
  last_closed: CautoPosition | null;
  last_entry: { day: string; outcome: string | null } | null;
}

const base = "/api/commodity-auto";

export async function fetchCautoSummary(): Promise<CautoSummary> {
  return apiFetch(`${base}/summary`);
}

export async function fetchCautoAccounts(commodity: CautoCommodity): Promise<CautoAccount[]> {
  const r = await apiFetch(`${base}/accounts?commodity=${commodity}`);
  return r.accounts ?? [];
}

export async function fetchCautoTrades(commodity: CautoCommodity, size?: number | null, limit = 300): Promise<CautoPosition[]> {
  const q = new URLSearchParams({ commodity, limit: String(limit) });
  if (size) q.set("size", String(size));
  const r = await apiFetch(`${base}/trades?${q.toString()}`);
  return r.trades ?? [];
}
