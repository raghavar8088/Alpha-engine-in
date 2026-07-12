"use client";

import { useCallback, useEffect, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import PageHeader from "../../components/PageHeader";
import ErrorBanner from "../../components/ErrorBanner";
import {
  RunDetail,
  RunSummary,
  StartRunRequest,
  StrategyInfo,
  fetchRun,
  fetchRuns,
  fetchStrategies,
  startRun,
  stopRun,
} from "../../lib/api";

const TIMEFRAMES = ["1m", "5m", "15m", "1h", "1d", "1w"];
const MODES: StartRunRequest["mode"][] = ["REPLAY", "SIMULATION", "PAPER", "LIVE"];
const MODE_LABEL: Record<string, string> = {
  HISTORICAL: "Historical (signals only)",
  BACKTEST: "Backtest",
  REPLAY: "Replay (recent historical bars)",
  SIMULATION: "Simulation (synthetic bars, no market data needed)",
  PAPER: "Paper (live bars, simulated fills)",
  LIVE: "Live (live bars, REAL Dhan orders)",
};

const inr = (v: number | null | undefined) =>
  v === null || v === undefined ? "-" : v.toLocaleString("en-IN", { maximumFractionDigits: 2 });

const POLL_MS = 5000;

export default function LivePage() {
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selected, setSelected] = useState<RunDetail | null>(null);
  const [form, setForm] = useState<StartRunRequest>({
    strategy_id: "",
    symbol: "NIFTY",
    timeframe: "1d",
    mode: "REPLAY",
    years: 1,
    simulation_bars: 300,
    confirm_live: false,
  });
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshRuns = useCallback(() => {
    fetchRuns().then(setRuns).catch(() => {});
  }, []);

  useEffect(() => {
    fetchStrategies()
      .then((list) => {
        setStrategies(list);
        if (list.length > 0) setForm((f) => ({ ...f, strategy_id: f.strategy_id || list[0].strategy_id }));
      })
      .catch(() => setError("Backend unreachable - is it running on port 8000?"));
    refreshRuns();
    const id = setInterval(refreshRuns, POLL_MS);
    return () => clearInterval(id);
  }, [refreshRuns]);

  useEffect(() => {
    if (!selected) return;
    if (selected.status !== "RUNNING") return;
    const id = setInterval(() => {
      fetchRun(selected.run_id).then(setSelected).catch(() => {});
    }, POLL_MS);
    return () => clearInterval(id);
  }, [selected]);

  const run = useCallback(async () => {
    setStarting(true);
    setError(null);
    try {
      const detail = await startRun(form);
      setSelected(detail);
      refreshRuns();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start run");
    } finally {
      setStarting(false);
    }
  }, [form, refreshRuns]);

  const openRun = useCallback(async (runId: string) => {
    setError(null);
    try {
      setSelected(await fetchRun(runId));
    } catch {
      setError("Failed to load run");
    }
  }, []);

  const stop = useCallback(async () => {
    if (!selected) return;
    try {
      await stopRun(selected.run_id);
      openRun(selected.run_id);
      refreshRuns();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to stop run");
    }
  }, [selected, openRun, refreshRuns]);

  const isStandingMode = form.mode === "PAPER" || form.mode === "LIVE";
  const snap = selected?.snapshot;

  return (
    <div className="page">
      <PageHeader
        crumb="Live Engine"
        title="Live Strategy Engine"
        subtitle="Every mode runs the exact same strategy + risk engine. Replay/Simulation/Backtest are one-shot (reuse the backtester directly); Paper/Live are standing runs against live bars."
      />

      <GlassPanel title="Start a run">
        <div className="form">
          <label>
            Strategy
            <select value={form.strategy_id} onChange={(e) => setForm({ ...form, strategy_id: e.target.value })}>
              {strategies.map((s) => (
                <option key={s.strategy_id} value={s.strategy_id}>
                  {s.name}
                  {s.validation?.real_money_ready ? " ★" : ""}
                </option>
              ))}
            </select>
          </label>
          <label>
            Symbol
            <input value={form.symbol} onChange={(e) => setForm({ ...form, symbol: e.target.value })} />
          </label>
          <label>
            Timeframe
            <select value={form.timeframe} onChange={(e) => setForm({ ...form, timeframe: e.target.value })}>
              {TIMEFRAMES.map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
          </label>
          <label>
            Mode
            <select
              value={form.mode}
              onChange={(e) => setForm({ ...form, mode: e.target.value as StartRunRequest["mode"], confirm_live: false })}
            >
              {MODES.map((m) => (
                <option key={m} value={m}>
                  {MODE_LABEL[m]}
                </option>
              ))}
            </select>
          </label>
          {form.mode === "REPLAY" && (
            <label>
              Years
              <input
                type="number"
                min={0.1}
                step={0.1}
                value={form.years}
                onChange={(e) => setForm({ ...form, years: Number(e.target.value) })}
              />
            </label>
          )}
          {form.mode === "SIMULATION" && (
            <label>
              Bars
              <input
                type="number"
                min={20}
                value={form.simulation_bars}
                onChange={(e) => setForm({ ...form, simulation_bars: Number(e.target.value) })}
              />
            </label>
          )}
          <button onClick={run} disabled={starting || !form.strategy_id}>
            {starting ? "Starting..." : isStandingMode ? "Start run" : "Run"}
          </button>
        </div>

        {form.mode === "LIVE" && (
          <div className="live-warning">
            <strong>LIVE mode places real orders on your connected Dhan account.</strong> It will
            refuse to start if the risk kill-switch is active (see the Risk page). You must
            explicitly confirm below.
            <label className="confirm-row">
              <input
                type="checkbox"
                checked={form.confirm_live}
                onChange={(e) => setForm({ ...form, confirm_live: e.target.checked })}
              />
              I understand this places real orders with real money
            </label>
          </div>
        )}
        {error && <ErrorBanner message={error} />}
      </GlassPanel>

      <div className="grid-2">
        <GlassPanel title="Runs" note={`${runs.length}`}>
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr><th>Started</th><th>Strategy</th><th>Symbol</th><th>Mode</th><th>Status</th><th>P&amp;L</th></tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.run_id} className="clickable" onClick={() => openRun(r.run_id)}>
                    <td>{r.started_at.slice(0, 16).replace("T", " ")}</td>
                    <td>{r.strategy_id}</td>
                    <td>{r.symbol} {r.timeframe}</td>
                    <td><span className={`mode-badge ${r.mode.toLowerCase()}`}>{r.mode}</span></td>
                    <td><span className={`status-badge ${r.status.toLowerCase()}`}>{r.status}</span></td>
                    <td>
                      {r.snapshot?.total_pnl !== undefined ? (
                        <span className={r.snapshot.total_pnl >= 0 ? "gain" : "loss"}>{inr(r.snapshot.total_pnl)}</span>
                      ) : (
                        "-"
                      )}
                    </td>
                  </tr>
                ))}
                {runs.length === 0 && (
                  <tr><td colSpan={6} className="empty">No runs yet.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </GlassPanel>

        {selected && (
          <GlassPanel
            title={`${selected.strategy_id} - ${selected.symbol} ${selected.timeframe}`}
            note={selected.status}
          >
            <div className="detail">
              <div className="detail-row">
                <span className={`status-badge ${selected.status.toLowerCase()}`}>{selected.status}</span>
                <span className={`mode-badge ${selected.mode.toLowerCase()}`}>{selected.mode}</span>
                {selected.status === "RUNNING" && (
                  <button className="stop-btn" onClick={stop}>Stop</button>
                )}
              </div>

              {selected.error && <div className="error">{selected.error}</div>}

              {snap && (
                <>
                  <div className="tiles">
                    <div className="tile">
                      <div className="tile-label">Equity</div>
                      <div className="tile-value">{inr(snap.equity)}</div>
                    </div>
                    <div className="tile">
                      <div className="tile-label">Total P&amp;L</div>
                      <div className={`tile-value ${snap.total_pnl >= 0 ? "gain" : "loss"}`}>{inr(snap.total_pnl)}</div>
                    </div>
                    <div className="tile">
                      <div className="tile-label">Closed trades</div>
                      <div className="tile-value">{snap.closed_trades}</div>
                    </div>
                    <div className="tile">
                      <div className="tile-label">Last action</div>
                      <div className="tile-value">{snap.last_action ?? "-"}</div>
                    </div>
                  </div>

                  {snap.position && (
                    <div className="position-row">
                      <span className="best-label">Open position</span>
                      <span>{snap.position.direction} {snap.position.quantity} @ {snap.position.entry_price}</span>
                      <span>SL {snap.position.stop_loss ?? "-"}</span>
                      <span>TGT {snap.position.target ?? "-"}</span>
                    </div>
                  )}
                  {snap.last_signal && (
                    <div className="signal-row">
                      <span className="best-label">Last signal</span>
                      <span>{snap.last_signal.signal}</span>
                      <span className="reasoning">{snap.last_signal.reasoning}</span>
                    </div>
                  )}

                  {snap.recent_trades?.length > 0 && (
                    <div className="table-scroll">
                      <table className="data-table">
                        <thead>
                          <tr><th>Entry</th><th>Exit</th><th>Dir</th><th>Qty</th><th>P&amp;L</th><th>Reason</th></tr>
                        </thead>
                        <tbody>
                          {[...snap.recent_trades].reverse().map((t: any, i: number) => (
                            <tr key={i}>
                              <td>{t.entry_price}</td>
                              <td>{t.exit_price ?? "-"}</td>
                              <td>{t.direction === "BUY" ? "Long" : "Short"}</td>
                              <td>{t.quantity}</td>
                              <td className={t.pnl >= 0 ? "gain" : "loss"}>{inr(t.pnl)}</td>
                              <td>{t.exit_reason}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </>
              )}

              {selected.result && (
                <div className="result-json">
                  <div className="best-label">Result</div>
                  <pre>{JSON.stringify(selected.result, null, 2)}</pre>
                </div>
              )}
            </div>
          </GlassPanel>
        )}
      </div>

      <style jsx>{`
        .page {
          display: flex;
          flex-direction: column;
          gap: 18px;
        }
        .form {
          display: flex;
          flex-wrap: wrap;
          gap: 14px;
          padding: 18px 20px;
          align-items: flex-end;
        }
        label {
          display: flex;
          flex-direction: column;
          gap: 6px;
          font-size: 11.5px;
          font-weight: 600;
          color: var(--text-muted);
          letter-spacing: 0.04em;
          text-transform: uppercase;
        }
        input, select {
          background: var(--canvas-soft);
          border: 1px solid var(--panel-border);
          border-radius: 9px;
          padding: 9px 12px;
          font-size: 13.5px;
          min-width: 110px;
        }
        button {
          background: linear-gradient(145deg, var(--accent), var(--accent-hover));
          color: #241404;
          font-weight: 700;
          font-size: 13.5px;
          border: none;
          border-radius: 10px;
          padding: 11px 22px;
          cursor: pointer;
        }
        button:disabled {
          opacity: 0.55;
          cursor: default;
        }
        .live-warning {
          margin: 0 20px 18px;
          padding: 14px 16px;
          border-radius: 10px;
          background: var(--loss-dim);
          border: 1px solid rgba(217, 45, 63, 0.3);
          color: var(--text);
          font-size: 12.5px;
          line-height: 1.5;
        }
        .confirm-row {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-top: 10px;
          text-transform: none;
          font-weight: 500;
          font-size: 12.5px;
          color: var(--text);
        }
        .confirm-row input {
          min-width: 0;
          accent-color: var(--loss);
        }
        .error {
          margin: 0 20px 16px;
          padding: 10px 14px;
          border-radius: 9px;
          background: var(--loss-dim);
          border: 1px solid rgba(217, 45, 63, 0.3);
          color: var(--loss);
          font-size: 13px;
        }
        .grid-2 {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 18px;
        }
        @media (max-width: 1000px) {
          .grid-2 { grid-template-columns: 1fr; }
        }
        .table-scroll {
          overflow-x: auto;
          max-height: 420px;
          overflow-y: auto;
        }
        .data-table {
          width: 100%;
          border-collapse: collapse;
          font-size: 12.5px;
        }
        .data-table th {
          text-align: left;
          padding: 10px 16px;
          font-size: 10.5px;
          font-weight: 700;
          letter-spacing: 0.05em;
          text-transform: uppercase;
          color: var(--text-muted);
          border-bottom: 1px solid var(--panel-border);
          position: sticky;
          top: 0;
          background: var(--panel);
        }
        .data-table td {
          padding: 9px 16px;
          border-bottom: 1px solid var(--panel-border);
          font-variant-numeric: tabular-nums;
        }
        .clickable { cursor: pointer; }
        .clickable:hover td { background: var(--canvas-soft); }
        .empty {
          padding: 22px 20px;
          color: var(--text-faint);
          font-size: 13px;
          text-align: center;
        }
        .mode-badge, .status-badge {
          display: inline-block;
          font-size: 10px;
          font-weight: 800;
          letter-spacing: 0.05em;
          padding: 3px 8px;
          border-radius: 999px;
          text-transform: uppercase;
        }
        .mode-badge.live { color: var(--loss); background: var(--loss-dim); border: 1px solid rgba(217, 45, 63, 0.3); }
        .mode-badge.paper { color: var(--accent); background: var(--accent-dim); border: 1px solid rgba(200, 147, 63, 0.3); }
        .mode-badge.replay, .mode-badge.simulation, .mode-badge.backtest, .mode-badge.historical {
          color: var(--text-muted); background: var(--canvas-soft); border: 1px solid var(--panel-border);
        }
        .status-badge.running { color: var(--gain); background: var(--gain-dim); border: 1px solid rgba(14, 159, 110, 0.3); }
        .status-badge.stopped { color: var(--text-faint); background: var(--canvas-soft); border: 1px solid var(--panel-border); }
        .status-badge.completed { color: var(--accent); background: var(--accent-dim); border: 1px solid rgba(200, 147, 63, 0.3); }
        .status-badge.error { color: var(--loss); background: var(--loss-dim); border: 1px solid rgba(217, 45, 63, 0.26); }
        .detail {
          padding: 4px 20px 18px;
          display: flex;
          flex-direction: column;
          gap: 14px;
        }
        .detail-row {
          display: flex;
          align-items: center;
          gap: 10px;
          padding-top: 14px;
        }
        .stop-btn {
          margin-left: auto;
          background: var(--loss-dim);
          color: var(--loss);
          border: 1px solid rgba(217, 45, 63, 0.35);
          padding: 6px 14px;
          font-size: 12px;
          border-radius: 8px;
        }
        .tiles {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
          gap: 10px;
        }
        .tile {
          background: var(--canvas-soft);
          border: 1px solid var(--panel-border);
          border-radius: 10px;
          padding: 10px 12px;
        }
        .tile-label {
          font-size: 10px;
          font-weight: 700;
          letter-spacing: 0.05em;
          text-transform: uppercase;
          color: var(--text-faint);
        }
        .tile-value {
          margin-top: 4px;
          font-family: var(--font-data);
          font-variant-numeric: tabular-nums;
          font-size: 14px;
          font-weight: 600;
        }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
        .position-row, .signal-row {
          display: flex;
          flex-wrap: wrap;
          gap: 6px 14px;
          font-size: 12px;
          padding: 10px 0;
          border-top: 1px solid var(--panel-border);
        }
        .best-label {
          font-size: 9.5px;
          font-weight: 800;
          letter-spacing: 0.06em;
          text-transform: uppercase;
          color: var(--text-faint);
        }
        .reasoning {
          color: var(--text-muted);
        }
        .result-json {
          padding-top: 10px;
          border-top: 1px solid var(--panel-border);
        }
        .result-json pre {
          font-size: 11px;
          max-height: 260px;
          overflow: auto;
          background: var(--canvas-soft);
          padding: 10px;
          border-radius: 8px;
        }
      `}</style>
    </div>
  );
}
