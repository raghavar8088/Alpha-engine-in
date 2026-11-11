// The Rank column on the Premium Strategies boards (11 Nov 2026).
//
// The paper desk runs in its own service and its server sends no rank, so each tab ranks its own strategies in the
// browser with `rankOnClient` (components/StrategyRank.tsx), the same maths the backend uses for every other desk.
// Its summary carries four of the seven factors. The t-stat, positive days and last 5 sessions need each account's
// trade-by-trade and day-by-day record, which the summary does not include, so - by the rank's own rule - those three
// drop out and their weight is shared over the four that are here.
import type { RankFactorMeta } from "../../lib/api";
import type { ClientRankRow } from "../../components/StrategyRank";
import type { Account } from "./PaperDesk";

/** The four of the seven rank factors the desk's summary carries, at their usual weights (re-scaled to 100). */
export const PREMIUM_RANK_FACTORS: RankFactorMeta[] = [
  { key: "net_bp_per_trade", label: "Net return per trade", weight: 20, higher_is_better: true, unit: "bp" },
  { key: "profit_factor", label: "Profit factor", weight: 15, higher_is_better: true, unit: "ratio" },
  { key: "max_drawdown_pct", label: "Max drawdown", weight: 15, higher_is_better: false, unit: "pct" },
  { key: "win_rate", label: "Win rate", weight: 5, higher_is_better: true, unit: "fraction" },
];

export const ACCOUNT_RANK_NOTE =
  "each account's figures, with the net return per trade as bp of its ₹10 lakh; the t-stat, positive days and last 5 sessions " +
  "need its trade-by-trade record, which this page does not load, so their weight is shared over these four";

export const BOOK_RANK_NOTE =
  "each strategy's trades in this market, with the net return per trade as bp of its ₹10 lakh; profit factor and drawdown are " +
  "the account's, so a strategy that also trades other markets counts as middle on them here; the t-stat, positive days and " +
  "last 5 sessions need its trade-by-trade record, which this page does not load, so their weight is shared over these four";

// No losing trade at all is the best profit factor, not a missing one (as the backend's _factor_value).
const profitFactor = (pf: number | null | undefined, closed: number, wins: number, realised: number) =>
  pf != null ? pf : closed > 0 && wins === closed && realised > 0 ? Number.POSITIVE_INFINITY : null;

/** One account as a rank row: its closed trades, realised P&L per closed trade, profit factor, drawdown and win rate. */
export function accountRankRow(a: Account): ClientRankRow {
  const closed = a.closed || 0;
  const capital = a.capital || 1_000_000;
  return {
    id: a.id,
    trades: closed,
    tiebreak: a.equity - a.capital,
    values: {
      net_bp_per_trade: closed ? (a.realised / closed / capital) * 1e4 : null,
      profit_factor: profitFactor(a.profit_factor, closed, a.wins, a.realised),
      max_drawdown_pct: closed ? a.max_dd_pct : null,
      win_rate: closed ? a.wins / closed : null,
    },
  };
}

/** One strategy's book in one market: its own trades there; profit factor and drawdown only when the account
 *  trades nothing else (then the account's figures are this book's). */
export function bookRankRow(id: string, b: { closed: number; wins: number; pnl: number; unrealised: number },
                            acct: Account | undefined, onlyMarket: boolean): ClientRankRow {
  const closed = b.closed || 0;
  const realised = b.pnl - (b.unrealised || 0);
  const capital = acct?.capital || 1_000_000;
  const whole = onlyMarket && acct;
  return {
    id,
    trades: closed,
    tiebreak: b.pnl,
    values: {
      net_bp_per_trade: closed ? (realised / closed / capital) * 1e4 : null,
      profit_factor: whole ? profitFactor(acct.profit_factor, acct.closed, acct.wins, acct.realised) : null,
      max_drawdown_pct: whole && acct.closed ? acct.max_dd_pct : null,
      win_rate: closed ? b.wins / closed : null,
    },
  };
}
