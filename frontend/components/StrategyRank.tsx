"use client";

import { useEffect, useState, type ReactNode } from "react";
import {
  fetchStrategyRanks,
  type IntradayRankFactor,
  type RankFactorMeta,
  type StrategyRankBoard,
  type StrategyRankEntry,
} from "../lib/api";

/**
 * The Rank column, shared by every strategy leaderboard in the app.
 *
 * The server ranks each desk (backend services/strategy_rank_desks.py): paper and live desks on
 * the same seven factors computed from their own closed trades, backtest boards on the metrics
 * they report. This file only shows it, so every board's Rank looks and reads the same.
 *
 * THE CELL'S TEXT IS ONLY THE RANK NUMBER. SortableTables sorts on textContent, and "1 · 91.5"
 * would not parse as a number; the score is drawn beside it by CSS (::after) from data-score.
 *
 * NO COLUMN UNTIL A BOARD HAS LOADED. If the rank cannot be fetched the table looks exactly as
 * it did before, rather than gaining a column of dashes.
 */

export type RankParams = Partial<Record<"book" | "side" | "symbol" | "venue", string | null | undefined>>;

const REFRESH_MS = 60_000;

/** One desk's rank board, refetched every minute (the server caches it for 60 s). */
export function useStrategyRanks(desk: string | null, params: RankParams = {}): StrategyRankBoard | null {
  const query = Object.entries(params)
    .filter(([, v]) => !!v)
    .map(([k, v]) => `${k}=${v}`)
    .sort()
    .join("&");
  const [board, setBoard] = useState<StrategyRankBoard | null>(null);
  useEffect(() => {
    setBoard(null);
    if (!desk) return;
    let alive = true;
    const p: Record<string, string> = {};
    for (const part of query ? query.split("&") : []) {
      const i = part.indexOf("=");
      p[part.slice(0, i)] = part.slice(i + 1);
    }
    const load = () =>
      fetchStrategyRanks(desk, p)
        .then((b) => { if (alive) setBoard(b); })
        .catch(() => { /* keep the last good board; never loaded means no column */ });
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => { alive = false; clearInterval(id); };
  }, [desk, query]);
  return board;
}

/** Rows in rank order (1 first); strategies without a rank keep their order, after them. */
export function sortByRank<T>(rows: T[], board: StrategyRankBoard | null, idOf: (r: T) => string): T[] {
  if (!board) return rows;
  return rows
    .map((r, i) => ({ r, i, rank: board.ranks[idOf(r)]?.rank ?? Number.POSITIVE_INFINITY }))
    .sort((a, b) => (a.rank === b.rank ? a.i - b.i : a.rank - b.rank))
    .map((x) => x.r);
}

/** The Tournament's board carries its rank inline on each row; same shape as a fetched one. */
export function boardFromRows(
  rows: { strategy_id: string; trades: number; rank?: number | null; rank_score?: number | null;
          rank_shrunk?: boolean; rank_factors?: IntradayRankFactor[] }[],
  minTrades = 30,
): StrategyRankBoard | null {
  const first = rows.find((r) => r.rank_factors?.length);
  if (!first?.rank_factors) return null;
  const factors: RankFactorMeta[] = first.rank_factors.map(({ key, label, weight, higher_is_better, unit }) =>
    ({ key, label, weight, higher_is_better, unit }));
  const ranks: Record<string, StrategyRankEntry> = {};
  for (const r of rows) {
    if (r.rank == null || r.rank_score == null) continue;
    const by = new Map((r.rank_factors ?? []).map((f) => [f.key, f]));
    ranks[r.strategy_id] = {
      rank: r.rank, score: r.rank_score, shrunk: !!r.rank_shrunk, trades: r.trades,
      values: factors.map((f) => by.get(f.key)?.value ?? null),
      pct: factors.map((f) => by.get(f.key)?.percentile ?? null),
    };
  }
  return { desk: "tournament", basis: "trades", min_trades: minTrades, strategies: rows.length,
           ranked: Object.keys(ranks).length, factors, ranks };
}

// Older boards sent no unit; these are the Tournament's own factors.
const UNIT_BY_KEY: Record<string, string> = {
  t_stat: "t", net_bp_per_trade: "bp", profit_factor: "ratio", max_drawdown_pct: "pct",
  max_drawdown: "inr", positive_days_pct: "pct", recent_pnl: "inr", win_rate: "fraction",
};

const rupees = (v: number) => Math.abs(v).toLocaleString("en-IN", { maximumFractionDigits: 0 });

function shown(f: RankFactorMeta, v: number | null, pct: number | null): string {
  if (v === null || v === undefined) return f.key === "profit_factor" && pct === 100 ? "no losing trade" : "n/a";
  switch (f.unit ?? UNIT_BY_KEY[f.key]) {
    case "t":
    case "ratio": return v.toFixed(2);
    case "bp": return `${v.toFixed(1)} bp`;
    case "pct": return `${v.toFixed(1)}%`;
    case "fraction": return `${(v * 100).toFixed(1)}%`;
    case "r": return `${v.toFixed(2)}R`;
    // A drawdown is a size, not a gain or a loss: no sign on it.
    case "inr": return f.higher_is_better ? `${v < 0 ? "-" : "+"}₹${rupees(v)}` : `₹${rupees(v)}`;
    default: return String(v);
  }
}

const weightText = (w: number) => (Number.isInteger(w) ? String(w) : w.toFixed(1));

/** The hover breakdown of one rank: each factor's value and how much of the board it beats. */
export function rankTitle(board: StrategyRankBoard, e: StrategyRankEntry | undefined): string {
  if (!e) return board.basis === "backtest" ? "Not ranked: no backtest result." : "Not ranked: no closed trades of its own on this desk.";
  return [
    `Rank ${e.rank} of ${board.ranked} · score ${e.score.toFixed(1)} / 100`,
    ...board.factors.map((f, i) => {
      const p = e.pct[i];
      return `${f.label} ${shown(f, e.values[i], p)}: ${p == null ? "no figure, counted as middle" : `better than ${p.toFixed(0)}%`} (weight ${weightText(f.weight)}%)`;
    }),
    ...(e.shrunk ? [`Only ${e.trades} trades: score pulled toward 50 until the record is long enough.`] : []),
  ].join("\n");
}

function RankCss() {
  // styled-jsx wants a style tag as a direct child of the outermost element, hence the fragment.
  return (
    <>
      <style jsx global>{`
        .srank-note { font-size: 12px; line-height: 1.5; color: var(--text-muted); margin: 0 0 10px; }
        .srank-cell { font-weight: 700; font-variant-numeric: tabular-nums; cursor: help; white-space: nowrap; }
        .srank-cell::after { content: " · " attr(data-score); font-weight: 500; font-size: 11px; color: var(--text-faint); }
        .srank-cell[data-score=""]::after { content: ""; }
      `}</style>
    </>
  );
}

export function RankTh() {
  return (
    <th title="Multi-factor rank on this desk (1 = best). Hover a rank for its breakdown.">
      Rank
      <RankCss />
    </th>
  );
}

export function RankTd({ board, id }: { board: StrategyRankBoard; id: string }) {
  const e = board.ranks[id];
  return (
    <td className="srank-cell" title={rankTitle(board, e)} data-score={e ? e.score.toFixed(1) : ""}>
      {e ? e.rank : "-"}
    </td>
  );
}

/** One line above a board: what the rank blends, and that it is relative. */
export function RankNote({ board, children }: { board: StrategyRankBoard; children?: ReactNode }) {
  const what = board.basis === "backtest" ? "strategies with a backtest result" : "strategies with closed trades";
  if (!board.ranked) {
    return (
      <div className="srank-note">
        <RankCss />
        <strong>Rank</strong> appears once {board.basis === "backtest" ? "strategies here have a backtest result" : "strategies here have closed trades"}.
      </div>
    );
  }
  return (
    <div className="srank-note">
      <RankCss />
      <strong>Rank</strong> blends {board.factors.length} factors, each scored as a percentile among the{" "}
      {board.ranked} {what}:{" "}
      {board.factors.map((f) => `${f.label} ${weightText(f.weight)}%${f.higher_is_better ? "" : " (lower is better)"}`).join(", ")}.
      A record under {board.min_trades} trades is pulled toward the middle. Hover a rank for its
      breakdown. A rank is relative: #1 is the best here, not proof of an edge.
      {children ? <>{" "}{children}</> : null}
    </div>
  );
}
