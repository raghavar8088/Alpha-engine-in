import { Header } from '@/components/layout/Header'
import { TradesTable } from '@/components/trades/TradesTable'

export default function TradesPage() {
  return (
    <div>
      <Header title="Trade History" />
      <div className="p-6 space-y-6 max-w-screen-2xl mx-auto">
        <div>
          <h2 className="text-text-primary text-xl font-bold">Trade History</h2>
          <p className="text-text-secondary text-sm mt-0.5">
            All trades executed by the engine — click any row for full breakdown
          </p>
        </div>
        <TradesTable />
      </div>
    </div>
  )
}
