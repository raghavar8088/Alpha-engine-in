'use client'
import { useStrategies } from '@/hooks/useStrategies'
import { useTrades } from '@/hooks/useTrades'
import { formatWinRate, formatSharpe, sharpeClass } from '@/lib/formatters'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'

export function QuickStats() {
  const { data: strategies, isLoading: sLoading } = useStrategies()
  const { data: trades, isLoading: tLoading } = useTrades()

  const isLoading = sLoading || tLoading

  const totalTrades = trades?.length ?? 0
  const wins = trades?.filter((t) => t.netPnl > 0).length ?? 0
  const winRate = totalTrades > 0 ? wins / totalTrades : 0

  const avgSharpe =
    strategies && strategies.length > 0
      ? strategies.reduce((s, x) => s + x.sharpe, 0) / strategies.length
      : 0

  const maxDD =
    strategies && strategies.length > 0
      ? Math.min(...strategies.map((s) => s.maxDrawdown))
      : 0

  const activeCount = strategies?.filter((s) => s.status === 'ACTIVE').length ?? 0

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
      {isLoading ? (
        Array.from({ length: 4 }).map((_, i) => (
          <Card key={i}>
            <CardHeader><Skeleton className="h-3 w-20" /></CardHeader>
            <CardContent><Skeleton className="h-7 w-16" /></CardContent>
          </Card>
        ))
      ) : (
        <>
          <Card>
            <CardHeader><CardTitle>Win Rate</CardTitle></CardHeader>
            <CardContent>
              <div className={`text-2xl font-bold font-mono ${winRate >= 0.5 ? 'text-profit-green' : 'text-loss-red'}`}>
                {formatWinRate(winRate)}
              </div>
              <p className="text-text-muted text-xs mt-1">{totalTrades} total trades</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Avg Sharpe</CardTitle></CardHeader>
            <CardContent>
              <div className={`text-2xl font-bold font-mono ${sharpeClass(avgSharpe)}`}>
                {formatSharpe(avgSharpe)}
              </div>
              <p className="text-text-muted text-xs mt-1">across all strategies</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Max Drawdown</CardTitle></CardHeader>
            <CardContent>
              <div className="text-2xl font-bold font-mono text-loss-red">
                {(maxDD * 100).toFixed(1)}%
              </div>
              <p className="text-text-muted text-xs mt-1">worst strategy</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Active Strategies</CardTitle></CardHeader>
            <CardContent>
              <div className="text-2xl font-bold font-mono text-profit-green">
                {activeCount}
                <span className="text-text-muted text-sm font-normal"> / 29</span>
              </div>
              <p className="text-text-muted text-xs mt-1">currently enabled</p>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}
