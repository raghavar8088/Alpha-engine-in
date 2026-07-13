import { Suspense } from "react";
import { MockTradingPage } from "@/components/mock-trading/MockTradingPage";

export const metadata = { title: "Mock Trading — NIFTY Pilot Sovereign" };

export default function Page() {
  return (
    <Suspense fallback={<div className="p-8 text-[var(--muted)]">Loading mock trading engine…</div>}>
      <MockTradingPage />
    </Suspense>
  );
}
