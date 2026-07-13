'use client'
import { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { useStrategies } from '@/hooks/useStrategies'
import { STRATEGIES, TIMEFRAME_COLORS, STATUS_COLORS } from '@/lib/constants'
import { formatINR, formatWinRate, formatSharpe, sharpeClass, pnlClass } from '@/lib/formatters'
import type { FilterState, StrategyStats } from '@/lib/types'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { StrategyFilter } from './StrategyFilter'

function StatusBadge({ status }: { status: StrategyStats['status'] }) {
  const color = STATUS_COLORS[status] ?? '#8B949E'
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium"
      style={{ backgroundColor: `${color}20`, color }}
    >
      {status.replace('_', ' ')}
    </span>
  )
}

function ExpandedRow({ id }: { id: string }) {
  const def = STRATEGIES.find((s) => s.id === id)
  if (!def) return null
  return (
    <tr>
      <td colSpan={11} className="bg-surface-elevated px-6 py-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
          <div>
            <p className="text-text-secondary text-xs uppercase tracking-wide mb-1">Strategy Logic</p>
            <p className="text-text-primary">{def.description}</p>
          </div>
          <div className="space-y-2">
            <div>
              <p className="text-text-secondary text-xs uppercase tracking-wide mb-1">Allowed Regimes</p>
              <div className="flex flex-wrap gap-1">
                {def.allowedRegimes.map((r) => (
                  <span key={r} className="bg-surface border border-border px-2 py-0.5 rounded text-xs text-text-primary">
                    {r}
                  </span>
                ))}
              </div>
            </div>
            <div>
              <p className="text-text-secondary text-xs uppercase tracking-wide mb-1">Instruments</p>
              <div className="flex gap-1">
                {def.instruments.map((i) => (
                  <span key={i} className="bg-surface border border-border px-2 py-0.5 rounded text-xs text-text-primary">
                    {i}
                  </span>
                ))}
              </div>
            </div>
            <div className="flex gap-6 text-xs text-text-secondary">
              <span>Min SL: <span className="text-text-primary font-mono">{def.minSLPct}%</span></span>
              <span>Min R:R: <span className="text-text-primary font-mono">{def.minRR === 0 ? 'N/A' : `${def.minRR}:1`}</span></span>
              <span>Target WR: <span className="text-text-primary font-mono">{(def.targetWinRate * 100).toFixed(0)}%</span></span>
            </div>
          </div>
        </div>
      </td>
    </tr>
  )
}

export function StrategyLeaderboard() {
  const { data: stats, isLoading } = useStrategies()
  const [filter, setFilter] = useState<FilterState>({
    timeframe: 'all',
    regime: 'all',
    status: 'all',
    sortField: 'sharpe',
    sortDirection: 'desc',
  })
  const [expanded, setExpanded] = useState<string | null>(null)

  // Merge API stats with static definitions — show all 29 always
  const rows = STRATEGIES.map((def) => {
    const live = stats?.find((s) => s.id === def.id)
    return {
      id: def.id,
      name: def.name,
      timeframe: def.timeframe,
      allowedRegimes: def.allowedRegimes,
      totalTrades: live?.totalTrades ?? 0,
      winRate: live?.winRate ?? 0,
      netPnl: live?.netPnl ?? 0,
      sharpe: live?.sharpe ?? 0,
      maxDrawdown: live?.maxDrawdown ?? 0,
      status: live?.status ?? ('INSUFFICIENT_DATA' as StrategyStats['status']),
      promotionWindow: live?.promotionWindow ?? 0,
    }
  })

  // Filter
  const filtered = rows.filter((r) => {
    if (filter.timeframe !== 'all' && r.timeframe !== filter.timeframe) return false
    if (filter.regime !== 'all' && !r.allowedRegimes.includes(filter.regime)) return false
    if (filter.status !== 'all' && r.status !== filter.status) return false
    return true
  })

  // Sort
  filtered.sort((a, b) => {
    const dir = filter.sortDirection === 'asc' ? 1 : -1
    const field = filter.sortField
    return (a[field] - b[field]) * dir
  })

  return (
    <div className="space-y-4">
      <StrategyFilter filter={filter} onChange={setFilter} />
      <Card className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full trading-table">
            <thead>
              <tr>
                <th className="text-left w-8">#</th>
                <th className="text-left">ID</th>
                <th className="text-left">Name</th>
                <th className="text-left">Frame</th>
                <th className="text-right">Win Rate</th>
                <th className="text-right">Trades</th>
                <th className="text-right">Net P&L</th>
                <th className="text-right">Sharpe</th>
                <th className="text-right">Max DD</th>
                <th className="text-left">Status</th>
                <th className="text-left">Walk-Fwd</th>
              </tr>
            </thead>
            <tbody>
              {isLoading
                ? Array.from({ length: 8 }).map((_, i) => (
                    <tr key={i}>
                      {Array.from({ length: 11 }).map((_, j) => (
                        <td key={j}><Skeleton className="h-4 w-full" /></td>
                      ))}
                    </tr>
                  ))
                : filtered.map((row, idx) => (
                    <>
                      <tr
                        key={row.id}
                        className="cursor-pointer hover:bg-surface-elevated/50 transition-colors"
                        onClick={() => setExpanded(expanded === row.id ? null : row.id)}
                      >
                        <td className="text-text-muted font-mono text-xs">{idx + 1}</td>
                        <td>
                          <span
                            className="font-mono text-xs font-bold px-1.5 py-0.5 rounded"
                            style={{
                              backgroundColor: `${TIMEFRAME_COLORS[row.timeframe]}20`,
                              color: TIMEFRAME_COLORS[row.timeframe],
                            }}
                          >
                            {row.id}
                          </span>
                        </td>
                        <td className="text-text-primary text-sm max-w-48 truncate">
                          <div className="flex items-center gap-1.5">
                            {expanded === row.id ? (
                              <ChevronDown size={12} className="text-text-muted shrink-0" />
                            ) : (
                              <ChevronRight size={12} className="text-text-muted shrink-0" />
                            )}
                            {row.name}
                          </div>
                        </td>
                        <td>
                          <span
                            className="text-xs px-1.5 py-0.5 rounded capitalize"
                            style={{
                              backgroundColor: `${TIMEFRAME_COLORS[row.timeframe]}15`,
                              color: TIMEFRAME_COLORS[row.timeframe],
                            }}
                          >
                            {row.timeframe}
                          </span>
                        </td>
                        <td className={`text-right font-mono font-medium ${row.winRate >= 0.5 ? 'text-profit-green' : 'text-loss-red'}`}>
                          {formatWinRate(row.winRate)}
                        </td>
                        <td className={`text-right font-mono ${row.totalTrades < 30 ? 'text-text-muted' : 'text-text-primary'}`}>
                          {row.totalTrades}
                        </td>
                        <td className={`text-right font-mono ${pnlClass(row.netPnl)}`}>
                          {formatINR(row.netPnl)}
                        </td>
                        <td className={`text-right font-mono ${sharpeClass(row.sharpe)}`}>
                          {formatSharpe(row.sharpe)}
                        </td>
                        <td className="text-right font-mono text-loss-red">
                          {(row.maxDrawdown * 100).toFixed(1)}%
                        </td>
                        <td><StatusBadge status={row.status} /></td>
                        <td className="text-text-muted text-xs font-mono">
                          {row.promotionWindow === 0 ? '—' : `W1 ✓${row.promotionWindow >= 2 ? ' W2 ✓' : ' W2 ✗'}`}
                        </td>
                      </tr>
                      {expanded === row.id && <ExpandedRow key={`${row.id}-exp`} id={row.id} />}
                    </>
                  ))}
            </tbody>
          </table>
        </div>
        <div className="px-5 py-3 border-t border-border text-xs text-text-muted">
          Showing {filtered.length} of 29 strategies
        </div>
      </Card>
    </div>
  )
}
