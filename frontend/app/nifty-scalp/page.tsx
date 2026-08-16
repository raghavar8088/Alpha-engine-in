"use client";

import { useCallback, useEffect, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import PageHeader from "../../components/PageHeader";
import ErrorBanner from "../../components/ErrorBanner";
import {
  fetchNiftyScalpSummary,
  fetchNiftyScalpLeaderboard,
  fetchNiftyScalpTimeframes,
  fetchNiftyScalpPositions,
  fetchNiftyScalpSignals,
  fetchNiftyScalpDaily,
  type NiftyScalpSummary,
  type NiftyScalpScore,
  type NiftyScalpTimeframe,
  type NiftyScalpPosition,
  type NiftyScalpSignal,
  type DailyRoi,
} from "../../lib/api";

const REFRESH_MS = 30000;
type Tab = "leaderboard" | "timeframes" | "open" | "closed" | "signals" | "daily";
const TABS: { key: Tab; label: string }[] = [
  { key: "leaderboard", label: "Strategy leaderboard" },
  { key: "timeframes", label: "By timeframe" },
  { key: "open", label: "Open positions" },
  { key: "closed", label: "Closed" },
  { key: "signals", label: "Signal history" },
  { key: "daily", label: "Daily ROI" },
];
const TF_KEYS = ["1m", "5m", "10m", "15m", "30m", "1h", "4h", "1d"];
// `chart_pattern` is the 13 geometric formations — head & shoulders, double/triple
// tops, triangles, wedges, flags, pennants, cup & handle, rounding, diamond,
// broadening. They are worth isolating because they work differently from the rest:
// they read swing STRUCTURE, not the last candle.
const FAMILIES = [
  { key: "chart_pattern", label: "Chart patterns" },
  { key: "pattern", label: "Candlesticks" },
  { key: "trend", label: "Trend" },
  { key: "momentum", label: "Momentum" },
  { key: "mean_reversion", label: "Mean reversion" },
  { key: "breakout", label: "Breakout" },
];

const inr = (v: number | null | undefined) =>
  (v ?? 0).toLocaleString("en-IN", { maximumFractionDigits: 0 });
const inr2 = (v: number | null | undefined) =>
  (v ?? 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const roiPct = (v: number | null | undefined, dp = 2) =>
  `${(v ?? 0) >= 0 ? "+" : ""}${(v ?? 0).toFixed(dp)}%`;
const cls = (v: number | null | undefined) => ((v ?? 0) >= 0 ? "gain" : "loss");

export default function NiftyScalpPage() {
  const [tab, setTab] = useState<Tab>("leaderboard");
  const [tf, setTf] = useState<string | null>(null);
  const [fam, setFam] = useState<string | null>(null);
  const [summary, setSummary] = useState<NiftyScalpSummary | null>(null);
  const [board, setBoard] = useState<NiftyScalpScore[]>([]);
  const [frames, setFrames] = useState<NiftyScalpTimeframe[]>([]);
  const [open, setOpen] = useState<NiftyScalpPosition[]>([]);
  const [closed, setClosed] = useState<NiftyScalpPosition[]>([]);
  const [signals, setSignals] = useState<NiftyScalpSignal[]>([]);
  const [daily, setDaily] = useState<DailyRoi[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [s, b, f, o, c, g, d] = await Promise.all([
        fetchNiftyScalpSummary(),
        fetchNiftyScalpLeaderboard(tf ?? undefined, fam ?? undefined),
        fetchNiftyScalpTimeframes(),
        fetchNiftyScalpPositions("OPEN", tf ?? undefined),
        fetchNiftyScalpPositions("CLOSED", tf ?? undefined),
        fetchNiftyScalpSignals(150),
        fetchNiftyScalpDaily(60),
      ]);
      setSummary(s); setBoard(b); setFrames(f);
      setOpen(o); setClosed(c); setSignals(g); setDaily(d);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load the NIFTY scalping desk");
    }
  }, [tf, fam]);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  return (
    <div className="page">
      <PageHeader
        crumb="NIFTY 50 Option Scalping"
        title="NIFTY 50 Option Scalping"
        subtitle="A 504-strategy hunt for edges worth real money: 63 candle-and-indicator templates — including 13 classic geometric chart patterns — run on every timeframe from 1 minute to 1 day, each on its own ₹2,00,000. Signals are read off NIFTY spot candles and expressed by BUYING the near-expiry option nearest the money — a call when bullish, a put when bearish. Never sold, so the most any position can lose is the premium. Paper, on live Angel One prices, with real Angel One F&O costs charged on every close."
      />

      <div className="desk-banner">
        <strong>STYLE FOLLOWS THE CANDLE.</strong> 1m and 5m are <strong>scalps</strong> (tight
        bar limit, out the same session), 10m–1h are <strong>intraday</strong>, 4h and 1d
        carry overnight as <strong>swings</strong> — holding a 1-minute signal for a week
        would not be testing the 1-minute signal. Targets and stops are on{" "}
        <em>option premium</em>, not the index: a 0.3% move in NIFTY can be 10% of an ATM
        premium, so they are deliberately wide. Each strategy takes at most{" "}
        <strong>one trade per closed bar</strong> and holds one position at a time.
      </div>

      {error && <ErrorBanner message={error} />}

      <div className="tiles">
        <div className="tile"><div className="tile-label">Mode</div><div className="tile-value gain">PAPER</div><div className="tile-sub">{summary?.enabled ? "armed · live Angel feed" : "disabled"}</div></div>
        <div className="tile"><div className="tile-label">Desk capital</div><div className="tile-value">₹{inr(summary?.initial_capital)}</div><div className="tile-sub">{summary?.strategy_count ?? 504} × ₹{inr(summary?.per_strategy_capital)}</div></div>
        <div className="tile"><div className="tile-label">Equity</div><div className="tile-value">₹{inr(summary?.equity)}</div><div className="tile-sub">₹{inr(summary?.unrealized_pnl)} unrealised</div></div>
        <div className="tile"><div className="tile-label">ROI</div><div className={`tile-value ${cls(summary?.roi_pct)}`}>{roiPct(summary?.roi_pct, 3)}</div><div className="tile-sub">on ₹{inr(summary?.initial_capital)} desk capital</div></div>
        <div className="tile"><div className="tile-label">Today P&amp;L</div><div className={`tile-value ${cls(summary?.today_pnl)}`}>{(summary?.today_pnl ?? 0) >= 0 ? "+" : ""}₹{inr(summary?.today_pnl)}</div><div className="tile-sub">{roiPct(summary?.today_roi_pct, 3)} today</div></div>
        <div className="tile"><div className="tile-label">Angel F&amp;O fees</div><div className="tile-value loss">−₹{inr(summary?.total_fees)}</div><div className="tile-sub">gross ₹{inr(summary?.gross_realized_pnl)} before costs</div></div>
        <div className="tile"><div className="tile-label">Open positions</div><div className="tile-value">{summary?.open_positions ?? 0}</div><div className="tile-sub">₹{inr(summary?.deployed_capital)} deployed</div></div>
        <div className="tile"><div className="tile-label">Expiry in use</div><div className="tile-value sm">{summary?.expiry ?? "—"}</div><div className="tile-sub">{summary?.closed_positions ?? 0} trades closed</div></div>
      </div>

      {!!summary?.last_notes?.length && (
        <div className="notes">
          {summary.last_notes.map((n, i) => <div key={i}>• {n}</div>)}
        </div>
      )}

      <div className="filters">
        <span className="flabel">Timeframe</span>
        <button className={tf === null ? "chip active" : "chip"} onClick={() => setTf(null)}>All {summary?.strategy_count ?? 504}</button>
        {TF_KEYS.map((k) => (
          <button key={k} className={tf === k ? "chip active" : "chip"} onClick={() => setTf(k)}>{k}</button>
        ))}
      </div>

      <div className="filters">
        <span className="flabel">Family</span>
        <button className={fam === null ? "chip active" : "chip"} onClick={() => setFam(null)}>All</button>
        {FAMILIES.map((f) => (
          <button key={f.key} className={fam === f.key ? "chip active" : "chip"} onClick={() => setFam(f.key)}>{f.label}</button>
        ))}
      </div>

      <div className="tabs">
        {TABS.map((t) => (
          <button key={t.key} className={tab === t.key ? "tab active" : "tab"} onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === "leaderboard" && (
        <GlassPanel title={`Strategy leaderboard${tf ? ` · ${tf}` : ` · all ${summary?.strategy_count ?? 504}`}`}>
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th style={{ textAlign: "left" }}>Strategy</th><th>TF</th><th>Style</th><th>Family</th><th>Trades</th><th>Win %</th><th>Gross</th><th>Fees</th><th>Net P&amp;L</th><th>ROI</th></tr></thead>
              <tbody>
                {board.map((r) => (
                  <tr key={r.strategy_id}>
                    <td style={{ textAlign: "left" }}>{r.template}</td>
                    <td><span className="badge">{r.timeframe}</span></td>
                    <td style={{ fontSize: 11 }}>{r.style}</td>
                    <td style={{ fontSize: 11 }}>{r.family}</td>
                    <td>{r.trades}</td>
                    <td>{(r.win_rate * 100).toFixed(1)}%</td>
                    <td className={cls(r.gross_pnl)}>₹{inr(r.gross_pnl)}</td>
                    <td className="loss">−₹{inr(r.fees)}</td>
                    <td className={cls(r.net_pnl)}>{r.net_pnl >= 0 ? "+" : ""}₹{inr(r.net_pnl)}</td>
                    <td className={cls(r.roi_pct)}>{roiPct(r.roi_pct, 2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </GlassPanel>
      )}

      {tab === "timeframes" && (
        <GlassPanel title="Which horizon is working — every strategy aggregated per candle">
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th style={{ textAlign: "left" }}>Candle</th><th>Style</th><th>Strategies</th><th>Capital</th><th>Trades</th><th>Win %</th><th>Gross</th><th>Fees</th><th>Net P&amp;L</th><th>ROI</th></tr></thead>
              <tbody>
                {frames.map((f) => (
                  <tr key={f.timeframe}>
                    <td style={{ textAlign: "left" }}><strong>{f.label}</strong></td>
                    <td style={{ fontSize: 11 }}>{f.style}</td>
                    <td>{f.strategies}</td>
                    <td>₹{inr(f.capital)}</td>
                    <td>{f.trades}</td>
                    <td>{(f.win_rate * 100).toFixed(1)}%</td>
                    <td className={cls(f.gross_pnl)}>₹{inr(f.gross_pnl)}</td>
                    <td className="loss">−₹{inr(f.fees)}</td>
                    <td className={cls(f.net_pnl)}>{f.net_pnl >= 0 ? "+" : ""}₹{inr(f.net_pnl)}</td>
                    <td className={cls(f.roi_pct)}>{roiPct(f.roi_pct, 3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </GlassPanel>
      )}

      {(tab === "open" || tab === "closed") && (
        <GlassPanel title={tab === "open" ? `Open positions (${open.length})` : `Closed positions (${closed.length})`}>
          {!(tab === "open" ? open : closed).length ? (
            <div className="empty">
              {tab === "open"
                ? "No open positions — entries run during market hours up to 15:05 IST."
                : "No closed trades yet."}
            </div>
          ) : (
            <div className="table-scroll">
              <table className="data-table">
                <thead><tr><th style={{ textAlign: "left" }}>Strategy</th><th>TF</th><th>Option</th><th>Dir</th><th>Lots</th><th>Entry</th><th>{tab === "open" ? "LTP" : "Exit"}</th><th>Target</th><th>Stop</th><th>{tab === "open" ? "Unrealised" : "Net P&L"}</th>{tab === "closed" && <th>Fees</th>}{tab === "closed" && <th>Why</th>}</tr></thead>
                <tbody>
                  {(tab === "open" ? open : closed).map((p) => (
                    <tr key={p.position_id}>
                      <td style={{ textAlign: "left", fontSize: 11 }}>{p.template}</td>
                      <td><span className="badge">{p.timeframe}</span></td>
                      <td style={{ fontSize: 11 }}>{p.strike} {p.option_type}</td>
                      <td><span className={p.direction === "BEARISH" ? "badge loss" : "badge"}>{p.direction === "BEARISH" ? "PUT" : "CALL"}</span></td>
                      <td>{p.lots}</td>
                      <td>₹{inr2(p.entry_premium)}</td>
                      <td>₹{inr2(tab === "open" ? p.ltp : p.exit_premium)}</td>
                      <td>₹{inr2(p.target_premium)}</td>
                      <td>₹{inr2(p.stop_premium)}</td>
                      <td className={cls(tab === "open" ? p.unrealized_pnl : p.realized_pnl)}>
                        {((tab === "open" ? p.unrealized_pnl : p.realized_pnl) ?? 0) >= 0 ? "+" : ""}₹{inr(tab === "open" ? p.unrealized_pnl : p.realized_pnl)}
                      </td>
                      {tab === "closed" && <td className="loss">−₹{inr(p.fees)}</td>}
                      {tab === "closed" && <td style={{ fontSize: 11 }}>{p.exit_reason}</td>}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </GlassPanel>
      )}

      {tab === "signals" && (
        <GlassPanel title="Signal history — including signals no strategy could fund">
          {!signals.length ? <div className="empty">No signals recorded yet.</div> : (
            <div className="table-scroll">
              <table className="data-table">
                <thead><tr><th style={{ textAlign: "left" }}>When</th><th style={{ textAlign: "left" }}>Strategy</th><th>TF</th><th>Direction</th><th>NIFTY</th><th>Option</th><th>Premium</th></tr></thead>
                <tbody>
                  {signals.map((g, i) => (
                    <tr key={i}>
                      <td style={{ textAlign: "left", fontSize: 11 }}>{new Date(g.ts).toLocaleString("en-IN")}</td>
                      <td style={{ textAlign: "left", fontSize: 11 }}>{g.strategy_name}</td>
                      <td><span className="badge">{g.timeframe}</span></td>
                      <td><span className={g.direction === "BEARISH" ? "badge loss" : "badge"}>{g.direction}</span></td>
                      <td>{inr2(g.spot)}</td>
                      <td style={{ fontSize: 11 }}>{g.option ?? "—"}</td>
                      <td>{g.premium ? `₹${inr2(g.premium)}` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </GlassPanel>
      )}

      {tab === "daily" && (
        <GlassPanel title={`Daily ROI — on ₹${inr(summary?.initial_capital)} desk capital`}>
          {!daily.length ? <div className="empty">No closed sessions yet.</div> : (
            <div className="table-scroll">
              <table className="data-table">
                <thead><tr><th style={{ textAlign: "left" }}>Date</th><th>Trades</th><th>Win %</th><th>Gross P&amp;L</th><th>Angel fees</th><th>Net P&amp;L</th><th>ROI</th></tr></thead>
                <tbody>
                  {daily.map((d) => (
                    <tr key={d.date}>
                      <td style={{ textAlign: "left" }}>{d.date}</td>
                      <td>{d.trades}</td>
                      <td>{(d.win_rate * 100).toFixed(1)}%</td>
                      <td className={cls(d.gross_pnl)}>{d.gross_pnl >= 0 ? "+" : ""}₹{inr(d.gross_pnl)}</td>
                      <td className="loss">−₹{inr(d.fees)}</td>
                      <td className={cls(d.realized_pnl)}>{d.realized_pnl >= 0 ? "+" : ""}₹{inr(d.realized_pnl)}</td>
                      <td className={cls(d.roi_pct)}>{roiPct(d.roi_pct, 4)}</td>
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
        .tiles { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); }
        .tile { padding: 12px 14px; border-radius: 10px; background: var(--panel); border: 1px solid var(--panel-border); }
        .tile-label { font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); }
        .tile-value { margin-top: 5px; font-family: var(--font-data); font-variant-numeric: tabular-nums; font-size: 16px; font-weight: 600; }
        .tile-value.sm { font-size: 13px; }
        .tile-sub { margin-top: 3px; font-size: 10.5px; color: var(--text-faint); line-height: 1.4; }
        .tabs { display: flex; gap: 8px; flex-wrap: wrap; }
        .tab { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); padding: 9px 16px; border-radius: 9px; font-size: 12.5px; font-weight: 600; cursor: pointer; }
        .tab.active { background: var(--purple-dim); border-color: rgba(125, 52, 220, 0.3); color: var(--purple); }
        .table-scroll { overflow-x: auto; max-height: 460px; overflow-y: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; }
        .data-table th { text-align: center; padding: 8px 10px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); position: sticky; top: 0; background: var(--panel); }
        .data-table td { padding: 7px 10px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .badge { display: inline-block; padding: 3px 8px; border-radius: 6px; font-size: 10px; font-weight: 700; letter-spacing: 0.05em; background: var(--canvas-soft); border: 1px solid var(--panel-border); }
        .badge.loss { background: var(--loss-dim); border-color: rgba(217, 45, 63, 0.3); }
        .empty { padding: 18px 20px; font-size: 12px; color: var(--text-faint); text-align: center; }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
        .sub { font-size: 10.5px; color: var(--text-faint); }
        .desk-banner { background: var(--canvas-edge); border: 1px solid var(--panel-border); border-radius: 12px; padding: 12px 16px; font-size: 12px; line-height: 1.7; color: var(--text-muted); }
        .notes { background: var(--canvas-edge); border: 1px solid var(--panel-border); border-radius: 10px; padding: 9px 14px; font-size: 11px; color: var(--text-faint); display: flex; flex-direction: column; gap: 3px; }
        .filters { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; }
        .flabel { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; color: var(--text-muted); margin-right: 3px; }
        .chip { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); padding: 5px 12px; border-radius: 999px; cursor: pointer; font-size: 11.5px; font-weight: 600; }
        .chip.active { background: var(--purple-dim); border-color: rgba(125, 52, 220, 0.3); color: var(--purple); }
      `}</style>
    </div>
  );
}
