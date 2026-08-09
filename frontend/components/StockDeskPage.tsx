"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import PageHeader from "./PageHeader";
import GlassPanel from "./GlassPanel";
import ErrorBanner from "./ErrorBanner";
import {
  StockDeskPosition,
  StockDeskScore,
  StockDeskSummary,
  fetchStockDeskLeaderboard,
  fetchStockDeskPositions,
  fetchStockDeskSummary,
} from "../lib/api";

const REFRESH_MS = 30000;

const inr = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
const signed = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;

export default function StockDeskPage({ side }: { side: "buying" | "selling" }) {
  const buying = side === "buying";
  const [summary, setSummary] = useState<StockDeskSummary | null>(null);
  const [board, setBoard] = useState<StockDeskScore[]>([]);
  const [positions, setPositions] = useState<StockDeskPosition[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [antiOnly, setAntiOnly] = useState(false);

  const load = useCallback(async () => {
    try {
      const [s, lb, pos] = await Promise.all([
        fetchStockDeskSummary(side),
        fetchStockDeskLeaderboard(side),
        fetchStockDeskPositions(side),
      ]);
      setSummary(s);
      setBoard(lb);
      setPositions(pos.positions ?? []);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load the desk");
    }
  }, [side]);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  const rows = useMemo(() => {
    const f = filter.trim().toLowerCase();
    let rs = board;
    if (antiOnly) rs = rs.filter((r) => r.is_anti);
    if (f) rs = rs.filter((r) => (r.name || "").toLowerCase().includes(f) || r.strategy_id.toLowerCase().includes(f));
    return rs;
  }, [board, filter, antiOnly]);

  const traded = board.filter((r) => r.trades > 0).length;
  const antiCount = board.filter((r) => r.is_anti).length;

  return (
    <div className="page">
      <PageHeader
        crumb={`Stock Pre-Live · ${buying ? "Buying" : "Selling"}`}
        title={`Stock Pre-Live Desk · ${buying ? "Buying" : "Selling"}`}
        subtitle={
          buying
            ? "PAPER desk that BUYS options on single stocks — the stock twin of the NIFTY buying desk. Every strategy in the option-buying library plus its ANTI mirror runs against a universe of liquid F&O stocks on live Angel One data, buying the real ATM contract at its real premium. Lot size, strike ladder and the monthly expiry all come from the actual listed contract, per stock."
            : "PAPER desk that SELLS options on single stocks — the stock twin of the NIFTY selling desk. Every position is a DEFINED-RISK credit spread (short the ATM, long a further strike), never a naked short, priced off live Angel One premiums. Lot size, strike ladder and the monthly expiry all come from the actual listed contract, per stock."
        }
      />

      {error && <ErrorBanner message={error} />}

      <div className="tiles">
        <Tile label="Mode" value="PAPER" sub={`${summary?.strategy_count ?? 0} strategies · ${summary?.timeframe ?? ""}`} />
        <Tile label="Equity" value={inr(summary?.equity)} sub={`from ${inr(summary?.initial_capital)}`} />
        <Tile
          label="Today P&L"
          value={signed(summary?.today_pnl)}
          tone={(summary?.today_pnl ?? 0) >= 0 ? "gain" : "loss"}
          sub={`breaker at −${inr(summary?.daily_loss_limit)}`}
        />
        <Tile
          label="Realised P&L"
          value={signed(summary?.realized_pnl)}
          tone={(summary?.realized_pnl ?? 0) >= 0 ? "gain" : "loss"}
          sub={`${summary?.closed_positions ?? 0} closed`}
        />
        <Tile label="Open positions" value={String(summary?.open_positions ?? 0)} sub={`${signed(summary?.unrealized_pnl)} unrealised`} />
        <Tile label="Deployed" value={inr(summary?.deployed_capital)} sub={buying ? "premium paid" : "max loss at risk"} />
        <Tile label="ANTI strategies" value={String(antiCount)} sub={`${traded} have traded`} />
      </div>

      <div className="note">
        <b>Universe.</b> {(summary?.universe ?? []).join(" · ") || "—"}
        <span className="dim">
          {" "}— live Angel One prices. Quotes are batched to Angel&apos;s 50-token cap and paced, so the whole desk
          costs a handful of requests per cycle rather than one per leg.
        </span>
        {summary?.last_notes?.length ? <div className="dim">{summary.last_notes.join(" ")}</div> : null}
      </div>

      <GlassPanel title={`Strategy leaderboard (${rows.length})`}>
        <div className="controls">
          <button className={antiOnly ? "toggle on" : "toggle"} onClick={() => setAntiOnly((v) => !v)}>
            ANTI only
          </button>
          <input className="filter" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter strategy…" />
        </div>
        {!rows.length ? (
          <div className="empty">No strategy has closed a trade yet — the board fills as positions close.</div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Strategy</th>
                  <th>Trades</th>
                  <th>Win %</th>
                  <th>PF</th>
                  <th>Net P&amp;L</th>
                  <th>Account</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.strategy_id}>
                    <td style={{ textAlign: "left" }}>
                      <span className="sname">
                        {r.is_anti && <span className="anti">ANTI</span>}
                        {r.name}
                      </span>
                    </td>
                    <td>{r.trades}</td>
                    <td>{r.trades ? `${(r.win_rate * 100).toFixed(1)}%` : "—"}</td>
                    <td>{r.profit_factor == null ? "—" : r.profit_factor.toFixed(2)}</td>
                    <td className={r.net_pnl >= 0 ? "gain" : "loss"}>{signed(r.net_pnl)}</td>
                    <td>{inr(r.allocated_capital)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>

      <GlassPanel title={`Open positions (${positions.length})`}>
        {!positions.length ? (
          <div className="empty">No open positions.</div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Stock</th>
                  <th style={{ textAlign: "left" }}>Structure</th>
                  <th>Expiry</th>
                  <th>Lot</th>
                  <th>{buying ? "Premium" : "Credit"}</th>
                  <th>Now</th>
                  <th>{buying ? "Deployed" : "Max loss"}</th>
                  <th>Unrealised</th>
                  <th style={{ textAlign: "left" }}>Strategy</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={p.position_id}>
                    <td style={{ textAlign: "left" }} className="sym">{p.symbol}</td>
                    <td style={{ textAlign: "left" }}>{p.structure}</td>
                    <td className="dim">{p.expiry}</td>
                    <td>{p.lot_size}</td>
                    <td>{inr(p.entry_premium)}</td>
                    <td>{inr(p.ltp)}</td>
                    <td>{inr(buying ? p.capital_deployed : p.max_loss)}</td>
                    <td className={(p.unrealized_pnl ?? 0) >= 0 ? "gain" : "loss"}>{signed(p.unrealized_pnl)}</td>
                    <td style={{ textAlign: "left" }} className="dim">
                      {p.is_anti && <span className="anti">ANTI</span>}
                      {p.strategy_name}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>

      <style jsx>{`
        .page { display: flex; flex-direction: column; gap: 16px; }
        .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }
        .note { padding: 11px 15px; border-radius: 9px; background: var(--canvas-soft); border: 1px solid var(--panel-border); font-size: 12px; line-height: 1.6; }
        .dim { color: var(--text-faint); }
        .controls { display: flex; gap: 10px; align-items: center; padding-bottom: 10px; flex-wrap: wrap; }
        .toggle { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); padding: 8px 13px; border-radius: 9px; font-size: 12px; font-weight: 700; cursor: pointer; }
        .toggle.on { background: var(--purple-dim); border-color: rgba(125, 52, 220, 0.35); color: var(--purple); }
        .filter { background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 9px; padding: 8px 13px; font-size: 12.5px; min-width: 220px; }
        .empty { padding: 22px 20px; font-size: 13px; color: var(--text-faint); }
        .table-scroll { overflow-x: auto; max-height: 620px; overflow-y: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; white-space: nowrap; }
        .data-table th { text-align: center; padding: 9px 12px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); position: sticky; top: 0; background: var(--panel); }
        .data-table td { padding: 8px 12px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .sname { display: inline-flex; align-items: center; gap: 7px; font-weight: 600; }
        .anti { font-size: 9px; font-weight: 800; padding: 1px 5px; border-radius: 4px; background: var(--purple-dim); color: var(--purple); margin-right: 6px; }
        .sym { font-weight: 700; }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
      `}</style>

      {/* Wide tables — use the full content width for this page only, as the other desks do. */}
      <style jsx global>{`
        .app-main { max-width: none !important; margin-left: 0 !important; margin-right: 0 !important; }
      `}</style>
    </div>
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
