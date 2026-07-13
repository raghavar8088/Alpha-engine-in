import { FlaskConical, Terminal } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { STRATEGIES } from '@/lib/constants'

export function BacktestEmpty() {
  return (
    <div className="space-y-6">
      <Card className="border-dashed border-border/50">
        <CardContent className="flex flex-col items-center justify-center py-20 text-center">
          <FlaskConical size={48} className="text-text-muted mb-4" />
          <h3 className="text-text-primary font-semibold text-lg mb-2">No Backtest Run Yet</h3>
          <p className="text-text-secondary text-sm max-w-md mb-6">
            Run the backtest engine to see strategy walk-forward results, equity curves,
            and promotion decisions for all 29 strategies.
          </p>
          <div className="bg-surface-elevated border border-border rounded-lg p-4 text-left w-full max-w-lg">
            <div className="flex items-center gap-2 mb-3">
              <Terminal size={16} className="text-primary" />
              <span className="text-text-secondary text-xs uppercase tracking-wide">CLI Instructions</span>
            </div>
            <div className="space-y-2 font-mono text-xs">
              <div>
                <span className="text-text-muted"># Navigate to engine directory</span>
                <pre className="text-profit-green mt-0.5">cd NIFTY-PILOT-SOVEREIGN/engine</pre>
              </div>
              <div>
                <span className="text-text-muted"># Run the backtest binary</span>
                <pre className="text-profit-green mt-0.5">go run cmd/backtest/main.go</pre>
              </div>
              <div>
                <span className="text-text-muted"># Results saved to:</span>
                <pre className="text-neutral-yellow mt-0.5">backtest_results/{'<run-id>'}/leaderboard.json</pre>
                <pre className="text-neutral-yellow">backtest_results/{'<run-id>'}/summary.json</pre>
                <pre className="text-neutral-yellow">backtest_results/{'<run-id>'}/equity_curve.csv</pre>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Strategy template table */}
      <Card>
        <div className="px-5 pt-5 pb-3 border-b border-border">
          <h3 className="text-text-secondary text-xs uppercase tracking-wide font-medium">Walk-Forward Framework — 29 Strategies</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full trading-table">
            <thead>
              <tr>
                <th className="text-left">Strategy</th>
                <th className="text-left">Name</th>
                <th className="text-left">Timeframe</th>
                <th className="text-right">Target WR</th>
                <th className="text-right">Min R:R</th>
                <th className="text-left">Status</th>
              </tr>
            </thead>
            <tbody>
              {STRATEGIES.map((s) => (
                <tr key={s.id}>
                  <td><span className="font-mono text-xs bg-primary/15 text-primary px-1.5 py-0.5 rounded">{s.id}</span></td>
                  <td className="text-text-primary text-sm">{s.name}</td>
                  <td><span className="text-text-secondary text-xs capitalize">{s.timeframe}</span></td>
                  <td className="text-right font-mono text-text-secondary text-xs">{(s.targetWinRate * 100).toFixed(0)}%</td>
                  <td className="text-right font-mono text-text-secondary text-xs">{s.minRR === 0 ? 'N/A' : `${s.minRR}:1`}</td>
                  <td><span className="text-text-muted text-xs italic">Run backtest</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  )
}
