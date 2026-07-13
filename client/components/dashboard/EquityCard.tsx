'use client'
import { useEquity } from '@/hooks/useEquity'
import { formatINR, formatPct, pnlClass } from '@/lib/formatters'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { TrendingUp, TrendingDown, Wallet, Target, BarChart2 } from 'lucide-react'

function StatCard({
  title,
  icon: Icon,
  value,
  sub,
  valueClass,
}: {
  title: string
  icon: React.ElementType
  value: string
  sub?: string
  valueClass?: string
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>{title}</CardTitle>
          <Icon size={16} className="text-text-muted" />
        </div>
      </CardHeader>
      <CardContent>
        <div className={`text-2xl font-bold font-mono ${valueClass ?? 'text-text-primary'}`}>
          {value}
        </div>
        {sub && <p className="text-text-muted text-xs mt-1">{sub}</p>}
      </CardContent>
    </Card>
  )
}

function StatCardSkeleton() {
  return (
    <Card>
      <CardHeader>
        <Skeleton className="h-4 w-24" />
      </CardHeader>
      <CardContent>
        <Skeleton className="h-8 w-40 mb-2" />
        <Skeleton className="h-3 w-28" />
      </CardContent>
    </Card>
  )
}

export function EquityCards() {
  const { data, isLoading, isError } = useEquity()

  if (isLoading) {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => <StatCardSkeleton key={i} />)}
      </div>
    )
  }

  if (isError || !data) {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Card key={i} className="border-loss-red/20">
            <CardContent className="pt-5">
              <p className="text-text-muted text-sm">Engine offline</p>
            </CardContent>
          </Card>
        ))}
      </div>
    )
  }

  const { capital, equity, margin_used, margin_available, pnl } = data
  const marginPct = data.margin_utilization_pct
  const pnlPct = capital > 0 ? pnl / capital : 0
  const available = margin_available

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
      <StatCard
        title="Portfolio Equity"
        icon={Wallet}
        value={formatINR(equity ?? capital, true)}
        sub={`Capital: ${formatINR(capital, true)}`}
      />
      <StatCard
        title="Net P&L"
        icon={pnl >= 0 ? TrendingUp : TrendingDown}
        value={formatINR(pnl)}
        sub={`${formatPct(pnlPct, 2, true)} since inception`}
        valueClass={pnlClass(pnl)}
      />
      <StatCard
        title="Margin Used"
        icon={BarChart2}
        value={formatINR(margin_used, true)}
        sub={`${marginPct.toFixed(1)}% utilised`}
        valueClass={marginPct > 80 ? 'text-loss-red' : marginPct > 60 ? 'text-neutral-yellow' : 'text-text-primary'}
      />
      <StatCard
        title="Available Margin"
        icon={Target}
        value={formatINR(available, true)}
        sub="Free margin"
        valueClass="text-profit-green"
      />
    </div>
  )
}
