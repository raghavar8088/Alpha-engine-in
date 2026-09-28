"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import GlassPanel from "./GlassPanel";
import ErrorBanner from "./ErrorBanner";
import {
  StockBookKey,
  StockBookPosition,
  StockBookScore,
  StockBookSummary,
  fetchStockBookLeaderboard,
  fetchStockBookPositions,
  fetchStockBookSummary,
} from "../lib/api";

const REFRESH_MS = 30000;

const inr = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
const signed = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
const tone = (v: number | null | undefined) => ((v ?? 0) >= 0 ? "gain" : "loss");

type PosTab = "OPEN" | "CLOSED" | "DECLINED";

export default function StockBookView({ book }: { book: StockBookKey }) {
  const [summary, setSummary] = useState<StockBookSummary | null>(null);
  const [board, setBoard] = useState<StockBookScore[]>([]);
  const [rows, setRows] = useState<StockBookPosition[]>([]);
  const [posTab, setPosTab] = useState<PosTab>("OPEN");
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [antiOnly, setAntiOnly] = useState(false);

  const load = useCallback(async () => {
    try {
      const [s, lb, pos] = await Promise.all([
        fetchStockBookSummary(book),
        fetchStockBookLeaderboard(book),
        fetchStockBookPositions(book, posTab, 400),
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

  const shown = useMemo(() => {
    const f = filter.trim().toLowerCase();
    let rs = board;
    if (antiOnly) rs = rs.filter((r) => r.is_anti);
    if (f)
      rs = rs.filter(
        (r) => (r.strategy_name || "").toLowerCase().includes(f) || r.strategy_id.toLowerCase().includes(f),
      );
    return rs;
  }, [board, filter, antiOnly]);

  const capital = summary?.capital ?? 0;
  const feeShare =
    summary && Math.abs(summary.gross_pnl) > 0 ? (summary.fees / Math.abs(summary.gross_pnl)) * 100 : null;

  return (
    <>
      {error && <ErrorBanner message={error} onRetry={load} />}

      <div className="tiles">
        <Tile label="Mode" value="PAPER" sub={`${summary?.strategies ?? 0} strategies have traded`} />
        <Tile label="Equity" value={inr(summary?.equity)} sub={`from ${inr(capital)}`} />
        <Tile
          label="Net P&L"
          value={signed((summary?.realized_pnl ?? 0) + (summary?.unrealized_pnl ?? 0))}
          tone={tone((summary?.realized_pnl ?? 0) + (summary?.unrealized_pnl ?? 0))}
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
          sub={feeShare === null ? "real Angel One option charges" : `${feeShare.toFixed(0)}% of gross P&L`}
        />
        <Tile label="Cash" value={inr(summary?.cash)} sub={`${inr(summary?.deployed)} deployed`} />
        <Tile
          label="Open / Declined"
          value={`${summary?.open_positions ?? 0} / ${summary?.declined ?? 0}`}
          sub={`${signed(summary?.unrealized_pnl)} unrealised`}
        />
      </div>

      <div className="note">
        <b>{summary?.label ?? "Paper book"}.</b> One shared account of {inr(capital)} that follows the
        Stock Pre-Live buying desk — the <em>same</em> strategies, entering and exiting at the <em>same</em>{" "}
        premiums. Two things differ, and they are the point. The account can run out: a signal it cannot afford
        in whole lots is <b>declined</b>, and the reason is kept. And every close pays real Angel One option
        charges — ₹20 per order flat, plus STT, exchange and GST — which the desk itself never charges. One
        position may take at most {inr(summary?.position_cap)}.
      </div>

      <GlassPanel title={`Strategy leaderboard (${shown.length})`}>
        <div className="controls">
          <button className={antiOnly ? "toggle on" : "toggle"} onClick={() => setAntiOnly((v) => !v)}>
            ANTI only
          </button>
          <input
            className="filter"
            placeholder="Filter strategy…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </div>
        {shown.length === 0 ? (
          <div className="empty">
            No closed trades in this book yet. It follows the desk, so it fills as the desk&apos;s current
            positions close and new ones open during market hours.
          </div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Strategy</th>
                  <th>Trades</th>
                  <th>Win %</th>
                  <th>PF</th>
                  <th>Gross</th>
                  <th>Fees</th>
                  <th>Net P&amp;L</th>
                  <th>Declined</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((r) => (
                  <tr key={r.strategy_id}>
                    <td style={{ textAlign: "left" }}>
                      {r.is_anti && <span className="anti">ANTI</span>}
                      {r.strategy_name || r.strategy_id}
                    </td>
                    <td>{r.trades}</td>
                    <td>{r.trades ? `${(r.win_rate * 100).toFixed(1)}%` : "—"}</td>
                    <td>{r.profit_factor == null ? "—" : r.profit_factor.toFixed(2)}</td>
                    <td className={tone(r.gross_pnl)}>{signed(r.gross_pnl)}</td>
                    <td className="loss">{r.fees ? `−₹${r.fees.toLocaleString("en-IN", { maximumFractionDigits: 0 })}` : "—"}</td>
                    <td className={tone(r.net_pnl)}>{signed(r.net_pnl)}</td>
                    <td className={r.declined ? "loss" : "dim"}>{r.declined || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
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
            {posTab === "DECLINED"
              ? "Nothing declined — every signal so far fitted in this book."
              : posTab === "OPEN"
                ? "No open positions."
                : "No closed positions yet."}
          </div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Strategy</th>
                  <th>Contract</th>
                  <th>Lots × size</th>
                  <th>Entry</th>
                  {posTab === "DECLINED" ? (
                    <th style={{ textAlign: "left" }}>Why it was declined</th>
                  ) : (
                    <>
                      <th>{posTab === "OPEN" ? "LTP" : "Exit"}</th>
                      <th>Deployed</th>
                      {posTab === "CLOSED" && <th>Fees</th>}
                      <th>{posTab === "OPEN" ? "Unrealised" : "Net P&L"}</th>
                      {posTab === "CLOSED" && <th>Reason</th>}
                    </>
                  )}
                </tr>
              </thead>
              <tbody>
                {rows.map((p) => (
                  <tr key={p.position_id}>
                    <td style={{ textAlign: "left" }}>
                      {p.is_anti && <span className="anti">ANTI</span>}
                      {p.strategy_name || p.strategy_id}
                    </td>
                    <td>
                      <span className="sym">{p.symbol}</span> {p.strike} {p.option_type}
                    </td>
                    <td>{p.lots ? `${p.lots} × ${p.lot_size}` : `0 × ${p.lot_size}`}</td>
                    <td>{inr(p.entry_premium)}</td>
                    {posTab === "DECLINED" ? (
                      <td style={{ textAlign: "left", whiteSpace: "normal", minWidth: 320 }} className="dim">
                        {p.decline_reason}
                      </td>
                    ) : (
                      <>
                        <td>{inr(posTab === "OPEN" ? p.ltp : p.exit_premium)}</td>
                        <td>{inr(p.capital_deployed)}</td>
                        {posTab === "CLOSED" && <td className="loss">{inr(p.fees)}</td>}
                        <td className={tone(posTab === "OPEN" ? p.unrealized_pnl : p.realized_pnl)}>
                          {signed(posTab === "OPEN" ? p.unrealized_pnl : p.realized_pnl)}
                        </td>
                        {posTab === "CLOSED" && <td className="dim">{p.exit_reason ?? "—"}</td>}
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
        .note { padding: 11px 15px; border-radius: 9px; background: var(--canvas-soft); border: 1px solid var(--panel-border); font-size: 12px; line-height: 1.6; }
        .dim { color: var(--text-faint); }
        .controls { display: flex; gap: 10px; align-items: center; padding-bottom: 10px; flex-wrap: wrap; }
        .toggle { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); padding: 8px 13px; border-radius: 9px; font-size: 12px; font-weight: 700; cursor: pointer; }
        .toggle.on { background: var(--purple-dim); border-color: rgba(125, 52, 220, 0.35); color: var(--purple); }
        .filter { background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 9px; padding: 8px 13px; font-size: 12.5px; min-width: 220px; }
        .empty { padding: 22px 20px; font-size: 13px; color: var(--text-faint); line-height: 1.5; }
        .table-scroll { overflow-x: auto; max-height: 620px; overflow-y: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; white-space: nowrap; }
        .data-table th { text-align: center; padding: 9px 12px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); position: sticky; top: 0; background: var(--panel); }
        .data-table td { padding: 8px 12px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .anti { font-size: 9px; font-weight: 800; padding: 1px 5px; border-radius: 4px; background: var(--purple-dim); color: var(--purple); margin-right: 6px; }
        .sym { font-weight: 700; }
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
