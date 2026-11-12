"use client";

// Commodity Trading rank-band paper accounts (12 Nov 2026): Top 5, Top 5-10, Top 10-15, Top 15-20. Each book is five
// strategies frozen at their Rank band, each with its own ₹10 lakh, copied from the desk's own trades.
// Backend: app/services/rank_band_books.py (GET /api/rank-band-books/...). Paper only: nothing here places an order.
import { useCallback, useEffect, useState } from "react";
import GlassPanel from "./GlassPanel";
import ErrorBanner from "./ErrorBanner";
import { apiFetch } from "../lib/api";

export type RankBandKey = "top5" | "top5_10" | "top10_15" | "top15_20";
export const RANK_BANDS: { key: RankBandKey; label: string }[] = [
  { key: "top5", label: "Top 5 Paper Trading" },
  { key: "top5_10", label: "Top 5-10 Paper Trading" },
  { key: "top10_15", label: "Top 10-15 Paper Trading" },
  { key: "top15_20", label: "Top 15-20 Paper Trading" },
];

type Summary = {
  label: string; desk_label: string; board: string; instrument: string; cost_basis: string; notes: string[];
  picked_at: string; strategies: number; board_ranks: number[]; per_strategy_capital: number; desk_capital: number;
  equity: number; realized_pnl: number; unrealized_pnl: number; gross_pnl: number; fees: number; deployed: number;
  available_cash: number; open_positions: number; closed_positions: number; wins: number; roi_pct: number;
  skipped: Record<string, number>; copying_since: string | null; enabled: boolean;
};
type Row = {
  key: string; name: string; picked_rank: number; picked_score: number | null; picked_trades: number;
  picked_bp: number | null; picked_net_pnl: number | null; trades: number; wins: number; win_rate: number;
  net_pnl: number; gross_pnl: number; fees: number; unrealized_pnl: number; deployed: number; allocation: number;
  equity: number; roi_pct: number; open_positions: number; skipped: Record<string, number>; skipped_total: number;
};
type Position = {
  position_id: string; strategy_name: string; symbol: string; label: string | null; side: string; lots: number;
  units: number; entry_px: number; exit_px: number | null; ltp: number | null; capital_deployed: number;
  fees: number | null; realized_pnl: number | null; unrealized_pnl: number; opened_at: string; closed_at: string | null;
  exit_reason: string | null;
};

const REFRESH_MS = 30000;
const inr = (v: number | null | undefined, dp = 0) =>
  v === null || v === undefined ? "—" : `₹${v.toLocaleString("en-IN", { maximumFractionDigits: dp })}`;
const signed = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${v >= 0 ? "+" : "−"}₹${Math.abs(v).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
const tone = (v: number | null | undefined): "gain" | "loss" | "" => ((v ?? 0) > 0 ? "gain" : (v ?? 0) < 0 ? "loss" : "");
const pctText = (v: number | null | undefined, dp = 2) =>
  v === null || v === undefined ? "—" : `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(dp)}%`;
const when = (v: string | null | undefined) =>
  v ? new Date(v).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "—";
const px = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : v.toLocaleString("en-IN", { maximumFractionDigits: 2 });
const SKIP_LABEL: Record<string, string> = {
  full: "the strategy already holds a position (one at a time)",
  symbol_held: "already holding that contract",
  price_above_cap: "one lot needs more margin than the strategy's ₹10 lakh",
  no_cash: "not enough free cash in the strategy's account",
};

export default function RankBandBook({ book }: { book: RankBandKey }) {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [posTab, setPosTab] = useState<"OPEN" | "CLOSED">("OPEN");
  const [positions, setPositions] = useState<Position[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const q = `book=${encodeURIComponent(book)}`;
      const [s, b, p] = await Promise.all([
        apiFetch(`/api/rank-band-books/summary?${q}`) as Promise<Summary>,
        apiFetch(`/api/rank-band-books/leaderboard?${q}`) as Promise<{ rows: Row[] }>,
        apiFetch(`/api/rank-band-books/positions?${q}&status=${posTab}`) as Promise<{ positions: Position[] }>,
      ]);
      setSummary(s);
      setRows(b.rows ?? []);
      setPositions(p.positions ?? []);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load this paper account");
    }
  }, [book, posTab]);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  const label = summary?.label ?? RANK_BANDS.find((b) => b.key === book)?.label ?? "Paper Trading";
  const net = (summary?.realized_pnl ?? 0) + (summary?.unrealized_pnl ?? 0);
  const sk = summary?.skipped ?? {};
  const skippedTotal = Object.values(sk).reduce((a, b) => a + b, 0);
  const pickedOn = summary?.picked_at
    ? new Date(summary.picked_at).toLocaleString("en-IN", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" })
    : "12 Nov 2026";
  const ranks = summary?.board_ranks ?? [];

  return (
    <>
      {error && <ErrorBanner message={error} onRetry={load} />}

      <div className="note">
        <p>
          <b>{label} · {summary?.desk_label ?? "Commodity Trading"}.</b> Five strategies, each with its own{" "}
          {inr(summary?.per_strategy_capital ?? 1000000)} ({inr(summary?.desk_capital ?? 5000000)} in all): the live strategies
          at board ranks {ranks.length ? ranks.join(", ") : "—"} on {summary?.board ?? "the desk's Rank"}, picked on {pickedOn}{" "}and
          fixed — they are not re-picked as ranks move. It copies the desk&apos;s own trades of those five.
        </p>
        <p>
          <b>Rules.</b>{" "}One position at a time for each strategy, as on the desk, sized in whole lots of the trade&apos;s own
          contract on {summary?.cost_basis ?? "the broker's margin"}, within that strategy&apos;s own money; Angel One&apos;s MCX
          charges on the account&apos;s lots. Signals it cannot take are counted, by reason. Nothing is backfilled
          {summary?.copying_since ? `: copying since ${when(summary.copying_since)}` : ": it starts with the backend's next cycle"}.
        </p>
        {(summary?.notes ?? []).map((n) => <p key={n}>{n}</p>)}
        <p>
          <b>A rank band is not a recommendation.</b> These five ranked well on a board where luck collects, and none is
          validated; this account is the out-of-sample test of whether they keep earning. Paper fills, not broker executions.
        </p>
      </div>

      <div className="tiles">
        <Tile label="Mode" value="PAPER" sub={`${summary?.strategies ?? 5} strategies · ${inr(summary?.per_strategy_capital ?? 1000000)} each`} />
        <Tile label="Equity" value={inr(summary?.equity, 2)} sub={`from ${inr(summary?.desk_capital ?? 5000000)}`} />
        <Tile label="Net P&L" value={signed(net)} tone={tone(net) || undefined} sub={`${pctText(summary?.roi_pct)} on the book`} />
        <Tile label="Realised (after costs)" value={signed(summary?.realized_pnl)} tone={tone(summary?.realized_pnl) || undefined}
              sub={`gross ${signed(summary?.gross_pnl)} · ${summary?.closed_positions ?? 0} closed`} />
        <Tile label="Angel One charges" value={inr(summary?.fees, 2)} tone={(summary?.fees ?? 0) > 0 ? "loss" : undefined} sub="on this account's lots" />
        <Tile label="Margin in use" value={inr(summary?.deployed)} sub={`${inr(summary?.available_cash)} free`} />
        <Tile label="Open" value={`${summary?.open_positions ?? 0}`} sub={`${signed(summary?.unrealized_pnl)} unrealised`} />
        <Tile label="Skipped" value={`${skippedTotal}`}
              sub={skippedTotal ? Object.entries(sk).filter(([, v]) => v).map(([k, v]) => `${v} ${k.replace(/_/g, " ")}`).join(" · ") : "none yet"} />
      </div>

      <GlassPanel title={`The five, picked ${pickedOn}`} note="each on its own ₹10 lakh">
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th title="Its rank and score on the desk's board when this account was created">Picked at</th>
                <th style={{ textAlign: "left" }}>Strategy</th>
                <th>Capital</th>
                <th>Equity</th>
                <th title="Its net P&L, closed and open, on its own ₹10 lakh">Return</th>
                <th>Trades</th>
                <th>Win %</th>
                <th>Charges</th>
                <th>Net P&amp;L</th>
                <th>Open</th>
                <th title="Signals this strategy's account could not take, by reason">Skipped</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.key}>
                  <td className="rank-cell" title={`#${r.picked_rank} when picked${r.picked_score != null ? `: score ${r.picked_score.toFixed(1)}` : ""}, ${r.picked_trades} trades`
                    + (r.picked_bp != null ? `, ${r.picked_bp >= 0 ? "+" : ""}${r.picked_bp.toFixed(1)} bp a trade` : "")
                    + (r.picked_net_pnl != null ? `, ${signed(r.picked_net_pnl)} net there` : "")}>
                    {r.picked_rank}{r.picked_score != null && <span className="dim"> · {r.picked_score.toFixed(1)}</span>}
                  </td>
                  <td style={{ textAlign: "left" }}>{r.name}</td>
                  <td>{inr(r.allocation)}</td>
                  <td>{inr(r.equity)}</td>
                  <td className={tone(r.roi_pct)}>{r.trades || r.open_positions ? pctText(r.roi_pct, 3) : "—"}</td>
                  <td>{r.trades}</td>
                  <td>{r.trades ? `${(r.win_rate * 100).toFixed(1)}%` : "—"}</td>
                  <td className="loss">{r.fees ? `−₹${r.fees.toLocaleString("en-IN", { maximumFractionDigits: 0 })}` : "—"}</td>
                  <td className={tone(r.net_pnl)}>{r.trades ? signed(r.net_pnl) : "—"}</td>
                  <td>{r.open_positions ? `${r.open_positions} · ${signed(r.unrealized_pnl)}` : "—"}</td>
                  <td className="dim" title={Object.entries(r.skipped).filter(([, v]) => v).map(([k, v]) => `${SKIP_LABEL[k] ?? k}: ${v}`).join("\n")}>
                    {r.skipped_total || "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </GlassPanel>

      <GlassPanel title="Positions">
        <div className="controls">
          {(["OPEN", "CLOSED"] as const).map((t) => (
            <button key={t} className={posTab === t ? "toggle on" : "toggle"} onClick={() => setPosTab(t)}>
              {t === "OPEN" ? `Open (${summary?.open_positions ?? 0})` : `Closed (${summary?.closed_positions ?? 0})`}
            </button>
          ))}
        </div>
        {!positions.length ? (
          <div className="empty">
            {posTab === "OPEN"
              ? "Nothing open. A strategy's account takes a position when the desk opens one for it and it holds nothing."
              : "No closed trades yet. The account started empty and copies only trades from its start."}
          </div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Strategy</th>
                  <th style={{ textAlign: "left" }}>Contract</th>
                  <th>Side</th>
                  <th>Lots</th>
                  <th>Entry</th>
                  <th>{posTab === "OPEN" ? "LTP" : "Exit"}</th>
                  <th>Margin</th>
                  {posTab === "CLOSED" && <th>Charges</th>}
                  <th>{posTab === "OPEN" ? "Unrealised" : "Net P&L"}</th>
                  <th>Opened</th>
                  {posTab === "CLOSED" && <th>Closed</th>}
                </tr>
              </thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={p.position_id}>
                    <td style={{ textAlign: "left" }}>{p.strategy_name}</td>
                    <td style={{ textAlign: "left" }} className="dim">{p.label || p.symbol}</td>
                    <td><span className={p.side === "SELL" ? "side short" : "side long"}>{p.side}</span></td>
                    <td title={`${p.units} units`}>{p.lots}</td>
                    <td>{px(p.entry_px)}</td>
                    <td>{px(posTab === "OPEN" ? p.ltp : p.exit_px)}</td>
                    <td>{inr(p.capital_deployed)}</td>
                    {posTab === "CLOSED" && <td className="loss">{inr(p.fees, 2)}</td>}
                    <td className={tone(posTab === "OPEN" ? p.unrealized_pnl : p.realized_pnl)}>
                      {signed(posTab === "OPEN" ? p.unrealized_pnl : p.realized_pnl)}
                    </td>
                    <td className="dim">{when(p.opened_at)}</td>
                    {posTab === "CLOSED" && <td className="dim" title={p.exit_reason ?? ""}>{when(p.closed_at)}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>

      <style jsx>{`
        .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }
        .note { padding: 12px 16px; border-radius: 10px; background: var(--canvas-soft); border: 1px solid var(--panel-border);
                font-size: 12.5px; line-height: 1.6; color: var(--text-muted); }
        .note p { margin: 0 0 8px; }
        .note p:last-child { margin-bottom: 0; }
        .note b { color: var(--text); }
        .dim { color: var(--text-faint); }
        .rank-cell { font-weight: 700; white-space: nowrap; cursor: help; }
        .controls { display: flex; gap: 10px; align-items: center; padding-bottom: 10px; flex-wrap: wrap; }
        .toggle { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); padding: 8px 13px; border-radius: 9px; font-size: 12px; font-weight: 700; cursor: pointer; }
        .toggle.on { background: var(--brand-dim); border-color: rgba(var(--brand-rgb), 0.35); color: var(--brand); }
        .empty { padding: 22px 20px; font-size: 13px; color: var(--text-faint); line-height: 1.5; }
        .table-scroll { overflow-x: auto; max-height: 620px; overflow-y: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; white-space: nowrap; }
        .data-table th { text-align: center; padding: 9px 12px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); position: sticky; top: 0; background: var(--panel); }
        .data-table td { padding: 8px 12px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .side { font-size: 9.5px; font-weight: 800; letter-spacing: 0.04em; padding: 2px 6px; border-radius: 5px; }
        .side.short { background: var(--loss-dim); color: var(--loss); }
        .side.long { background: var(--brand-dim); color: var(--brand); }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
      `}</style>
    </>
  );
}

function Tile({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "gain" | "loss" }) {
  return (
    <div className="tile">
      <div className="t-label">{label}</div>
      <div className={`t-value ${tone ?? ""}`}>{value}</div>
      {sub && <div className="t-sub">{sub}</div>}
      <style jsx>{`
        .tile { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 12px; padding: 14px 16px; }
        .t-label { font-size: 10px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; color: var(--text-muted); }
        .t-value { font-family: var(--font-display); font-weight: 800; font-size: 21px; margin-top: 6px; }
        .t-value.gain { color: var(--gain); }
        .t-value.loss { color: var(--loss); }
        .t-sub { font-size: 11px; color: var(--text-faint); margin-top: 4px; }
      `}</style>
    </div>
  );
}
