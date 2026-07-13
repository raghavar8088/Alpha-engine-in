import { Header } from '@/components/layout/Header'
import { EquityCards } from '@/components/dashboard/EquityCard'
import { EquityCurveChart } from '@/components/dashboard/EquityCurveChart'
import { DailyPnLChart } from '@/components/dashboard/DailyPnLChart'
import { OpenPositionsTable } from '@/components/dashboard/OpenPositionsTable'
import { QuickStats } from '@/components/dashboard/QuickStats'
import { RegimePanelCard } from '@/components/dashboard/RegimePanelCard'

export default function DashboardPage() {
  return (
    <div>
      <Header title="Dashboard" />
      <div className="p-6 space-y-6 max-w-screen-2xl mx-auto">
        {/* Row 1: Equity stat cards */}
        <EquityCards />

        {/* Row 2: Quick stats */}
        <QuickStats />

        {/* Row 3: Equity curve + Regime panel */}
        <div className="grid grid-cols-1 xl:grid-cols-5 gap-6">
          <div className="xl:col-span-3">
            <EquityCurveChart />
          </div>
          <div className="xl:col-span-2">
            <RegimePanelCard />
          </div>
        </div>

        {/* Row 4: Daily P&L chart */}
        <DailyPnLChart />

        {/* Row 5: Open positions */}
        <OpenPositionsTable />
      </div>
    </div>
  )
}
