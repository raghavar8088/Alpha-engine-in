"use client";

import type { EquitySnapshot, GreeksExposure } from "@/lib/types";

// Greeks exposure summary has no BTC-engine equivalent — essential for
// an options paper trading system. Net values are aggregated client-side
// here; a future iteration can move this to a dedicated engine endpoint
// once per-position Greeks are persisted on the Trade record.
export function GreeksSummary({ greeks }: { greeks?: GreeksExposure }) {
  const g = greeks ?? { netDelta: 0, netGamma: 0, netTheta: 0, netVega: 0 };
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--panel)] p-4">
      <h2 className="mb-3 text-sm font-semibold">Greeks Exposure</h2>
      <div className="grid grid-cols-4 gap-3 text-center font-mono text-sm">
        <GreekStat label="Net Delta" value={g.netDelta} />
        <GreekStat label="Net Gamma" value={g.netGamma} />
        <GreekStat label="Net Theta" value={g.netTheta} />
        <GreekStat label="Net Vega" value={g.netVega} />
      </div>
    </div>
  );
}

function GreekStat({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-[var(--muted)]">{label}</div>
      <div className={value >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}>{value.toFixed(2)}</div>
    </div>
  );
}

export function MarginBar({ equity }: { equity?: EquitySnapshot }) {
  const pct = Math.min(100, Math.max(0, (equity?.margin_utilization_pct ?? 0) * 100));
  const barColor = pct >= 80 ? "bg-[var(--red)]" : pct >= 50 ? "bg-[var(--amber)]" : "bg-[var(--green)]";
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--panel)] p-4">
      <div className="mb-2 flex items-center justify-between text-sm">
        <h2 className="font-semibold">Margin Utilization</h2>
        <span className="font-mono">{pct.toFixed(1)}%</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-[var(--border)]">
        <div className={`h-2 rounded-full ${barColor}`} style={{ width: `${pct}%` }} />
      </div>
      <div className="mt-2 flex justify-between text-xs text-[var(--muted)] font-mono">
        <span>Used: ₹{(equity?.margin_used_inr ?? 0).toLocaleString("en-IN")}</span>
        <span>Available: ₹{(equity?.margin_available_inr ?? 0).toLocaleString("en-IN")}</span>
      </div>
    </div>
  );
}
