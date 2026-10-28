// Top-10 paper books (2026-10-27): Rs 2 lakh and Rs 10 lakh accounts copying the top 10 by Rank of
// Zero Hero, NIFTY 50 Option Scalping, Index Option Buying (NIFTY 50), the two Stock Pre-Live desks
// and Commodity Trading. Backend: app/services/top10_books.py, /api/top10-books.
import { apiFetch } from "./api";

export type Top10BookKey = "top2L" | "top10L";
export type Top10Desk = "zero-hero" | "nifty-scalp" | "prelive" | "stock-buying" | "stock-selling" | "commodity"
  | "strategy-factory";

export const TOP10_BOOKS: { key: Top10BookKey; label: string }[] = [
  { key: "top2L", label: "Top 10 Paper Trade · ₹2 lakh" },
  { key: "top10L", label: "Top 10 Paper Trade · ₹10 lakh" },
];

export interface Top10Summary {
  desk: string;
  desk_label: string;
  book: Top10BookKey;
  label: string;
  mode: string;
  enabled: boolean;
  instrument: string;
  cost_basis: string;
  board: string;
  notes: string[];
  picked_at: string;
  roster: string[];
  strategies: number;
  max_open_positions: number;
  position_cap: number;
  skip_expiry_day: boolean;
  desk_capital: number;
  equity: number;
  realized_pnl: number;
  unrealized_pnl: number;
  gross_pnl: number;
  fees: number;
  deployed: number;
  available_cash: number;
  open_positions: number;
  closed_positions: number;
  wins: number;
  roi_pct: number;
  skipped: Record<string, number>;
  copying_since: string | null;
}

export interface Top10Row {
  key: string;
  strategy_id: string;
  name: string;
  picked_rank: number;
  // null where the ten were not picked by a Rank score (Strategy Factory: best combined backtest).
  picked_score: number | null;
  picked_trades: number;
  picked_bp: number | null;
  picked_net_pnl: number | null;
  trades: number;
  wins: number;
  win_rate: number;
  net_pnl: number;
  gross_pnl: number;
  fees: number;
  roi_pct: number;
  open_positions: number;
  skipped: Record<string, number>;
  skipped_total: number;
}

export interface Top10Position {
  position_id: string;
  key: string;
  strategy_name: string;
  symbol: string;
  label: string | null;
  side: "BUY" | "SELL";
  lots: number;
  lot_size: number | null;
  units: number;
  entry_px: number;
  cost_per_lot: number;
  capital_deployed: number;
  ltp: number | null;
  unrealized_pnl: number | null;
  realized_pnl: number | null;
  gross_pnl: number | null;
  fees: number | null;
  exit_px: number | null;
  exit_reason: string | null;
  status: "OPEN" | "CLOSED";
  expiry: string | null;
  opened_at: string | null;
  closed_at: string | null;
}

const t10 = "/api/top10-books";

export async function fetchTop10Summary(desk: Top10Desk, book: Top10BookKey): Promise<Top10Summary> {
  return apiFetch(`${t10}/${desk}/summary?book=${book}`);
}

export async function fetchTop10Leaderboard(desk: Top10Desk, book: Top10BookKey): Promise<Top10Row[]> {
  const r = await apiFetch(`${t10}/${desk}/leaderboard?book=${book}`);
  return r.rows ?? [];
}

export async function fetchTop10Positions(
  desk: Top10Desk,
  book: Top10BookKey,
  status: "OPEN" | "CLOSED" = "OPEN",
  limit = 200,
): Promise<Top10Position[]> {
  const r = await apiFetch(`${t10}/${desk}/positions?book=${book}&status=${status}&limit=${limit}`);
  return r.positions ?? [];
}
