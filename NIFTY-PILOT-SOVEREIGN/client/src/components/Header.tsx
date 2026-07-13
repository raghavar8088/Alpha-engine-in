"use client";

import type { HealthSnapshot } from "@/lib/types";

const statusColor: Record<HealthSnapshot["status"], string> = {
  OPEN: "bg-green-500",
  CLOSED: "bg-gray-500",
  PRE_OPEN: "bg-amber-400",
  KILL_SWITCH_ACTIVE: "bg-red-500",
};

const statusLabel: Record<HealthSnapshot["status"], string> = {
  OPEN: "Market Open",
  CLOSED: "Market Closed",
  PRE_OPEN: "Pre-Open",
  KILL_SWITCH_ACTIVE: "Kill Switch Active",
};

export function Header({
  health,
  niftySpot,
  bankNiftySpot,
  indiaVIX,
  title = "Dashboard",
}: {
  health?: HealthSnapshot;
  niftySpot?: number;
  bankNiftySpot?: number;
  indiaVIX?: number;
  title?: string;
}) {
  return (
    <header className="flex flex-wrap items-center justify-between gap-4 border-b border-[var(--border)] px-6 py-4 bg-[var(--panel)]">
      <h1 className="text-base font-semibold tracking-tight text-white">{title}</h1>

      <div className="flex flex-wrap items-center gap-6 text-sm">
        {niftySpot !== undefined && <Stat label="NIFTY" value={niftySpot.toFixed(2)} />}
        {bankNiftySpot !== undefined && <Stat label="BANKNIFTY" value={bankNiftySpot.toFixed(2)} />}
        {indiaVIX !== undefined && (
          <Stat
            label="VIX"
            value={indiaVIX.toFixed(2)}
            valueClass={indiaVIX >= 20 ? "text-[var(--red)]" : indiaVIX >= 15 ? "text-[var(--amber)]" : "text-[var(--green)]"}
          />
        )}
        <div className="flex items-center gap-2">
          <span className={`h-2 w-2 rounded-full ${health ? statusColor[health.status] : "bg-gray-700"} ${health?.status === "OPEN" ? "animate-pulse" : ""}`} />
          <span className="text-xs font-medium text-[var(--muted)]">
            {health ? statusLabel[health.status] : "Connecting…"}
          </span>
        </div>
        {health?.time_ist && (
          <span className="text-xs text-[var(--muted)] font-mono">
            {new Date(health.time_ist).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false })} IST
          </span>
        )}
      </div>
    </header>
  );
}

function Stat({ label, value, valueClass = "font-mono" }: { label: string; value: string; valueClass?: string }) {
  return (
    <div className="text-right">
      <div className="text-[10px] uppercase tracking-wide text-[var(--muted)]">{label}</div>
      <div className={valueClass}>{value}</div>
    </div>
  );
}
