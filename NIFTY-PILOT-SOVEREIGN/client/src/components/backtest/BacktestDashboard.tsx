"use client";

import { useState, useCallback, useRef } from "react";
import type {
  BacktestConfig,
  BacktestJobStatus,
  BacktestFullResults,
  WalkForwardResult,
  YearlyBreakdown,
  RegimePerformance,
  DrawdownPeriod,
  PerStrategyExtended,
  MonthlyReturnsRow,
} from "@/lib/types";
import {
  STRATEGIES,
  DATA_SOURCES,
  DEFAULT_BACKTEST_CONFIG,
} from "@/lib/constants";

type Tab =
  | "overview"
  | "leaderboard"
  | "yearly"
  | "regime"
  | "drawdown"
  | "correlation"
  | "trades";

const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "leaderboard", label: "Leaderboard" },
  { id: "yearly", label: "Yearly" },
  { id: "regime", label: "Regime" },
  { id: "drawdown", label: "Drawdown" },
  { id: "correlation", label: "Correlation" },
  { id: "trades", label: "Trade Log" },
];

function fmt(n: number | null | undefined, decimals = 2): string {
  if (n == null || isNaN(n)) return "—";
  return n.toFixed(decimals);
}

function fmtPct(n: number | null | undefined): string {
  if (n == null || isNaN(n)) return "—";
  return (n * 100).toFixed(1) + "%";
}

function fmtINR(n: number): string {
  return "₹" + n.toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

// ─── Config Panel ─────────────────────────────────────────────────────────────

function ConfigPanel({
  onSubmit,
  loading,
}: {
  onSubmit: (cfg: BacktestConfig) => void;
  loading: boolean;
}) {
  const [years, setYears] = useState<number>(DEFAULT_BACKTEST_CONFIG.years);
  const [capital, setCapital] = useState<number>(DEFAULT_BACKTEST_CONFIG.capital);
  const [instruments, setInstruments] = useState<string>(
    DEFAULT_BACKTEST_CONFIG.instruments
  );
  const [dataSource, setDataSource] = useState<string>(
    DEFAULT_BACKTEST_CONFIG.data_source
  );
  const [selectedStrats, setSelectedStrats] = useState<string[]>([]);
  const [maxConcurrent, setMaxConcurrent] = useState(0);

  const toggleStrat = (id: string) => {
    setSelectedStrats((prev) =>
      prev.includes(id) ? prev.filter((s) => s !== id) : [...prev, id]
    );
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit({
      years,
      capital,
      instruments,
      data_source: dataSource,
      strategies: selectedStrats,
      max_concurrent: maxConcurrent,
    });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <label className="block">
          <span className="text-xs text-gray-400 uppercase tracking-wide">Years</span>
          <input
            type="number"
            min={1}
            max={5}
            value={years}
            onChange={(e) => setYears(Number(e.target.value))}
            className="mt-1 block w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm"
          />
        </label>
        <label className="block">
          <span className="text-xs text-gray-400 uppercase tracking-wide">Capital (INR)</span>
          <input
            type="number"
            min={100000}
            step={100000}
            value={capital}
            onChange={(e) => setCapital(Number(e.target.value))}
            className="mt-1 block w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm"
          />
        </label>
        <label className="block">
          <span className="text-xs text-gray-400 uppercase tracking-wide">Instruments</span>
          <input
            type="text"
            value={instruments}
            onChange={(e) => setInstruments(e.target.value)}
            className="mt-1 block w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm"
          />
        </label>
        <label className="block">
          <span className="text-xs text-gray-400 uppercase tracking-wide">Data Source</span>
          <select
            value={dataSource}
            onChange={(e) => setDataSource(e.target.value)}
            className="mt-1 block w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm"
          >
            {DATA_SOURCES.map((ds) => (
              <option key={ds} value={ds}>
                {ds}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="text-xs text-gray-400 uppercase tracking-wide">Max Concurrent Positions</span>
          <input
            type="number"
            min={0}
            value={maxConcurrent}
            onChange={(e) => setMaxConcurrent(Number(e.target.value))}
            className="mt-1 block w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm"
          />
        </label>
      </div>

      <div>
        <span className="text-xs text-gray-400 uppercase tracking-wide">
          Strategies ({selectedStrats.length === 0 ? "all" : selectedStrats.length + " selected"})
        </span>
        <div className="mt-2 flex flex-wrap gap-1 max-h-40 overflow-y-auto">
          {STRATEGIES.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => toggleStrat(s.id)}
              className={`px-2 py-0.5 rounded text-xs border transition-colors ${
                selectedStrats.includes(s.id)
                  ? "bg-blue-600 border-blue-500 text-white"
                  : "bg-gray-800 border-gray-700 text-gray-300 hover:border-gray-500"
              }`}
            >
              {s.id}
            </button>
          ))}
        </div>
      </div>

      <button
        type="submit"
        disabled={loading}
        className="w-full py-2 rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-sm font-medium transition-colors"
      >
        {loading ? "Running..." : "Run Backtest"}
      </button>
    </form>
  );
}

// ─── Progress Bar ─────────────────────────────────────────────────────────────

function ProgressSection({ job }: { job: BacktestJobStatus | null }) {
  if (!job) return null;
  const pct = Math.round((job.progress ?? 0) * 100);
  return (
    <div className="space-y-2">
      <div className="flex justify-between text-sm">
        <span className={job.status === "ERROR" ? "text-red-400" : "text-gray-300"}>
          {job.status === "ERROR" ? job.error : (job.message ?? job.status)}
        </span>
        <span className="text-gray-400">{pct}%</span>
      </div>
      <div className="w-full bg-gray-800 rounded-full h-2">
        <div
          className={`h-2 rounded-full transition-all ${
            job.status === "ERROR"
              ? "bg-red-500"
              : job.status === "DONE"
              ? "bg-green-500"
              : "bg-blue-500"
          }`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

// ─── Equity Curve (plain canvas) ─────────────────────────────────────────────

function EquityCurve({ results }: { results: BacktestFullResults }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const equity = results.equity ?? [];

  const draw = useCallback(
    (canvas: HTMLCanvasElement | null) => {
      if (!canvas || equity.length < 2) return;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      const { width, height } = canvas;
      const pad = { t: 20, r: 20, b: 30, l: 70 };
      const W = width - pad.l - pad.r;
      const H = height - pad.t - pad.b;

      ctx.clearRect(0, 0, width, height);

      const values = equity.map((e) => e.equity_inr);
      const minV = Math.min(...values);
      const maxV = Math.max(...values);
      const range = maxV - minV || 1;

      const xOf = (i: number) => pad.l + (i / (equity.length - 1)) * W;
      const yOf = (v: number) => pad.t + H - ((v - minV) / range) * H;

      // Grid lines
      ctx.strokeStyle = "#374151";
      ctx.lineWidth = 1;
      for (let i = 0; i <= 4; i++) {
        const y = pad.t + (i / 4) * H;
        ctx.beginPath();
        ctx.moveTo(pad.l, y);
        ctx.lineTo(pad.l + W, y);
        ctx.stroke();
        const val = maxV - (i / 4) * range;
        ctx.fillStyle = "#9CA3AF";
        ctx.font = "10px monospace";
        ctx.textAlign = "right";
        ctx.fillText("₹" + (val / 1e5).toFixed(0) + "L", pad.l - 4, y + 4);
      }

      // Equity line
      ctx.beginPath();
      ctx.strokeStyle = "#3B82F6";
      ctx.lineWidth = 2;
      equity.forEach((e, i) => {
        const x = xOf(i);
        const y = yOf(e.equity_inr);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();

      // Start/end dates
      ctx.fillStyle = "#6B7280";
      ctx.font = "10px monospace";
      ctx.textAlign = "left";
      ctx.fillText(equity[0].time.slice(0, 10), pad.l, height - 6);
      ctx.textAlign = "right";
      ctx.fillText(equity[equity.length - 1].time.slice(0, 10), pad.l + W, height - 6);
    },
    [equity]
  );

  return (
    <canvas
      ref={(el) => {
        (canvasRef as React.MutableRefObject<HTMLCanvasElement | null>).current =
          el;
        draw(el);
      }}
      width={900}
      height={260}
      className="w-full rounded bg-gray-900"
    />
  );
}

// ─── Tab: Overview ────────────────────────────────────────────────────────────

function OverviewTab({ results }: { results: BacktestFullResults }) {
  const startEq = results.capital_inr;
  const endEq =
    results.equity?.length > 0
      ? results.equity[results.equity.length - 1].equity_inr
      : startEq;
  const netPnL = endEq - startEq;
  const netPct = (netPnL / startEq) * 100;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-4 gap-3">
        {[
          { label: "Net PnL", value: fmtINR(netPnL), sub: fmt(netPct) + "%" },
          { label: "Capital", value: fmtINR(startEq) },
          { label: "End Equity", value: fmtINR(endEq) },
          { label: "Total Trades", value: String(results.trades?.length ?? 0) },
        ].map((card) => (
          <div key={card.label} className="bg-gray-800 rounded-lg p-4">
            <p className="text-xs text-gray-400">{card.label}</p>
            <p
              className={`text-xl font-bold mt-1 ${
                card.label === "Net PnL"
                  ? netPnL >= 0
                    ? "text-green-400"
                    : "text-red-400"
                  : "text-white"
              }`}
            >
              {card.value}
            </p>
            {card.sub && <p className="text-xs text-gray-400 mt-0.5">{card.sub}</p>}
          </div>
        ))}
      </div>
      <EquityCurve results={results} />
      <WalkForwardSummary walkForward={results.walk_forward ?? []} />
    </div>
  );
}

function WalkForwardSummary({ walkForward }: { walkForward: WalkForwardResult[] }) {
  const promoted = walkForward.filter((w) => w.promotion_status === "PROMOTED").length;
  const rejected = walkForward.filter((w) => w.promotion_status === "REJECTED").length;
  const insufficient = walkForward.length - promoted - rejected;
  return (
    <div className="bg-gray-800 rounded-lg p-4">
      <h3 className="text-sm font-medium text-gray-300 mb-3">Walk-Forward Promotion</h3>
      <div className="flex gap-6">
        <span className="text-green-400 text-sm">✓ {promoted} Promoted</span>
        <span className="text-red-400 text-sm">✗ {rejected} Rejected</span>
        <span className="text-gray-400 text-sm">– {insufficient} Insufficient</span>
      </div>
    </div>
  );
}

// ─── Tab: Leaderboard ─────────────────────────────────────────────────────────

function LeaderboardTab({ results }: { results: BacktestFullResults }) {
  const rows = (results.per_strategy ?? []).sort(
    (a, b) => b.net_pnl_inr - a.net_pnl_inr
  );
  return (
    <div className="overflow-auto">
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="text-xs text-gray-400 border-b border-gray-700">
            {["Strategy", "Trades", "Net PnL", "WinRate", "Sharpe", "Sortino", "Calmar", "MaxDD", "Status"].map(
              (h) => (
                <th key={h} className="text-left py-2 px-3 whitespace-nowrap">
                  {h}
                </th>
              )
            )}
          </tr>
        </thead>
        <tbody>
          {rows.map((r: PerStrategyExtended) => (
            <tr key={r.strategy} className="border-b border-gray-800 hover:bg-gray-800/50">
              <td className="py-1.5 px-3 font-mono text-xs">{r.strategy}</td>
              <td className="py-1.5 px-3">{r.total_trades}</td>
              <td
                className={`py-1.5 px-3 ${
                  r.net_pnl_inr >= 0 ? "text-green-400" : "text-red-400"
                }`}
              >
                {fmtINR(r.net_pnl_inr)}
              </td>
              <td className="py-1.5 px-3">{fmtPct(r.win_rate)}</td>
              <td className="py-1.5 px-3">{fmt(r.sharpe)}</td>
              <td className="py-1.5 px-3">{fmt(r.sortino)}</td>
              <td className="py-1.5 px-3">{fmt(r.calmar)}</td>
              <td className="py-1.5 px-3">{fmtPct(r.max_drawdown)}</td>
              <td className="py-1.5 px-3">
                <span
                  className={`px-1.5 py-0.5 rounded text-xs ${
                    r.promotion_status === "PROMOTED"
                      ? "bg-green-900 text-green-300"
                      : r.promotion_status === "REJECTED"
                      ? "bg-red-900 text-red-300"
                      : "bg-gray-700 text-gray-400"
                  }`}
                >
                  {r.promotion_status}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── Tab: Yearly ──────────────────────────────────────────────────────────────

function YearlyTab({ results }: { results: BacktestFullResults }) {
  const map = results.yearly_breakdowns ?? {};
  const strategies = Object.keys(map);
  const allYears = Array.from(
    new Set(strategies.flatMap((s) => (map[s] ?? []).map((y: YearlyBreakdown) => y.year)))
  ).sort();

  return (
    <div className="space-y-4 overflow-auto">
      {strategies.map((strat) => (
        <div key={strat} className="bg-gray-800 rounded-lg p-3">
          <h4 className="text-xs font-mono text-gray-300 mb-2">{strat}</h4>
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr className="text-gray-400 border-b border-gray-700">
                {["Year", "Trades", "Net PnL", "WinRate", "Sharpe", "MaxDD", "Calmar"].map(
                  (h) => (
                    <th key={h} className="text-left py-1 px-2">
                      {h}
                    </th>
                  )
                )}
              </tr>
            </thead>
            <tbody>
              {(map[strat] ?? []).map((y: YearlyBreakdown) => (
                <tr key={y.year} className="border-b border-gray-700/50">
                  <td className="py-1 px-2">{y.year}</td>
                  <td className="py-1 px-2">{y.trades}</td>
                  <td
                    className={`py-1 px-2 ${
                      y.net_pnl_inr >= 0 ? "text-green-400" : "text-red-400"
                    }`}
                  >
                    {fmtINR(y.net_pnl_inr)}
                  </td>
                  <td className="py-1 px-2">{fmtPct(y.win_rate)}</td>
                  <td className="py-1 px-2">{fmt(y.sharpe)}</td>
                  <td className="py-1 px-2">{fmtPct(y.max_drawdown)}</td>
                  <td className="py-1 px-2">{fmt(y.calmar)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
      {strategies.length === 0 && (
        <p className="text-gray-500 text-sm">No yearly data available.</p>
      )}
      {/* Monthly heatmap per strategy — first strategy only for readability */}
      {strategies.length > 0 && results.monthly_returns_map && (
        <MonthlyHeatmap
          strategy={strategies[0]}
          monthlyMap={results.monthly_returns_map[strategies[0]] ?? {}}
          allYears={allYears}
        />
      )}
    </div>
  );
}

const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

function MonthlyHeatmap({
  strategy,
  monthlyMap,
  allYears,
}: {
  strategy: string;
  monthlyMap: Record<string, number>;
  allYears: number[];
}) {
  // Build a year×month table
  const data: Record<number, Record<number, number>> = {};
  Object.entries(monthlyMap).forEach(([key, pnl]) => {
    const [yr, mo] = key.split("-").map(Number);
    if (!data[yr]) data[yr] = {};
    data[yr][mo] = (data[yr][mo] ?? 0) + pnl;
  });

  const allVals = Object.values(data).flatMap((row) => Object.values(row));
  const maxAbs = Math.max(...allVals.map(Math.abs), 1);

  const cellColor = (pnl: number | undefined): string => {
    if (pnl == null) return "bg-gray-800";
    const intensity = Math.min(Math.abs(pnl) / maxAbs, 1);
    if (pnl > 0) return `bg-green-${Math.round(intensity * 4 + 5)}00/60`;
    return `bg-red-${Math.round(intensity * 4 + 5)}00/60`;
  };

  const inlineColor = (pnl: number | undefined): React.CSSProperties => {
    if (pnl == null) return {};
    const intensity = Math.min(Math.abs(pnl) / maxAbs, 1);
    const alpha = 0.15 + intensity * 0.7;
    return pnl > 0
      ? { background: `rgba(34,197,94,${alpha})` }
      : { background: `rgba(239,68,68,${alpha})` };
  };

  return (
    <div>
      <h4 className="text-xs text-gray-400 mb-2">Monthly Returns — {strategy}</h4>
      <div className="overflow-x-auto">
        <table className="text-xs border-collapse">
          <thead>
            <tr>
              <th className="py-1 pr-2 text-gray-500 text-left">Year</th>
              {MONTHS.map((m) => (
                <th key={m} className="py-1 px-1 text-gray-500 text-center w-14">
                  {m}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {allYears.map((yr) => (
              <tr key={yr}>
                <td className="py-0.5 pr-2 text-gray-400">{yr}</td>
                {Array.from({ length: 12 }, (_, i) => i + 1).map((mo) => {
                  const pnl = data[yr]?.[mo];
                  return (
                    <td
                      key={mo}
                      className="py-0.5 px-1 text-center rounded"
                      style={inlineColor(pnl)}
                      title={pnl != null ? fmtINR(pnl) : "—"}
                    >
                      {pnl != null ? (pnl >= 0 ? "+" : "") + (pnl / 1000).toFixed(0) + "k" : ""}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Tab: Regime ──────────────────────────────────────────────────────────────

function RegimeTab({ results }: { results: BacktestFullResults }) {
  const map = results.regime_performances ?? {};
  const strategies = Object.keys(map);
  return (
    <div className="space-y-4 overflow-auto">
      {strategies.map((strat) => (
        <div key={strat} className="bg-gray-800 rounded-lg p-3">
          <h4 className="text-xs font-mono text-gray-300 mb-2">{strat}</h4>
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr className="text-gray-400 border-b border-gray-700">
                {["Regime", "Trades", "Net PnL", "WinRate", "Avg PnL"].map((h) => (
                  <th key={h} className="text-left py-1 px-2">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(map[strat] ?? []).map((r: RegimePerformance) => (
                <tr key={r.regime} className="border-b border-gray-700/50">
                  <td className="py-1 px-2">{r.regime}</td>
                  <td className="py-1 px-2">{r.trades}</td>
                  <td
                    className={`py-1 px-2 ${
                      r.net_pnl_inr >= 0 ? "text-green-400" : "text-red-400"
                    }`}
                  >
                    {fmtINR(r.net_pnl_inr)}
                  </td>
                  <td className="py-1 px-2">{fmtPct(r.win_rate)}</td>
                  <td className="py-1 px-2">{fmtINR(r.avg_pnl_inr)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
      {strategies.length === 0 && (
        <p className="text-gray-500 text-sm">No regime data available.</p>
      )}
    </div>
  );
}

// ─── Tab: Drawdown ────────────────────────────────────────────────────────────

function DrawdownTab({ results }: { results: BacktestFullResults }) {
  const periods = results.drawdown_periods ?? [];
  return (
    <div className="overflow-auto">
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="text-xs text-gray-400 border-b border-gray-700">
            {["#", "Start", "Trough", "End", "Drawdown", "Duration", "Recovery"].map(
              (h) => (
                <th key={h} className="text-left py-2 px-3">
                  {h}
                </th>
              )
            )}
          </tr>
        </thead>
        <tbody>
          {periods.map((p: DrawdownPeriod, i: number) => (
            <tr key={i} className="border-b border-gray-800 hover:bg-gray-800/50">
              <td className="py-1.5 px-3 text-gray-500">{i + 1}</td>
              <td className="py-1.5 px-3">{p.start?.slice(0, 10)}</td>
              <td className="py-1.5 px-3">{p.trough?.slice(0, 10)}</td>
              <td className="py-1.5 px-3">{p.end?.slice(0, 10)}</td>
              <td className="py-1.5 px-3 text-red-400">{fmtPct(p.drawdown_pct / 100)}</td>
              <td className="py-1.5 px-3">{p.duration_days}d</td>
              <td className="py-1.5 px-3">{p.recovery_days > 0 ? p.recovery_days + "d" : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {periods.length === 0 && (
        <p className="text-gray-500 text-sm py-4">No drawdown periods.</p>
      )}
    </div>
  );
}

// ─── Tab: Correlation ─────────────────────────────────────────────────────────

function CorrelationTab({ results }: { results: BacktestFullResults }) {
  const matrix = results.correlation_matrix ?? {};
  const strats = Object.keys(matrix).sort();
  if (strats.length === 0)
    return <p className="text-gray-500 text-sm">No correlation data.</p>;

  const cellBg = (v: number): React.CSSProperties => {
    const alpha = Math.min(Math.abs(v), 1) * 0.8;
    return v > 0
      ? { background: `rgba(59,130,246,${alpha})` }
      : { background: `rgba(239,68,68,${alpha})` };
  };

  return (
    <div className="overflow-auto">
      <table className="text-xs border-collapse">
        <thead>
          <tr>
            <th className="py-1 pr-2" />
            {strats.map((s) => (
              <th
                key={s}
                className="py-1 px-1 text-gray-400 font-mono"
                style={{ writingMode: "vertical-lr", transform: "rotate(180deg)", maxWidth: 24 }}
              >
                {s}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {strats.map((rowS) => (
            <tr key={rowS}>
              <td className="py-0.5 pr-2 text-gray-400 font-mono">{rowS}</td>
              {strats.map((colS) => {
                const v = matrix[rowS]?.[colS] ?? 0;
                return (
                  <td
                    key={colS}
                    className="py-0.5 px-1 text-center w-10 h-8 rounded"
                    style={cellBg(v)}
                    title={`${rowS} × ${colS}: ${fmt(v)}`}
                  >
                    {fmt(v, 1)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── Tab: Trade Log ───────────────────────────────────────────────────────────

function TradeLogTab({ results }: { results: BacktestFullResults }) {
  const trades = results.trades ?? [];
  const [page, setPage] = useState(0);
  const PAGE = 50;
  const slice = trades.slice(page * PAGE, (page + 1) * PAGE);
  const pages = Math.ceil(trades.length / PAGE);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between text-xs text-gray-400">
        <span>{trades.length} trades</span>
        <div className="flex gap-2">
          <button
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0}
            className="px-2 py-0.5 rounded bg-gray-800 disabled:opacity-40"
          >
            ←
          </button>
          <span>
            {page + 1} / {pages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(pages - 1, p + 1))}
            disabled={page >= pages - 1}
            className="px-2 py-0.5 rounded bg-gray-800 disabled:opacity-40"
          >
            →
          </button>
        </div>
      </div>
      <div className="overflow-auto">
        <table className="w-full text-xs border-collapse">
          <thead>
            <tr className="text-gray-400 border-b border-gray-700">
              {["Strategy", "Dir", "Instr", "Entry", "Exit", "PnL"].map((h) => (
                <th key={h} className="text-left py-1 px-2">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {slice.map((t) => (
              <tr key={t.ID} className="border-b border-gray-800 hover:bg-gray-800/50">
                <td className="py-1 px-2 font-mono">{t.Strategy}</td>
                <td
                  className={`py-1 px-2 ${
                    t.Direction === "LONG" ? "text-green-400" : "text-red-400"
                  }`}
                >
                  {t.Direction}
                </td>
                <td className="py-1 px-2">{t.Instrument}</td>
                <td className="py-1 px-2 text-gray-400">{t.EntryAt?.slice(0, 16)}</td>
                <td className="py-1 px-2 text-gray-400">{t.ExitAt?.slice(0, 16) ?? "—"}</td>
                <td
                  className={`py-1 px-2 ${
                    t.NetPnL >= 0 ? "text-green-400" : "text-red-400"
                  }`}
                >
                  {fmtINR(t.NetPnL)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Historical Runs Sidebar ──────────────────────────────────────────────────

function HistoricalSidebar({
  jobs: jobList,
  onSelect,
  selectedId,
}: {
  jobs: BacktestJobStatus[];
  onSelect: (id: string) => void;
  selectedId: string | null;
}) {
  return (
    <div className="w-56 shrink-0 border-r border-gray-800 pr-3 space-y-1">
      <p className="text-xs text-gray-500 uppercase tracking-wide mb-2">Runs</p>
      {jobList.length === 0 && (
        <p className="text-xs text-gray-600">No runs yet.</p>
      )}
      {jobList.map((j) => (
        <button
          key={j.id}
          onClick={() => onSelect(j.id)}
          className={`w-full text-left px-2 py-1.5 rounded text-xs transition-colors ${
            selectedId === j.id
              ? "bg-blue-700 text-white"
              : "hover:bg-gray-800 text-gray-300"
          }`}
        >
          <div className="flex justify-between">
            <span className="truncate font-mono">{j.id.slice(-8)}</span>
            <span
              className={
                j.status === "DONE"
                  ? "text-green-400"
                  : j.status === "ERROR"
                  ? "text-red-400"
                  : "text-yellow-400"
              }
            >
              {j.status === "RUNNING"
                ? Math.round((j.progress ?? 0) * 100) + "%"
                : j.status}
            </span>
          </div>
        </button>
      ))}
    </div>
  );
}

// ─── Main Dashboard ───────────────────────────────────────────────────────────

export function BacktestDashboard() {
  const [activeTab, setActiveTab] = useState<Tab>("overview");
  const [allJobs, setAllJobs] = useState<BacktestJobStatus[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [results, setResults] = useState<BacktestFullResults | null>(null);
  const [loading, setLoading] = useState(false);
  const [currentJob, setCurrentJob] = useState<BacktestJobStatus | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = () => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = null;
  };

  const pollJob = useCallback((id: string) => {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch(`/api/backtest/${id}`);
        const job: BacktestJobStatus = await res.json();
        setCurrentJob(job);
        setAllJobs((prev) =>
          prev.map((j) => (j.id === id ? { ...j, ...job } : j))
        );
        if (job.status === "DONE" || job.status === "ERROR") {
          stopPolling();
          setLoading(false);
        }
      } catch {
        // network error — keep polling
      }
    }, 1000);
  }, []);

  const handleSubmit = async (cfg: BacktestConfig) => {
    setLoading(true);
    setResults(null);
    setCurrentJob(null);
    try {
      const res = await fetch("/api/backtest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(cfg),
      });
      const { job_id } = await res.json();
      const newJob: BacktestJobStatus = {
        id: job_id,
        status: "RUNNING",
        progress: 0,
      };
      setAllJobs((prev) => [newJob, ...prev]);
      setSelectedJobId(job_id);
      setCurrentJob(newJob);
      pollJob(job_id);
    } catch (err) {
      setLoading(false);
      console.error(err);
    }
  };

  const handleSelectJob = async (id: string) => {
    setSelectedJobId(id);
    const job = allJobs.find((j) => j.id === id);
    if (!job) return;
    setCurrentJob(job);
    if (job.status === "RUNNING") {
      pollJob(id);
    }
    // For a DONE job try to load results from API.
    if (job.status === "DONE") {
      try {
        const res = await fetch(`/api/backtest/${id}`);
        const data = await res.json();
        if (data.results) setResults(data.results as BacktestFullResults);
      } catch {
        // silently ignore
      }
    }
  };

  return (
    <div className="min-h-screen bg-gray-900 text-white">
      <div className="max-w-screen-xl mx-auto p-6 space-y-6">
        <h1 className="text-2xl font-bold tracking-tight">Backtest Engine</h1>

        <div className="flex gap-6">
          <HistoricalSidebar
            jobs={allJobs}
            onSelect={handleSelectJob}
            selectedId={selectedJobId}
          />

          <div className="flex-1 space-y-4">
            {/* Config panel */}
            <div className="bg-gray-850 border border-gray-800 rounded-xl p-5">
              <h2 className="text-sm font-semibold text-gray-200 mb-4">Configuration</h2>
              <ConfigPanel onSubmit={handleSubmit} loading={loading} />
            </div>

            {/* Progress */}
            {currentJob && (
              <div className="bg-gray-850 border border-gray-800 rounded-xl p-4">
                <ProgressSection job={currentJob} />
              </div>
            )}

            {/* Results tabs */}
            {results && (
              <div className="bg-gray-850 border border-gray-800 rounded-xl p-5">
                <div className="flex gap-1 border-b border-gray-800 mb-4">
                  {TABS.map((t) => (
                    <button
                      key={t.id}
                      onClick={() => setActiveTab(t.id)}
                      className={`px-3 py-2 text-sm rounded-t transition-colors ${
                        activeTab === t.id
                          ? "bg-gray-800 text-white"
                          : "text-gray-400 hover:text-white"
                      }`}
                    >
                      {t.label}
                    </button>
                  ))}
                </div>
                {activeTab === "overview" && <OverviewTab results={results} />}
                {activeTab === "leaderboard" && <LeaderboardTab results={results} />}
                {activeTab === "yearly" && <YearlyTab results={results} />}
                {activeTab === "regime" && <RegimeTab results={results} />}
                {activeTab === "drawdown" && <DrawdownTab results={results} />}
                {activeTab === "correlation" && <CorrelationTab results={results} />}
                {activeTab === "trades" && <TradeLogTab results={results} />}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
