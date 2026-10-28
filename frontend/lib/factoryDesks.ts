// Strategy Factory tabs (2026-10-27): the Factory's 546 strategies on six modules' own instruments -
// Index Option Buying / Selling, Stock Pre-Live Buying / Selling, Momentum, Gold.
// Backend: app/services/factory_desks.py, /api/factory-desks.
import { apiFetch } from "./api";

export type FactoryDeskKey = "index-buying" | "index-selling" | "stock-buying" | "stock-selling" | "momentum" | "gold";

export interface FactoryDeskSummary {
  desk: FactoryDeskKey;
  module: string;
  label: string;
  kind: "option_buy" | "credit_spread" | "equity_long" | "perp";
  instrument: string;
  notes: string[];
  currency: "INR" | "USD";
  strategies: number;
  families: Record<string, number>;
  per_strategy_capital: number;
  desk_capital: number;
  equity: number;
  realized_pnl: number;
  unrealized_pnl: number;
  gross_pnl: number;
  fees: number;
  deployed: number;
  open_positions: number;
  closed_positions: number;
  wins: number;
  roi_pct: number;
  coverage: Record<string, number>;
  stale_tfs: string[];
  skipped: Record<string, number>;
  entry_gate: string | null;
  last_cycle_at: string | null;
  last_notes: string[];
}

export interface FactoryDeskRow {
  strategy_id: string;
  name: string;
  family: string;
  timeframe: string;
  htf: string | null;
  target_r: number | null;
  trades: number;
  wins: number;
  win_rate: number;
  net_pnl: number;
  fees: number;
  profit_factor: number | null;
  open_positions: number;
  unrealized_pnl: number;
  roi_pct: number;
}

export interface FactoryLeg {
  token: string;
  tradingsymbol: string;
  strike: number;
  option_type: "CE" | "PE";
  expiry: string;
  side: "BUY" | "SELL";
  entry: number;
}

export interface FactoryPosition {
  position_id: string;
  strategy_id: string;
  strategy_name: string;
  family: string;
  timeframe: string;
  symbol: string;
  signal_side: "BUY" | "SELL";
  kind: string;
  legs: FactoryLeg[] | null;
  lots: number;
  lot_size: number;
  credit: number | null;
  entry_px: number | null;
  under_entry: number;
  stop: number;
  target: number;
  capital_deployed: number;
  unrealized_pnl: number | null;
  realized_pnl: number | null;
  gross_pnl: number | null;
  fees: number | null;
  exit_reason: string | null;
  exit_basis: string | null;
  exit_px?: number | null;
  exit_legs?: number[] | null;
  mark_legs?: number[] | null;
  under_ltp?: number | null;
  status: "OPEN" | "CLOSED";
  currency: "INR" | "USD";
  opened_at: string | null;
  closed_at: string | null;
}

const fd = "/api/factory-desks";

export async function fetchFactoryDeskSummary(desk: FactoryDeskKey): Promise<FactoryDeskSummary> {
  return apiFetch(`${fd}/${desk}/summary`);
}

export async function fetchFactoryDeskLeaderboard(
  desk: FactoryDeskKey,
  family?: string | null,
  timeframe?: string | null,
): Promise<FactoryDeskRow[]> {
  const q = new URLSearchParams();
  if (family) q.set("family", family);
  if (timeframe) q.set("timeframe", timeframe);
  const qs = q.toString();
  const r = await apiFetch(`${fd}/${desk}/leaderboard${qs ? `?${qs}` : ""}`);
  return r.rows ?? [];
}

export async function fetchFactoryDeskPositions(
  desk: FactoryDeskKey,
  status: "OPEN" | "CLOSED" = "OPEN",
  limit = 200,
): Promise<FactoryPosition[]> {
  const r = await apiFetch(`${fd}/${desk}/positions?status=${status}&limit=${limit}`);
  return r.positions ?? [];
}
