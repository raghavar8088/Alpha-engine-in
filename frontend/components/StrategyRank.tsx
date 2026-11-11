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

export type RankParams = Partial<Record<"book" | "desk" | "side" | "symbol" | "venue", string | null | undefined>>;

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

/** Sessions on which the strategy closed at least one trade, from its rank board; null when the
 *  board has no day count (a backtest board, or a server older than the field). */
export function rankDays(board: StrategyRankBoard | null, id: string): number | null {
  const e = board?.ranks[id] as (StrategyRankEntry & { days?: number | null }) | undefined;
  return typeof e?.days === "number" ? e.days : null;
}

/** A board for a desk whose server sends no rank, computed here with the backend's own maths
 *  (services/strategy_rank.py rank_rows + compact): each factor an average-rank percentile among the strategies with
 *  closed trades (ties share a rank); a factor nobody has is dropped and the rest re-weighted to 100; a figure one
 *  strategy lacks counts as the middle (50); a record under `minTrades` trades is pulled toward 50. A value may be
 *  Infinity (a profit factor with no losing trade): it ranks best and prints as "no losing trade". */
export type ClientRankRow = { id: string; trades: number; tiebreak?: number; values: Record<string, number | null | undefined> };

function round1(x: number): number {
  // Python's round(x, 1), which the backend uses: the exact binary value, an exact half going to the even digit
  // (81.25 -> 81.2). JavaScript's toFixed rounds an exact half up, so the halves are handled here first.
  const s = Math.abs(x).toFixed(60);
  const dot = s.indexOf(".");
  if (/^50*$/.test(s.slice(dot + 2))) {
    const tenths = Number(s.slice(0, dot) + s[dot + 1]);
    return ((x < 0 ? -1 : 1) * (tenths % 2 === 0 ? tenths : tenths + 1)) / 10;
  }
  return Number(x.toFixed(1));
}

function percentiles(values: (number | null)[], higherIsBetter: boolean): (number | null)[] {
  const present = values
    .map((v, i) => [v, i] as [number | null, number])
    .filter((x): x is [number, number] => x[0] !== null)
    .map(([v, i]) => [higherIsBetter ? v : -v, i] as [number, number])
    .sort((a, b) => (a[0] === b[0] ? a[1] - b[1] : a[0] < b[0] ? -1 : 1));
  const out: (number | null)[] = values.map(() => null);
  const n = present.length;
  if (n === 0) return out;
  if (n === 1) {
    out[present[0][1]] = 100;
    return out;
  }
  let j = 0;
  while (j < n) {
    let k = j;
    while (k + 1 < n && present[k + 1][0] === present[j][0]) k++;
    const p = ((j + k) / 2 / (n - 1)) * 100;
    for (let m = j; m <= k; m++) out[present[m][1]] = p;
    j = k + 1;
  }
  return out;
}

export function rankOnClient(rows: ClientRankRow[], factors: RankFactorMeta[],
                             opts: { desk: string; minTrades?: number; basisNote?: string }): StrategyRankBoard {
  const minTrades = opts.minTrades ?? 30;
  const value = (r: ClientRankRow, key: string): number | null => {
    const v = r.values[key];
    return v == null || Number.isNaN(v) ? null : v;
  };
  const scored = rows.filter((r) => r.trades > 0);
  const used = factors.filter((f) => scored.some((r) => value(r, f.key) !== null));
  const total = used.reduce((s, f) => s + f.weight, 0) || 1;
  const pcts = used.map((f) => percentiles(scored.map((r) => value(r, f.key)), f.higher_is_better));
  const entries = scored.map((r, i) => {
    const raw = used.reduce((s, f, j) => s + f.weight * (pcts[j][i] ?? 50), 0) / total;
    const trust = Math.min(1, r.trades / Math.max(minTrades, 1));
    return { r, i, score: round1(50 + (raw - 50) * trust), shrunk: trust < 1 };
  });
  entries.sort((a, b) => b.score - a.score || (b.r.tiebreak ?? 0) - (a.r.tiebreak ?? 0));
  const ranks: Record<string, StrategyRankEntry> = {};
  entries.forEach((e, n) => {
    ranks[e.r.id] = {
      rank: n + 1, score: e.score, shrunk: e.shrunk, trades: e.r.trades,
      values: used.map((f) => {
        const v = value(e.r, f.key);
        return v != null && Number.isFinite(v) ? v : null;
      }),
      pct: used.map((_, j) => {
        const p = pcts[j][e.i];
        return p == null ? null : round1(p);
      }),
    };
  });
  return {
    desk: opts.desk, basis: "trades", basis_note: opts.basisNote ?? null, min_trades: minTrades,
    strategies: rows.length, ranked: entries.length,
    factors: used.map((f) => ({ ...f, weight: round1((f.weight / total) * 100) })), ranks,
  };
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
      {board.factors.map((f) => `${f.label} ${weightText(f.weight)}%${f.higher_is_better ? "" : " (lower is better)"}`).join(", ")}.{" "}
      {board.basis_note ? `Computed on ${board.basis_note}. ` : ""}A record under {board.min_trades}{" "}
      trades is pulled toward the middle. Hover a rank for its breakdown. A rank is relative: #1 is
      the best here, not proof of an edge.
      {children ? <>{" "}{children}</> : null}
    </div>
  );
}
