"use client";

// One Top-10 paper book (₹2 lakh or ₹10 lakh) on one desk: the ten strategies frozen at the pick,
// copied from the desk's own trades into one account. Backend: app/services/top10_books.py.
import { useCallback, useEffect, useState } from "react";
import GlassPanel from "./GlassPanel";
import ErrorBanner from "./ErrorBanner";
import { RankNote, RankTd, RankTh, sortByRank, useStrategyRanks } from "./StrategyRank";
import {
  Top10BookKey,
  Top10Desk,
  Top10Position,
  Top10Row,
  Top10Summary,
  fetchTop10Leaderboard,
  fetchTop10Positions,
  fetchTop10Summary,
} from "../lib/top10Books";

const REFRESH_MS = 30000;

const inr = (v: number | null | undefined, dp = 0) =>
  v === null || v === undefined ? "—" : `₹${v.toLocaleString("en-IN", { maximumFractionDigits: dp })}`;
const signed = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${v >= 0 ? "+" : "−"}₹${Math.abs(v).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
const tone = (v: number | null | undefined) => ((v ?? 0) >= 0 ? "gain" : "loss");
const when = (v: string | null | undefined) =>
  v ? new Date(v).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "—";
const px = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : v.toLocaleString("en-IN", { maximumFractionDigits: 2 });

const SKIP_LABEL: Record<string, string> = {
  full: "slots full",
  symbol_held: "already holding that contract / stock",
  price_above_cap: "one lot costs more than the position cap",
  no_cash: "not enough free cash",
  expiry_day: "entry on the contract's own expiry day",
};

export default function Top10Book({ desk, book }: { desk: Top10Desk; book: Top10BookKey }) {
  const [summary, setSummary] = useState<Top10Summary | null>(null);
  const [board, setBoard] = useState<Top10Row[]>([]);
  const [posTab, setPosTab] = useState<"OPEN" | "CLOSED">("OPEN");
  const [positions, setPositions] = useState<Top10Position[]>([]);
  const [error, setError] = useState<string | null>(null);
  const ranks = useStrategyRanks("top10-books", { desk, book });

  const load = useCallback(async () => {
    try {
      const [s, b, p] = await Promise.all([
        fetchTop10Summary(desk, book),
        fetchTop10Leaderboard(desk, book),
        fetchTop10Positions(desk, book, posTab),
      ]);
      setSummary(s);
      setBoard(b);
      setPositions(p);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load the Top-10 book");
    }
  }, [desk, book, posTab]);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  const net = (summary?.realized_pnl ?? 0) + (summary?.unrealized_pnl ?? 0);
  const sk = summary?.skipped ?? {};
  const skippedTotal = Object.values(sk).reduce((a, b) => a + b, 0);
  const pickedOn = summary?.picked_at ? new Date(summary.picked_at).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "27 Oct 2026";

  return (
    <>
      {error && <ErrorBanner message={error} onRetry={load} />}

      <div className="note">
        <p>
          <b>{summary?.label ?? "Top 10 Paper Trade"} · {summary?.desk_label ?? ""}.</b> One {inr(summary?.desk_capital)} paper
          account copying the trades of just ten strategies: the ten ranked 1–10 on {summary?.board ?? "the desk's Rank"}, picked
          on {pickedOn} and fixed — they are not re-picked as ranks move. It trades {summary?.instrument ?? "what the desk trades"}.
        </p>
        <p>
          <b>Rules.</b> The desk’s own entry and exit prices; at most {summary?.max_open_positions ?? 5} positions at a time, each up
          to {inr(summary?.position_cap)}; whole lots only, and a lot costs {summary?.cost_basis ?? "what the desk pays for it"}; never two
          positions in one contract{desk === "stock-buying" || desk === "stock-selling" ? " (one stock)" : desk === "commodity" ? " (one commodity)" : ""};
          Angel One’s charges on this account’s own quantity.{summary?.skip_expiry_day ? " Entries on the contract’s own expiry day are skipped." : ""}{" "}
          Signals it cannot take are counted, by reason. Nothing is backfilled{summary?.copying_since ? `: copying since ${when(summary.copying_since)}` : ""}.
        </p>
        {(summary?.notes ?? []).map((n) => <p key={n}>{n}</p>)}
        <p>
          <b>These ten led a board where luck collects, and none is validated.</b> This account is the out-of-sample test of whether
          they keep leading. “Picked at” is where each stood when chosen. Paper fills, not broker executions.
        </p>
      </div>

      <div className="tiles">
        <Tile label="Mode" value="PAPER" sub={`${summary?.strategies ?? 10} picked strategies`} />
        <Tile label="Equity" value={inr(summary?.equity, 2)} sub={`from ${inr(summary?.desk_capital)}`} />
        <Tile label="Net P&L" value={signed(net)} tone={tone(net)}
              sub={`${(summary?.roi_pct ?? 0) >= 0 ? "+" : ""}${(summary?.roi_pct ?? 0).toFixed(2)}% on the book`} />
        <Tile label="Realised (after costs)" value={signed(summary?.realized_pnl)} tone={tone(summary?.realized_pnl)}
              sub={`gross ${signed(summary?.gross_pnl)} · ${summary?.closed_positions ?? 0} closed`} />
        <Tile label="Angel One charges" value={inr(summary?.fees, 2)} tone={(summary?.fees ?? 0) > 0 ? "loss" : undefined}
              sub="on this account's quantity" />
        <Tile label="Deployed" value={inr(summary?.deployed)} sub={`${inr(summary?.available_cash)} free`} />
        <Tile label="Open" value={`${summary?.open_positions ?? 0}`} sub={`${signed(summary?.unrealized_pnl)} unrealised`} />
        <Tile label="Skipped" value={`${skippedTotal}`}
              sub={skippedTotal ? Object.entries(sk).filter(([, v]) => v).map(([k, v]) => `${v} ${k.replace("_", " ")}`).join(" · ") : "none yet"} />
      </div>

      <GlassPanel title={`The ten, picked ${pickedOn}`}>
        {ranks && <RankNote board={ranks} />}
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                {ranks && <RankTh />}
                <th title="Its Rank and score on the desk's board when this account was created">Picked at</th>
                <th style={{ textAlign: "left" }}>Strategy</th>
                <th>Trades</th>
                <th>Win %</th>
                <th>Charges</th>
                <th>Net P&amp;L</th>
                <th title="Net P&L as a share of this book's capital">Share of book</th>
                <th>Open</th>
                <th title="Signals this book could not take, by reason">Skipped</th>
              </tr>
            </thead>
            <tbody>
              {sortByRank(board, ranks, (r) => r.key).map((r) => (
                <tr key={r.key}>
                  {ranks && <RankTd board={ranks} id={r.key} />}
                  <td className="srank-cell" data-score={r.picked_score == null ? "" : r.picked_score.toFixed(1)}
                      title={`#${r.picked_rank} when picked${r.picked_score != null ? `: score ${r.picked_score.toFixed(1)}` : ""}, ${r.picked_trades} trades`
                        + (r.picked_bp != null ? `, ${r.picked_bp >= 0 ? "+" : ""}${r.picked_bp.toFixed(0)} bp a trade` : "")
                        + (r.picked_net_pnl != null ? `, ${signed(r.picked_net_pnl)} net there` : "")}>
                    {r.picked_rank}
                  </td>
                  <td style={{ textAlign: "left" }}>{r.name}</td>
                  <td>{r.trades}</td>
                  <td>{r.trades ? `${(r.win_rate * 100).toFixed(1)}%` : "—"}</td>
                  <td className="loss">{r.fees ? `−₹${r.fees.toLocaleString("en-IN", { maximumFractionDigits: 0 })}` : "—"}</td>
                  <td className={tone(r.net_pnl)}>{r.trades ? signed(r.net_pnl) : "—"}</td>
                  <td className={tone(r.roi_pct)}>{r.trades ? `${r.roi_pct >= 0 ? "+" : ""}${r.roi_pct.toFixed(3)}%` : "—"}</td>
                  <td>{r.open_positions || "—"}</td>
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
              ? "Nothing open. This account takes a position when the desk opens one for one of its ten and a slot is free."
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
                  <th>Deployed</th>
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
