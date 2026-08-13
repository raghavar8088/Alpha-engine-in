"use client";

import { useCallback, useEffect, useState } from "react";
import PageHeader from "../../components/PageHeader";
import GlassPanel from "../../components/GlassPanel";
import ErrorBanner from "../../components/ErrorBanner";
import {
  MomentumTradingDaily,
  MomentumTradingPosition,
  MomentumTradingPreview,
  MomentumTradingSummary,
  fetchMomentumTradingDaily,
  fetchMomentumTradingPositions,
  fetchMomentumTradingPreview,
  fetchMomentumTradingSummary,
} from "../../lib/api";

const REFRESH_MS = 20000;
type Tab = "candidates" | "open" | "closed" | "daily";

const inr = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
const signed = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
const pct = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;

export default function MomentumTradingPage() {
  const [tab, setTab] = useState<Tab>("candidates");
  const [summary, setSummary] = useState<MomentumTradingSummary | null>(null);
  const [prev, setPrev] = useState<MomentumTradingPreview | null>(null);
  const [open, setOpen] = useState<MomentumTradingPosition[]>([]);
  const [closed, setClosed] = useState<MomentumTradingPosition[]>([]);
  const [daily, setDaily] = useState<MomentumTradingDaily[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [s, p, o, c, d] = await Promise.all([
        fetchMomentumTradingSummary(),
        fetchMomentumTradingPreview(),
        fetchMomentumTradingPositions("OPEN"),
        fetchMomentumTradingPositions("CLOSED"),
        fetchMomentumTradingDaily(),
      ]);
      setSummary(s);
      setPrev(p);
      setOpen(o.positions ?? []);
      setClosed(c.positions ?? []);
      setDaily(d);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load Momentum Trading");
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  const done = summary?.done_today ?? [];

  return (
    <div className="page">
      <PageHeader
        crumb="Momentum Trading"
        title="Momentum Trading"
        subtitle="Intraday cash-equity momentum. At 09:20, 09:40 and 10:00 IST it checks every F&O stock against its previous close: up 2% or more is bought, down 2% or more is sold short. Target +2%, stop −2%, and anything still open is squared off at 15:00. Paper, on live Angel One prices."
      />

      {error && <ErrorBanner message={error} />}

      <div className="rules">
        <span><b>Trigger</b> ±{summary?.move_pct ?? 2}% vs previous close</span>
        <span><b>Long</b> if up · <b>Short</b> if down</span>
        <span><b>Target</b> +{summary?.target_pct ?? 2}%</span>
        <span><b>Stop</b> −{summary?.stop_pct ?? 2}%</span>
        <span><b>Square-off</b> {summary?.squareoff ?? "15:00"}</span>
        <span><b>Size</b> {inr(summary?.position_size)}/position</span>
      </div>

      <div className="tiles">
        <Tile label="Desk capital" value={inr(summary?.total_capital)} sub={`up to ${summary?.max_concurrent ?? 0} positions`} />
        <Tile
          label="Equity"
          value={inr(summary?.equity)}
          tone={(summary?.equity ?? 0) >= (summary?.total_capital ?? 0) ? "gain" : "loss"}
          sub={`${signed(summary?.realized_pnl)} realised`}
        />
        <Tile label="Deployed" value={inr(summary?.deployed_capital)} sub={`${inr(summary?.free_capital)} free`} />
        <Tile
          label="Open"
          value={String(summary?.open_positions ?? 0)}
          sub={`${summary?.longs ?? 0} long · ${summary?.shorts ?? 0} short`}
        />
        <Tile
          label="Closed"
          value={String(summary?.closed_positions ?? 0)}
          sub={`${summary?.wins ?? 0} won · ${((summary?.win_rate ?? 0) * 100).toFixed(0)}%`}
        />
        <Tile
          label="Checkpoints"
          value={`${done.length}/${(summary?.checkpoints ?? []).length}`}
          tone={summary?.next_due ? "gain" : undefined}
          sub={summary?.next_due ? `${summary.next_due} due now` : `done: ${done.join(" ") || "none yet"}`}
        />
      </div>

      <div className="note">
        <b>Now {summary?.now_ist} IST.</b> Checkpoints {(summary?.checkpoints ?? []).join(" · ")}
        {done.length ? ` — already run today: ${done.join(", ")}.` : " — none run yet today."}
        <span className="dim"> A stock already holding an open position is not entered again at a later
        checkpoint, so a name that stays up 2% all morning is one position, not three.</span>
      </div>

      <div className="tabs">
        {([
          ["candidates", `Candidates (${prev?.candidates ?? 0})`],
          ["open", `Open (${open.length})`],
          ["closed", `Closed (${closed.length})`],
          ["daily", `Daily P&L (${daily.length})`],
        ] as [Tab, string][]).map(([k, label]) => (
          <button key={k} className={tab === k ? "tab active" : "tab"} onClick={() => setTab(k)}>
            {label}
          </button>
        ))}
      </div>

      {tab === "candidates" && (
        <GlassPanel title={`Qualifying now — ${prev?.up ?? 0} up, ${prev?.down ?? 0} down of ${prev?.scanned ?? 0}`}>
          {!prev?.rows?.length ? (
            <div className="empty">No stock is moving ±{summary?.move_pct ?? 2}% right now.</div>
          ) : (
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th style={{ textAlign: "left" }}>Stock</th>
                    <th>Move</th>
                    <th>Side</th>
                    <th>LTP</th>
                    <th>Qty</th>
                    <th>Cost</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {prev.rows.map((r) => (
                    <tr key={r.symbol}>
                      <td style={{ textAlign: "left" }} className="sym">{r.symbol}</td>
                      <td className={r.change_pct >= 0 ? "gain" : "loss"}>{pct(r.change_pct)}</td>
                      <td><span className={r.side === "BUY" ? "side buy" : "side sell"}>{r.side === "BUY" ? "LONG" : "SHORT"}</span></td>
                      <td>{inr(r.ltp)}</td>
                      <td>{r.qty}</td>
                      <td>{r.qty ? inr(r.cost) : "—"}</td>
                      <td className="dim">
                        {r.already_open ? "already held" : r.qty < 1 ? "1 share > position size" : "would take"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </GlassPanel>
      )}

      {(tab === "open" || tab === "closed") && (
        <GlassPanel title={tab === "open" ? `Open positions (${open.length})` : `Closed positions (${closed.length})`}>
          {!(tab === "open" ? open : closed).length ? (
            <div className="empty">
              {tab === "open" ? "No open positions — entries happen at the morning checkpoints." : "Nothing closed yet."}
            </div>
          ) : (
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th style={{ textAlign: "left" }}>Stock</th>
                    <th>Side</th>
                    <th>At entry</th>
                    <th>Qty</th>
                    <th>Entry</th>
                    <th>{tab === "open" ? "LTP" : "Exit"}</th>
                    <th>Target</th>
                    <th>Stop</th>
                    <th>{tab === "open" ? "Unrealised" : "Realised"}</th>
                    {tab === "closed" && <th>Outcome</th>}
                    <th>CP</th>
                  </tr>
                </thead>
                <tbody>
                  {(tab === "open" ? open : closed).map((p) => (
                    <tr key={p.position_id}>
                      <td style={{ textAlign: "left" }} className="sym">{p.symbol}</td>
                      <td><span className={p.side === "BUY" ? "side buy" : "side sell"}>{p.side === "BUY" ? "LONG" : "SHORT"}</span></td>
                      <td className={p.change_pct_at_entry >= 0 ? "gain" : "loss"}>{pct(p.change_pct_at_entry)}</td>
                      <td>{p.qty}</td>
                      <td>{inr(p.entry_price)}</td>
                      <td>{inr(tab === "open" ? p.ltp : p.exit_price)}</td>
                      <td className="gain">{inr(p.target_price)}</td>
                      <td className="loss">{inr(p.stop_price)}</td>
                      <td className={((tab === "open" ? p.unrealized_pnl : p.realized_pnl) ?? 0) >= 0 ? "gain" : "loss"}>
                        {signed(tab === "open" ? p.unrealized_pnl : p.realized_pnl)}
                      </td>
                      {tab === "closed" && (
                        <td>
                          <span className={p.exit_reason === "target" ? "out win" : p.exit_reason === "stoploss" ? "out lose" : "out flat"}>
                            {p.exit_reason}
                          </span>
                        </td>
                      )}
                      <td className="dim">{p.checkpoint}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </GlassPanel>
      )}

      {tab === "daily" && (
        <GlassPanel title="Daily P&L by session">
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
      )}

      <style jsx>{`
        .page { display: flex; flex-direction: column; gap: 16px; }
        .rules { display: flex; gap: 18px; flex-wrap: wrap; padding: 11px 15px; border-radius: 9px; background: var(--canvas-soft); border: 1px solid var(--panel-border); font-size: 12px; color: var(--text-muted); }
        .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }
        .note { padding: 11px 15px; border-radius: 9px; background: var(--canvas-soft); border: 1px solid var(--panel-border); font-size: 12px; line-height: 1.6; }
        .dim { color: var(--text-faint); }
        .tabs { display: flex; gap: 8px; flex-wrap: wrap; }
        .tab { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); padding: 9px 15px; border-radius: 9px; font-size: 12.5px; font-weight: 600; cursor: pointer; }
        .tab.active { background: var(--purple-dim); border-color: rgba(125, 52, 220, 0.3); color: var(--purple); }
        .empty { padding: 22px 20px; font-size: 13px; color: var(--text-faint); }
        .table-scroll { overflow-x: auto; max-height: 620px; overflow-y: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; white-space: nowrap; }
        .data-table th { text-align: center; padding: 9px 11px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); position: sticky; top: 0; background: var(--panel); }
        .data-table td { padding: 8px 11px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .sym { font-weight: 700; }
        .side { font-size: 10px; font-weight: 800; padding: 2px 8px; border-radius: 6px; }
        .side.buy { background: var(--gain-dim); color: var(--gain); }
        .side.sell { background: var(--loss-dim); color: var(--loss); }
        .out { font-size: 10.5px; font-weight: 800; padding: 2px 8px; border-radius: 6px; }
        .out.win { background: var(--gain-dim); color: var(--gain); }
        .out.lose { background: var(--loss-dim); color: var(--loss); }
        .out.flat { background: var(--canvas-soft); color: var(--text-muted); }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
      `}</style>

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
