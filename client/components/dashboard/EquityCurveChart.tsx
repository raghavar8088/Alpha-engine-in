'use client'
import { useState } from 'react'
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'
import { useTrades } from '@/hooks/useTrades'
import { formatINR, formatIST } from '@/lib/formatters'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'

type Range = '1W' | '1M' | '3M' | 'ALL'

function buildEquityCurve(
  trades: { exitAt: string | null; netPnl: number; status: string }[],
  capital: number,
  range: Range
) {
  const now = Date.now()
  const ms: Record<Range, number> = {
    '1W': 7 * 86400_000,
    '1M': 30 * 86400_000,
    '3M': 90 * 86400_000,
    ALL: Infinity,
  }
  const cutoff = now - ms[range]

  const closed = trades
    .filter((t) => t.status === 'CLOSED' && t.exitAt)
    .map((t) => ({ at: new Date(t.exitAt!).getTime(), pnl: t.netPnl }))
    .sort((a, b) => a.at - b.at)

  let equity = capital
  const points: { date: string; equity: number }[] = [
    { date: formatIST(new Date(closed[0]?.at ?? now).toISOString(), 'date'), equity },
  ]

  for (const p of closed) {
    if (p.at < cutoff) continue
    equity += p.pnl
    points.push({
      date: formatIST(new Date(p.at).toISOString(), 'date'),
      equity: Math.round(equity),
    })
  }

  return points
}

const CustomTooltip = ({
  active,
  payload,
}: {
  active?: boolean
  payload?: { value: number; payload: { date: string } }[]
}) => {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-surface-elevated border border-border rounded-lg p-3 shadow-lg">
      <p className="text-text-secondary text-xs">{payload[0].payload.date}</p>
      <p className="text-text-primary font-mono font-bold">{formatINR(payload[0].value)}</p>
    </div>
  )
}

export function EquityCurveChart({ capital = 10_000_000 }: { capital?: number }) {
  const { data: trades, isLoading } = useTrades()
  const [range, setRange] = useState<Range>('1M')

  const ranges: Range[] = ['1W', '1M', '3M', 'ALL']

  const chartData = trades ? buildEquityCurve(trades, capital, range) : []

  return (
    <Card className="h-full">
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Equity Curve</CardTitle>
          <div className="flex gap-1">
            {ranges.map((r) => (
              <button
                key={r}
                onClick={() => setRange(r)}
                className={`px-2.5 py-1 text-xs rounded font-medium transition-colors ${
                  range === r
                    ? 'bg-primary text-white'
                    : 'text-text-secondary hover:text-text-primary hover:bg-surface-elevated'
                }`}
              >
                {r}
              </button>
            ))}
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-52 w-full" />
        ) : chartData.length <= 1 ? (
          <div className="h-52 flex flex-col items-center justify-center text-text-muted">
            <div className="text-4xl mb-2">📈</div>
            <p className="text-sm">No trades yet — equity curve will appear here</p>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={208}>
            <AreaChart data={chartData} margin={{ top: 4, right: 4, left: 4, bottom: 4 }}>
              <defs>
                <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#00C087" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#00C087" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#30363D" vertical={false} />
              <XAxis
                dataKey="date"
                tick={{ fill: '#8B949E', fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                interval="preserveStartEnd"
              />
              <YAxis
                tick={{ fill: '#8B949E', fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                tickFormatter={(v: number) => formatINR(v, true)}
                width={72}
              />
              <Tooltip content={<CustomTooltip />} />
              <Area
                type="monotone"
                dataKey="equity"
                stroke="#00C087"
                strokeWidth={2}
                fill="url(#equityGrad)"
                dot={false}
                activeDot={{ r: 4, fill: '#00C087' }}
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  )
}
