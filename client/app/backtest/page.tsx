'use client'
import { useEffect, useState } from 'react'
import { Header } from '@/components/layout/Header'
import { BacktestDashboard } from '@/components/backtest/BacktestDashboard'
import { BacktestEmpty } from '@/components/backtest/BacktestEmpty'
import { Skeleton } from '@/components/ui/skeleton'
import { Card, CardContent } from '@/components/ui/card'

export interface BacktestSummary {
  backtest_from_ist: string
  backtest_to_ist: string
  capital_inr: number
  data_source: string
  ending_equity_inr: number
  net_pnl_inr: number
  portfolio_max_drawdown_pct: number
  portfolio_return_annualized: number
  portfolio_sharpe_annualized: number
  promoted_count: number
  rejected_count: number
  insufficient_count: number
  total_trades: number
  kill_events: number
  strategies_promoted: string[]
  strategies_rejected: string[]
  strategies_insufficient: string[]
  disclaimer: string
}

export interface LeaderboardEntry {
  strategy: string
  total_trades: number
  win_rate: number
  sharpe_per_trade: number | null
  max_drawdown_pct: number
  profit_factor: number | string
  net_pnl_inr: number
  promotion_status: 'PROMOTED' | 'REJECTED' | 'INSUFFICIENT_DATA'
}

export interface WalkforwardWindow {
  start_trade: number
  end_trade: number
  trades: number
  sharpe: number
  win_rate: number
  max_drawdown: number
  profit_factor: number
  avg_win_size_inr: number
  avg_loss_size_inr: number
  status: string
}

export interface WalkforwardEntry {
  strategy: string
  total_trades: number
  window1: WalkforwardWindow
  window2: WalkforwardWindow
  promotion_status: string
  reasoning: string
}

export interface EquityCurvePoint {
  timestamp_ist: string
  equity_inr: string
  cumulative_pnl_inr: string
  period_return_pct: string
}

export interface DailyPnLPoint {
  date_ist: string
  daily_pnl_inr: string
  daily_return_pct: string
  max_intraday_dd_pct: string
  winning_trades: string
  losing_trades: string
}

export interface BacktestData {
  available: boolean
  run: string | null
  summary: BacktestSummary | null
  leaderboard: LeaderboardEntry[]
  walkforward: WalkforwardEntry[]
  equityCurve: EquityCurvePoint[]
  dailyPnl: DailyPnLPoint[]
  regimeAnalysis: Record<string, string>[]
}

export default function BacktestPage() {
  const [data, setData] = useState<BacktestData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch('/api/backtest')
      .then((r) => r.json())
      .then((d: BacktestData) => setData(d))
      .catch(() => setData({ available: false, run: null, summary: null, leaderboard: [], walkforward: [], equityCurve: [], dailyPnl: [], regimeAnalysis: [] }))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div>
      <Header title="Backtest" />
      <div className="p-6 space-y-6 max-w-screen-2xl mx-auto">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-text-primary text-xl font-bold">Backtest Results</h2>
            {data?.run && (
              <p className="text-text-secondary text-sm mt-0.5 font-mono">Run: {data.run}</p>
            )}
          </div>
          {data?.summary?.data_source && (
            <span className="text-xs bg-neutral-yellow/15 text-neutral-yellow border border-neutral-yellow/30 px-3 py-1.5 rounded-full font-medium">
              {data.summary.data_source} DATA
            </span>
          )}
        </div>

        {loading ? (
          <div className="space-y-4">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              {Array.from({ length: 4 }).map((_, i) => (
                <Card key={i}><CardContent className="pt-5"><Skeleton className="h-16 w-full" /></CardContent></Card>
              ))}
            </div>
            <Skeleton className="h-64 w-full" />
            <Skeleton className="h-96 w-full" />
          </div>
        ) : !data?.available ? (
          <BacktestEmpty />
        ) : (
          <BacktestDashboard data={data} />
        )}
      </div>
    </div>
  )
}
