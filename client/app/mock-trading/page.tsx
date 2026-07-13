'use client'

import { useEffect, useState } from 'react'
import { api } from '@/lib/api'
import type {
  MockTradingStatus,
  MockTradingPortfolio,
  MockTradingAnalytics,
  LeaderboardEntry,
  StrategyValidationStatus,
  Trade,
  EquityPoint,
  DailyPnLPoint,
  MonthlyReturnPoint,
} from '@/lib/types'

const POLL_MS = 5000

type Tab = 'portfolio' | 'positions' | 'closed' | 'analytics' | 'charts' | 'leaderboard' | 'validation'

const TABS: { id: Tab; label: string }[] = [
  { id: 'portfolio',   label: 'Portfolio' },
  { id: 'positions',   label: 'Open Positions' },
  { id: 'closed',      label: 'Closed Trades' },
  { id: 'analytics',   label: 'Performance' },
  { id: 'charts',      label: 'Charts' },
  { id: 'leaderboard', label: 'Leaderboard' },
  { id: 'validation',  label: 'Validation' },
]

// ─── Formatters ───────────────────────────────────────────────────────────────

function fmtINR(n: number | null | undefined): string {
  if (n == null || isNaN(n)) return '—'
  const abs = Math.abs(n)
  const sign = n < 0 ? '-' : ''
  if (abs >= 1e7) return `${sign}₹${(abs / 1e7).toFixed(2)}Cr`
  if (abs >= 1e5) return `${sign}₹${(abs / 1e5).toFixed(2)}L`
  return `${sign}₹${abs.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
}

function fmtPct(n: number | null | undefined, d = 1): string {
  if (n == null || isNaN(n)) return '—'
  return (n * 100).toFixed(d) + '%'
}

function fmtNum(n: number | null | undefined, d = 2): string {
  if (n == null || isNaN(n)) return '—'
  return n.toFixed(d)
}

function pnlCls(n: number) {
  return n > 0 ? 'text-green-400' : n < 0 ? 'text-red-400' : 'text-text-muted'
}

function fmtDur(mins: number): string {
  if (mins < 60) return `${Math.round(mins)}m`
  return `${Math.floor(mins / 60)}h ${Math.round(mins % 60)}m`
}

// ─── Shared components ────────────────────────────────────────────────────────

function Card({ label, value, sub, cls = '', accent = false }: {
  label: string; value: string; sub?: string; cls?: string; accent?: boolean
}) {
  return (
    <div className={`rounded-xl border p-4 ${accent ? 'border-primary/30 bg-primary/5' : 'border-border bg-surface'}`}>
      <p className="text-xs text-text-muted uppercase tracking-wider mb-1">{label}</p>
      <p className={`text-xl font-bold font-mono ${cls}`}>{value}</p>
      {sub && <p className="text-xs text-text-muted mt-0.5">{sub}</p>}
    </div>
  )
}

function StatusPill({ status }: { status: string }) {
  const map: Record<string, string> = {
    PROBATION: 'bg-neutral-800 text-neutral-400',
    PENDING:   'bg-yellow-900/40 text-yellow-400',
    ACTIVE:    'bg-green-900/40 text-green-400',
    DEMOTED:   'bg-red-900/40 text-red-400',
  }
  return (
    <span className={`inline-flex px-2 py-0.5 rounded-full text-[11px] font-semibold ${map[status] ?? 'bg-neutral-800 text-neutral-400'}`}>
      {status}
    </span>
  )
}

function Empty({ label }: { label: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-text-muted gap-3">
      <span className="text-5xl">📊</span>
      <p className="text-sm">{label}</p>
    </div>
  )
}

// ─── Portfolio tab ────────────────────────────────────────────────────────────

function PortfolioTab({ portfolio, status }: {
  portfolio: MockTradingPortfolio | null
  status: MockTradingStatus | null
}) {
  if (!portfolio) return <Empty label="Loading portfolio…" />

  return (
    <div className="space-y-6">
      {/* Engine status banner */}
      {status && (
        <div className={`flex items-start gap-4 rounded-xl border p-5 ${
          status.mock_trading_active
            ? 'border-green-500/30 bg-green-950/20'
            : 'border-border bg-surface'
        }`}>
          <div className={`mt-1 h-3 w-3 rounded-full shrink-0 ${
            status.mock_trading_active ? 'bg-green-500 animate-pulse' : 'bg-neutral-500'
          }`} />
          <div>
            <p className="font-semibold text-text-primary">
              {status.mock_trading_active
                ? 'Mock Trading Active — Automatically placing trades'
                : `Engine Status: ${status.engine_status.replace(/_/g, ' ')}`}
            </p>
            <p className="text-sm text-text-muted mt-0.5">
              Market hours: {status.market_open_time}–{status.market_close_time} IST ·
              Auto-detection enabled ·
              {status.market_open
                ? ` Session active since ${new Date(status.session_start).toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit' })}`
                : status.next_market_open
                  ? ` Next open: ${new Date(status.next_market_open).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}`
                  : ''}
            </p>
          </div>
        </div>
      )}

      {/* Primary metrics grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Card label="Portfolio Value"    value={fmtINR(portfolio.portfolio_value_inr)}  sub={`Capital: ${fmtINR(portfolio.capital_inr)}`} accent />
        <Card label="Total P&L"          value={fmtINR(portfolio.total_pnl_inr)}         sub={`${((portfolio.total_pnl_inr / portfolio.capital_inr) * 100).toFixed(2)}% since inception`} cls={pnlCls(portfolio.total_pnl_inr)} />
        <Card label="Realized P&L"       value={fmtINR(portfolio.realized_pnl_inr)}      sub="Closed trades" cls={pnlCls(portfolio.realized_pnl_inr)} />
        <Card label="Unrealized P&L"     value={fmtINR(portfolio.unrealized_pnl_inr)}    sub={`${portfolio.open_positions} open position${portfolio.open_positions !== 1 ? 's' : ''}`} cls={pnlCls(portfolio.unrealized_pnl_inr)} />
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Card label="Available Margin"   value={fmtINR(portfolio.margin_available_inr)}  sub={`${portfolio.margin_utilization_pct.toFixed(1)}% utilised`} />
        <Card label="Daily P&L"          value={fmtINR(portfolio.daily_pnl_inr)}          sub="Last 24 hours" cls={pnlCls(portfolio.daily_pnl_inr)} />
        <Card label="Weekly P&L"         value={fmtINR(portfolio.weekly_pnl_inr)}         sub="Last 7 days"   cls={pnlCls(portfolio.weekly_pnl_inr)} />
        <Card label="Monthly P&L"        value={fmtINR(portfolio.monthly_pnl_inr)}        sub="Last 30 days"  cls={pnlCls(portfolio.monthly_pnl_inr)} />
      </div>

      {/* Today's session */}
      <div className="rounded-xl border border-border bg-surface p-5">
        <h3 className="text-sm font-semibold text-text-primary mb-4">Today&apos;s Session</h3>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-6">
          {[
            { label: 'Trades Executed', value: portfolio.today_trades, cls: 'text-text-primary' },
            { label: 'Wins', value: portfolio.today_wins, cls: 'text-green-400' },
            { label: 'Losses', value: Math.max(0, portfolio.today_trades - portfolio.today_wins), cls: 'text-red-400' },
            { label: "Win Rate", value: portfolio.today_trades > 0 ? `${((portfolio.today_wins / portfolio.today_trades) * 100).toFixed(0)}%` : '—', cls: '' },
          ].map(({ label, value, cls }) => (
            <div key={label}>
              <p className="text-xs text-text-muted">{label}</p>
              <p className={`text-3xl font-bold font-mono mt-1 ${cls}`}>{value}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Margin bar */}
      <div className="rounded-xl border border-border bg-surface p-5">
        <div className="flex justify-between mb-2">
          <span className="text-sm font-semibold text-text-primary">Margin Utilisation</span>
          <span className="text-sm font-mono text-text-primary">{portfolio.margin_utilization_pct.toFixed(1)}%</span>
        </div>
        <div className="h-3 w-full rounded-full bg-neutral-800">
          <div
            className={`h-3 rounded-full transition-all ${
              portfolio.margin_utilization_pct > 80 ? 'bg-red-500' :
              portfolio.margin_utilization_pct > 60 ? 'bg-yellow-500' : 'bg-primary'
            }`}
            style={{ width: `${Math.min(100, portfolio.margin_utilization_pct)}%` }}
          />
        </div>
        <div className="flex justify-between text-xs text-text-muted mt-1.5">
          <span>Used: {fmtINR(portfolio.margin_used_inr)}</span>
          <span>Available: {fmtINR(portfolio.margin_available_inr)}</span>
        </div>
      </div>
    </div>
  )
}

// ─── Open Positions tab ───────────────────────────────────────────────────────

function OpenPositionsTab({ trades }: { trades: Trade[] }) {
  if (trades.length === 0) return <Empty label="No open positions right now" />

  return (
    <div className="overflow-x-auto rounded-xl border border-border">
      <table className="w-full text-sm">
        <thead className="border-b border-border bg-surface">
          <tr>
            {['Symbol', 'Strategy', 'Dir', 'Entry', 'SL', 'Target', 'Qty', 'Unrealized P&L', 'Duration'].map(h => (
              <th key={h} className="py-3 px-4 text-left text-xs text-text-muted font-medium whitespace-nowrap">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {trades.map(t => {
            const durMins = (Date.now() - new Date(t.entryAt).getTime()) / 60000
            return (
              <tr key={t.id} className="border-b border-border hover:bg-surface-elevated transition-colors">
                <td className="py-2.5 px-4 font-mono text-xs">{t.instrument}</td>
                <td className="py-2.5 px-4 text-xs text-text-muted">{t.strategy.split('_').slice(0, 2).join('_')}</td>
                <td className={`py-2.5 px-4 text-xs font-semibold ${t.direction === 'LONG' ? 'text-green-400' : 'text-red-400'}`}>
                  {t.direction}
                </td>
                <td className="py-2.5 px-4 font-mono text-xs">{t.entryPrice.toFixed(2)}</td>
                <td className="py-2.5 px-4 font-mono text-xs text-red-400">{t.stopLoss.toFixed(2)}</td>
                <td className="py-2.5 px-4 font-mono text-xs text-green-400">{t.takeProfit.toFixed(2)}</td>
                <td className="py-2.5 px-4 font-mono text-xs">{t.quantity}</td>
                <td className={`py-2.5 px-4 font-mono text-xs font-semibold ${pnlCls(t.grossPnl)}`}>{fmtINR(t.grossPnl)}</td>
                <td className="py-2.5 px-4 text-xs text-text-muted">{fmtDur(durMins)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ─── Closed Trades tab ────────────────────────────────────────────────────────

function ClosedTradesTab({ trades }: { trades: Trade[] }) {
  const [page, setPage] = useState(0)
  const PAGE = 50
  const pages = Math.max(1, Math.ceil(trades.length / PAGE))
  const slice = trades.slice(page * PAGE, (page + 1) * PAGE)

  if (trades.length === 0) return <Empty label="No closed trades yet — trades will appear here once the engine closes positions" />

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm text-text-muted">{trades.length} closed trades</span>
        <div className="flex items-center gap-2 text-xs text-text-muted">
          <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0}
            className="px-2 py-1 rounded border border-border bg-surface disabled:opacity-30">←</button>
          <span>{page + 1} / {pages}</span>
          <button onClick={() => setPage(p => Math.min(pages - 1, p + 1))} disabled={page >= pages - 1}
            className="px-2 py-1 rounded border border-border bg-surface disabled:opacity-30">→</button>
        </div>
      </div>
      <div className="overflow-x-auto rounded-xl border border-border">
        <table className="w-full text-xs">
          <thead className="border-b border-border bg-surface">
            <tr>
              {['Entry Time', 'Exit Time', 'Strategy', 'Symbol', 'Dir', 'Entry', 'Exit', 'Qty', 'Net P&L', 'ROI', 'Exit Reason'].map(h => (
                <th key={h} className="py-2.5 px-3 text-left text-text-muted font-medium whitespace-nowrap">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {slice.map(t => {
              const roi = t.marginBlockedINR > 0 ? (t.netPnl / t.marginBlockedINR) * 100 : 0
              return (
                <tr key={t.id} className="border-b border-border hover:bg-surface-elevated transition-colors">
                  <td className="py-2 px-3 font-mono text-text-muted">{t.entryAt?.slice(0, 16).replace('T', ' ')}</td>
                  <td className="py-2 px-3 font-mono text-text-muted">{t.exitAt?.slice(0, 16).replace('T', ' ') ?? '—'}</td>
                  <td className="py-2 px-3 text-text-secondary">{t.strategy.split('_').slice(0, 2).join('_')}</td>
                  <td className="py-2 px-3 font-mono">{t.instrument}</td>
                  <td className={`py-2 px-3 font-semibold ${t.direction === 'LONG' ? 'text-green-400' : 'text-red-400'}`}>{t.direction}</td>
                  <td className="py-2 px-3 font-mono">{t.entryPrice.toFixed(2)}</td>
                  <td className="py-2 px-3 font-mono">{t.exitPrice?.toFixed(2) ?? '—'}</td>
                  <td className="py-2 px-3 font-mono">{t.quantity}</td>
                  <td className={`py-2 px-3 font-mono font-bold ${pnlCls(t.netPnl)}`}>{fmtINR(t.netPnl)}</td>
                  <td className={`py-2 px-3 font-mono ${pnlCls(roi)}`}>{roi.toFixed(1)}%</td>
                  <td className="py-2 px-3 text-text-muted">{t.exitReason || '—'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ─── Performance Analytics tab ────────────────────────────────────────────────

function AnalyticsTab({ analytics }: { analytics: MockTradingAnalytics | null }) {
  if (!analytics) return <Empty label="No analytics data yet" />
  if (analytics.total_trades === 0) return <Empty label="Analytics will appear after the first closed trade" />

  const allPass = analytics.win_rate >= 0.4 && analytics.profit_factor > 1 && analytics.expectancy_inr > 0

  return (
    <div className="space-y-6">
      {/* Validation status */}
      <div className={`rounded-xl border p-5 flex items-start gap-4 ${allPass ? 'border-green-500/30 bg-green-950/15' : 'border-red-500/30 bg-red-950/15'}`}>
        <span className="text-2xl">{allPass ? '✅' : '❌'}</span>
        <div>
          <p className="font-semibold text-text-primary">
            {allPass ? 'Portfolio meets all Mock Trading validation criteria' : 'Portfolio does not meet all validation criteria'}
          </p>
          <p className="text-sm text-text-muted mt-1">
            Win Rate {(analytics.win_rate * 100).toFixed(1)}% {analytics.win_rate >= 0.4 ? '✓' : '✗ (need ≥40%)'} ·
            Profit Factor {analytics.profit_factor.toFixed(2)} {analytics.profit_factor > 1 ? '✓' : '✗ (need >1.0)'} ·
            Expectancy {fmtINR(analytics.expectancy_inr)} {analytics.expectancy_inr > 0 ? '✓' : '✗ (must be positive)'}
          </p>
        </div>
      </div>

      {/* Stat groups */}
      {[
        {
          title: 'Trade Statistics',
          items: [
            { l: 'Total Trades',           v: String(analytics.total_trades) },
            { l: 'Winning Trades',         v: String(analytics.winning_trades), c: 'text-green-400' },
            { l: 'Losing Trades',          v: String(analytics.losing_trades),  c: 'text-red-400' },
            { l: 'Breakeven',              v: String(analytics.breakeven_trades) },
            { l: 'Win Rate',               v: fmtPct(analytics.win_rate), c: analytics.win_rate >= 0.4 ? 'text-green-400' : 'text-red-400' },
            { l: 'Loss Rate',              v: fmtPct(analytics.loss_rate) },
            { l: 'Max Consec. Wins',       v: String(analytics.max_consecutive_wins), c: 'text-green-400' },
            { l: 'Max Consec. Losses',     v: String(analytics.max_consecutive_losses), c: 'text-red-400' },
            { l: 'Avg Hold Time',          v: fmtDur(analytics.avg_hold_minutes) },
          ],
        },
        {
          title: 'Profit & Loss',
          items: [
            { l: 'Net P&L',                v: fmtINR(analytics.net_pnl_inr),      c: pnlCls(analytics.net_pnl_inr) },
            { l: 'Gross P&L',              v: fmtINR(analytics.gross_pnl_inr),     c: pnlCls(analytics.gross_pnl_inr) },
            { l: 'Total Fees & Taxes',     v: fmtINR(analytics.total_fees_inr),    c: 'text-red-400' },
            { l: 'Avg Win',                v: fmtINR(analytics.avg_win_inr),       c: 'text-green-400' },
            { l: 'Avg Loss',               v: fmtINR(analytics.avg_loss_inr),      c: 'text-red-400' },
            { l: 'Largest Win',            v: fmtINR(analytics.largest_win_inr),   c: 'text-green-400' },
            { l: 'Largest Loss',           v: fmtINR(analytics.largest_loss_inr),  c: 'text-red-400' },
            { l: 'Expectancy / Trade',     v: fmtINR(analytics.expectancy_inr),    c: pnlCls(analytics.expectancy_inr) },
            { l: 'Profit Factor',          v: analytics.profit_factor >= 999 ? '∞' : fmtNum(analytics.profit_factor), c: analytics.profit_factor > 1 ? 'text-green-400' : 'text-red-400' },
            { l: 'Risk : Reward',          v: analytics.risk_reward_ratio > 0 ? `1 : ${analytics.risk_reward_ratio.toFixed(2)}` : '—' },
          ],
        },
        {
          title: 'Risk Metrics',
          items: [
            { l: 'Max Drawdown',           v: `${analytics.max_drawdown_pct.toFixed(2)}%`,                                  c: 'text-red-400' },
            { l: 'Max Drawdown (₹)',       v: fmtINR(analytics.max_drawdown_inr),                                            c: 'text-red-400' },
            { l: 'Sharpe Ratio',           v: isNaN(analytics.sharpe_ratio) ? '—' : fmtNum(analytics.sharpe_ratio),         c: analytics.sharpe_ratio >= 1 ? 'text-green-400' : '' },
            { l: 'Sortino Ratio',          v: isFinite(analytics.sortino_ratio) ? fmtNum(analytics.sortino_ratio) : '∞',    c: analytics.sortino_ratio >= 1 ? 'text-green-400' : '' },
            { l: 'CAGR',                   v: isNaN(analytics.cagr) ? '—' : fmtPct(analytics.cagr),                         c: analytics.cagr > 0 ? 'text-green-400' : 'text-red-400' },
            { l: 'Recovery Factor',        v: isFinite(analytics.recovery_factor) ? fmtNum(analytics.recovery_factor) : '∞' },
          ],
        },
      ].map(group => (
        <div key={group.title} className="rounded-xl border border-border bg-surface p-5">
          <h3 className="text-sm font-semibold text-text-primary mb-4">{group.title}</h3>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-y-5">
            {group.items.map(({ l, v, c }) => (
              <div key={l}>
                <p className="text-xs text-text-muted">{l}</p>
                <p className={`text-base font-bold font-mono mt-0.5 ${c ?? 'text-text-primary'}`}>{v}</p>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

// ─── Charts tab ───────────────────────────────────────────────────────────────

function ChartsTab({ analytics }: { analytics: MockTradingAnalytics | null }) {
  if (!analytics || analytics.total_trades === 0)
    return <Empty label="Charts will appear after the first closed trade" />

  return (
    <div className="space-y-6">
      <EquityCurveChart equity={analytics.equity_curve} />
      <DailyPnLChart daily={analytics.daily_pnl} />
      <MonthlyHeatmap monthly={analytics.monthly_returns} />
      <PnLDistribution buckets={analytics.pnl_distribution} />
    </div>
  )
}

function EquityCurveChart({ equity }: { equity: EquityPoint[] }) {
  if (equity.length < 2) return null
  const vals = equity.map(e => e.equity_inr)
  const minV = Math.min(...vals), maxV = Math.max(...vals)
  const range = maxV - minV || 1
  const W = 800, H = 220
  const pad = { t: 20, r: 20, b: 30, l: 75 }
  const iW = W - pad.l - pad.r, iH = H - pad.t - pad.b

  const pts = equity.map((e, i) =>
    `${pad.l + (i / (equity.length - 1)) * iW},${pad.t + iH - ((e.equity_inr - minV) / range) * iH}`
  ).join(' ')

  const fillPts = [
    `${pad.l},${pad.t + iH}`,
    ...equity.map((e, i) =>
      `${pad.l + (i / (equity.length - 1)) * iW},${pad.t + iH - ((e.equity_inr - minV) / range) * iH}`
    ),
    `${pad.l + iW},${pad.t + iH}`,
  ].join(' ')

  return (
    <div className="rounded-xl border border-border bg-surface p-5">
      <h3 className="text-sm font-semibold text-text-primary mb-4">Equity Curve</h3>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
        <defs>
          <linearGradient id="eqg" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#3b82f6" stopOpacity="0.35" />
            <stop offset="100%" stopColor="#3b82f6" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0,1,2,3,4].map(i => {
          const y = pad.t + (i / 4) * iH
          const v = maxV - (i / 4) * range
          return (
            <g key={i}>
              <line x1={pad.l} y1={y} x2={pad.l + iW} y2={y} stroke="#1f2937" strokeWidth="1" />
              <text x={pad.l - 5} y={y + 4} fill="#6b7280" fontSize="10" textAnchor="end">
                {v >= 1e7 ? `₹${(v/1e7).toFixed(1)}Cr` : `₹${(v/1e5).toFixed(0)}L`}
              </text>
            </g>
          )
        })}
        <polygon points={fillPts} fill="url(#eqg)" />
        <polyline points={pts} fill="none" stroke="#3b82f6" strokeWidth="2.5" strokeLinejoin="round" />
        <text x={pad.l} y={H - 4} fill="#6b7280" fontSize="10">{equity[0].date}</text>
        <text x={pad.l + iW} y={H - 4} fill="#6b7280" fontSize="10" textAnchor="end">{equity[equity.length - 1].date}</text>
      </svg>
    </div>
  )
}

function DailyPnLChart({ daily }: { daily: DailyPnLPoint[] }) {
  if (daily.length === 0) return null
  const slice = daily.slice(-60)
  const maxAbs = Math.max(...slice.map(d => Math.abs(d.pnl_inr)), 1)

  return (
    <div className="rounded-xl border border-border bg-surface p-5">
      <h3 className="text-sm font-semibold text-text-primary mb-4">Daily P&L (last {slice.length} trading days)</h3>
      <div className="flex items-end gap-px h-28">
        {slice.map((d, i) => {
          const h = (Math.abs(d.pnl_inr) / maxAbs) * 100
          return (
            <div key={i} className="flex-1 flex flex-col justify-end h-full group relative cursor-default" title={`${d.date}: ${fmtINR(d.pnl_inr)} · ${d.trades}T · ${(d.win_rate*100).toFixed(0)}%WR`}>
              <div
                className={`w-full rounded-sm ${d.pnl_inr >= 0 ? 'bg-green-500' : 'bg-red-500'} group-hover:opacity-75 transition-opacity`}
                style={{ height: `${Math.max(h, 1)}%` }}
              />
              <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 hidden group-hover:flex flex-col items-center bg-neutral-900 border border-border rounded px-2 py-1 text-[10px] whitespace-nowrap z-10 shadow-lg">
                <span className="font-semibold">{d.date}</span>
                <span className={pnlCls(d.pnl_inr)}>{fmtINR(d.pnl_inr)}</span>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function MonthlyHeatmap({ monthly }: { monthly: MonthlyReturnPoint[] }) {
  if (monthly.length === 0) return null
  const maxAbs = Math.max(...monthly.map(m => Math.abs(m.pnl_inr)), 1)

  return (
    <div className="rounded-xl border border-border bg-surface p-5">
      <h3 className="text-sm font-semibold text-text-primary mb-4">Monthly Returns</h3>
      <div className="flex flex-wrap gap-2">
        {monthly.map(m => {
          const intensity = Math.min(Math.abs(m.pnl_inr) / maxAbs, 1)
          const alpha = 0.15 + intensity * 0.7
          const bg = m.pnl_inr >= 0 ? `rgba(34,197,94,${alpha})` : `rgba(239,68,68,${alpha})`
          return (
            <div
              key={m.month}
              className="rounded-lg p-3 min-w-[90px] cursor-default"
              style={{ background: bg }}
              title={`${m.month}: ${fmtINR(m.pnl_inr)} (${m.return_pct.toFixed(1)}%)\n${m.trades} trades · ${(m.win_rate*100).toFixed(0)}% WR`}
            >
              <p className="text-[10px] text-white/70 font-medium">{m.month}</p>
              <p className="text-sm font-bold text-white mt-0.5">{m.pnl_inr >= 0 ? '+' : ''}{fmtINR(m.pnl_inr)}</p>
              <p className="text-[10px] text-white/60 mt-0.5">{m.trades}T · {(m.win_rate*100).toFixed(0)}%WR</p>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function PnLDistribution({ buckets }: { buckets: { label: string; count: number }[] }) {
  if (buckets.length === 0) return null
  const maxC = Math.max(...buckets.map(b => b.count), 1)

  return (
    <div className="rounded-xl border border-border bg-surface p-5">
      <h3 className="text-sm font-semibold text-text-primary mb-4">P&L Distribution</h3>
      <div className="space-y-2">
        {buckets.map(b => {
          const w = (b.count / maxC) * 100
          const neg = b.label.startsWith('<') || b.label.startsWith('-')
          return (
            <div key={b.label} className="flex items-center gap-3">
              <span className="text-xs text-text-muted text-right w-28 shrink-0">{b.label}</span>
              <div className="flex-1 bg-neutral-800 rounded h-5">
                <div className={`h-5 rounded ${neg ? 'bg-red-500/60' : 'bg-green-500/60'}`} style={{ width: `${w}%` }} />
              </div>
              <span className="text-xs text-text-muted w-6 text-right">{b.count}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ─── Leaderboard tab ──────────────────────────────────────────────────────────

function LeaderboardTab({ entries }: { entries: LeaderboardEntry[] }) {
  if (entries.length === 0) return <Empty label="Loading leaderboard…" />

  return (
    <div className="space-y-4">
      <div className="text-xs text-text-muted bg-surface border border-border rounded-lg px-4 py-3">
        <strong className="text-text-secondary">Score formula:</strong> 30% Win Rate + 25% Profit Factor + 20% Sharpe + 15% MaxDrawdown + 10% Recovery Factor ·
        Minimum to approve: WR ≥ 40%, PF &gt; 1.0, Expectancy &gt; 0
      </div>
      <div className="overflow-x-auto rounded-xl border border-border">
        <table className="w-full text-xs">
          <thead className="border-b border-border bg-surface">
            <tr>
              {['#', 'Strategy', 'Status', 'Score', 'Win Rate', 'Trades', 'Net P&L', 'Profit Factor', 'Sharpe', 'Max DD', 'Recovery', 'MT Approved'].map(h => (
                <th key={h} className="py-3 px-3 text-left text-text-muted font-medium whitespace-nowrap">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {entries.map(e => (
              <tr key={e.name} className={`border-b border-border hover:bg-surface-elevated transition-colors ${!e.mock_trading_approved ? 'opacity-70' : ''}`}>
                <td className="py-2.5 px-3 text-text-muted">{e.rank}</td>
                <td className="py-2.5 px-3 font-mono">{e.name.split('_').slice(0, 3).join('_')}</td>
                <td className="py-2.5 px-3"><StatusPill status={e.status} /></td>
                <td className="py-2.5 px-3 font-bold font-mono text-text-primary">{e.overall_score.toFixed(1)}</td>
                <td className={`py-2.5 px-3 font-mono ${e.win_rate >= 0.4 ? 'text-green-400' : 'text-red-400'}`}>
                  {fmtPct(e.win_rate)}
                </td>
                <td className="py-2.5 px-3 font-mono">{e.total_trades}</td>
                <td className={`py-2.5 px-3 font-mono font-semibold ${pnlCls(e.net_pnl_inr)}`}>{fmtINR(e.net_pnl_inr)}</td>
                <td className={`py-2.5 px-3 font-mono ${e.profit_factor > 1 ? 'text-green-400' : 'text-red-400'}`}>
                  {e.profit_factor >= 999 ? '∞' : fmtNum(e.profit_factor)}
                </td>
                <td className="py-2.5 px-3 font-mono">{fmtNum(e.sharpe)}</td>
                <td className={`py-2.5 px-3 font-mono ${e.max_drawdown_pct < -15 ? 'text-red-400' : ''}`}>
                  {e.max_drawdown_pct.toFixed(1)}%
                </td>
                <td className="py-2.5 px-3 font-mono">{isFinite(e.recovery_factor) ? fmtNum(e.recovery_factor) : '∞'}</td>
                <td className="py-2.5 px-3 font-semibold">
                  {e.mock_trading_approved
                    ? <span className="text-green-400">✓ Approved</span>
                    : <span className="text-text-muted">✗ Pending</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ─── Validation tab ───────────────────────────────────────────────────────────

function ValidationTab({ validations }: { validations: StrategyValidationStatus[] }) {
  if (validations.length === 0) return <Empty label="Loading validation data…" />

  const approved = validations.filter(v => v.mock_trading_approved).length
  const pending  = validations.filter(v => !v.mock_trading_approved && v.status !== 'DEMOTED').length
  const demoted  = validations.filter(v => v.status === 'DEMOTED').length

  return (
    <div className="space-y-6">
      {/* Summary cards */}
      <div className="grid grid-cols-3 gap-4">
        <Card label="Approved" value={String(approved)} sub="Ready for mock trading" cls="text-green-400" />
        <Card label="In Validation" value={String(pending)} sub="Accumulating trade windows" />
        <Card label="Demoted" value={String(demoted)} sub="Requires operator review" cls="text-red-400" />
      </div>

      {/* Criteria */}
      <div className="rounded-xl border border-border bg-surface p-5">
        <h3 className="text-sm font-semibold text-text-primary mb-4">Validation Criteria (all must pass)</h3>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          {[
            { rule: 'Win Rate', req: '≥ 40%', desc: 'Min % of profitable trades' },
            { rule: 'Profit Factor', req: '> 1.0', desc: 'Total profit ÷ total loss > 1' },
            { rule: 'Expectancy', req: '> ₹0', desc: 'Positive expected value per trade' },
            { rule: 'Sharpe Ratio', req: '≥ 0.60', desc: 'Risk-adjusted return score' },
            { rule: 'Max Drawdown', req: '≤ 25%', desc: 'Max peak-to-trough decline' },
            { rule: 'Min Trades', req: '≥ 30 / window', desc: 'Two consecutive windows must pass' },
          ].map(c => (
            <div key={c.rule} className="bg-background rounded-lg p-3 border border-border">
              <p className="text-sm font-semibold text-text-primary">{c.rule}</p>
              <p className="text-primary font-mono text-sm mt-0.5">{c.req}</p>
              <p className="text-xs text-text-muted mt-1">{c.desc}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Per-strategy table */}
      <div className="overflow-x-auto rounded-xl border border-border">
        <table className="w-full text-xs">
          <thead className="border-b border-border bg-surface">
            <tr>
              {['Strategy', 'Status', 'MT Approved', 'Windows', 'Progress', 'Win Rate', 'Profit Factor', 'Sharpe', 'Expectancy', 'Max DD', 'Rejection Reason'].map(h => (
                <th key={h} className="py-2.5 px-3 text-left text-text-muted font-medium whitespace-nowrap">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {validations.map(v => (
              <tr key={v.strategy} className={`border-b border-border hover:bg-surface-elevated transition-colors ${v.mock_trading_approved ? '' : 'opacity-75'}`}>
                <td className="py-2 px-3 font-mono">{v.strategy.split('_').slice(0, 2).join('_')}</td>
                <td className="py-2 px-3"><StatusPill status={v.status} /></td>
                <td className={`py-2 px-3 font-semibold ${v.mock_trading_approved ? 'text-green-400' : 'text-text-muted'}`}>
                  {v.mock_trading_approved ? '✓ Yes' : '✗ No'}
                </td>
                <td className="py-2 px-3 font-mono text-center">{v.windows_completed}</td>
                <td className="py-2 px-3">
                  <div className="flex items-center gap-2">
                    <div className="w-14 bg-neutral-800 rounded-full h-1.5">
                      <div className="h-1.5 rounded-full bg-primary" style={{ width: `${(v.current_window_progress / 30) * 100}%` }} />
                    </div>
                    <span className="font-mono text-text-muted">{v.current_window_progress}/30</span>
                  </div>
                </td>
                <td className={`py-2 px-3 font-mono ${(v.last_window?.WinRate ?? 0) >= 0.4 ? 'text-green-400' : 'text-red-400'}`}>
                  {v.last_window ? fmtPct(v.last_window.WinRate) : '—'}
                </td>
                <td className={`py-2 px-3 font-mono ${(v.last_window?.ProfitFactor ?? 0) > 1 ? 'text-green-400' : 'text-red-400'}`}>
                  {v.last_window ? fmtNum(v.last_window.ProfitFactor) : '—'}
                </td>
                <td className={`py-2 px-3 font-mono ${(v.last_window?.Sharpe ?? 0) >= 0.6 ? 'text-green-400' : 'text-red-400'}`}>
                  {v.last_window ? fmtNum(v.last_window.Sharpe) : '—'}
                </td>
                <td className={`py-2 px-3 font-mono ${(v.last_window?.Expectancy ?? 0) > 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {v.last_window ? fmtINR(v.last_window.Expectancy) : '—'}
                </td>
                <td className={`py-2 px-3 font-mono ${(v.last_window?.MaxDrawdown ?? 0) < -0.25 ? 'text-red-400' : ''}`}>
                  {v.last_window ? `${(v.last_window.MaxDrawdown * 100).toFixed(1)}%` : '—'}
                </td>
                <td className="py-2 px-3 text-red-400 max-w-xs">
                  <span className="truncate block" title={v.rejection_reason}>{v.rejection_reason || '—'}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function MockTradingPage() {
  const [tab, setTab] = useState<Tab>('portfolio')
  const [status, setStatus] = useState<MockTradingStatus | null>(null)
  const [portfolio, setPortfolio] = useState<MockTradingPortfolio | null>(null)
  const [analytics, setAnalytics] = useState<MockTradingAnalytics | null>(null)
  const [leaderboard, setLeaderboard] = useState<LeaderboardEntry[]>([])
  const [validations, setValidations] = useState<StrategyValidationStatus[]>([])
  const [positions, setPositions] = useState<Trade[]>([])
  const [closedTrades, setClosedTrades] = useState<Trade[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function poll() {
      try {
        const [s, p, a, lb, v, pos, ct] = await Promise.all([
          api.mockTradingStatus(),
          api.mockTradingPortfolio(),
          api.mockTradingAnalytics(),
          api.mockTradingLeaderboard(),
          api.strategiesValidation(),
          api.positions(),
          api.trades(),
        ])
        if (cancelled) return
        setStatus(s)
        setPortfolio(p)
        setAnalytics(a)
        setLeaderboard(lb ?? [])
        setValidations(v ?? [])
        setPositions(pos ?? [])
        setClosedTrades(ct ?? [])
        setError(null)
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Engine unreachable')
      }
    }
    poll()
    const id = setInterval(poll, POLL_MS)
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  return (
    <div className="min-h-screen">
      {/* Page header */}
      <div className="border-b border-border px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-base font-semibold text-text-primary">Mock Trading</h1>
          {status?.mock_trading_active && (
            <span className="flex items-center gap-1.5 text-xs font-medium text-green-400">
              <span className="h-2 w-2 rounded-full bg-green-500 animate-pulse" />
              Auto-executing
            </span>
          )}
          {status && !status.mock_trading_active && (
            <span className="text-xs text-text-muted">{status.engine_status.replace(/_/g, ' ')}</span>
          )}
        </div>
        {status && (
          <span className="text-xs text-text-muted font-mono">{status.time_ist} IST</span>
        )}
      </div>

      {error && (
        <div className="mx-6 mt-4 rounded-xl border border-red-500/30 bg-red-950/20 px-4 py-3 text-sm text-red-400">
          Engine unreachable: {error} — start the Go engine on :8090
        </div>
      )}

      <div className="px-6 py-6 space-y-6">
        {/* Tab bar */}
        <div className="flex gap-1 border-b border-border overflow-x-auto">
          {TABS.map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`px-4 py-2.5 text-sm font-medium rounded-t whitespace-nowrap transition-colors ${
                tab === t.id
                  ? 'text-primary border-b-2 border-primary'
                  : 'text-text-muted hover:text-text-secondary'
              }`}
            >
              {t.label}
              {t.id === 'positions' && positions.length > 0 && (
                <span className="ml-1.5 bg-primary/20 text-primary text-[10px] font-bold px-1.5 py-0.5 rounded-full">
                  {positions.length}
                </span>
              )}
            </button>
          ))}
        </div>

        {/* Tab content */}
        {tab === 'portfolio'   && <PortfolioTab portfolio={portfolio} status={status} />}
        {tab === 'positions'   && <OpenPositionsTab trades={positions} />}
        {tab === 'closed'      && <ClosedTradesTab trades={closedTrades} />}
        {tab === 'analytics'   && <AnalyticsTab analytics={analytics} />}
        {tab === 'charts'      && <ChartsTab analytics={analytics} />}
        {tab === 'leaderboard' && <LeaderboardTab entries={leaderboard} />}
        {tab === 'validation'  && <ValidationTab validations={validations} />}
      </div>
    </div>
  )
}
