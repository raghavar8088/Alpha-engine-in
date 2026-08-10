"use client";

import { useCallback, useEffect, useState } from "react";
import PageHeader from "../../components/PageHeader";
import GlassPanel from "../../components/GlassPanel";
import ErrorBanner from "../../components/ErrorBanner";
import {
  BuyLowDaily,
  BuyLowFaller,
  BuyLowPosition,
  BuyLowSignal,
  BuyLowSummary,
  BuyLowTrade,
  fetchBuyLowDaily,
  fetchBuyLowFallers,
  fetchBuyLowPositions,
  fetchBuyLowSignals,
  fetchBuyLowSummary,
  fetchBuyLowTrades,
} from "../../lib/api";

const REFRESH_MS = 30000;
type Tab = "fallers" | "open" | "closed" | "daily" | "signals";

const inr = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
const signed = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
const pct = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;

export default function BuyLowPage() {
  const [tab, setTab] = useState<Tab>("fallers");
  const [summary, setSummary] = useState<BuyLowSummary | null>(null);
  const [fallers, setFallers] = useState<BuyLowFaller[]>([]);
  const [open, setOpen] = useState<BuyLowPosition[]>([]);
  const [closed, setClosed] = useState<BuyLowPosition[]>([]);
  const [trades, setTrades] = useState<BuyLowTrade[]>([]);
  const [daily, setDaily] = useState<BuyLowDaily[]>([]);
  const [signals, setSignals] = useState<BuyLowSignal[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [s, f, o, c, t, d, g] = await Promise.all([
        fetchBuyLowSummary(),
        fetchBuyLowFallers(),
        fetchBuyLowPositions("OPEN"),
        fetchBuyLowPositions("CLOSED"),
        fetchBuyLowTrades(),
        fetchBuyLowDaily(),
        fetchBuyLowSignals(),
      ]);
      setSummary(s);
      setFallers(f);
      setOpen(o.positions ?? []);
      setClosed(c.positions ?? []);
      setTrades(t);
      setDaily(d);
      setSignals(g);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load Buy Low Options");
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  const triggering = fallers.filter((f) => f.triggers).length;

  return (
    <div className="page">
      <PageHeader
        crumb="Buy Low Options"
        title="Buy Low Options"
        subtitle="At 3 PM every trading day this desk checks all 208 F&O stocks against their previous close. Anything down more than 4% gets a cheap out-of-the-money CALL bought on it — a bounded-risk bet that a sharp one-day fall snaps back. Ten stocks fall, ten calls; the same stock falling again another day is a fresh bet. Paper, on live Angel One premiums."
      />

      {error && <ErrorBanner message={error} />}

      <div className="rules">
        <span><b>Trigger</b> down &gt; {summary?.fall_pct ?? 4}% on the day</span>
        <span><b>Buy</b> OTM call, nearest expiry</span>
        <span><b>Cost cap</b> {inr(summary?.max_position_cost)} per position</span>
        <span><b>Target</b> +{inr(summary?.target_rupees)}</span>
        <span><b>Stop</b> −{inr(summary?.stop_rupees)}</span>
        <span><b>Window</b> {summary?.scan_window ?? "15:00–15:25 IST"}</span>
      </div>

      <div className="tiles">
        <Tile label="Desk capital" value={inr(summary?.total_capital)} sub={`up to ${summary?.max_concurrent ?? 0} concurrent`} />
        <Tile
          label="Equity"
          value={inr(summary?.equity)}
          tone={(summary?.equity ?? 0) >= (summary?.total_capital ?? 0) ? "gain" : "loss"}
          sub={`${signed(summary?.realized_pnl)} realised`}
        />
        <Tile label="Deployed" value={inr(summary?.deployed_capital)} sub={`${inr(summary?.free_capital)} free`} />
        <Tile label="Open calls" value={String(summary?.open_positions ?? 0)} sub={`${signed(summary?.unrealized_pnl)} unrealised`} />
        <Tile
          label="Closed"
          value={String(summary?.closed_positions ?? 0)}
          sub={`${summary?.wins ?? 0} winners · ${((summary?.win_rate ?? 0) * 100).toFixed(0)}%`}
        />
        <Tile
          label="Falling now"
          value={String(triggering)}
          tone={triggering ? "loss" : undefined}
          sub={`of ${fallers.length} F&O stocks`}
        />
      </div>

      {summary?.last_notes?.length ? <div className="note">{summary.last_notes.join(" · ")}</div> : null}

      <div className="tabs">
        {([
          ["fallers", `Fallers (${fallers.length})`],
          ["open", `Open (${open.length})`],
          ["closed", `Closed (${closed.length})`],
          ["daily", `Daily P&L (${daily.length})`],
          ["signals", `Signals (${signals.length})`],
        ] as [Tab, string][]).map(([k, label]) => (
          <button key={k} className={tab === k ? "tab active" : "tab"} onClick={() => setTab(k)}>
            {label}
          </button>
        ))}
      </div>

      {tab === "fallers" && (
        <GlassPanel title="Today's F&O fallers — worst first">
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Stock</th>
                  <th>Prev close</th>
                  <th>LTP</th>
                  <th>Change</th>
                  <th>Triggers?</th>
                </tr>
              </thead>
              <tbody>
                {fallers.map((f) => (
                  <tr key={f.symbol} className={f.triggers ? "hit" : ""}>
                    <td style={{ textAlign: "left" }} className="sym">{f.symbol}</td>
                    <td className="dim">{inr(f.prev_close)}</td>
                    <td>{inr(f.ltp)}</td>
                    <td className={f.change_pct >= 0 ? "gain" : "loss"}>{pct(f.change_pct)}</td>
                    <td>{f.triggers ? <span className="out buy">BUY CALL</span> : <span className="dim">—</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </GlassPanel>
      )}

      {(tab === "open" || tab === "closed") && (
        <GlassPanel title={tab === "open" ? `Open calls (${open.length})` : `Closed calls (${closed.length})`}>
          {!(tab === "open" ? open : closed).length ? (
            <div className="empty">
              {tab === "open" ? "No open calls — entries happen at the 3 PM check." : "Nothing closed yet."}
            </div>
          ) : (
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th style={{ textAlign: "left" }}>Stock</th>
                    <th>Fell</th>
                    <th>Spot @ entry</th>
                    <th>Strike</th>
                    <th>Expiry</th>
                    <th>Lot</th>
                    <th>Premium</th>
                    <th>{tab === "open" ? "Now" : "Exit"}</th>
                    <th>Cost</th>
                    <th>{tab === "open" ? "Unrealised" : "Realised"}</th>
                    {tab === "closed" && <th>Outcome</th>}
                  </tr>
                </thead>
                <tbody>
                  {(tab === "open" ? open : closed).map((p) => (
                    <tr key={p.position_id}>
                      <td style={{ textAlign: "left" }} className="sym">{p.symbol}</td>
                      <td className="loss">{pct(p.change_pct_at_entry)}</td>
                      <td className="dim">{inr(p.spot_at_entry)}</td>
                      <td className="sym">{p.strike} CE</td>
                      <td className="dim">{p.expiry}</td>
                      <td>{p.lot_size}</td>
                      <td>{inr(p.entry_premium)}</td>
                      <td>{inr(tab === "open" ? p.ltp : p.exit_premium)}</td>
                      <td>{inr(p.cost)}</td>
                      <td className={((tab === "open" ? p.unrealized_pnl : p.realized_pnl) ?? 0) >= 0 ? "gain" : "loss"}>
                        {signed(tab === "open" ? p.unrealized_pnl : p.realized_pnl)}
                      </td>
                      {tab === "closed" && (
                        <td>
                          <span className={p.exit_reason === "target" ? "out win" : "out lose"}>
                            {p.exit_reason === "expired_worthless" ? "expired ₹0" : p.exit_reason}
                          </span>
                        </td>
                      )}
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
                  <tr><th>Session</th><th>Trades</th><th>Winners</th><th>Win %</th><th>Net P&amp;L</th></tr>
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
          {trades.length > 0 && (
            <div className="sub">
              <div className="sub-head">Recent closed trades</div>
              <div className="table-scroll">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Session</th><th style={{ textAlign: "left" }}>Stock</th><th>Strike</th>
                      <th>Fell</th><th>Entry</th><th>Exit</th><th>P&amp;L</th><th>Outcome</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trades.slice(0, 60).map((t) => (
                      <tr key={t.trade_id}>
                        <td className="dim">{t.session}</td>
                        <td style={{ textAlign: "left" }} className="sym">{t.symbol}</td>
                        <td>{t.strike} CE</td>
                        <td className="loss">{pct(t.change_pct_at_entry)}</td>
                        <td>{inr(t.entry_premium)}</td>
                        <td>{inr(t.exit_premium)}</td>
                        <td className={t.realized_pnl >= 0 ? "gain" : "loss"}>{signed(t.realized_pnl)}</td>
                        <td>
                          <span className={t.exit_reason === "target" ? "out win" : "out lose"}>
                            {t.exit_reason === "expired_worthless" ? "expired ₹0" : t.exit_reason}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </GlassPanel>
      )}

      {tab === "signals" && (
        <GlassPanel title="Signal history">
          <div className="note">
            Every faller the desk evaluated. A skip carries its reason — usually that no OTM
            strike was cheap enough to fit the {inr(summary?.max_position_cost)} cap once the
            lot size is applied.
          </div>
          {!signals.length ? (
            <div className="empty">No signals recorded yet.</div>
          ) : (
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Time</th><th style={{ textAlign: "left" }}>Stock</th><th>Fell</th>
                    <th>Spot</th><th>Strike</th><th>Cost</th><th>Taken</th>
                    <th style={{ textAlign: "left" }}>Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {signals.map((s) => (
                    <tr key={s.signal_id}>
                      <td className="dim">{(s.ts || "").replace("T", " ").slice(0, 16)}</td>
                      <td style={{ textAlign: "left" }} className="sym">{s.symbol}</td>
                      <td className="loss">{pct(s.change_pct)}</td>
                      <td className="dim">{inr(s.spot)}</td>
                      <td>{s.strike ? `${s.strike} CE` : "—"}</td>
                      <td>{s.cost ? inr(s.cost) : "—"}</td>
                      <td><span className={s.taken ? "out win" : "out skip"}>{s.taken ? "bought" : "skipped"}</span></td>
                      <td style={{ textAlign: "left" }} className="dim">{s.reason || ""}</td>
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
        .note { padding: 10px 14px; border-radius: 9px; background: var(--canvas-soft); border: 1px solid var(--panel-border); font-size: 12px; color: var(--text-muted); line-height: 1.6; }
        .tabs { display: flex; gap: 8px; flex-wrap: wrap; }
        .tab { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); padding: 9px 15px; border-radius: 9px; font-size: 12.5px; font-weight: 600; cursor: pointer; }
        .tab.active { background: var(--purple-dim); border-color: rgba(125, 52, 220, 0.3); color: var(--purple); }
        .empty { padding: 22px 20px; font-size: 13px; color: var(--text-faint); }
        .table-scroll { overflow-x: auto; max-height: 620px; overflow-y: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; white-space: nowrap; }
        .data-table th { text-align: center; padding: 9px 11px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); position: sticky; top: 0; background: var(--panel); }
        .data-table td { padding: 8px 11px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        tr.hit { background: rgba(224, 49, 49, 0.06); }
        .sym { font-weight: 700; }
        .dim { color: var(--text-faint); }
        .out { font-size: 10.5px; font-weight: 800; padding: 2px 8px; border-radius: 6px; }
        .out.win { background: var(--gain-dim); color: var(--gain); }
        .out.lose { background: var(--loss-dim); color: var(--loss); }
        .out.skip { background: var(--canvas-soft); color: var(--text-faint); }
        .out.buy { background: var(--accent); color: #241404; }
        .sub { margin-top: 18px; }
        .sub-head { font-size: 11.5px; font-weight: 700; color: var(--text-muted); padding-bottom: 8px; }
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
