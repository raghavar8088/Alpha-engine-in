'use client'
import { Eye } from 'lucide-react'
import { motion } from 'framer-motion'
import { usePositions } from '@/hooks/usePositions'
import { formatINR, formatIST, formatLots, formatPrice, pnlClass, getStrategyName } from '@/lib/formatters'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Badge } from '@/components/ui/badge'

export function OpenPositionsTable() {
  const { data: positions, isLoading } = usePositions()

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Open Positions</CardTitle>
          {positions && (
            <Badge variant={positions.length > 0 ? 'profit' : 'muted'}>
              {positions.length} open
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent className="px-0 pb-0">
        {isLoading ? (
          <div className="px-5 pb-5 space-y-3">
            {Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}
          </div>
        ) : !positions || positions.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-text-muted">
            <motion.div
              animate={{ opacity: [0.5, 1, 0.5] }}
              transition={{ repeat: Infinity, duration: 2 }}
            >
              <Eye size={40} className="mb-3" />
            </motion.div>
            <p className="text-sm font-medium">No open positions</p>
            <p className="text-xs mt-1">Engine is watching 29 strategies</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full trading-table">
              <thead>
                <tr>
                  <th className="text-left">Strategy</th>
                  <th className="text-left">Underlying</th>
                  <th className="text-left">Type</th>
                  <th className="text-left">Dir</th>
                  <th className="text-right">Strike</th>
                  <th className="text-right">Lots</th>
                  <th className="text-right">Entry</th>
                  <th className="text-right">Unrealized P&L</th>
                  <th className="text-right">SL</th>
                  <th className="text-right">TP</th>
                  <th className="text-right">Since</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={p.id} className={`${p.netPnl >= 0 ? 'bg-profit-green/3' : 'bg-loss-red/3'}`}>
                    <td>
                      <span className="font-mono text-xs bg-surface-elevated px-1.5 py-0.5 rounded text-primary">
                        {p.strategy}
                      </span>
                      <span className="ml-2 text-text-secondary text-xs hidden xl:inline">
                        {getStrategyName(p.strategy)}
                      </span>
                    </td>
                    <td className="text-text-primary font-medium">{p.underlying}</td>
                    <td>
                      <span className="text-text-secondary text-xs">{p.instrument}</span>
                    </td>
                    <td>
                      <Badge variant={p.direction === 'LONG' ? 'profit' : 'loss'}>
                        {p.direction}
                      </Badge>
                    </td>
                    <td className="text-right font-mono">{p.strike > 0 ? formatPrice(p.strike) : '—'}</td>
                    <td className="text-right font-mono">{formatLots(p.lots, p.underlying)}</td>
                    <td className="text-right font-mono">{formatPrice(p.entryPrice)}</td>
                    <td className={`text-right font-mono font-semibold ${pnlClass(p.netPnl)}`}>
                      {formatINR(p.netPnl)}
                    </td>
                    <td className="text-right font-mono text-loss-red">{formatPrice(p.stopLoss)}</td>
                    <td className="text-right font-mono text-profit-green">{formatPrice(p.takeProfit)}</td>
                    <td className="text-right text-text-muted text-xs">{formatIST(p.entryAt, 'relative')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
