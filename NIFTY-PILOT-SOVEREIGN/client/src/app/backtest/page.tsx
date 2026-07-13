import { Suspense } from "react";
import { BacktestDashboard } from "@/components/backtest/BacktestDashboard";

export const metadata = { title: "Backtest — NIFTY Pilot Sovereign" };

export default function BacktestPage() {
  return (
    <Suspense fallback={<div className="p-8 text-gray-400">Loading backtest engine…</div>}>
      <BacktestDashboard />
    </Suspense>
  );
}
