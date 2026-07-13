"use client";

import { useEffect, useState } from "react";
import { engine } from "@/lib/engineClient";
import { Header } from "@/components/Header";
import type {
  MockTradingStatus,
  MockTradingPortfolio,
  MockTradingAnalytics,
  LeaderboardEntry,
  StrategyValidationStatus,
  Trade,
  HealthSnapshot,
  MarketSnapshot,
  EquityPoint,
  DailyPnLPoint,
  MonthlyReturnPoint,
} from "@/lib/types";

const POLL_MS = 5000;

type Tab = "dashboard" | "positions" | "closed" | "analytics" | "charts" | "leaderboard" | "validation";

const TABS: { id: Tab; label: string }[] = [
  { id: "dashboard",   label: "Portfolio" },
  { id: "positions",   label: "Open Positions" },
  { id: "closed",      label: "Closed Trades" },
  { id: "analytics",   label: "Performance" },
  { id: "charts",      label: "Charts" },
  { id: "leaderboard", label: "Leaderboard" },
  { id: "validation",  label: "Validation" },
];

// ─── Formatters ──────────────────────────────────────────────────────────────

function fmtINR(n: number | undefined | null): string {
  if (n == null || isNaN(n)) return "—";
  const abs = Math.abs(n);
  const sign = n < 0 ? "-" : "";
  if (abs >= 1e7) return `${sign}₹${(abs / 1e7).toFixed(2)}Cr`;
  if (abs >= 1e5) return `${sign}₹${(abs / 1e5).toFixed(2)}L`;
  return `${sign}₹${abs.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

function fmtPct(n: number | undefined | null, decimals = 1): string {
  if (n == null || isNaN(n)) return "—";
  return (n * 100).toFixed(decimals) + "%";
}

function fmtNum(n: number | undefined | null, decimals = 2): string {
  if (n == null || isNaN(n)) return "—";
  return n.toFixed(decimals);
}

function pnlClass(n: number): string {
  return n > 0 ? "text-[var(--green)]" : n < 0 ? "text-[var(--red)]" : "text-[var(--muted)]";
}

function fmtDuration(minutes: number): string {
  if (minutes < 60) return `${Math.round(minutes)}m`;
  return `${Math.floor(minutes / 60)}h ${Math.round(minutes % 60)}m`;
}

// ─── Shared card component ────────────────────────────────────────────────────

function MetricCard({ label, value, sub, valueClass = "", highlight = false }: {
  label: string; value: string; sub?: string; valueClass?: string; highlight?: boolean;
}) {
  return (
    <div className={`rounded-xl border p-4 ${highlight ? "border-blue-600/40 bg-blue-950/20" : "border-[var(--border)] bg-[var(--panel)]"}`}>
      <div className="text-[11px] uppercase tracking-wider text-[var(--muted)] mb-1">{label}</div>
      <div className={`text-xl font-bold font-mono ${valueClass}`}>{value}</div>
      {sub && <div className="text-xs text-[var(--muted)] mt-0.5">{sub}</div>}
    </div>
  );
}

// ─── Tab: Portfolio Dashboard ─────────────────────────────────────────────────

function PortfolioDashboard({ portfolio, status }: {
  portfolio: MockTradingPortfolio | null;
  status: MockTradingStatus | null;
}) {
  if (!portfolio) return <EmptyState label="Portfolio data loading…" />;

  const pnlSign = portfolio.total_pnl_inr >= 0;

  return (
    <div className="space-y-6">
      {/* Status banner */}
      {status && (
        <div className={`flex items-center gap-3 rounded-xl border p-4 ${
          status.mock_trading_active
            ? "border-green-600/40 bg-green-950/20"
            : "border-[var(--border)] bg-[var(--panel)]"
        }`}>
          <span className={`h-3 w-3 rounded-full ${status.mock_trading_active ? "bg-green-500 animate-pulse" : "bg-gray-500"}`} />
          <div>
            <div className="text-sm font-semibold text-white">
              {status.mock_trading_active ? "Mock Trading Active — Auto-executing strategies" : `Mock Trading Inactive — ${status.engine_status.replace(/_/g, " ")}`}
            </div>
            <div className="text-xs text-[var(--muted)]">
              Market: {status.market_open_time} – {status.market_close_time} IST · Auto-detection enabled
              {!status.market_open && status.next_market_open && ` · Next open: ${new Date(status.next_market_open).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}`}
            </div>
          </div>
        </div>
      )}

      {/* Primary metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          label="Portfolio Value"
          value={fmtINR(portfolio.portfolio_value_inr)}
          sub={`Capital: ${fmtINR(portfolio.capital_inr)}`}
          highlight
        />
        <MetricCard
          label="Total P&L"
          value={fmtINR(portfolio.total_pnl_inr)}
          sub={`${pnlSign ? "+" : ""}${((portfolio.total_pnl_inr / portfolio.capital_inr) * 100).toFixed(2)}% since inception`}
          valueClass={pnlClass(portfolio.total_pnl_inr)}
        />
        <MetricCard
          label="Realized P&L"
          value={fmtINR(portfolio.realized_pnl_inr)}
          sub="From closed trades"
          valueClass={pnlClass(portfolio.realized_pnl_inr)}
        />
        <MetricCard
          label="Unrealized P&L"
          value={fmtINR(portfolio.unrealized_pnl_inr)}
          sub={`${portfolio.open_positions} open position${portfolio.open_positions !== 1 ? "s" : ""}`}
          valueClass={pnlClass(portfolio.unrealized_pnl_inr)}
        />
      </div>

      {/* Margin + time-bucketed P&L */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          label="Available Margin"
          value={fmtINR(portfolio.margin_available_inr)}
          sub={`${portfolio.margin_utilization_pct.toFixed(1)}% utilised`}
        />
        <MetricCard
          label="Daily P&L"
          value={fmtINR(portfolio.daily_pnl_inr)}
          sub="Last 24 hours"
          valueClass={pnlClass(portfolio.daily_pnl_inr)}
        />
        <MetricCard
          label="Weekly P&L"
          value={fmtINR(portfolio.weekly_pnl_inr)}
          sub="Last 7 days"
          valueClass={pnlClass(portfolio.weekly_pnl_inr)}
        />
        <MetricCard
          label="Monthly P&L"
          value={fmtINR(portfolio.monthly_pnl_inr)}
          sub="Last 30 days"
          valueClass={pnlClass(portfolio.monthly_pnl_inr)}
        />
      </div>

      {/* Today's session */}
      <div className="rounded-xl border border-[var(--border)] bg-[var(--panel)] p-5">
        <h3 className="text-sm font-semibold mb-4">Today&apos;s Session</h3>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-6">
          <div>
            <div className="text-xs text-[var(--muted)]">Trades Executed</div>
            <div className="text-2xl font-bold font-mono mt-1">{portfolio.today_trades}</div>
          </div>
          <div>
            <div className="text-xs text-[var(--muted)]">Wins Today</div>
            <div className="text-2xl font-bold font-mono text-[var(--green)] mt-1">{portfolio.today_wins}</div>
          </div>
          <div>
            <div className="text-xs text-[var(--muted)]">Losses Today</div>
            <div className="text-2xl font-bold font-mono text-[var(--red)] mt-1">{Math.max(0, portfolio.today_trades - portfolio.today_wins)}</div>
          </div>
          <div>
            <div className="text-xs text-[var(--muted)]">Today Win Rate</div>
            <div className="text-2xl font-bold font-mono mt-1">
              {portfolio.today_trades > 0 ? `${((portfolio.today_wins / portfolio.today_trades) * 100).toFixed(0)}%` : "—"}
            </div>
          </div>
        </div>
      </div>

      {/* Margin bar */}
      <div className="rounded-xl border border-[var(--border)] bg-[var(--panel)] p-5">
        <div className="flex justify-between items-center mb-2">
          <span className="text-sm font-semibold">Margin Utilisation</span>
          <span className="text-sm font-mono">{portfolio.margin_utilization_pct.toFixed(1)}%</span>
        </div>
        <div className="w-full bg-gray-800 rounded-full h-3">
          <div
            className={`h-3 rounded-full transition-all ${
              portfolio.margin_utilization_pct > 80 ? "bg-red-500" :
              portfolio.margin_utilization_pct > 60 ? "bg-amber-500" : "bg-blue-500"
            }`}
            style={{ width: `${Math.min(100, portfolio.margin_utilization_pct)}%` }}
          />
        </div>
        <div className="flex justify-between text-xs text-[var(--muted)] mt-1">
          <span>Used: {fmtINR(portfolio.margin_used_inr)}</span>
          <span>Available: {fmtINR(portfolio.margin_available_inr)}</span>
        </div>
      </div>
    </div>
  );
}

// ─── Tab: Open Positions ──────────────────────────────────────────────────────

function OpenPositions({ trades }: { trades: Trade[] }) {
  if (trades.length === 0) return <EmptyState label="No open positions" />;

  return (
    <div className="overflow-auto rounded-xl border border-[var(--border)]">
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="border-b border-[var(--border)] bg-[var(--panel)]">
            {["Symbol", "Strategy", "Direction", "Entry", "Current", "SL", "Target", "Qty", "Unrealized P&L", "Duration"].map(h => (
              <th key={h} className="py-2.5 px-3 text-left text-xs text-[var(--muted)] whitespace-nowrap">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {trades.map(t => {
            const entryTime = new Date(t.EntryAt);
            const durationMins = (Date.now() - entryTime.getTime()) / 60000;
            return (
              <tr key={t.ID} className="border-b border-[var(--border)] hover:bg-[var(--panel)]/50">
                <td className="py-2 px-3 font-mono text-xs">{t.Instrument}</td>
                <td className="py-2 px-3 text-xs">{t.Strategy}</td>
                <td className={`py-2 px-3 text-xs font-semibold ${t.Direction === "LONG" ? "text-[var(--green)]" : "text-[var(--red)]"}`}>
                  {t.Direction}
                </td>
                <td className="py-2 px-3 font-mono text-xs">{t.EntryPrice.toFixed(2)}</td>
                <td className="py-2 px-3 font-mono text-xs text-[var(--muted)]">—</td>
                <td className="py-2 px-3 font-mono text-xs text-[var(--red)]">{t.StopLoss.toFixed(2)}</td>
                <td className="py-2 px-3 font-mono text-xs text-[var(--green)]">{t.TakeProfit.toFixed(2)}</td>
                <td className="py-2 px-3 font-mono text-xs">{t.Quantity}</td>
                <td className={`py-2 px-3 font-mono text-xs ${pnlClass(t.GrossPnL)}`}>{fmtINR(t.GrossPnL)}</td>
                <td className="py-2 px-3 text-xs text-[var(--muted)]">{fmtDuration(durationMins)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ─── Tab: Closed Trades ───────────────────────────────────────────────────────

function ClosedTrades({ trades }: { trades: Trade[] }) {
  const [page, setPage] = useState(0);
  const PAGE = 50;
  const pages = Math.ceil(trades.length / PAGE);
  const slice = trades.slice(page * PAGE, (page + 1) * PAGE);

  if (trades.length === 0) return <EmptyState label="No closed trades yet" />;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs text-[var(--muted)]">{trades.length} total trades</span>
        <div className="flex gap-2 text-xs">
          <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0}
            className="px-2 py-1 rounded bg-[var(--panel)] border border-[var(--border)] disabled:opacity-40">←</button>
          <span className="px-2 py-1">{page + 1} / {pages}</span>
          <button onClick={() => setPage(p => Math.min(pages - 1, p + 1))} disabled={page >= pages - 1}
            className="px-2 py-1 rounded bg-[var(--panel)] border border-[var(--border)] disabled:opacity-40">→</button>
        </div>
      </div>
      <div className="overflow-auto rounded-xl border border-[var(--border)]">
        <table className="w-full text-xs border-collapse">
          <thead>
            <tr className="border-b border-[var(--border)] bg-[var(--panel)]">
              {["Entry Time", "Exit Time", "Strategy", "Symbol", "Dir", "Entry", "Exit", "Qty", "Net P&L", "ROI", "Exit Reason"].map(h => (
                <th key={h} className="py-2.5 px-3 text-left text-[var(--muted)] whitespace-nowrap">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {slice.map(t => {
              const roi = t.MarginBlockedINR > 0 ? (t.NetPnL / t.MarginBlockedINR) * 100 : 0;
              return (
                <tr key={t.ID} className="border-b border-[var(--border)] hover:bg-[var(--panel)]/50">
                  <td className="py-1.5 px-3 font-mono text-[var(--muted)]">{t.EntryAt?.slice(0, 16).replace("T", " ")}</td>
                  <td className="py-1.5 px-3 font-mono text-[var(--muted)]">{t.ExitAt?.slice(0, 16).replace("T", " ") ?? "—"}</td>
                  <td className="py-1.5 px-3">{t.Strategy}</td>
                  <td className="py-1.5 px-3 font-mono">{t.Instrument}</td>
                  <td className={`py-1.5 px-3 font-semibold ${t.Direction === "LONG" ? "text-[var(--green)]" : "text-[var(--red)]"}`}>{t.Direction}</td>
                  <td className="py-1.5 px-3 font-mono">{t.EntryPrice.toFixed(2)}</td>
                  <td className="py-1.5 px-3 font-mono">{t.ExitPrice?.toFixed(2) ?? "—"}</td>
                  <td className="py-1.5 px-3 font-mono">{t.Quantity}</td>
                  <td className={`py-1.5 px-3 font-mono font-semibold ${pnlClass(t.NetPnL)}`}>{fmtINR(t.NetPnL)}</td>
                  <td className={`py-1.5 px-3 font-mono ${pnlClass(roi)}`}>{roi.toFixed(1)}%</td>
                  <td className="py-1.5 px-3 text-[var(--muted)]">{t.ExitReason ?? "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Tab: Performance Analytics ───────────────────────────────────────────────

function PerformanceAnalytics({ analytics }: { analytics: MockTradingAnalytics | null }) {
  if (!analytics) return <EmptyState label="No trade data yet — analytics will appear after first closed trade" />;
  if (analytics.total_trades === 0) return <EmptyState label="No closed trades yet — complete some trades to see analytics" />;

  const statGroups = [
    {
      title: "Trade Statistics",
      items: [
        { label: "Total Trades",         value: String(analytics.total_trades) },
        { label: "Winning Trades",       value: String(analytics.winning_trades), cls: "text-[var(--green)]" },
        { label: "Losing Trades",        value: String(analytics.losing_trades), cls: "text-[var(--red)]" },
        { label: "Breakeven Trades",     value: String(analytics.breakeven_trades) },
        { label: "Win Rate",             value: fmtPct(analytics.win_rate), cls: analytics.win_rate >= 0.4 ? "text-[var(--green)]" : "text-[var(--red)]" },
        { label: "Loss Rate",            value: fmtPct(analytics.loss_rate) },
        { label: "Max Consec. Wins",     value: String(analytics.max_consecutive_wins), cls: "text-[var(--green)]" },
        { label: "Max Consec. Losses",   value: String(analytics.max_consecutive_losses), cls: "text-[var(--red)]" },
        { label: "Avg Hold Time",        value: fmtDuration(analytics.avg_hold_minutes) },
      ],
    },
    {
      title: "Profit & Loss",
      items: [
        { label: "Net P&L",              value: fmtINR(analytics.net_pnl_inr), cls: pnlClass(analytics.net_pnl_inr) },
        { label: "Gross P&L",            value: fmtINR(analytics.gross_pnl_inr), cls: pnlClass(analytics.gross_pnl_inr) },
        { label: "Total Fees & Taxes",   value: fmtINR(analytics.total_fees_inr), cls: "text-[var(--red)]" },
        { label: "Avg Win",              value: fmtINR(analytics.avg_win_inr), cls: "text-[var(--green)]" },
        { label: "Avg Loss",             value: fmtINR(analytics.avg_loss_inr), cls: "text-[var(--red)]" },
        { label: "Largest Win",          value: fmtINR(analytics.largest_win_inr), cls: "text-[var(--green)]" },
        { label: "Largest Loss",         value: fmtINR(analytics.largest_loss_inr), cls: "text-[var(--red)]" },
        { label: "Expectancy",           value: fmtINR(analytics.expectancy_inr), cls: pnlClass(analytics.expectancy_inr) },
        { label: "Profit Factor",        value: fmtNum(analytics.profit_factor), cls: analytics.profit_factor > 1 ? "text-[var(--green)]" : "text-[var(--red)]" },
        { label: "Risk:Reward",          value: analytics.risk_reward_ratio > 0 ? `1 : ${analytics.risk_reward_ratio.toFixed(2)}` : "—" },
      ],
    },
    {
      title: "Risk Metrics",
      items: [
        { label: "Max Drawdown",         value: `${analytics.max_drawdown_pct.toFixed(2)}%`, cls: "text-[var(--red)]" },
        { label: "Max Drawdown (₹)",     value: fmtINR(analytics.max_drawdown_inr), cls: "text-[var(--red)]" },
        { label: "Sharpe Ratio",         value: isNaN(analytics.sharpe_ratio) ? "—" : fmtNum(analytics.sharpe_ratio), cls: analytics.sharpe_ratio >= 1 ? "text-[var(--green)]" : "" },
        { label: "Sortino Ratio",        value: isFinite(analytics.sortino_ratio) ? fmtNum(analytics.sortino_ratio) : "∞", cls: analytics.sortino_ratio >= 1 ? "text-[var(--green)]" : "" },
        { label: "CAGR",                 value: isNaN(analytics.cagr) ? "—" : fmtPct(analytics.cagr), cls: analytics.cagr > 0 ? "text-[var(--green)]" : "text-[var(--red)]" },
        { label: "Recovery Factor",      value: isFinite(analytics.recovery_factor) ? fmtNum(analytics.recovery_factor) : "∞" },
      ],
    },
  ];

  return (
    <div className="space-y-6">
      {/* Validation banner */}
      <div className={`flex items-center gap-3 rounded-xl border p-4 ${
        analytics.win_rate >= 0.4 && analytics.profit_factor > 1 && analytics.expectancy_inr > 0
          ? "border-green-600/40 bg-green-950/20"
          : "border-red-600/40 bg-red-950/20"
      }`}>
        <span className="text-lg">{analytics.win_rate >= 0.4 && analytics.profit_factor > 1 && analytics.expectancy_inr > 0 ? "✅" : "❌"}</span>
        <div>
          <div className="text-sm font-semibold text-white">
            {analytics.win_rate >= 0.4 && analytics.profit_factor > 1 && analytics.expectancy_inr > 0
              ? "Portfolio meets all Mock Trading validation criteria"
              : "Portfolio does not meet all Mock Trading validation criteria"}
          </div>
          <div className="text-xs text-[var(--muted)]">
            WinRate {(analytics.win_rate * 100).toFixed(1)}% {analytics.win_rate >= 0.4 ? "✓" : "✗ (need ≥40%)"} ·
            ProfitFactor {analytics.profit_factor.toFixed(2)} {analytics.profit_factor > 1 ? "✓" : "✗ (need >1)"} ·
            Expectancy {fmtINR(analytics.expectancy_inr)} {analytics.expectancy_inr > 0 ? "✓" : "✗ (must be positive)"}
          </div>
        </div>
      </div>

      {statGroups.map(group => (
        <div key={group.title} className="rounded-xl border border-[var(--border)] bg-[var(--panel)] p-5">
          <h3 className="text-sm font-semibold mb-4">{group.title}</h3>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-y-4">
            {group.items.map(item => (
              <div key={item.label}>
                <div className="text-xs text-[var(--muted)]">{item.label}</div>
                <div className={`text-base font-bold font-mono mt-0.5 ${item.cls ?? ""}`}>{item.value}</div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── Tab: Charts ──────────────────────────────────────────────────────────────

function Charts({ analytics }: { analytics: MockTradingAnalytics | null }) {
  if (!analytics || analytics.total_trades === 0) return <EmptyState label="No trade data yet — charts will appear after first closed trade" />;

  return (
    <div className="space-y-6">
      <EquityCurveChart equity={analytics.equity_curve} />
      <DailyPnLChart daily={analytics.daily_pnl} />
      <MonthlyReturnsHeatmap monthly={analytics.monthly_returns} />
      <PnLDistributionChart buckets={analytics.pnl_distribution} />
    </div>
  );
}

function EquityCurveChart({ equity }: { equity: EquityPoint[] }) {
  if (equity.length < 2) return null;
  const values = equity.map(e => e.equity_inr);
  const minV = Math.min(...values);
  const maxV = Math.max(...values);
  const range = maxV - minV || 1;

  const W = 800, H = 200;
  const pad = { t: 20, r: 20, b: 30, l: 70 };
  const iW = W - pad.l - pad.r;
  const iH = H - pad.t - pad.b;

  const pts = equity.map((e, i) => {
    const x = pad.l + (i / (equity.length - 1)) * iW;
    const y = pad.t + iH - ((e.equity_inr - minV) / range) * iH;
    return `${x},${y}`;
  }).join(" ");

  const fillPts = [
    `${pad.l},${pad.t + iH}`,
    ...equity.map((e, i) => {
      const x = pad.l + (i / (equity.length - 1)) * iW;
      const y = pad.t + iH - ((e.equity_inr - minV) / range) * iH;
      return `${x},${y}`;
    }),
    `${pad.l + iW},${pad.t + iH}`,
  ].join(" ");

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--panel)] p-5">
      <h3 className="text-sm font-semibold mb-4">Equity Curve</h3>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
        <defs>
          <linearGradient id="eq-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#3b82f6" stopOpacity="0.3" />
            <stop offset="100%" stopColor="#3b82f6" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0, 1, 2, 3, 4].map(i => {
          const y = pad.t + (i / 4) * iH;
          const val = maxV - (i / 4) * range;
          return (
            <g key={i}>
              <line x1={pad.l} y1={y} x2={pad.l + iW} y2={y} stroke="#1f2937" strokeWidth="1" />
              <text x={pad.l - 4} y={y + 4} fill="#6b7280" fontSize="10" textAnchor="end">
                {val >= 1e7 ? `₹${(val / 1e7).toFixed(1)}Cr` : `₹${(val / 1e5).toFixed(0)}L`}
              </text>
            </g>
          );
        })}
        <polygon points={fillPts} fill="url(#eq-fill)" />
        <polyline points={pts} fill="none" stroke="#3b82f6" strokeWidth="2" />
        <text x={pad.l} y={H - 6} fill="#6b7280" fontSize="10">{equity[0].date}</text>
        <text x={pad.l + iW} y={H - 6} fill="#6b7280" fontSize="10" textAnchor="end">{equity[equity.length - 1].date}</text>
      </svg>
    </div>
  );
}

function DailyPnLChart({ daily }: { daily: DailyPnLPoint[] }) {
  if (daily.length === 0) return null;
  const MAX_BARS = 60;
  const slice = daily.slice(-MAX_BARS);
  const values = slice.map(d => d.pnl_inr);
  const maxAbs = Math.max(...values.map(Math.abs), 1);

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--panel)] p-5">
      <h3 className="text-sm font-semibold mb-4">Daily P&L (last {slice.length} days)</h3>
      <div className="flex items-end gap-0.5 h-28">
        {slice.map((d, i) => {
          const hPct = (Math.abs(d.pnl_inr) / maxAbs) * 100;
          const isPos = d.pnl_inr >= 0;
          return (
            <div key={i} className="flex-1 flex flex-col items-center justify-end h-full group relative" title={`${d.date}: ${fmtINR(d.pnl_inr)}`}>
              <div
                className={`w-full rounded-t ${isPos ? "bg-green-500" : "bg-red-500"} transition-opacity group-hover:opacity-70`}
                style={{ height: `${hPct}%`, minHeight: hPct > 0 ? 2 : 0 }}
              />
              <div className="hidden group-hover:block absolute bottom-full left-1/2 -translate-x-1/2 bg-gray-900 text-xs px-2 py-1 rounded whitespace-nowrap z-10">
                {d.date}<br />{fmtINR(d.pnl_inr)}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function MonthlyReturnsHeatmap({ monthly }: { monthly: MonthlyReturnPoint[] }) {
  if (monthly.length === 0) return null;
  const maxAbs = Math.max(...monthly.map(m => Math.abs(m.pnl_inr)), 1);

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--panel)] p-5">
      <h3 className="text-sm font-semibold mb-4">Monthly Returns</h3>
      <div className="overflow-x-auto">
        <div className="flex gap-1 flex-wrap">
          {monthly.map(m => {
            const intensity = Math.min(Math.abs(m.pnl_inr) / maxAbs, 1);
            const alpha = 0.15 + intensity * 0.7;
            const color = m.pnl_inr >= 0 ? `rgba(34,197,94,${alpha})` : `rgba(239,68,68,${alpha})`;
            return (
              <div
                key={m.month}
                className="rounded p-3 min-w-[80px] cursor-default"
                style={{ background: color }}
                title={`${m.month}: ${fmtINR(m.pnl_inr)} (${m.return_pct.toFixed(1)}%)`}
              >
                <div className="text-[10px] text-white/70">{m.month}</div>
                <div className="text-xs font-bold text-white mt-0.5">
                  {m.pnl_inr >= 0 ? "+" : ""}{fmtINR(m.pnl_inr)}
                </div>
                <div className="text-[10px] text-white/60">{m.trades}T · {(m.win_rate * 100).toFixed(0)}%WR</div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function PnLDistributionChart({ buckets }: { buckets: { label: string; count: number }[] }) {
  if (buckets.length === 0) return null;
  const maxCount = Math.max(...buckets.map(b => b.count), 1);

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--panel)] p-5">
      <h3 className="text-sm font-semibold mb-4">P&L Distribution</h3>
      <div className="space-y-2">
        {buckets.map(b => {
          const widthPct = (b.count / maxCount) * 100;
          const isNeg = b.label.startsWith("-") || b.label.startsWith("<");
          return (
            <div key={b.label} className="flex items-center gap-3">
              <div className="w-28 text-xs text-[var(--muted)] text-right shrink-0">{b.label}</div>
              <div className="flex-1 bg-gray-800 rounded h-5 relative">
                <div
                  className={`h-5 rounded ${isNeg ? "bg-red-500/70" : "bg-green-500/70"}`}
                  style={{ width: `${widthPct}%` }}
                />
              </div>
              <div className="w-8 text-xs text-[var(--muted)] shrink-0">{b.count}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Tab: Leaderboard ─────────────────────────────────────────────────────────

function Leaderboard({ entries }: { entries: LeaderboardEntry[] }) {
  if (entries.length === 0) return <EmptyState label="Loading leaderboard…" />;

  return (
    <div className="space-y-4">
      <div className="text-xs text-[var(--muted)] flex gap-4">
        <span>Score = 30%×WinRate + 25%×ProfitFactor + 20%×Sharpe + 15%×MaxDD + 10%×Recovery</span>
      </div>
      <div className="overflow-auto rounded-xl border border-[var(--border)]">
        <table className="w-full text-xs border-collapse">
          <thead>
            <tr className="border-b border-[var(--border)] bg-[var(--panel)]">
              {["#", "Strategy", "Status", "Score", "Win Rate", "Trades", "Net P&L", "Profit Factor", "Sharpe", "Max DD", "Recovery", "Approved"].map(h => (
                <th key={h} className="py-2.5 px-3 text-left text-[var(--muted)] whitespace-nowrap">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {entries.map(e => (
              <tr key={e.name} className="border-b border-[var(--border)] hover:bg-[var(--panel)]/50">
                <td className="py-2 px-3 text-[var(--muted)]">{e.rank}</td>
                <td className="py-2 px-3 font-mono">{e.name}</td>
                <td className="py-2 px-3">
                  <StatusBadge status={e.status as "PROBATION" | "PENDING" | "ACTIVE" | "DEMOTED"} />
                </td>
                <td className="py-2 px-3 font-bold font-mono">{e.overall_score.toFixed(1)}</td>
                <td className={`py-2 px-3 font-mono ${e.win_rate >= 0.4 ? "text-[var(--green)]" : "text-[var(--red)]"}`}>
                  {fmtPct(e.win_rate)}
                </td>
                <td className="py-2 px-3 font-mono">{e.total_trades}</td>
                <td className={`py-2 px-3 font-mono ${pnlClass(e.net_pnl_inr)}`}>{fmtINR(e.net_pnl_inr)}</td>
                <td className={`py-2 px-3 font-mono ${e.profit_factor > 1 ? "text-[var(--green)]" : "text-[var(--red)]"}`}>
                  {e.profit_factor >= 999 ? "∞" : fmtNum(e.profit_factor)}
                </td>
                <td className="py-2 px-3 font-mono">{fmtNum(e.sharpe)}</td>
                <td className={`py-2 px-3 font-mono ${e.max_drawdown_pct < -15 ? "text-[var(--red)]" : ""}`}>
                  {e.max_drawdown_pct.toFixed(1)}%
                </td>
                <td className="py-2 px-3 font-mono">{isFinite(e.recovery_factor) ? fmtNum(e.recovery_factor) : "∞"}</td>
                <td className="py-2 px-3">
                  {e.mock_trading_approved
                    ? <span className="text-[var(--green)] font-semibold">✓ Approved</span>
                    : <span className="text-[var(--red)]">✗ Pending</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: "PROBATION" | "PENDING" | "ACTIVE" | "DEMOTED" }) {
  const map = {
    PROBATION: "bg-gray-800 text-gray-400",
    PENDING:   "bg-amber-900/50 text-amber-400",
    ACTIVE:    "bg-green-900/50 text-green-400",
    DEMOTED:   "bg-red-900/50 text-red-400",
  };
  return <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${map[status]}`}>{status}</span>;
}

// ─── Tab: Validation ──────────────────────────────────────────────────────────

function ValidationPanel({ validations }: { validations: StrategyValidationStatus[] }) {
  if (validations.length === 0) return <EmptyState label="Loading validation data…" />;

  const approved = validations.filter(v => v.mock_trading_approved);
  const pending = validations.filter(v => !v.mock_trading_approved && v.status !== "DEMOTED");
  const demoted = validations.filter(v => v.status === "DEMOTED");

  return (
    <div className="space-y-6">
      {/* Summary */}
      <div className="grid grid-cols-3 gap-4">
        <MetricCard label="Approved" value={String(approved.length)} sub="Ready for mock trading" valueClass="text-[var(--green)]" />
        <MetricCard label="In Validation" value={String(pending.length)} sub="Accumulating trade windows" />
        <MetricCard label="Demoted" value={String(demoted.length)} sub="Requires operator review" valueClass="text-[var(--red)]" />
      </div>

      {/* Criteria */}
      <div className="rounded-xl border border-[var(--border)] bg-[var(--panel)] p-5">
        <h3 className="text-sm font-semibold mb-3">Validation Criteria</h3>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-xs">
          {[
            { rule: "Win Rate", req: "≥ 40%", desc: "Minimum percentage of profitable trades" },
            { rule: "Profit Factor", req: "> 1.0", desc: "Total profit ÷ total loss must exceed 1" },
            { rule: "Expectancy", req: "> ₹0", desc: "Expected value per trade must be positive" },
            { rule: "Sharpe Ratio", req: "≥ 0.60", desc: "Risk-adjusted return per unit of volatility" },
            { rule: "Max Drawdown", req: "≤ 25%", desc: "Maximum peak-to-trough portfolio decline" },
            { rule: "Min Trades", req: "≥ 30/window", desc: "Two consecutive 30-trade windows must pass" },
          ].map(c => (
            <div key={c.rule} className="bg-[var(--bg)] rounded-lg p-3">
              <div className="font-semibold text-white">{c.rule}</div>
              <div className="text-blue-400 font-mono mt-0.5">{c.req}</div>
              <div className="text-[var(--muted)] mt-1 text-[10px]">{c.desc}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Per-strategy validation table */}
      <div className="overflow-auto rounded-xl border border-[var(--border)]">
        <table className="w-full text-xs border-collapse">
          <thead>
            <tr className="border-b border-[var(--border)] bg-[var(--panel)]">
              {["Strategy", "Status", "Mock Trading", "Windows", "Progress", "Win Rate", "Profit Factor", "Sharpe", "Expectancy", "Max DD", "Rejection Reason"].map(h => (
                <th key={h} className="py-2.5 px-3 text-left text-[var(--muted)] whitespace-nowrap">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {validations.map(v => (
              <tr key={v.strategy} className={`border-b border-[var(--border)] hover:bg-[var(--panel)]/50 ${v.mock_trading_approved ? "" : "opacity-75"}`}>
                <td className="py-2 px-3 font-mono">{v.strategy}</td>
                <td className="py-2 px-3"><StatusBadge status={v.status as "PROBATION" | "PENDING" | "ACTIVE" | "DEMOTED"} /></td>
                <td className="py-2 px-3">
                  {v.mock_trading_approved
                    ? <span className="text-[var(--green)] font-semibold">✓ Approved</span>
                    : <span className="text-[var(--red)]">✗ Not Approved</span>}
                </td>
                <td className="py-2 px-3 font-mono">{v.windows_completed}</td>
                <td className="py-2 px-3">
                  <div className="flex items-center gap-2">
                    <div className="w-16 bg-gray-800 rounded-full h-1.5">
                      <div className="h-1.5 rounded-full bg-blue-500" style={{ width: `${(v.current_window_progress / 30) * 100}%` }} />
                    </div>
                    <span className="font-mono text-[var(--muted)]">{v.current_window_progress}/30</span>
                  </div>
                </td>
                <td className={`py-2 px-3 font-mono ${(v.last_window?.WinRate ?? 0) >= 0.4 ? "text-[var(--green)]" : "text-[var(--red)]"}`}>
                  {v.last_window ? fmtPct(v.last_window.WinRate) : "—"}
                </td>
                <td className={`py-2 px-3 font-mono ${(v.last_window?.ProfitFactor ?? 0) > 1 ? "text-[var(--green)]" : "text-[var(--red)]"}`}>
                  {v.last_window ? fmtNum(v.last_window.ProfitFactor) : "—"}
                </td>
                <td className={`py-2 px-3 font-mono ${(v.last_window?.Sharpe ?? 0) >= 0.6 ? "text-[var(--green)]" : "text-[var(--red)]"}`}>
                  {v.last_window ? fmtNum(v.last_window.Sharpe) : "—"}
                </td>
                <td className={`py-2 px-3 font-mono ${(v.last_window?.Expectancy ?? 0) > 0 ? "text-[var(--green)]" : "text-[var(--red)]"}`}>
                  {v.last_window ? fmtINR(v.last_window.Expectancy) : "—"}
                </td>
                <td className={`py-2 px-3 font-mono ${(v.last_window?.MaxDrawdown ?? 0) < -0.25 ? "text-[var(--red)]" : ""}`}>
                  {v.last_window ? `${(v.last_window.MaxDrawdown * 100).toFixed(1)}%` : "—"}
                </td>
                <td className="py-2 px-3 text-[var(--red)] max-w-xs truncate" title={v.rejection_reason}>
                  {v.rejection_reason ?? "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Empty State ──────────────────────────────────────────────────────────────

function EmptyState({ label }: { label: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-[var(--muted)]">
      <div className="text-4xl mb-4">📊</div>
      <div className="text-sm">{label}</div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export function MockTradingPage() {
  const [tab, setTab] = useState<Tab>("dashboard");
  const [status, setStatus] = useState<MockTradingStatus | null>(null);
  const [portfolio, setPortfolio] = useState<MockTradingPortfolio | null>(null);
  const [analytics, setAnalytics] = useState<MockTradingAnalytics | null>(null);
  const [leaderboard, setLeaderboard] = useState<LeaderboardEntry[]>([]);
  const [validations, setValidations] = useState<StrategyValidationStatus[]>([]);
  const [positions, setPositions] = useState<Trade[]>([]);
  const [closedTrades, setClosedTrades] = useState<Trade[]>([]);
  const [health, setHealth] = useState<HealthSnapshot>();
  const [market, setMarket] = useState<MarketSnapshot>();
  const [error, setError] = useState<string>();

  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const [h, m, s, p, a, lb, v, pos, ct] = await Promise.all([
          engine.health(),
          engine.market(),
          engine.mockTradingStatus(),
          engine.mockTradingPortfolio(),
          engine.mockTradingAnalytics(),
          engine.mockTradingLeaderboard(),
          engine.strategiesValidation(),
          engine.positions(),
          engine.trades(),
        ]);
        if (cancelled) return;
        setHealth(h);
        setMarket(m);
        setStatus(s);
        setPortfolio(p);
        setAnalytics(a);
        setLeaderboard(lb ?? []);
        setValidations(v ?? []);
        setPositions(pos ?? []);
        setClosedTrades(ct ?? []);
        setError(undefined);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "engine unreachable");
      }
    }
    poll();
    const id = setInterval(poll, POLL_MS);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  return (
    <div className="min-h-screen">
      <Header
        health={health}
        niftySpot={market?.nifty_spot}
        bankNiftySpot={market?.banknifty_spot}
        indiaVIX={market?.india_vix}
        title="Mock Trading"
      />

      <div className="max-w-screen-2xl mx-auto px-6 py-6 space-y-6">
        {error && (
          <div className="rounded-xl border border-[var(--red)] bg-red-950/20 p-4 text-sm text-[var(--red)]">
            Engine unreachable: {error}. Start the Go engine on :8090 to connect.
          </div>
        )}

        {/* Tab bar */}
        <div className="flex gap-1 border-b border-[var(--border)]">
          {TABS.map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`px-4 py-2.5 text-sm font-medium rounded-t transition-colors ${
                tab === t.id
                  ? "bg-[var(--panel)] text-white border-b-2 border-blue-500"
                  : "text-[var(--muted)] hover:text-white"
              }`}
            >
              {t.label}
              {t.id === "positions" && positions.length > 0 && (
                <span className="ml-2 bg-blue-600 text-white text-[10px] font-bold px-1.5 py-0.5 rounded-full">
                  {positions.length}
                </span>
              )}
            </button>
          ))}
        </div>

        {/* Tab content */}
        <div>
          {tab === "dashboard"   && <PortfolioDashboard portfolio={portfolio} status={status} />}
          {tab === "positions"   && <OpenPositions trades={positions} />}
          {tab === "closed"      && <ClosedTrades trades={closedTrades} />}
          {tab === "analytics"   && <PerformanceAnalytics analytics={analytics} />}
          {tab === "charts"      && <Charts analytics={analytics} />}
          {tab === "leaderboard" && <Leaderboard entries={leaderboard} />}
          {tab === "validation"  && <ValidationPanel validations={validations} />}
        </div>
      </div>
    </div>
  );
}
