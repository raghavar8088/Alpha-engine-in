'use client'
import { useEquity } from '@/hooks/useEquity'
import { formatINR } from '@/lib/formatters'
import { Skeleton } from '@/components/ui/skeleton'

export function MarginBar() {
  const { data, isLoading } = useEquity()

  if (isLoading) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="h-2.5 w-full rounded-full" />
        <Skeleton className="h-3 w-36" />
      </div>
    )
  }

  if (!data) return null

  const { capital, margin_used, margin_utilization_pct } = data
  const pct = Math.min(margin_utilization_pct ?? (capital > 0 ? (margin_used / capital) * 100 : 0), 100)
  const barColor = pct > 80 ? '#FF5733' : pct > 60 ? '#F5A623' : '#00C087'

  return (
    <div className="space-y-2">
      <div className="flex justify-between text-xs">
        <span className="text-text-secondary font-medium">Margin Used</span>
        <span className="font-mono text-text-primary">{pct.toFixed(1)}%</span>
      </div>
      <div className="h-2 bg-surface-elevated rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, backgroundColor: barColor }}
        />
      </div>
      <div className="flex justify-between text-xs text-text-muted">
        <span>{formatINR(margin_used, true)} used</span>
        <span>{formatINR(data.margin_available, true)} free</span>
      </div>
    </div>
  )
}
