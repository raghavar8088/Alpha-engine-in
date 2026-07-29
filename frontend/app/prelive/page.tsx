"use client";

import { useCallback, useEffect, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import PageHeader from "../../components/PageHeader";
import ErrorBanner from "../../components/ErrorBanner";
import {
  PreLiveDay,
  PreLiveScore,
  PreLiveStatus,
  PreLiveTrade,
  fetchPreLiveDaily,
  fetchPreLiveLeaderboard,
  fetchPreLiveStatus,
  fetchPreLiveTrades,
} from "../../lib/api";

const inr = (v: number | null | undefined) =>
  v === null || v === undefined ? "-" : v.toLocaleString("en-IN", { maximumFractionDigits: 0 });
const pct = (v: number | null | undefined) => (v === null || v === undefined ? "-" : `${v.toFixed(1)}%`);
const DEFAULT_INITIAL_CAPITAL = 10_000_000; // ₹1 crore — matches prelive_engine.py's default

export default function PreLivePage() {
  const [status, setStatus] = useState<PreLiveStatus | null>(null);
  const [board, setBoard] = useState<PreLiveScore[]>([]);
  const [trades, setTrades] = useState<PreLiveTrade[]>([]);
  const [days, setDays] = useState<PreLiveDay[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [s, b, t, d] = await Promise.all([
        fetchPreLiveStatus(), fetchPreLiveLeaderboard(), fetchPreLiveTrades(80), fetchPreLiveDaily(60),
      ]);
      setStatus(s); setBoard(b.strategies); setTrades(t.trades); setDays(d.days); setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load pre-live data");
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 15000); // live refresh every 15s
    return () => clearInterval(id);
  }, [load]);

  const eng = status?.engine;
  const running = eng?.status === "running";
  const noUniverse = eng?.status === "no_qualified_universe";
  const totalNet = days.reduce((a, d) => a + (d.net_pnl || 0), 0);
  const greenDays = days.filter((d) => (d.net_pnl || 0) > 0).length;
  const src = eng?.universe_source;
  const sweepDate = src?.created_at ? new Date(src.created_at).toLocaleDateString() : null;

  return (
    <div className="page">
      <PageHeader
        crumb="Pre-Live Desk"
        title="Pre-Live Paper Desk"
        subtitle="Strategy-selection tournament: EVERY registered option-buying strategy, traded automatically every market day on LIVE Dhan data — each on its own independent ₹10 lakh account at 1 lot/position, REAL option premiums (paper, no real orders). This builds the forward, real-premium track record a historical backtest can't (Dhan purges expired-contract history), so the leaderboard can select the best for real-money trading."
      />

      {error && <ErrorBanner message={error} />}
      {noUniverse && (
        <ErrorBanner message={eng?.note ?? "No qualified strategies to trade right now — run the options sweep to populate one."} />
      )}

      <div className="tiles">
        <div className="tile">
          <div className="tile-label">Engine</div>
          <div className={`tile-value ${running ? "gain" : noUniverse ? "loss" : ""}`}>
            <span className={`dot ${running ? "live" : "off"}`} /> {eng?.status ?? "offline"}
          </div>
          <div className={`tile-sub ${eng?.heartbeat_stale ? "loss" : ""}`}>
            {eng?.heartbeat ? `beat ${new Date(eng.heartbeat).toLocaleTimeString()}` : "no heartbeat"}
            {eng?.heartbeat_stale ? ` — STALE (${Math.round((eng.heartbeat_age_seconds ?? 0) / 60)}min)` : ""}
          </div>
        </div>
        <div className="tile">
          <div className="tile-label">Equity</div>
          <div className={`tile-value ${(eng?.equity ?? DEFAULT_INITIAL_CAPITAL) >= (eng?.initial_capital ?? DEFAULT_INITIAL_CAPITAL) ? "gain" : "loss"}`}>
            ₹{inr(eng?.equity ?? eng?.balance ?? DEFAULT_INITIAL_CAPITAL)}
          </div>
          <div className="tile-sub">from ₹{inr(eng?.initial_capital ?? DEFAULT_INITIAL_CAPITAL)} start · avail ₹{inr(eng?.available_cash ?? DEFAULT_INITIAL_CAPITAL)}</div>
        </div>
        <div className="tile">
          <div className="tile-label">Today P&amp;L</div>
          <div className={`tile-value ${(status?.today?.net_pnl ?? eng?.day_pnl ?? 0) >= 0 ? "gain" : "loss"}`}>
            ₹{inr(status?.today?.net_pnl ?? eng?.day_pnl)}
          </div>
          <div className="tile-sub">{status?.today ? `${status.today.trades} trades · ${pct(status.today.roi_pct)} ROI` : "no session yet"}</div>
        </div>
        <div className="tile">
          <div className="tile-label">Capital Deployed</div>
          <div className="tile-value">₹{inr(eng?.capital_locked)}</div>
          <div className="tile-sub">{status?.open_positions?.length ?? 0} open position(s) · ₹{inr(eng?.capital_per_trade)}/trade budget</div>
        </div>
        <div className="tile">
          <div className="tile-label">Qualified Universe</div>
          <div className={`tile-value ${noUniverse ? "loss" : ""}`}>{eng?.universe_size ?? 0} strategies</div>
          <div className="tile-sub">
            {src?.fallback ? "TOP20 fallback (opt-in)" : src?.sweep_id ? `sweep ${src.sweep_id.slice(0, 8)}${sweepDate ? ` · ${sweepDate}` : ""}` : "no sweep yet"}
          </div>
        </div>
        <div className="tile">
          <div className="tile-label">Track Record</div>
          <div className={`tile-value ${totalNet >= 0 ? "gain" : "loss"}`}>₹{inr(totalNet)}</div>
          <div className="tile-sub">{days.length} sessions · {greenDays} green</div>
        </div>
      </div>

      {status?.open_positions && status.open_positions.length > 0 && (
        <GlassPanel title="Open Paper Positions (live-marked)">
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th>Strategy</th><th>TF</th><th>Leg</th><th>Strike</th><th>Entry ₹</th><th>Mark ₹</th><th>Unrealized</th></tr></thead>
              <tbody>
                {status.open_positions.map((p) => (
                  <tr key={p.key}>
                    <td style={{ textAlign: "left" }}>{p.strategy_id}</td>
                    <td>{p.timeframe}</td>
                    <td className={p.option_type === "CE" ? "gain" : "loss"}>{p.option_type}</td>
                    <td>{p.strike}</td>
                    <td>{p.entry_premium}</td>
                    <td>{p.mark}</td>
                    <td className={p.unrealized >= 0 ? "gain" : "loss"}>₹{inr(p.unrealized)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </GlassPanel>
      )}

      <div className="grid-2">
        <GlassPanel title="Strategy Leaderboard (paper, live-forward)">
          {board.length === 0 ? (
            <div className="empty">No paper trades yet. The desk trades automatically when the market is open and a Dhan token is connected.</div>
          ) : (
            <div className="table-scroll">
              <table className="data-table">
                <thead><tr><th>#</th><th style={{ textAlign: "left" }}>Strategy</th><th>TF</th><th>Trades</th><th>Win%</th><th>PF</th><th>Net ₹</th><th>Allocated</th></tr></thead>
                <tbody>
                  {board.map((s, i) => (
                    <tr key={s.key}>
                      <td>{i + 1}</td>
                      <td style={{ textAlign: "left" }}>{s.strategy_id}</td>
                      <td>{s.timeframe}</td>
                      <td>{s.trades}</td>
                      <td className={s.win_rate >= 0.5 ? "gain" : ""}>{(s.win_rate * 100).toFixed(0)}%</td>
                      <td>{s.profit_factor ?? "-"}</td>
                      <td className={s.net_pnl >= 0 ? "gain" : "loss"}>₹{inr(s.net_pnl)}</td>
                      <td>₹{inr(s.allocated_capital)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </GlassPanel>

        <GlassPanel title="Daily P&L History">
          {days.length === 0 ? (
            <div className="empty">No sessions recorded yet.</div>
          ) : (
            <div className="table-scroll">
              <table className="data-table">
                <thead><tr><th>Session</th><th>Trades</th><th>Net ₹</th><th>ROI</th><th>Cumulative ₹</th></tr></thead>
                <tbody>
                  {[...days].reverse().map((d) => (
                    <tr key={d.session}>
                      <td>{d.session}</td>
                      <td>{d.trades}</td>
                      <td className={d.net_pnl >= 0 ? "gain" : "loss"}>₹{inr(d.net_pnl)}</td>
                      <td className={(d.roi_pct ?? 0) >= 0 ? "gain" : "loss"}>{pct(d.roi_pct)}</td>
                      <td className={d.cumulative_pnl >= 0 ? "gain" : "loss"}>₹{inr(d.cumulative_pnl)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </GlassPanel>
      </div>

      <GlassPanel title="Recent Paper Trades (real Dhan premiums)">
        {trades.length === 0 ? (
          <div className="empty">No trades yet.</div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th>Exit</th><th style={{ textAlign: "left" }}>Strategy</th><th>Leg</th><th>Strike</th><th>Entry ₹</th><th>Exit ₹</th><th>Reason</th><th>P&amp;L</th></tr></thead>
              <tbody>
                {trades.map((t) => (
                  <tr key={t.id}>
                    <td style={{ fontSize: 11 }}>{new Date(t.exit_ts).toLocaleString()}</td>
                    <td style={{ textAlign: "left" }}>{t.strategy_id}@{t.timeframe}</td>
                    <td className={t.option_type === "CE" ? "gain" : "loss"}>{t.option_type}</td>
                    <td>{t.strike}</td>
                    <td>{t.entry_premium}</td>
                    <td>{t.exit_premium}</td>
                    <td style={{ fontSize: 11 }}>{t.exit_reason}</td>
                    <td className={t.pnl >= 0 ? "gain" : "loss"}>₹{inr(t.pnl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>

      <style jsx>{`
        .page { display: flex; flex-direction: column; gap: 18px; }
        .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; }
        .tile { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 12px; padding: 14px 16px; }
        .tile-label { font-size: 10.5px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; color: var(--text-muted); }
        .tile-value { margin-top: 6px; font-family: var(--font-data); font-size: 20px; font-weight: 700; display: flex; align-items: center; gap: 8px; }
        .tile-sub { margin-top: 4px; font-size: 11px; color: var(--text-faint); }
        .dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
        .dot.live { background: var(--gain); box-shadow: 0 0 8px var(--gain); animation: pulse 1.6s infinite; }
        .dot.off { background: var(--text-faint); }
        @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
        .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
        @media (max-width: 1000px) { .grid-2 { grid-template-columns: 1fr; } }
        .table-scroll { overflow-x: auto; max-height: 440px; overflow-y: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums; }
        .data-table th { text-align: center; padding: 8px 10px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); position: sticky; top: 0; background: var(--panel); }
        .data-table td { padding: 7px 10px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .empty { padding: 28px 20px; text-align: center; color: var(--text-faint); font-size: 13px; }
      `}</style>
    </div>
  );
}
