// Index Option Buying picked-strategy paper accounts (12 Nov 2026). Backend: app/services/prelive_pick_books.py,
// GET /api/prelive-pick-books/{books,summary,leaderboard,positions}. Paper only: nothing here places an order.
//   best2L       Best Strategies of Top 10: ₹2 lakh, one account, the two that led both Top 10 paper accounts
//   sf_top10     the Strategy Factory tab's Rank 1-10, ₹10 lakh for each strategy
//   sf_top10_20  its Rank 11-20, ₹10 lakh for each strategy
import { apiFetch } from "./api";

export type PickBookKey = "best2L" | "sf_top10" | "sf_top10_20";

export const PICK_BOOKS: { key: PickBookKey; label: string }[] = [
  { key: "best2L", label: "Best Strategies of Top 10 · ₹2 lakh" },
  { key: "sf_top10", label: "Top 10 Performing Strategies · ₹10 lakh each" },
  { key: "sf_top10_20", label: "Top 10-20 Performing Strategies · ₹10 lakh each" },
];

export interface PickBookSummary {
  book: PickBookKey;
  label: string;
  module: string;
  desk_label: string;
  mode: string;
  enabled: boolean;
  instrument: string;
  cost_basis: string;
  board: string;
  pick_rule: string;
  notes: string[];
  picked_at: string;
  strategies: number;
  board_ranks: number[];
  // true: every strategy has its own capital (the Strategy Factory books); false: one shared account
  per_strategy: boolean;
  per_strategy_capital: number | null;
  positions_per_strategy: number | null;
  max_open_positions: number;
  position_cap: number;
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

export interface PickBookRow {
  key: string;
  name: string;
  picked_rank: number;
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
  unrealized_pnl: number;
  deployed: number;
  allocation: number | null;   // its own account's capital (per-strategy books); null in a shared account
  equity: number | null;
  roi_pct: number;             // its own account's return, or its share of the shared book
  open_positions: number;
  skipped: Record<string, number>;
  skipped_total: number;
}

export interface PickBookPosition {
  position_id: string;
  key: string;
  strategy_name: string;
  symbol: string;
  label: string | null;
  side: "BUY" | "SELL";
  lots: number;
  units: number;
  entry_px: number;
  exit_px: number | null;
  ltp: number | null;
  capital_deployed: number;
  fees: number | null;
  realized_pnl: number | null;
  unrealized_pnl: number | null;
  exit_reason: string | null;
  status: "OPEN" | "CLOSED";
  opened_at: string | null;
  closed_at: string | null;
}

const base = "/api/prelive-pick-books";

export async function fetchPickBookSummary(book: PickBookKey): Promise<PickBookSummary> {
  return apiFetch(`${base}/summary?book=${book}`);
}

export async function fetchPickBookLeaderboard(book: PickBookKey): Promise<PickBookRow[]> {
  const r = await apiFetch(`${base}/leaderboard?book=${book}`);
  return r.rows ?? [];
}

export async function fetchPickBookPositions(
  book: PickBookKey,
  status: "OPEN" | "CLOSED" = "OPEN",
  limit = 200,
): Promise<PickBookPosition[]> {
  const r = await apiFetch(`${base}/positions?book=${book}&status=${status}&limit=${limit}`);
  return r.positions ?? [];
}
