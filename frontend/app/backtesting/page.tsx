"use client";

import { useCallback, useEffect, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import PageHeader from "../../components/PageHeader";
import ErrorBanner from "../../components/ErrorBanner";
import Histogram from "../../components/charts/Histogram";
import LineChart from "../../components/charts/LineChart";
import MonthlyHeatmap from "../../components/charts/MonthlyHeatmap";
import {
  BacktestSummary,
  StrategyInfo,
  fetchBacktest,
  fetchBacktests,
  fetchStrategies,
  runBacktest,
} from "../../lib/api";

const TIMEFRAMES = ["1m", "5m", "15m", "1h", "1d", "1w"];

const inr = (v: number | null | undefined) =>
  v === null || v === undefined ? "-" : v.toLocaleString("en-IN", { maximumFractionDigits: 0 });

export default function BacktestingPage() {
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [history, setHistory] = useState<BacktestSummary[]>([]);
  const [form, setForm] = useState({
    strategy_id: "",
    symbol: "NIFTY",
    timeframe: "1d",
    years: 5,
    initial_capital: 1_000_000,
    walk_forward: false,
    monte_carlo: true,
    paramsJson: "{}",
  });
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Record<string, any> | null>(null);

  useEffect(() => {
    fetchStrategies()
      .then((list) => {
        setStrategies(list);
        if (list.length > 0) setForm((f) => ({ ...f, strategy_id: f.strategy_id || list[0].strategy_id }));
      })
      .catch(() => setError("Backend unreachable - is it running on port 8000?"));
    fetchBacktests().then(setHistory).catch(() => {});
  }, []);

  const run = useCallback(async () => {
    setRunning(true);
    setError(null);
    try {
      const params = JSON.parse(form.paramsJson || "{}");
      const doc = await runBacktest({
        strategy_id: form.strategy_id,
        symbol: form.symbol.trim().toUpperCase(),
        timeframe: form.timeframe,
        years: form.years,
        initial_capital: form.initial_capital,
        params,
        walk_forward: form.walk_forward,
        monte_carlo: form.monte_carlo,
      });
      setResult(doc);
      fetchBacktests().then(setHistory).catch(() => {});
    } catch (e) {
      setError(e instanceof Error ? e.message : "Backtest failed");
    } finally {
      setRunning(false);
    }
  }, [form]);

  const loadRun = useCallback(async (id: string) => {
    setError(null);
    try {
      setResult(await fetchBacktest(id));
    } catch {
      setError("Failed to load backtest");
    }
  }, []);

  const m = result?.metrics;

  return (
    <div className="page">
      <PageHeader
        crumb="Backtesting"
        title="Backtesting"
        subtitle="Event-driven simulation with the full Indian cost stack - signals fill at next bar's open, stops are worst-case. Bars come from the local backfill."
      />

      <GlassPanel title="Run a backtest">
        <div className="form">
          <label>
            Strategy
            <select
              value={form.strategy_id}
              onChange={(e) => setForm({ ...form, strategy_id: e.target.value })}
            >
              {strategies.map((s) => (
                <option key={s.strategy_id} value={s.strategy_id}>
                  {s.name} ({s.category})
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
            Years
            <input
              type="number"
              min={0.25}
              step={0.25}
              value={form.years}
              onChange={(e) => setForm({ ...form, years: Number(e.target.value) })}
            />
          </label>
          <label>
            Capital
            <input
              type="number"
              min={10000}
              step={10000}
              value={form.initial_capital}
              onChange={(e) => setForm({ ...form, initial_capital: Number(e.target.value) })}
            />
          </label>
          <label className="wide">
            Param overrides (JSON)
            <input
              value={form.paramsJson}
              onChange={(e) => setForm({ ...form, paramsJson: e.target.value })}
              placeholder='{"fast": 9, "slow": 21}'
            />
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={form.monte_carlo}
              onChange={(e) => setForm({ ...form, monte_carlo: e.target.checked })}
            />
            Monte Carlo
          </label>
          <label className="check" title="Re-optimizes on an expanding window; slower">
            <input
              type="checkbox"
              checked={form.walk_forward}
              onChange={(e) => setForm({ ...form, walk_forward: e.target.checked })}
            />
            Walk-forward
          </label>
          <button onClick={run} disabled={running || !form.strategy_id}>
            {running ? "Running..." : "Run backtest"}
          </button>
        </div>
        {error && <ErrorBanner message={error} />}
      </GlassPanel>

      {m && result && (
        <>
          <div className="tiles">
            {[
              { label: "Net profit", value: `${inr(m.net_profit)} (${m.total_return_pct > 0 ? "+" : ""}${m.total_return_pct}%)`, tone: m.net_profit >= 0 ? "gain" : "loss" },
              { label: "CAGR", value: m.cagr_pct !== null ? `${m.cagr_pct}%` : "-" },
              { label: "Trades / Win rate", value: m.win_rate !== null ? `${m.total_trades} / ${(m.win_rate * 100).toFixed(0)}%` : `${m.total_trades}` },
              { label: "Profit factor", value: m.profit_factor ?? "-" },
              { label: "Sharpe / Sortino", value: `${m.sharpe ?? "-"} / ${m.sortino ?? "-"}` },
              { label: "Max drawdown", value: `${m.max_drawdown_pct}%`, tone: "loss" },
              { label: "Expectancy", value: inr(m.expectancy) },
              { label: "Exposure", value: `${m.exposure_pct}%` },
              { label: "Charges", value: inr(m.total_charges) },
              { label: "Final equity", value: inr(m.final_equity) },
            ].map((t) => (
              <div className="tile" key={t.label}>
                <div className="tile-label">{t.label}</div>
                <div className={`tile-value ${t.tone ?? ""}`}>{t.value}</div>
              </div>
            ))}
          </div>

          <div className="grid-2">
            <GlassPanel title="Equity curve" note={`${result.symbol} ${result.timeframe} - ${result.bar_count} bars`}>
              <LineChart points={result.charts.equity_curve} color="var(--accent)" />
            </GlassPanel>
            <GlassPanel title="Drawdown" note="% below running peak">
              <LineChart points={result.charts.drawdown_curve} color="var(--loss)" fillToZero valueSuffix="%" />
            </GlassPanel>
          </div>

          <div className="grid-2">
            <GlassPanel title="Monthly returns" note="%, equity-based">
              <MonthlyHeatmap data={m.monthly_returns} />
            </GlassPanel>
            <GlassPanel title="Trade P&L distribution" note={`${m.total_trades} closed trades`}>
              <Histogram buckets={result.charts.trade_distribution} />
              {result.charts.rolling_return?.length > 1 && (
                <>
                  <div className="mini-title">Rolling return (63 bars)</div>
                  <LineChart points={result.charts.rolling_return} color="var(--accent)" height={120} valueSuffix="%" />
                </>
              )}
            </GlassPanel>
          </div>

          {result.walk_forward && (
            <GlassPanel
              title="Walk-forward (out-of-sample)"
              note={`consistency ${(result.walk_forward.consistency * 100).toFixed(0)}% - OOS net ${inr(result.walk_forward.oos_net_profit)}`}
            >
              <table className="data-table">
                <thead>
                  <tr><th>Window</th><th>Test period</th><th>Best params</th><th>OOS net</th><th>Trades</th><th>Win rate</th></tr>
                </thead>
                <tbody>
                  {result.walk_forward.windows.map((w: any) => (
                    <tr key={w.window}>
                      <td>W{w.window}</td>
                      <td>{w.test_start.slice(0, 10)} to {w.test_end.slice(0, 10)}</td>
                      <td className="mono">{JSON.stringify(w.best_params)}</td>
                      <td className={w.oos_metrics.net_profit >= 0 ? "gain" : "loss"}>{inr(w.oos_metrics.net_profit)}</td>
                      <td>{w.oos_metrics.total_trades}</td>
                      <td>{w.oos_metrics.win_rate !== null ? `${(w.oos_metrics.win_rate * 100).toFixed(0)}%` : "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </GlassPanel>
          )}

          {result.monte_carlo && !result.monte_carlo.error && (
            <GlassPanel title="Monte Carlo" note={`${result.monte_carlo.n_runs} bootstrap runs`}>
              <div className="mc-row">
                <div>
                  <div className="tile-label">Final equity p5 / p50 / p95</div>
                  <div className="tile-value">
                    {inr(result.monte_carlo.final_equity.p5)} / {inr(result.monte_carlo.final_equity.p50)} / {inr(result.monte_carlo.final_equity.p95)}
                  </div>
                </div>
                <div>
                  <div className="tile-label">Max DD p50 / p95</div>
                  <div className="tile-value">
                    {result.monte_carlo.max_drawdown_pct.p50}% / {result.monte_carlo.max_drawdown_pct.p95}%
                  </div>
                </div>
                <div>
                  <div className="tile-label">P(profit)</div>
                  <div className="tile-value gain">{(result.monte_carlo.prob_profit * 100).toFixed(0)}%</div>
                </div>
                <div>
                  <div className="tile-label">P(DD &gt; {result.monte_carlo.ruin_threshold_pct}%)</div>
                  <div className="tile-value loss">{(result.monte_carlo.prob_ruin * 100).toFixed(1)}%</div>
                </div>
              </div>
            </GlassPanel>
          )}

          <GlassPanel title="Trades" note="chronological">
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr><th>Entry</th><th>Exit</th><th>Dir</th><th>Qty</th><th>Entry px</th><th>Exit px</th><th>P&L</th><th>Charges</th><th>Reason</th></tr>
                </thead>
                <tbody>
                  {result.charts.trades.map((t: any, i: number) => (
                    <tr key={i}>
                      <td>{t.entry_ts.slice(0, 10)}</td>
                      <td>{t.exit_ts ? t.exit_ts.slice(0, 10) : "-"}</td>
                      <td>{t.direction === "BUY" ? "Long" : "Short"}</td>
                      <td>{t.quantity}</td>
                      <td>{t.entry_price}</td>
                      <td>{t.exit_price ?? "-"}</td>
                      <td className={t.pnl >= 0 ? "gain" : "loss"}>{inr(t.pnl)}</td>
                      <td>{inr(t.charges)}</td>
                      <td>{t.exit_reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </GlassPanel>
        </>
      )}

      <GlassPanel title="Previous runs" note="click to reload">
        {history.length === 0 ? (
          <div className="empty">No saved backtests yet.</div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr><th>When</th><th>Strategy</th><th>Symbol</th><th>TF</th><th>Net</th><th>PF</th><th>Max DD</th><th>Trades</th></tr>
              </thead>
              <tbody>
                {history.map((h) => (
                  <tr key={h.id} className="clickable" onClick={() => loadRun(h.id)}>
                    <td>{h.created_at.slice(0, 16).replace("T", " ")}</td>
                    <td>{h.strategy_id}</td>
                    <td>{h.symbol}</td>
                    <td>{h.timeframe}</td>
                    <td className={(h.metrics.net_profit ?? 0) >= 0 ? "gain" : "loss"}>{inr(h.metrics.net_profit)}</td>
                    <td>{h.metrics.profit_factor ?? "-"}</td>
                    <td>{h.metrics.max_drawdown_pct}%</td>
                    <td>{h.metrics.total_trades}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>

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
        label.wide {
          flex: 1;
          min-width: 220px;
        }
        label.check {
          flex-direction: row;
          align-items: center;
          gap: 8px;
          text-transform: none;
          font-size: 13px;
          font-weight: 500;
          color: var(--text);
          padding-bottom: 10px;
        }
        input,
        select {
          background: var(--canvas-soft);
          border: 1px solid var(--panel-border);
          border-radius: 9px;
          padding: 9px 12px;
          font-size: 13.5px;
          min-width: 110px;
        }
        input[type="checkbox"] {
          min-width: 0;
          accent-color: var(--accent);
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
        .error {
          margin: 0 20px 16px;
          padding: 10px 14px;
          border-radius: 9px;
          background: var(--loss-dim);
          border: 1px solid rgba(217, 45, 63, 0.3);
          color: var(--loss);
          font-size: 13px;
        }
        .tiles {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
          gap: 10px;
        }
        .tile {
          background: var(--panel);
          border: 1px solid var(--panel-border);
          border-radius: 12px;
          padding: 12px 14px;
        }
        .tile-label {
          font-size: 10.5px;
          font-weight: 700;
          letter-spacing: 0.05em;
          text-transform: uppercase;
          color: var(--text-muted);
        }
        .tile-value {
          margin-top: 5px;
          font-family: var(--font-data);
          font-variant-numeric: tabular-nums;
          font-size: 15px;
          font-weight: 600;
        }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
        .grid-2 {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 18px;
        }
        @media (max-width: 1000px) {
          .grid-2 { grid-template-columns: 1fr; }
        }
        .mini-title {
          padding: 10px 20px 0;
          font-size: 11px;
          font-weight: 700;
          letter-spacing: 0.05em;
          text-transform: uppercase;
          color: var(--text-muted);
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
        .data-table .mono {
          font-family: var(--font-data);
          font-size: 11.5px;
        }
        .clickable { cursor: pointer; }
        .clickable:hover td { background: var(--canvas-soft); }
        .mc-row {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
          gap: 16px;
          padding: 18px 20px;
        }
        .empty {
          padding: 22px 20px;
          color: var(--text-faint);
          font-size: 13px;
        }
      `}</style>
    </div>
  );
}
