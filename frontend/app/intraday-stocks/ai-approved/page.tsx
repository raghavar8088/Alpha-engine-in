"use client";

// intraday-stocks / AI Approved: the positions the AI final gate approved, its strategy leaderboard and every AI decision.
// The module's own paper trading is untouched (components/AIApprovedView.tsx, backend app/services/ai_gate.py).
import AIApprovedView from "../../../components/AIApprovedView";

export default function IntradayAIApprovedPage() {
  return <AIApprovedView module="intraday" />;
}
