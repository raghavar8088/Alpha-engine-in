'use client'
import { useMarket } from '@/hooks/useMarket'
import { RegimeChip } from './RegimeChip'
import { MarginBar } from '@/components/risk/MarginBar'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'

export function RegimePanelCard() {
  const { data: market, isLoading } = useMarket()

  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle>Market Regime &amp; Risk</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Regime chip */}
        {isLoading ? (
          <Skeleton className="h-10 w-40" />
        ) : market ? (
          <RegimeChip regime={market.regime} />
        ) : (
          <p className="text-text-muted text-sm">Engine offline</p>
        )}

        <hr className="border-border" />

        {/* Market metrics */}
        {market && (
          <div className="space-y-3">
            <div className="flex justify-between text-sm">
              <span className="text-text-secondary">PCR</span>
              <span className="font-mono text-text-primary">{market.pcr.toFixed(2)}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-text-secondary">Max Pain</span>
              <span className="font-mono text-text-primary">{market.max_pain.toLocaleString('en-IN')}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-text-secondary">India VIX</span>
              <span
                className={`font-mono font-medium ${
                  market.vix > 20 ? 'text-loss-red' : market.vix > 15 ? 'text-neutral-yellow' : 'text-profit-green'
                }`}
              >
                {market.vix.toFixed(1)}
              </span>
            </div>
          </div>
        )}

        <hr className="border-border" />

        {/* Margin bar */}
        <div>
          <MarginBar />
        </div>

        <hr className="border-border" />

        {/* Kill switch */}
        <div>
          <p className="text-text-muted text-xs uppercase tracking-wide mb-2">Kill Switch</p>
          <a
            href="/settings#kill-switch"
            className="block w-full text-center py-2 rounded-md border border-loss-red/50 text-loss-red text-sm font-medium hover:bg-loss-red/10 transition-colors"
          >
            Manage Kill Switch →
          </a>
        </div>
      </CardContent>
    </Card>
  )
}
