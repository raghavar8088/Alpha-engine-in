'use client'
import type { FilterState } from '@/lib/types'
import { REGIMES } from '@/lib/constants'

interface Props {
  filter: FilterState
  onChange: (f: FilterState) => void
}

const TIMEFRAMES = [
  { value: 'all', label: 'All' },
  { value: 'scalping', label: 'Scalping' },
  { value: 'intraday', label: 'Intraday' },
  { value: 'swing', label: 'Swing' },
] as const

const STATUSES = ['all', 'ACTIVE', 'BLOCKED', 'INSUFFICIENT_DATA', 'DEMOTED']
const SORT_OPTIONS = [
  { value: 'sharpe', label: 'Sharpe' },
  { value: 'winRate', label: 'Win Rate' },
  { value: 'netPnl', label: 'Net P&L' },
  { value: 'totalTrades', label: 'Trades' },
] as const

export function StrategyFilter({ filter, onChange }: Props) {
  const set = (partial: Partial<FilterState>) => onChange({ ...filter, ...partial })

  return (
    <div className="flex flex-wrap gap-3 items-center p-4 bg-surface rounded-lg border border-border">
      {/* Timeframe pills */}
      <div className="flex gap-1">
        {TIMEFRAMES.map((t) => (
          <button
            key={t.value}
            onClick={() => set({ timeframe: t.value as FilterState['timeframe'] })}
            className={`px-3 py-1.5 text-xs rounded-full font-medium transition-colors ${
              filter.timeframe === t.value
                ? 'bg-primary text-white'
                : 'bg-surface-elevated text-text-secondary hover:text-text-primary'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Regime dropdown */}
      <select
        value={filter.regime}
        onChange={(e) => set({ regime: e.target.value })}
        className="text-xs bg-surface-elevated border border-border rounded px-2 py-1.5 text-text-secondary focus:outline-none focus:border-primary"
      >
        <option value="all">All Regimes</option>
        {REGIMES.map((r) => (
          <option key={r.code} value={r.code}>{r.label}</option>
        ))}
      </select>

      {/* Status dropdown */}
      <select
        value={filter.status}
        onChange={(e) => set({ status: e.target.value })}
        className="text-xs bg-surface-elevated border border-border rounded px-2 py-1.5 text-text-secondary focus:outline-none focus:border-primary"
      >
        {STATUSES.map((s) => (
          <option key={s} value={s}>{s === 'all' ? 'All Status' : s.replace('_', ' ')}</option>
        ))}
      </select>

      {/* Sort */}
      <div className="flex items-center gap-2 ml-auto">
        <span className="text-text-muted text-xs">Sort:</span>
        <select
          value={filter.sortField}
          onChange={(e) => set({ sortField: e.target.value as FilterState['sortField'] })}
          className="text-xs bg-surface-elevated border border-border rounded px-2 py-1.5 text-text-secondary focus:outline-none focus:border-primary"
        >
          {SORT_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
        <button
          onClick={() => set({ sortDirection: filter.sortDirection === 'asc' ? 'desc' : 'asc' })}
          className="text-xs px-2 py-1.5 bg-surface-elevated border border-border rounded text-text-secondary hover:text-text-primary"
        >
          {filter.sortDirection === 'asc' ? '↑ ASC' : '↓ DESC'}
        </button>
      </div>
    </div>
  )
}
