'use client'
import { X } from 'lucide-react'
import type { Trade } from '@/lib/types'
import { formatINR, formatIST, formatLots, formatPrice, pnlClass, getStrategyName } from '@/lib/formatters'
import { Badge } from '@/components/ui/badge'

interface Props {
  trade: Trade
  onClose: () => void
}

function Row({ label, value, mono = false }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex justify-between items-center py-2 border-b border-border/50">
      <span className="text-text-secondary text-sm">{label}</span>
      <span className={`text-text-primary text-sm font-medium ${mono ? 'font-mono' : ''}`}>{value}</span>
    </div>
  )
}

export function TradeModal({ trade, onClose }: Props) {
  const rrAchieved =
    trade.exitPrice && trade.entryPrice && trade.stopLoss
      ? Math.abs(trade.exitPrice - trade.entryPrice) /
        (Math.abs(trade.entryPrice - trade.stopLoss) || 1)
      : 0

  const totalCosts = trade.entryCostINR + trade.exitCostINR

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/70" onClick={onClose} />

      {/* Modal */}
      <div className="relative bg-surface border border-border rounded-xl w-full max-w-lg shadow-2xl max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <div>
            <div className="flex items-center gap-2">
              <span className="font-mono text-sm bg-primary/15 text-primary px-2 py-0.5 rounded">
                {trade.strategy}
              </span>
              <span className="text-text-primary font-semibold">{getStrategyName(trade.strategy)}</span>
            </div>
            <p className="text-text-muted text-xs mt-0.5 font-mono">{trade.id}</p>
          </div>
          <button
            onClick={onClose}
            className="text-text-muted hover:text-text-primary transition-colors p-1"
            aria-label="Close"
          >
            <X size={20} />
          </button>
        </div>

        <div className="px-6 py-4 space-y-1">
          {/* Status + direction */}
          <div className="flex gap-2 mb-4">
            <Badge variant={trade.status === 'OPEN' ? 'warning' : 'muted'}>
              {trade.status}
            </Badge>
            <Badge variant={trade.direction === 'LONG' ? 'profit' : 'loss'}>
              {trade.direction}
            </Badge>
            <Badge>{trade.instrument}</Badge>
          </div>

          {/* Entry */}
          <div className="bg-surface-elevated rounded-lg p-3 mb-3">
            <p className="text-text-muted text-xs uppercase tracking-wide mb-2">Entry</p>
            <Row label="Price" value={formatPrice(trade.entryPrice)} mono />
            <Row label="Time" value={formatIST(trade.entryAt, 'datetime')} mono />
            <Row label="Lots" value={formatLots(trade.lots, trade.underlying)} mono />
            <Row label="Margin Blocked" value={formatINR(trade.marginBlockedINR)} mono />
            <Row label="Stop Loss" value={<span className="text-loss-red">{formatPrice(trade.stopLoss)}</span>} mono />
            <Row label="Take Profit" value={<span className="text-profit-green">{formatPrice(trade.takeProfit)}</span>} mono />
          </div>

          {/* Exit */}
          {trade.status === 'CLOSED' && (
            <div className="bg-surface-elevated rounded-lg p-3 mb-3">
              <p className="text-text-muted text-xs uppercase tracking-wide mb-2">Exit</p>
              <Row label="Price" value={formatPrice(trade.exitPrice)} mono />
              <Row label="Time" value={formatIST(trade.exitAt, 'datetime')} mono />
              <Row label="Reason" value={<Badge>{trade.exitReason}</Badge>} />
              {rrAchieved > 0 && (
                <Row label="R:R Achieved" value={<span className={rrAchieved >= 2 ? 'text-profit-green' : 'text-neutral-yellow'}>{rrAchieved.toFixed(2)}:1</span>} mono />
              )}
            </div>
          )}

          {/* Cost breakdown */}
          <div className="bg-surface-elevated rounded-lg p-3 mb-3">
            <p className="text-text-muted text-xs uppercase tracking-wide mb-2">Cost Breakdown</p>
            <Row label="Entry costs" value={formatINR(trade.entryCostINR)} mono />
            <Row label="Exit costs" value={formatINR(trade.exitCostINR)} mono />
            <Row
              label="Total transaction costs"
              value={<span className="text-neutral-yellow">{formatINR(totalCosts)}</span>}
              mono
            />
          </div>

          {/* P&L summary */}
          <div className="bg-surface-elevated rounded-lg p-3">
            <p className="text-text-muted text-xs uppercase tracking-wide mb-2">P&L Summary</p>
            <Row label="Gross P&L" value={formatINR(trade.grossPnl)} mono />
            <Row label="Total Costs" value={`-${formatINR(totalCosts)}`} mono />
            <div className="flex justify-between items-center pt-2 mt-1 border-t border-border">
              <span className="text-text-primary font-semibold">Net P&L</span>
              <span className={`text-xl font-bold font-mono ${pnlClass(trade.netPnl)}`}>
                {formatINR(trade.netPnl)}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
