"use client";

import { useCallback, useEffect, useState } from "react";
import GlassPanel from "./GlassPanel";
import ErrorBanner from "./ErrorBanner";
import {
  SellingBookPick,
  SellingBookPosition,
  SellingBookSummary,
  fetchSellingBookLeaderboard,
  fetchSellingBookPositions,
  fetchSellingBookSummary,
} from "../lib/api";

const REFRESH_MS = 30000;

const inr = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
const signed = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
const tone = (v: number | null | undefined) => ((v ?? 0) >= 0 ? "gain" : "loss");
const when = (v: string | null | undefined) =>
  v ? new Date(v).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "—";

type PosTab = "OPEN" | "CLOSED" | "DECLINED";

export default function SellingPaperBook({ book }: { book: string }) {
  const [summary, setSummary] = useState<SellingBookSummary | null>(null);
  const [board, setBoard] = useState<SellingBookPick[]>([]);
  const [rows, setRows] = useState<SellingBookPosition[]>([]);
  const [posTab, setPosTab] = useState<PosTab>("OPEN");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [s, lb, pos] = await Promise.all([
        fetchSellingBookSummary(book),
        fetchSellingBookLeaderboard(book),
        fetchSellingBookPositions(book, posTab, 400),
      ]);
      setSummary(s);
      setBoard(lb);
      setRows(pos);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load the paper book");
    }
  }, [book, posTab]);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  const net = (summary?.realized_pnl ?? 0) + (summary?.unrealized_pnl ?? 0);
  const dec = summary?.declined_by_reason;
  const antiCount = (summary?.roster ?? []).filter((r) => r.direction === "LONG").length;

  return (
    <>
      {error && <ErrorBanner message={error} onRetry={load} />}

      <div className="tiles">
        <Tile label="Mode" value="PAPER" sub={`${summary?.roster.length ?? 0} picked strategies`} />
        <Tile label="Equity" value={inr(summary?.equity)} sub={`from ${inr(summary?.capital)}`} />
        <Tile
          label="Net P&L"
          value={signed(net)}
          tone={tone(net)}
          sub={`${(summary?.roi_pct ?? 0) >= 0 ? "+" : ""}${(summary?.roi_pct ?? 0).toFixed(2)}% on the book`}
        />
        <Tile
          label="Realised (after fees)"
          value={signed(summary?.realized_pnl)}
          tone={tone(summary?.realized_pnl)}
          sub={`gross ${signed(summary?.gross_pnl)} · ${summary?.closed_positions ?? 0} closed`}
        />
        <Tile
          label="Fees paid"
          value={inr(summary?.fees)}
          tone={(summary?.fees ?? 0) > 0 ? "loss" : undefined}
          sub="₹20/order per leg + STT, exchange, GST"
        />
        <Tile label="Margin deployed" value={inr(summary?.deployed)} sub={`${inr(summary?.cash)} free`} />
        <Tile
          label="Open / Declined"
          value={`${summary?.open_positions ?? 0} / ${summary?.declined ?? 0}`}
          sub={`${signed(summary?.unrealized_pnl)} unrealised`}
        />
      </div>

      <div className="note">
        <p>
          <b>{summary?.label ?? "Paper Trading 01"}</b> — one {inr(summary?.capital)} account running the{" "}
          {summary?.roster.length ?? 16} strategies picked from the desk&apos;s leaderboard. It follows the desk&apos;s own
          fills{summary?.started_at ? ` from ${when(summary.started_at)}` : ""}: the same structures, opened and closed at
          the same premiums. What differs is that it is <b>one</b> account that can run out of margin, and it pays real
          Angel One option charges on every leg — the desk itself charges nothing.
        </p>
        <p>
          <b>The {antiCount} ANTI picks never traded on the desk.</b> Its leaderboard builds every ANTI row by flipping the
          sign of the original strategy&apos;s P&amp;L. Here they are traded for real: the book <em>buys</em> the exact
          structure the original <em>sells</em>, at the same premium. Before costs that is the leaderboard&apos;s number;
          after costs it is lower, because both sides of a trade pay fees.
        </p>
        <p>
          <b>Three rules decline a signal, and every decline is kept with its reason.</b>{" "}
          <span className="pill">expiry-day churn {dec?.expiry_day ?? 0}</span> the desk opens structures on the day they
          expire and closes them seconds later at the same price — only fees would change hands.{" "}
          <span className="pill">identical position {dec?.duplicate ?? 0}</span> several picks open the exact same
          structure in the same minute; the book holds it once, not six times.{" "}
          <span className="pill">money {dec?.money ?? 0}</span> over the {inr(summary?.position_cap)} per-position cap,
          or not enough free margin.
        </p>
      </div>

      <GlassPanel title={`Picked strategies (${board.length})`}>
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th style={{ textAlign: "left" }}>Strategy</th>
                <th>Side</th>
                <th>Trades</th>
                <th>Win %</th>
                <th>PF</th>
                <th>Gross</th>
                <th>Fees</th>
                <th>Net P&amp;L</th>
                <th>Open</th>
                <th title="expiry-day churn / identical position / money">Declined</th>
              </tr>
            </thead>
            <tbody>
              {board.map((r) => (
                <tr key={r.pick}>
                  <td style={{ textAlign: "left" }}>{r.pick}</td>
                  <td>
                    <span className={r.direction === "LONG" ? "side long" : "side short"}>
                      {r.direction === "LONG" ? "BUYS" : "SELLS"}
                    </span>
                  </td>
                  <td>{r.trades}</td>
                  <td>{r.win_rate == null ? "—" : `${(r.win_rate * 100).toFixed(1)}%`}</td>
                  <td>{r.profit_factor == null ? "—" : r.profit_factor.toFixed(2)}</td>
                  <td className={tone(r.gross_pnl)}>{r.trades ? signed(r.gross_pnl) : "—"}</td>
                  <td className="loss">{r.fees ? `−₹${r.fees.toLocaleString("en-IN", { maximumFractionDigits: 0 })}` : "—"}</td>
                  <td className={tone(r.net_pnl)}>{r.trades ? signed(r.net_pnl) : "—"}</td>
                  <td>{r.open ? `${r.open} · ${signed(r.unrealized_pnl)}` : "—"}</td>
                  <td className="dim">
                    {r.declined_expiry_day + r.declined_duplicate + r.declined_money
                      ? `${r.declined_expiry_day} / ${r.declined_duplicate} / ${r.declined_money}`
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </GlassPanel>

      <GlassPanel title="Positions">
        <div className="controls">
          {(["OPEN", "CLOSED", "DECLINED"] as PosTab[]).map((t) => (
            <button key={t} className={posTab === t ? "toggle on" : "toggle"} onClick={() => setPosTab(t)}>
              {t === "OPEN"
                ? `Open (${summary?.open_positions ?? 0})`
                : t === "CLOSED"
                  ? `Closed (${summary?.closed_positions ?? 0})`
                  : `Declined (${summary?.declined ?? 0})`}
            </button>
          ))}
        </div>
        {rows.length === 0 ? (
          <div className="empty">
            {posTab === "OPEN"
              ? "No open positions. The book follows the desk, so it fills as the picked strategies open new structures during market hours."
              : posTab === "CLOSED"
                ? "No closed trades yet."
                : "Nothing declined yet."}
          </div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Strategy</th>
                  <th>Side</th>
                  <th style={{ textAlign: "left" }}>Structure</th>
                  <th>Expiry</th>
                  <th>Lots</th>
                  <th>{posTab === "OPEN" || posTab === "DECLINED" ? "Premium" : "In → out"}</th>
                  {posTab === "DECLINED" ? (
                    <th style={{ textAlign: "left" }}>Why it was declined</th>
                  ) : (
                    <>
                      <th>Capital</th>
                      {posTab === "CLOSED" && <th>Fees</th>}
                      <th>{posTab === "OPEN" ? "Unrealised" : "Net P&L"}</th>
                      <th>{posTab === "OPEN" ? "Opened" : "Closed"}</th>
                    </>
                  )}
                </tr>
              </thead>
              <tbody>
                {rows.map((p) => (
                  <tr key={p.position_id}>
                    <td style={{ textAlign: "left" }}>{p.pick}</td>
                    <td>
                      <span className={p.direction === "LONG" ? "side long" : "side short"}>
                        {p.direction === "LONG" ? "BUY" : "SELL"}
                      </span>
                    </td>
                    <td style={{ textAlign: "left", whiteSpace: "normal", minWidth: 220 }}>{p.structure}</td>
                    <td>{p.expiry}</td>
                    <td>{p.lots || "—"}</td>
                    <td>
                      {posTab === "CLOSED"
                        ? `${inr(p.credit)} → ${inr(p.exit_cost)}`
                        : posTab === "OPEN"
                          ? `${inr(p.credit)} · now ${inr(p.mark)}`
                          : inr(p.credit)}
                    </td>
                    {posTab === "DECLINED" ? (
                      <td style={{ textAlign: "left", whiteSpace: "normal", minWidth: 340 }} className="dim">
                        {p.decline_reason}
                      </td>
                    ) : (
                      <>
                        <td>{inr(p.capital)}</td>
                        {posTab === "CLOSED" && <td className="loss">{inr(p.fees)}</td>}
                        <td className={tone(posTab === "OPEN" ? p.unrealized_pnl : p.realized_pnl)}>
                          {signed(posTab === "OPEN" ? p.unrealized_pnl : p.realized_pnl)}
                        </td>
                        <td className="dim">{when(posTab === "OPEN" ? p.opened_at : p.closed_at)}</td>
                      </>
                    )}
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
        .pill { display: inline-block; font-size: 10.5px; font-weight: 700; padding: 1px 7px; border-radius: 6px;
                background: var(--panel); border: 1px solid var(--panel-border); color: var(--text); margin-right: 2px; }
        .dim { color: var(--text-faint); }
        .controls { display: flex; gap: 10px; align-items: center; padding-bottom: 10px; flex-wrap: wrap; }
        .toggle { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); padding: 8px 13px; border-radius: 9px; font-size: 12px; font-weight: 700; cursor: pointer; }
        .toggle.on { background: var(--purple-dim); border-color: rgba(125, 52, 220, 0.35); color: var(--purple); }
        .empty { padding: 22px 20px; font-size: 13px; color: var(--text-faint); line-height: 1.5; }
        .table-scroll { overflow-x: auto; max-height: 620px; overflow-y: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; white-space: nowrap; }
        .data-table th { text-align: center; padding: 9px 12px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); position: sticky; top: 0; background: var(--panel); }
        .data-table td { padding: 8px 12px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .side { font-size: 9.5px; font-weight: 800; letter-spacing: 0.04em; padding: 2px 6px; border-radius: 5px; }
        .side.short { background: var(--loss-dim); color: var(--loss); }
        .side.long { background: var(--purple-dim); color: var(--purple); }
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
