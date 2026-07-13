'use client'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Cell,
  ResponsiveContainer,
} from 'recharts'
import { useTrades } from '@/hooks/useTrades'
import { formatINR, formatIST } from '@/lib/formatters'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'

function buildDailyPnL(trades: { exitAt: string | null; netPnl: number; status: string }[]) {
  const map: Record<string, { pnl: number; count: number; wins: number }> = {}

  for (const t of trades) {
    if (t.status !== 'CLOSED' || !t.exitAt) continue
    const day = formatIST(t.exitAt, 'date')
    if (!map[day]) map[day] = { pnl: 0, count: 0, wins: 0 }
    map[day].pnl += t.netPnl
    map[day].count++
    if (t.netPnl > 0) map[day].wins++
  }

  return Object.entries(map)
    .sort(([a], [b]) => a.localeCompare(b))
    .slice(-30)
    .map(([date, { pnl, count, wins }]) => ({
      date,
      pnl: Math.round(pnl),
      count,
      winRate: count > 0 ? wins / count : 0,
    }))
}

const CustomTooltip = ({
  active,
  payload,
}: {
  active?: boolean
  payload?: { value: number; payload: { date: string; count: number; winRate: number } }[]
}) => {
  if (!active || !payload?.length) return null
  const { date, count, winRate } = payload[0].payload
  const pnl = payload[0].value
  return (
    <div className="bg-surface-elevated border border-border rounded-lg p-3 shadow-lg text-xs">
      <p className="text-text-secondary mb-1">{date}</p>
      <p className={`font-mono font-bold ${pnl >= 0 ? 'text-profit-green' : 'text-loss-red'}`}>
        {formatINR(pnl)}
      </p>
      <p className="text-text-muted mt-1">{count} trades · {(winRate * 100).toFixed(0)}% WR</p>
    </div>
  )
}

export function DailyPnLChart() {
  const { data: trades, isLoading } = useTrades()
  const chartData = trades ? buildDailyPnL(trades) : []

  return (
    <Card>
      <CardHeader>
        <CardTitle>Daily P&amp;L — Last 30 Days</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-44 w-full" />
        ) : chartData.length === 0 ? (
          <div className="h-44 flex flex-col items-center justify-center text-text-muted">
            <p className="text-sm">No closed trades yet — daily P&L will appear here</p>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={176}>
            <BarChart data={chartData} margin={{ top: 4, right: 4, left: 4, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#30363D" vertical={false} />
              <XAxis
                dataKey="date"
                tick={{ fill: '#8B949E', fontSize: 10 }}
                axisLine={false}
                tickLine={false}
                interval="preserveStartEnd"
              />
              <YAxis
                tick={{ fill: '#8B949E', fontSize: 10 }}
                axisLine={false}
                tickLine={false}
                tickFormatter={(v: number) => formatINR(v, true)}
                width={64}
              />
              <Tooltip content={<CustomTooltip />} />
              <Bar dataKey="pnl" radius={[2, 2, 0, 0]}>
                {chartData.map((entry, index) => (
                  <Cell
                    key={index}
                    fill={entry.pnl >= 0 ? '#00C087' : '#FF5733'}
                    fillOpacity={0.85}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  )
}
