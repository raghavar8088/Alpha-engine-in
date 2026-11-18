// Top-10 paper books (2026-10-27): Rs 2 lakh and Rs 10 lakh accounts copying the top 10 by Rank of
// Zero Hero, NIFTY 50 Option Scalping, Index Option Buying (NIFTY 50), the two Stock Pre-Live desks
// and Commodity Trading. Backend: app/services/top10_books.py, /api/top10-books.
import { apiFetch } from "./api";

export type Top10BookKey = "top2L" | "top10L";
// prem2L / prem50k: "Premium Strategy" picked books on NIFTY 50 Option Scalping (2026-11-16), the
// owner's own three picks in a Rs 2 lakh and a Rs 50,000 account, on the same engine. Kept apart from
// Top10BookKey, which the stock desk pages narrow on.
// 17 Nov 2026, also on NIFTY 50 Option Scalping: 20 Rank-band accounts (rank1_5_2L ... rank46_50_10L) and 8
// Paper-book top-4 accounts (pb1_2L ... pb4_10L), shown together by group (fetchPickedAccounts).
export type RankBandBookKey = `rank${number}_${number}_${"2L" | "10L"}`;
export type PaperTopBookKey = `pb${number}_${"2L" | "10L"}`;
// 18 Nov 2026: the desk's Rank 1-25, each alone on Rs 2 lakh (each1_2L ... each25_2L, group "top25-each", shown
// in sets of five), and "Prime Premium Strategies" (prime2L / prime10L): the Paper book's top two in one account.
export type EachBookKey = `each${number}_2L`;
export type PickedBookKey = "prem2L" | "prem50k" | "prime2L" | "prime10L" | RankBandBookKey | PaperTopBookKey
  | EachBookKey;
export type PickedGroup = "rank-band" | "paper-top4" | "top25-each";
export type AnyBookKey = Top10BookKey | PickedBookKey;
export type Top10Desk = "zero-hero" | "nifty-scalp" | "prelive" | "stock-buying" | "stock-selling" | "commodity"
  | "strategy-factory";

export const TOP10_BOOKS: { key: Top10BookKey; label: string }[] = [
  { key: "top2L", label: "Top 10 Paper Trade · ₹2 lakh" },
  { key: "top10L", label: "Top 10 Paper Trade · ₹10 lakh" },
];

export interface Top10Summary {
  desk: string;
  desk_label: string;
  book: AnyBookKey;
  label: string;
  mode: string;
  enabled: boolean;
  instrument: string;
  cost_basis: string;
  board: string;
  notes: string[];
  // A picked book (the owner's own picks) says what they are; absent on the Top-10 books.
  picked?: boolean;
  pick_rule?: string | null;
  // "rank-band" | "paper-top4" for accounts shown together; null on the others.
  group?: string | null;
  picked_at: string;
  roster: string[];
  // the picks' names, in pick order (absent on an older server)
  pick_names?: string[];
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

export async function fetchTop10Summary(desk: Top10Desk, book: AnyBookKey): Promise<Top10Summary> {
  return apiFetch(`${t10}/${desk}/summary?book=${book}`);
}

export async function fetchTop10Leaderboard(desk: Top10Desk, book: AnyBookKey): Promise<Top10Row[]> {
  const r = await apiFetch(`${t10}/${desk}/leaderboard?book=${book}`);
  return r.rows ?? [];
}

export async function fetchTop10Positions(
  desk: Top10Desk,
  book: AnyBookKey,
  status: "OPEN" | "CLOSED" = "OPEN",
  limit = 200,
): Promise<Top10Position[]> {
  const r = await apiFetch(`${t10}/${desk}/positions?book=${book}&status=${status}&limit=${limit}`);
  return r.positions ?? [];
}

export interface PickedAccounts {
  desk: string;
  group: PickedGroup;
  groups: Record<string, string[]>;
  accounts: Top10Summary[];
  total: number;
}

/** One group of picked accounts, every account summarised. null when the server does not have the group
 *  yet (an older backend answers 404): the page then says so instead of showing another book's numbers. */
export async function fetchPickedAccounts(desk: Top10Desk, group: PickedGroup): Promise<PickedAccounts | null> {
  try {
    return await apiFetch(`${t10}/${desk}/accounts?group=${group}`);
  } catch (e) {
    const msg = e instanceof Error ? e.message : "";
    if (msg === "Not Found" || msg.startsWith("No '") || msg.includes("404")) return null;
    throw e;
  }
}
