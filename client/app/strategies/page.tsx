import { Header } from '@/components/layout/Header'
import { StrategyLeaderboard } from '@/components/strategies/StrategyLeaderboard'

export default function StrategiesPage() {
  return (
    <div>
      <Header title="Strategies" />
      <div className="p-6 space-y-6 max-w-screen-2xl mx-auto">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-text-primary text-xl font-bold">Strategy Leaderboard</h2>
            <p className="text-text-secondary text-sm mt-0.5">
              29 active strategies across scalping, intraday, and swing timeframes
            </p>
          </div>
          <div className="text-right">
            <p className="text-text-muted text-xs">All 29 strategies registered</p>
            <p className="text-text-muted text-xs">Paper trading mode active</p>
          </div>
        </div>
        <StrategyLeaderboard />
      </div>
    </div>
  )
}
