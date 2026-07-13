'use client'
import { useState } from 'react'
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis,
  CartesianGrid, Tooltip, Cell, ResponsiveContainer, ReferenceLine,
} from 'recharts'
import type { BacktestData, LeaderboardEntry, WalkforwardEntry } from '@/app/backtest/page'
import { formatINR, formatIST, formatWinRate, formatSharpe, sharpeClass, pnlClass } from '@/lib/formatters'
import { STRATEGIES } from '@/lib/constants'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { ChevronDown, ChevronRight, CheckCircle2, XCircle, MinusCircle } from 'lucide-react'

// ── Helpers ────────────────────────────────────────────────────────────────────

function shortId(raw: string): string {
  const m = /^(S\d+)/.exec(raw)
  return m ? m[1] : raw
}

function strategyName(raw: string): string {
  const id = shortId(raw)
  return STRATEGIES.find((s) => s.id === id)?.name ?? raw.replace(/_/g, ' ')
}

function promoVariant(status: string): 'profit' | 'loss' | 'warning' | 'muted' {
  if (status === 'PROMOTED') return 'profit'
  if (status === 'REJECTED') return 'loss'
  if (status === 'INSUFFICIENT_DATA') return 'warning'
  return 'muted'
}

function PromoIcon({ status }: { status: string }) {
  if (status === 'PROMOTED') return <CheckCircle2 size={14} className="text-profit-green" />
  if (status === 'REJECTED') return <XCircle size={14} className="text-loss-red" />
  return <MinusCircle size={14} className="text-neutral-yellow" />
}

// ── Summary Cards ──────────────────────────────────────────────────────────────

function SummaryCards({ data }: { data: BacktestData }) {
  const s = data.summary!
  const pnlPositive = s.net_pnl_inr > 0
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
      <Card>
        <CardHeader><CardTitle>Net P&L</CardTitle></CardHeader>
        <CardContent>
          <div className={`text-2xl font-bold font-mono ${pnlPositive ? 'text-profit-green' : 'text-loss-red'}`}>
            {formatINR(s.net_pnl_inr, true)}
          </div>
          <p className="text-text-muted text-xs mt-1">{s.backtest_from_ist} → {s.backtest_to_ist}</p>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Annualised Return</CardTitle></CardHeader>
        <CardContent>
          <div className={`text-2xl font-bold font-mono ${s.portfolio_return_annualized > 0 ? 'text-profit-green' : 'text-loss-red'}`}>
            {s.portfolio_return_annualized.toFixed(1)}%
          </div>
          <p className="text-text-muted text-xs mt-1">Sharpe: {s.portfolio_sharpe_annualized.toFixed(2)}</p>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Max Drawdown</CardTitle></CardHeader>
        <CardContent>
          <div className="text-2xl font-bold font-mono text-loss-red">
            {s.portfolio_max_drawdown_pct.toFixed(1)}%
          </div>
          <p className="text-text-muted text-xs mt-1">{s.total_trades} total trades</p>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Promotions</CardTitle></CardHeader>
        <CardContent>
          <div className="flex items-center gap-3">
            <span className="text-2xl font-bold font-mono text-profit-green">{s.promoted_count}</span>
            <span className="text-text-muted text-sm">promoted</span>
          </div>
          <p className="text-text-muted text-xs mt-1">
            {s.rejected_count} rejected · {s.insufficient_count} insufficient data
          </p>
        </CardContent>
      </Card>
    </div>
  )
}

// ── Equity Curve ───────────────────────────────────────────────────────────────

function EquityChart({ data }: { data: BacktestData }) {
  const raw = data.equityCurve
  // Sample every Nth point to avoid rendering 10k+ points
  const step = Math.max(1, Math.floor(raw.length / 300))
  const points = raw
    .filter((_, i) => i % step === 0)
    .map((r) => ({
      date: r.timestamp_ist.substring(0, 10),
      equity: parseFloat(r.equity_inr),
      pnl: parseFloat(r.cumulative_pnl_inr),
    }))

  const CustomTooltip = ({ active, payload }: { active?: boolean; payload?: { value: number; payload: { date: string; pnl: number } }[] }) => {
    if (!active || !payload?.length) return null
    return (
      <div className="bg-surface-elevated border border-border rounded-lg p-3 text-xs shadow-lg">
        <p className="text-text-secondary">{payload[0].payload.date}</p>
        <p className="text-text-primary font-mono font-bold">{formatINR(payload[0].value)}</p>
        <p className={`font-mono ${pnlClass(payload[0].payload.pnl)}`}>P&L: {formatINR(payload[0].payload.pnl)}</p>
      </div>
    )
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Backtest Equity Curve</CardTitle>
          <span className="text-text-muted text-xs">{data.summary?.backtest_from_ist} → {data.summary?.backtest_to_ist}</span>
        </div>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={240}>
          <AreaChart data={points} margin={{ top: 4, right: 4, left: 4, bottom: 4 }}>
            <defs>
              <linearGradient id="btGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#00C087" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#00C087" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#30363D" vertical={false} />
            <XAxis dataKey="date" tick={{ fill: '#8B949E', fontSize: 10 }} axisLine={false} tickLine={false} interval="preserveStartEnd" />
            <YAxis tick={{ fill: '#8B949E', fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={(v: number) => formatINR(v, true)} width={72} />
            <Tooltip content={<CustomTooltip />} />
            <Area type="monotone" dataKey="equity" stroke="#00C087" strokeWidth={2} fill="url(#btGrad)" dot={false} activeDot={{ r: 3 }} />
          </AreaChart>
        </ResponsiveContainer>
        {data.summary?.disclaimer && (
          <p className="text-text-muted text-xs mt-3 italic border-t border-border/50 pt-3">{data.summary.disclaimer}</p>
        )}
      </CardContent>
    </Card>
  )
}

// ── Daily P&L Chart ────────────────────────────────────────────────────────────

function DailyPnLChart({ data }: { data: BacktestData }) {
  const points = data.dailyPnl
    .filter((r) => r.date_ist !== '')
    .map((r) => ({
      date: r.date_ist,
      pnl: parseFloat(r.daily_pnl_inr),
      wins: parseInt(r.winning_trades),
      losses: parseInt(r.losing_trades),
    }))

  const CustomTooltip = ({ active, payload }: { active?: boolean; payload?: { value: number; payload: { date: string; wins: number; losses: number } }[] }) => {
    if (!active || !payload?.length) return null
    const { date, wins, losses } = payload[0].payload
    const pnl = payload[0].value
    return (
      <div className="bg-surface-elevated border border-border rounded-lg p-3 text-xs shadow-lg">
        <p className="text-text-secondary mb-1">{date}</p>
        <p className={`font-mono font-bold ${pnlClass(pnl)}`}>{formatINR(pnl)}</p>
        <p className="text-text-muted mt-1">{wins}W / {losses}L</p>
      </div>
    )
  }

  return (
    <Card>
      <CardHeader><CardTitle>Daily P&L</CardTitle></CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={180}>
          <BarChart data={points} margin={{ top: 4, right: 4, left: 4, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#30363D" vertical={false} />
            <XAxis dataKey="date" tick={{ fill: '#8B949E', fontSize: 10 }} axisLine={false} tickLine={false} interval="preserveStartEnd" />
            <YAxis tick={{ fill: '#8B949E', fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={(v: number) => formatINR(v, true)} width={72} />
            <ReferenceLine y={0} stroke="#30363D" strokeWidth={1} />
            <Tooltip content={<CustomTooltip />} />
            <Bar dataKey="pnl" radius={[2, 2, 0, 0]}>
              {points.map((entry, i) => (
                <Cell key={i} fill={entry.pnl >= 0 ? '#00C087' : '#FF5733'} fillOpacity={0.85} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}

// ── Leaderboard Table ──────────────────────────────────────────────────────────

function LeaderboardTable({ entries, walkforward }: { entries: LeaderboardEntry[]; walkforward: WalkforwardEntry[] }) {
  const [expanded, setExpanded] = useState<string | null>(null)

  const wfMap = Object.fromEntries(walkforward.map((w) => [w.strategy, w]))

  return (
    <Card>
      <CardHeader>
        <CardTitle>Strategy Walk-Forward Leaderboard</CardTitle>
      </CardHeader>
      <div className="overflow-x-auto">
        <table className="w-full trading-table">
          <thead>
            <tr>
              <th className="text-left w-8">#</th>
              <th className="text-left">Strategy</th>
              <th className="text-right">Trades</th>
              <th className="text-right">Win Rate</th>
              <th className="text-right">Sharpe</th>
              <th className="text-right">Max DD</th>
              <th className="text-right">Net P&L</th>
              <th className="text-left">W1</th>
              <th className="text-left">W2</th>
              <th className="text-left">Decision</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e, idx) => {
              const wf = wfMap[e.strategy]
              const isExp = expanded === e.strategy
              const rowBg = e.promotion_status === 'PROMOTED'
                ? 'bg-profit-green/5'
                : e.promotion_status === 'REJECTED'
                ? 'bg-loss-red/5'
                : ''

              return (
                <>
                  <tr
                    key={e.strategy}
                    className={`cursor-pointer hover:bg-surface-elevated/50 transition-colors ${rowBg}`}
                    onClick={() => setExpanded(isExp ? null : e.strategy)}
                  >
                    <td className="text-text-muted font-mono text-xs">{idx + 1}</td>
                    <td>
                      <div className="flex items-center gap-1.5">
                        {isExp ? <ChevronDown size={12} className="text-text-muted shrink-0" /> : <ChevronRight size={12} className="text-text-muted shrink-0" />}
                        <span className="font-mono text-xs bg-primary/15 text-primary px-1.5 py-0.5 rounded mr-1">{shortId(e.strategy)}</span>
                        <span className="text-text-primary text-sm truncate max-w-48">{strategyName(e.strategy)}</span>
                      </div>
                    </td>
                    <td className={`text-right font-mono ${e.total_trades < 30 ? 'text-text-muted' : 'text-text-primary'}`}>{e.total_trades}</td>
                    <td className={`text-right font-mono ${e.win_rate >= 0.5 ? 'text-profit-green' : 'text-loss-red'}`}>
                      {formatWinRate(e.win_rate)}
                    </td>
                    <td className={`text-right font-mono ${sharpeClass(e.sharpe_per_trade ?? 0)}`}>
                      {e.sharpe_per_trade != null ? formatSharpe(e.sharpe_per_trade) : '—'}
                    </td>
                    <td className="text-right font-mono text-loss-red">{e.max_drawdown_pct.toFixed(1)}%</td>
                    <td className={`text-right font-mono font-semibold ${pnlClass(e.net_pnl_inr)}`}>
                      {formatINR(e.net_pnl_inr, true)}
                    </td>
                    <td>
                      {wf?.window1 ? (
                        <span className={`text-xs font-mono ${wf.window1.status === 'PROMOTED' ? 'text-profit-green' : wf.window1.status === 'REJECTED' ? 'text-loss-red' : 'text-text-muted'}`}>
                          {wf.window1.status === 'PROMOTED' ? '✓' : wf.window1.status === 'REJECTED' ? '✗' : '—'}
                        </span>
                      ) : <span className="text-text-muted text-xs">—</span>}
                    </td>
                    <td>
                      {wf?.window2?.status ? (
                        <span className={`text-xs font-mono ${wf.window2.status === 'PROMOTED' ? 'text-profit-green' : wf.window2.status === 'REJECTED' ? 'text-loss-red' : 'text-text-muted'}`}>
                          {wf.window2.status === 'PROMOTED' ? '✓' : wf.window2.status === 'REJECTED' ? '✗' : '—'}
                        </span>
                      ) : <span className="text-text-muted text-xs">—</span>}
                    </td>
                    <td>
                      <div className="flex items-center gap-1">
                        <PromoIcon status={e.promotion_status} />
                        <Badge variant={promoVariant(e.promotion_status)}>
                          {e.promotion_status === 'INSUFFICIENT_DATA' ? 'LOW DATA' : e.promotion_status}
                        </Badge>
                      </div>
                    </td>
                  </tr>

                  {isExp && wf && (
                    <tr key={`${e.strategy}-exp`}>
                      <td colSpan={10} className="bg-surface-elevated px-6 py-4">
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 text-sm">
                          {/* W1 */}
                          <div>
                            <p className="text-text-secondary text-xs uppercase tracking-wide mb-2">Window 1 (Trades {wf.window1.start_trade}–{wf.window1.end_trade})</p>
                            <div className="space-y-1">
                              {[
                                ['Trades', wf.window1.trades],
                                ['Win Rate', formatWinRate(wf.window1.win_rate)],
                                ['Sharpe', formatSharpe(wf.window1.sharpe)],
                                ['Max DD', `${(wf.window1.max_drawdown * 100).toFixed(1)}%`],
                                ['Profit Factor', typeof wf.window1.profit_factor === 'number' ? wf.window1.profit_factor.toFixed(2) : wf.window1.profit_factor],
                                ['Avg Win', formatINR(wf.window1.avg_win_size_inr)],
                                ['Avg Loss', formatINR(wf.window1.avg_loss_size_inr)],
                              ].map(([k, v]) => (
                                <div key={String(k)} className="flex justify-between">
                                  <span className="text-text-muted text-xs">{k}</span>
                                  <span className="font-mono text-xs text-text-primary">{String(v)}</span>
                                </div>
                              ))}
                            </div>
                            <Badge variant={promoVariant(wf.window1.status)} className="mt-2">{wf.window1.status}</Badge>
                          </div>

                          {/* W2 + reasoning */}
                          <div>
                            {wf.window2?.trades > 0 && (
                              <>
                                <p className="text-text-secondary text-xs uppercase tracking-wide mb-2">Window 2 (Trades {wf.window2.start_trade}–{wf.window2.end_trade})</p>
                                <div className="space-y-1 mb-3">
                                  {[
                                    ['Trades', wf.window2.trades],
                                    ['Win Rate', formatWinRate(wf.window2.win_rate)],
                                    ['Sharpe', formatSharpe(wf.window2.sharpe)],
                                    ['Max DD', `${(wf.window2.max_drawdown * 100).toFixed(1)}%`],
                                  ].map(([k, v]) => (
                                    <div key={String(k)} className="flex justify-between">
                                      <span className="text-text-muted text-xs">{k}</span>
                                      <span className="font-mono text-xs text-text-primary">{String(v)}</span>
                                    </div>
                                  ))}
                                </div>
                                <Badge variant={promoVariant(wf.window2.status)} className="mb-3">{wf.window2.status || '—'}</Badge>
                              </>
                            )}
                            {wf.reasoning && (
                              <div className="bg-surface border border-border rounded p-2 mt-2">
                                <p className="text-text-muted text-xs uppercase tracking-wide mb-1">Reasoning</p>
                                <p className="text-text-secondary text-xs">{wf.reasoning}</p>
                              </div>
                            )}
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </>
              )
            })}
          </tbody>
        </table>
      </div>
      <div className="px-5 py-3 border-t border-border text-xs text-text-muted">
        {entries.length} strategies with backtest data · Click any row to expand walk-forward details
      </div>
    </Card>
  )
}

// ── Disclaimer banner ──────────────────────────────────────────────────────────

function DisclaimerBanner({ summary }: { summary: BacktestData['summary'] }) {
  if (!summary?.disclaimer) return null
  return (
    <div className="flex items-start gap-3 bg-neutral-yellow/10 border border-neutral-yellow/30 rounded-lg p-4 text-xs text-neutral-yellow">
      <span className="text-lg shrink-0">⚠</span>
      <p>{summary.disclaimer}</p>
    </div>
  )
}

// ── Main Dashboard ─────────────────────────────────────────────────────────────

export function BacktestDashboard({ data }: { data: BacktestData }) {
  return (
    <div className="space-y-6">
      <DisclaimerBanner summary={data.summary} />
      <SummaryCards data={data} />

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <div className="xl:col-span-2">
          <EquityChart data={data} />
        </div>
        <div className="xl:col-span-1">
          <DailyPnLChart data={data} />
        </div>
      </div>

      <LeaderboardTable entries={data.leaderboard} walkforward={data.walkforward} />
    </div>
  )
}
