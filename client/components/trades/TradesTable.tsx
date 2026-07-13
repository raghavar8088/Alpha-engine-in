'use client'
import { useState } from 'react'
import { useTrades } from '@/hooks/useTrades'
import { STRATEGIES } from '@/lib/constants'
import { formatINR, formatIST, formatLots, formatPrice, formatHolding, pnlClass, getStrategyName } from '@/lib/formatters'
import type { Trade, TradeFilter } from '@/lib/types'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { TradeModal } from './TradeModal'
import { TrendingUp } from 'lucide-react'

const PAGE_SIZE = 20

function FilterBar({ filter, onChange }: { filter: TradeFilter; onChange: (f: TradeFilter) => void }) {
  const set = (p: Partial<TradeFilter>) => onChange({ ...filter, ...p })
  return (
    <div className="flex flex-wrap gap-3 p-4 bg-surface rounded-lg border border-border">
      <select
        value={filter.strategy}
        onChange={(e) => set({ strategy: e.target.value })}
        className="text-xs bg-surface-elevated border border-border rounded px-2 py-1.5 text-text-secondary focus:outline-none focus:border-primary"
      >
        <option value="all">All Strategies</option>
        {STRATEGIES.map((s) => (
          <option key={s.id} value={s.id}>{s.id} — {s.name}</option>
        ))}
      </select>

      <select
        value={filter.instrument}
        onChange={(e) => set({ instrument: e.target.value })}
        className="text-xs bg-surface-elevated border border-border rounded px-2 py-1.5 text-text-secondary focus:outline-none focus:border-primary"
      >
        <option value="all">All Instruments</option>
        <option value="FUTURE">Futures</option>
        <option value="CE">CE</option>
        <option value="PE">PE</option>
        <option value="STRANGLE">Strangle</option>
        <option value="IRON_CONDOR">Iron Condor</option>
      </select>

      <select
        value={filter.direction}
        onChange={(e) => set({ direction: e.target.value })}
        className="text-xs bg-surface-elevated border border-border rounded px-2 py-1.5 text-text-secondary focus:outline-none focus:border-primary"
      >
        <option value="all">All Directions</option>
        <option value="LONG">Long</option>
        <option value="SHORT">Short</option>
      </select>

      <select
        value={filter.status}
        onChange={(e) => set({ status: e.target.value })}
        className="text-xs bg-surface-elevated border border-border rounded px-2 py-1.5 text-text-secondary focus:outline-none focus:border-primary"
      >
        <option value="all">All Status</option>
        <option value="OPEN">Open</option>
        <option value="CLOSED">Closed</option>
      </select>

      <select
        value={filter.exitReason}
        onChange={(e) => set({ exitReason: e.target.value })}
        className="text-xs bg-surface-elevated border border-border rounded px-2 py-1.5 text-text-secondary focus:outline-none focus:border-primary"
      >
        <option value="all">All Exit Reasons</option>
        <option value="TP">Take Profit</option>
        <option value="SL">Stop Loss</option>
        <option value="TIME">Time</option>
        <option value="EXPIRY">Expiry</option>
      </select>
    </div>
  )
}

function SummaryRow({ trades }: { trades: Trade[] }) {
  if (trades.length === 0) return null
  const closed = trades.filter((t) => t.status === 'CLOSED')
  const wins = closed.filter((t) => t.netPnl > 0)
  const winRate = closed.length > 0 ? wins.length / closed.length : 0
  const totalPnl = closed.reduce((s, t) => s + t.netPnl, 0)
  const best = closed.reduce((b, t) => (t.netPnl > b.netPnl ? t : b), closed[0])
  const worst = closed.reduce((b, t) => (t.netPnl < b.netPnl ? t : b), closed[0])

  return (
    <div className="flex flex-wrap gap-6 p-4 bg-surface rounded-lg border border-border text-sm">
      <div>
        <span className="text-text-muted text-xs">Total Trades</span>
        <p className="font-mono font-bold text-text-primary">{trades.length}</p>
      </div>
      <div>
        <span className="text-text-muted text-xs">Win Rate</span>
        <p className={`font-mono font-bold ${winRate >= 0.5 ? 'text-profit-green' : 'text-loss-red'}`}>
          {(winRate * 100).toFixed(1)}%
        </p>
      </div>
      <div>
        <span className="text-text-muted text-xs">Total Net P&L</span>
        <p className={`font-mono font-bold ${pnlClass(totalPnl)}`}>{formatINR(totalPnl)}</p>
      </div>
      {best && (
        <div>
          <span className="text-text-muted text-xs">Best Trade</span>
          <p className="font-mono font-bold text-profit-green">{formatINR(best.netPnl)}</p>
        </div>
      )}
      {worst && (
        <div>
          <span className="text-text-muted text-xs">Worst Trade</span>
          <p className="font-mono font-bold text-loss-red">{formatINR(worst.netPnl)}</p>
        </div>
      )}
    </div>
  )
}

export function TradesTable() {
  const { data: allTrades, isLoading } = useTrades()
  const [filter, setFilter] = useState<TradeFilter>({
    strategy: 'all',
    instrument: 'all',
    direction: 'all',
    status: 'all',
    exitReason: 'all',
    dateFrom: '',
    dateTo: '',
  })
  const [page, setPage] = useState(1)
  const [selectedTrade, setSelectedTrade] = useState<Trade | null>(null)

  const filtered = (allTrades ?? []).filter((t) => {
    if (filter.strategy !== 'all' && t.strategy !== filter.strategy) return false
    if (filter.instrument !== 'all' && t.instrument !== filter.instrument) return false
    if (filter.direction !== 'all' && t.direction !== filter.direction) return false
    if (filter.status !== 'all' && t.status !== filter.status) return false
    if (filter.exitReason !== 'all' && t.exitReason !== filter.exitReason) return false
    return true
  })

  const totalPages = Math.ceil(filtered.length / PAGE_SIZE)
  const paginated = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  return (
    <div className="space-y-4">
      <FilterBar filter={filter} onChange={(f) => { setFilter(f); setPage(1) }} />
      <SummaryRow trades={filtered} />

      <Card className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full trading-table">
            <thead>
              <tr>
                <th className="text-left">#</th>
                <th className="text-left">Strategy</th>
                <th className="text-left">Underlying</th>
                <th className="text-left">Instrument</th>
                <th className="text-left">Dir</th>
                <th className="text-right">Lots</th>
                <th className="text-right">Entry</th>
                <th className="text-right">Exit</th>
                <th className="text-right">Entry Time</th>
                <th className="text-right">Exit Time</th>
                <th className="text-right">Hold</th>
                <th className="text-right">Net P&L</th>
                <th className="text-left">Reason</th>
              </tr>
            </thead>
            <tbody>
              {isLoading
                ? Array.from({ length: 5 }).map((_, i) => (
                    <tr key={i}>
                      {Array.from({ length: 13 }).map((_, j) => (
                        <td key={j}><Skeleton className="h-4 w-full" /></td>
                      ))}
                    </tr>
                  ))
                : paginated.length === 0 ? (
                  <tr>
                    <td colSpan={13}>
                      <div className="flex flex-col items-center justify-center py-16 text-text-muted">
                        <TrendingUp size={40} className="mb-3 opacity-30" />
                        <p className="text-sm">Engine is live — waiting for first signal</p>
                        <p className="text-xs mt-1">Trades will appear here as the engine executes</p>
                      </div>
                    </td>
                  </tr>
                )
                : paginated.map((t, idx) => {
                    const rowNum = (page - 1) * PAGE_SIZE + idx + 1
                    const rowBg = t.status === 'OPEN'
                      ? 'bg-neutral-yellow/5'
                      : t.netPnl > 0
                      ? 'bg-profit-green/3'
                      : 'bg-loss-red/3'
                    return (
                      <tr
                        key={t.id}
                        className={`cursor-pointer hover:bg-surface-elevated/50 transition-colors ${rowBg}`}
                        onClick={() => setSelectedTrade(t)}
                      >
                        <td className="text-text-muted font-mono text-xs">{rowNum}</td>
                        <td>
                          <span className="font-mono text-xs bg-surface-elevated px-1.5 py-0.5 rounded text-primary">
                            {t.strategy}
                          </span>
                        </td>
                        <td className="text-text-primary font-medium">{t.underlying}</td>
                        <td className="text-text-secondary text-xs">{t.instrument}</td>
                        <td>
                          <Badge variant={t.direction === 'LONG' ? 'profit' : 'loss'}>
                            {t.direction === 'LONG' ? '↑ L' : '↓ S'}
                          </Badge>
                        </td>
                        <td className="text-right font-mono text-xs">{formatLots(t.lots, t.underlying)}</td>
                        <td className="text-right font-mono">{formatPrice(t.entryPrice)}</td>
                        <td className="text-right font-mono">
                          {t.exitPrice > 0 ? formatPrice(t.exitPrice) : '—'}
                        </td>
                        <td className="text-right text-text-secondary text-xs">{formatIST(t.entryAt, 'datetime')}</td>
                        <td className="text-right text-text-secondary text-xs">
                          {t.exitAt ? formatIST(t.exitAt, 'datetime') : '—'}
                        </td>
                        <td className="text-right text-text-muted text-xs">
                          {formatHolding(t.entryAt, t.exitAt)}
                        </td>
                        <td className={`text-right font-mono font-semibold ${pnlClass(t.netPnl)}`}>
                          {formatINR(t.netPnl)}
                        </td>
                        <td>
                          {t.exitReason ? (
                            <span className="text-text-secondary text-xs">{t.exitReason}</span>
                          ) : (
                            <Badge variant="warning">OPEN</Badge>
                          )}
                        </td>
                      </tr>
                    )
                  })}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between px-5 py-3 border-t border-border text-xs">
            <span className="text-text-muted">
              Showing {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, filtered.length)} of {filtered.length}
            </span>
            <div className="flex gap-1">
              <button
                disabled={page === 1}
                onClick={() => setPage((p) => p - 1)}
                className="px-3 py-1 rounded bg-surface-elevated text-text-secondary disabled:opacity-40 hover:text-text-primary"
              >
                ← Prev
              </button>
              <span className="px-3 py-1 text-text-primary">{page} / {totalPages}</span>
              <button
                disabled={page === totalPages}
                onClick={() => setPage((p) => p + 1)}
                className="px-3 py-1 rounded bg-surface-elevated text-text-secondary disabled:opacity-40 hover:text-text-primary"
              >
                Next →
              </button>
            </div>
          </div>
        )}
      </Card>

      {selectedTrade && (
        <TradeModal trade={selectedTrade} onClose={() => setSelectedTrade(null)} />
      )}
    </div>
  )
}
