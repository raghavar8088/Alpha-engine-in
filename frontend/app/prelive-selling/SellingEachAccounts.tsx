"use client";

// Index Option Selling: two paper accounts with ₹10 lakh for EACH strategy (13 Nov 2026) - the top 10 of the Strategy
// Factory · 546 tab (sf10) and the top 10 of the desk's own leaderboard (desk10). Every strategy has its own ₹10 lakh
// and copies its parent's trades. Backend: app/services/selling_each_books.py (GET /api/selling-books/each/...).
// Paper only: nothing here places an order.
import { useCallback, useEffect, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import ErrorBanner from "../../components/ErrorBanner";
import { apiFetch } from "../../lib/api";

export type SellingEachKey = "sf10" | "desk10";

type Summary = {
  account: SellingEachKey; label: string; source: "factory" | "desk"; board: string; instrument: string; notes: string[];
  picked_at: string; enabled: boolean; entries_on: boolean; strategies: number; per_strategy_capital: number;
  account_capital: number; position_share: number; max_lots: number; skip_expiry_day: boolean; equity: number;
  realized_pnl: number; unrealized_pnl: number; gross_pnl: number; fees: number; deployed: number; available_cash: number;
  open_positions: number; closed_positions: number; wins: number; roi_pct: number; skipped: Record<string, number>;
  voided: number; copying_since: string | null; last_run_at: string | null;
};
type Row = {
  strategy_id: string; name: string; picked_rank: number; picked_score: number; picked_trades: number;
  picked_net_pnl: number; capital: number; trades: number; wins: number; win_rate: number | null; gross_pnl: number;
  fees: number; net_pnl: number; unrealized_pnl: number; deployed: number; equity: number; roi_pct: number;
  open_positions: number; position_limit: number; lots_last: number | null; skipped: Record<string, number>;
  skipped_total: number; voided: number;
};
type Position = {
  position_id: string; strategy_id: string; name: string; pick_rank: number; status: string; structure: string;
  expiry: string; timeframe: string | null; credit: number; lots: number; lot_size: number; qty: number;
  margin_per_lot: number; capital_deployed: number; mark: number | null; unrealized_pnl: number;
  exit_cost: number | null; exit_reason: string | null; fees: number | null; realized_pnl: number | null;
  opened_at: string; closed_at: string | null; skip_reason: string | null; skip_note: string | null;
};
type PosTab = "OPEN" | "CLOSED" | "SKIPPED";

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
  expiry_day: "opened on its own expiry day",
  held: "already holding a position (one at a time)",
  margin: "one lot needs more margin than a position may use",
  off: "Main Control had the paper books switched off",
  data: "the parent's record had nothing to copy",
};

export default function SellingEachAccounts({ account }: { account: SellingEachKey }) {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [posTab, setPosTab] = useState<PosTab>("OPEN");
  const [positions, setPositions] = useState<Position[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const base = `/api/selling-books/each/${account}`;
      const [s, b, p] = await Promise.all([
        apiFetch(`${base}/summary`) as Promise<Summary>,
        apiFetch(`${base}/strategies`) as Promise<{ rows: Row[] }>,
        apiFetch(`${base}/positions?status=${posTab}&limit=300`) as Promise<{ positions: Position[] }>,
      ]);
      setSummary(s);
      setRows(b.rows ?? []);
      setPositions(p.positions ?? []);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load this paper account");
    }
  }, [account, posTab]);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  const isFactory = (summary?.source ?? (account === "sf10" ? "factory" : "desk")) === "factory";
  const label = summary?.label ?? (account === "sf10" ? "Top 10 of the 546 · ₹10 lakh each" : "Top 10 of the desk · ₹10 lakh each");
  const parent = isFactory ? "the Strategy Factory · 546 tab" : "the desk";
  const net = (summary?.realized_pnl ?? 0) + (summary?.unrealized_pnl ?? 0);
  const sk = summary?.skipped ?? {};
  const skippedTotal = Object.values(sk).reduce((a, b) => a + b, 0);
  const pickedOn = summary?.picked_at
    ? new Date(summary.picked_at).toLocaleString("en-IN", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" })
    : "12 Nov 2026";
  const perStrategy = summary?.per_strategy_capital ?? 1000000;
  const share = Math.round((summary?.position_share ?? 0.2) * 100);
  const maxLots = summary?.max_lots ?? 10;

  return (
    <>
      {error && <ErrorBanner message={error} onRetry={load} />}

      <div className="note">
        <p>
          <b>{label}.</b>{" "}Ten strategies, each with its own {inr(perStrategy)} ({inr(summary?.account_capital ?? 10000000)} in
          all): ranks 1–10 on {summary?.board ?? (isFactory ? "the Strategy Factory · 546 tab’s Rank" : "the desk’s Rank")},
          picked on {pickedOn} and fixed — they are not re-picked as ranks move. It copies {parent}’s own trades of those ten
          {isFactory ? ": NIFTY credit spreads with a 200-point wing." : ": the desk’s own NIFTY structures."}
        </p>
        <p>
          <b>Size.</b>{" "}One structure at a time for each strategy, as on {parent}. Whole lots: a position may use up to a
          fifth ({share}%) of that strategy’s own equity in margin ({inr(perStrategy * (summary?.position_share ?? 0.2))} to
          start) and at most {maxLots} lots, the desk’s own cap on one structure. The parent trades 1 lot, so a copy is
          usually 8–10 times it. Profit stays in the strategy’s account and its equity sizes the next position; a loss
          shrinks it, and never touches another strategy’s money.
        </p>
        <p>
          <b>Prices and charges.</b>{" "}In at the parent’s entry credit and out at the parent’s exit, with Angel One’s option
          charges on this account’s own lots{isFactory ? " (each leg’s real entry and exit premium)" : " (each leg’s entry premium; the desk records only the structure’s net exit)"}.
          The parent prices one lot off the quotes; the extra depth that 8–10 lots would take is not modelled. Open positions
          show the parent’s live mark, before the exit’s charges.
        </p>
        <p>
          <b>Entries it does not copy are counted, by reason</b>
          {summary?.skip_expiry_day ? " (on this account an entry on its own expiry day is skipped: the desk’s daemon closes those within seconds at the price they opened at, so a copy would only pay charges)" : ""}.
          Nothing is backfilled{summary?.copying_since ? `: copying since ${when(summary.copying_since)}` : ": it starts with the backend’s next cycle"}.
          {summary && !summary.entries_on ? " Main Control has the Index Option Selling paper books switched OFF, so new entries are being recorded as skipped." : ""}
        </p>
        {(summary?.notes ?? []).map((n) => <p key={n}>{n}</p>)}
        <p>
          <b>A top 10 is not a recommendation.</b>{" "}These ranked best on a board where luck collects, and none is validated;
          this account is the out-of-sample test of whether they keep earning. Paper fills, not broker executions.
        </p>
      </div>

      <div className="tiles">
        <Tile label="Mode" value="PAPER" sub={`${summary?.strategies ?? 10} strategies · ${inr(perStrategy)} each`} />
        <Tile label="Equity" value={inr(summary?.equity, 2)} sub={`from ${inr(summary?.account_capital ?? 10000000)}`} />
        <Tile label="Net P&L" value={signed(net)} tone={tone(net) || undefined} sub={`${pctText(summary?.roi_pct, 3)} on the account`} />
        <Tile label="Realised (after charges)" value={signed(summary?.realized_pnl)} tone={tone(summary?.realized_pnl) || undefined}
              sub={`gross ${signed(summary?.gross_pnl)} · ${summary?.closed_positions ?? 0} closed`} />
        <Tile label="Angel One charges" value={inr(summary?.fees, 2)} tone={(summary?.fees ?? 0) > 0 ? "loss" : undefined} sub="on this account’s lots" />
        <Tile label="Margin in use" value={inr(summary?.deployed)} sub={`${inr(summary?.available_cash)} free`} />
        <Tile label="Open" value={`${summary?.open_positions ?? 0}`} sub={`${signed(summary?.unrealized_pnl)} unrealised`} />
        <Tile label="Not copied" value={`${skippedTotal}`}
              sub={skippedTotal ? Object.entries(sk).filter(([, v]) => v).map(([k, v]) => `${v} ${k.replace(/_/g, " ")}`).join(" · ") : "none yet"} />
      </div>

      <GlassPanel title={`The ten, picked ${pickedOn}`} note={`each on its own ${inr(perStrategy)}`}>
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Rank</th>
                <th style={{ textAlign: "left" }}>Strategy</th>
                <th title="Its record on the board when it was picked (1 lot)">Board when picked</th>
                <th>Equity</th>
                <th>Return</th>
                <th>Trades</th>
                <th>Win %</th>
                <th>Charges</th>
                <th>Net P&amp;L</th>
                <th>Open</th>
                <th title="The most margin its next position may use: a fifth of its equity">Next position up to</th>
                <th>Not copied</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.strategy_id}>
                  <td className="rank-cell" title={`#${r.picked_rank} when picked: score ${r.picked_score.toFixed(1)}, ${r.picked_trades} trades`}>
                    {r.picked_rank}<span className="dim"> · {r.picked_score.toFixed(1)}</span>
                  </td>
                  <td style={{ textAlign: "left" }}>
                    {isFactory ? <><span className="dim">{r.strategy_id}</span> {r.name}</> : r.name}
                  </td>
                  <td className="dim">{r.picked_trades} trades · {signed(r.picked_net_pnl)}</td>
                  <td>{inr(r.equity)}</td>
                  <td className={tone(r.roi_pct)}>{r.trades || r.open_positions ? pctText(r.roi_pct, 3) : "—"}</td>
                  <td>{r.trades}</td>
                  <td>{r.win_rate === null ? "—" : `${(r.win_rate * 100).toFixed(1)}%`}</td>
                  <td className="loss">{r.fees ? `−₹${r.fees.toLocaleString("en-IN", { maximumFractionDigits: 0 })}` : "—"}</td>
                  <td className={tone(r.net_pnl)}>{r.trades ? signed(r.net_pnl) : "—"}</td>
                  <td>{r.open_positions ? `${r.open_positions} · ${signed(r.unrealized_pnl)}` : "—"}</td>
                  <td className="dim">{inr(r.position_limit)}</td>
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
          {(["OPEN", "CLOSED", "SKIPPED"] as const).map((t) => (
            <button key={t} className={posTab === t ? "toggle on" : "toggle"} onClick={() => setPosTab(t)}>
              {t === "OPEN" ? `Open (${summary?.open_positions ?? 0})` : t === "CLOSED" ? `Closed (${summary?.closed_positions ?? 0})` : `Not copied (${skippedTotal})`}
            </button>
          ))}
        </div>
        {!positions.length ? (
          <div className="empty">
            {posTab === "OPEN"
              ? `Nothing open. A strategy’s account takes a position when ${parent} opens one for it and it holds nothing.`
              : posTab === "CLOSED"
                ? "No closed trades yet. The account started empty and copies only trades from its start."
                : "Every entry so far has been copied."}
          </div>
        ) : posTab === "SKIPPED" ? (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Strategy</th>
                  <th style={{ textAlign: "left" }}>Structure</th>
                  <th>Expiry</th>
                  <th style={{ textAlign: "left" }}>Why not</th>
                  <th>Parent opened</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={p.position_id}>
                    <td style={{ textAlign: "left" }}>{p.name}</td>
                    <td style={{ textAlign: "left" }} className="dim">{p.structure}</td>
                    <td className="dim">{p.expiry}</td>
                    <td style={{ textAlign: "left", whiteSpace: "normal", minWidth: 280 }}>{p.skip_note ?? SKIP_LABEL[p.skip_reason ?? ""] ?? p.skip_reason}</td>
                    <td className="dim">{when(p.opened_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Strategy</th>
                  <th style={{ textAlign: "left" }}>Structure</th>
                  <th>Expiry</th>
                  <th title="The account's lots (the parent's: 1)">Lots</th>
                  <th title="Net credit per unit at entry">Credit</th>
                  <th title={posTab === "OPEN" ? "What buying it back costs now, per unit" : "What buying it back cost, per unit"}>{posTab === "OPEN" ? "Mark" : "Exit"}</th>
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
                    <td style={{ textAlign: "left" }}>{p.name}</td>
                    <td style={{ textAlign: "left" }} className="dim">{p.structure}</td>
                    <td className="dim">{p.expiry}</td>
                    <td title={`${p.lots} lots × ${p.lot_size} = ${p.qty}`}>{p.lots}</td>
                    <td>{px(p.credit)}</td>
                    <td>{px(posTab === "OPEN" ? p.mark : p.exit_cost)}</td>
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
