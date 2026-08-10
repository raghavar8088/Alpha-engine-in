"use client";

import { useCallback, useEffect, useState } from "react";
import GlassPanel from "./GlassPanel";
import ErrorBanner from "./ErrorBanner";
import {
  LivePaperDaily,
  LivePaperPosition,
  LivePaperScore,
  LivePaperSummary,
  fetchLivePaperDaily,
  fetchLivePaperLeaderboard,
  fetchLivePaperPositions,
  fetchLivePaperSummary,
} from "../lib/api";

const REFRESH_MS = 20000;

const inr = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
const signed = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;

export default function LivePaperBuying() {
  const [summary, setSummary] = useState<LivePaperSummary | null>(null);
  const [board, setBoard] = useState<LivePaperScore[]>([]);
  const [open, setOpen] = useState<LivePaperPosition[]>([]);
  const [closed, setClosed] = useState<LivePaperPosition[]>([]);
  const [daily, setDaily] = useState<LivePaperDaily[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [s, lb, o, c, d] = await Promise.all([
        fetchLivePaperSummary(),
        fetchLivePaperLeaderboard(),
        fetchLivePaperPositions("OPEN"),
        fetchLivePaperPositions("CLOSED"),
        fetchLivePaperDaily(),
      ]);
      setSummary(s);
      setBoard(lb);
      setOpen(o.positions ?? []);
      setClosed(c.positions ?? []);
      setDaily(d);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load Live Paper Buying");
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  return (
    <div className="lp">
      {error && <ErrorBanner message={error} />}

      <div className="intro">
        <b>Live Paper Buying · {inr(summary?.total_capital)}.</b> The five strategies that topped the
        tournament leaderboard, traded on a realistic {inr(summary?.total_capital)} book
        ({inr(summary?.per_strategy)} each) instead of the tournament&apos;s ₹10 lakh accounts — so the
        P&amp;L is what a real {inr(summary?.total_capital)} account would have done. Signals come from{" "}
        <b>{summary?.underlying ?? "NIFTY"} {summary?.timeframe ?? "15m"}</b> bars on live Angel One data;
        entries buy the ATM CE/PE at its real premium, stop at −35%, target at +60%, no new entries after{" "}
        {summary?.entry_cutoff ?? "15:00"} and everything squares off at {summary?.squareoff ?? "15:15"}.
        Paper — no real orders.
      </div>

      <div className="tiles">
        <Tile
          label="Session"
          value={summary?.market_open ? "OPEN" : "CLOSED"}
          tone={summary?.market_open ? "gain" : undefined}
          sub={summary?.market_open ? "trading automatically" : "resumes at 09:15 IST"}
        />
        <Tile
          label="Equity"
          value={inr(summary?.equity)}
          tone={(summary?.equity ?? 0) >= (summary?.total_capital ?? 0) ? "gain" : "loss"}
          sub={`from ${inr(summary?.total_capital)}`}
        />
        <Tile
          label="Realised"
          value={signed(summary?.realized_pnl)}
          tone={(summary?.realized_pnl ?? 0) >= 0 ? "gain" : "loss"}
          sub={`${summary?.closed_positions ?? 0} closed · ${summary?.wins ?? 0} won`}
        />
        <Tile label="Open" value={String(summary?.open_positions ?? 0)} sub={`${signed(summary?.unrealized_pnl)} unrealised`} />
        <Tile label="Deployed" value={inr(summary?.deployed_capital)} sub={`${inr(summary?.per_strategy)} per strategy`} />
        <Tile label="Strategies" value={String(summary?.strategy_count ?? 0)} sub="ANTI mirrors of the winners" />
      </div>

      {summary?.last_notes?.length ? <div className="note">{summary.last_notes.join(" · ")}</div> : null}

      <GlassPanel title="The five strategies">
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th style={{ textAlign: "left" }}>Strategy</th>
                <th>Trades</th>
                <th>Win %</th>
                <th>PF</th>
                <th>Expectancy</th>
                <th>Net P&amp;L</th>
                <th>Account</th>
              </tr>
            </thead>
            <tbody>
              {board.map((r) => (
                <tr key={r.strategy_id}>
                  <td style={{ textAlign: "left" }}>
                    <span className="anti">ANTI</span>
                    {r.name.replace(/^ANTI /, "")}
                  </td>
                  <td>{r.trades}</td>
                  <td>{r.trades ? `${(r.win_rate * 100).toFixed(0)}%` : "—"}</td>
                  <td>{r.profit_factor == null ? "—" : r.profit_factor.toFixed(2)}</td>
                  <td className={r.expectancy >= 0 ? "gain" : "loss"}>{r.trades ? signed(r.expectancy) : "—"}</td>
                  <td className={r.net_pnl >= 0 ? "gain" : "loss"}>{signed(r.net_pnl)}</td>
                  <td>{inr(r.allocated)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </GlassPanel>

      <GlassPanel title={`Open positions (${open.length})`}>
        {!open.length ? (
          <div className="empty">No open positions.</div>
        ) : (
          <PosTable rows={open} live />
        )}
      </GlassPanel>

      <div className="grid-2">
        <GlassPanel title={`Closed positions (${closed.length})`}>
          {!closed.length ? <div className="empty">Nothing closed yet.</div> : <PosTable rows={closed.slice(0, 40)} live={false} />}
        </GlassPanel>

        <GlassPanel title="Daily P&L">
          {!daily.length ? (
            <div className="empty">No completed sessions yet.</div>
          ) : (
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr><th>Session</th><th>Trades</th><th>Won</th><th>Win %</th><th>Net P&amp;L</th></tr>
                </thead>
                <tbody>
                  {daily.map((d) => (
                    <tr key={d.session}>
                      <td className="sym">{d.session}</td>
                      <td>{d.trades}</td>
                      <td>{d.wins}</td>
                      <td>{(d.win_rate * 100).toFixed(0)}%</td>
                      <td className={d.net_pnl >= 0 ? "gain" : "loss"}>{signed(d.net_pnl)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </GlassPanel>
      </div>

      <style jsx>{`
        .lp { display: flex; flex-direction: column; gap: 16px; }
        .intro { padding: 12px 16px; border-radius: 10px; background: var(--canvas-soft); border: 1px solid var(--panel-border); font-size: 12.5px; line-height: 1.65; color: var(--text-muted); }
        .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }
        .note { padding: 10px 14px; border-radius: 9px; background: var(--canvas-soft); border: 1px solid var(--panel-border); font-size: 12px; color: var(--text-muted); }
        .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
        @media (max-width: 1000px) { .grid-2 { grid-template-columns: 1fr; } }
        .empty { padding: 24px 20px; text-align: center; color: var(--text-faint); font-size: 13px; }
        .table-scroll { overflow-x: auto; max-height: 440px; overflow-y: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums; white-space: nowrap; }
        .data-table th { text-align: center; padding: 8px 10px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); position: sticky; top: 0; background: var(--panel); }
        .data-table td { padding: 7px 10px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .anti { font-size: 9px; font-weight: 800; padding: 1px 5px; border-radius: 4px; background: var(--purple-dim); color: var(--purple); margin-right: 7px; }
        .sym { font-weight: 700; }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
      `}</style>
    </div>
  );
}

function PosTable({ rows, live }: { rows: LivePaperPosition[]; live: boolean }) {
  return (
    <div className="table-scroll">
      <table className="data-table">
        <thead>
          <tr>
            <th>Contract</th>
            <th>Spot @ entry</th>
            <th>Lots</th>
            <th>Entry ₹</th>
            <th>{live ? "Now ₹" : "Exit ₹"}</th>
            <th>Cost</th>
            <th>{live ? "Unrealised" : "Realised"}</th>
            {!live && <th>Outcome</th>}
            <th style={{ textAlign: "left" }}>Strategy</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((p) => (
            <tr key={p.position_id}>
              <td className="sym">
                {p.strike} {p.option_type}
              </td>
              <td className="dim">{p.spot_at_entry}</td>
              <td>{p.lots}</td>
              <td>{inr(p.entry_premium)}</td>
              <td>{inr(live ? p.ltp : p.exit_premium)}</td>
              <td>{inr(p.cost)}</td>
              <td className={((live ? p.unrealized_pnl : p.realized_pnl) ?? 0) >= 0 ? "gain" : "loss"}>
                {signed(live ? p.unrealized_pnl : p.realized_pnl)}
              </td>
              {!live && (
                <td>
                  <span className={p.exit_reason === "target" ? "out win" : "out lose"}>{p.exit_reason}</span>
                </td>
              )}
              <td style={{ textAlign: "left" }} className="dim">
                {p.strategy_name.replace(/^ANTI /, "ANTI ")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <style jsx>{`
        .table-scroll { overflow-x: auto; max-height: 440px; overflow-y: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums; white-space: nowrap; }
        .data-table th { text-align: center; padding: 8px 10px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); position: sticky; top: 0; background: var(--panel); }
        .data-table td { padding: 7px 10px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .sym { font-weight: 700; }
        .dim { color: var(--text-faint); }
        .out { font-size: 10.5px; font-weight: 800; padding: 2px 8px; border-radius: 6px; }
        .out.win { background: var(--gain-dim); color: var(--gain); }
        .out.lose { background: var(--loss-dim); color: var(--loss); }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
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
