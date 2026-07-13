"use client";

import type { EquitySnapshot, Trade } from "@/lib/types";

export function EquityCard({
  equity,
  openTrades,
  closedTrades,
}: {
  equity?: EquitySnapshot;
  openTrades: Trade[];
  closedTrades: Trade[];
}) {
  const wins = closedTrades.filter((t) => t.NetPnL > 0).length;
  const winRate = closedTrades.length ? (wins / closedTrades.length) * 100 : 0;
  const unrealized = openTrades.reduce((sum, t) => sum + (t.GrossPnL || 0), 0);

  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
      <Card label="Equity" value={fmtINR(equity?.equity_inr)} accent />
      <Card label="Realized PnL" value={fmtINR(equity?.realized_pnl_inr)} signed={equity?.realized_pnl_inr} />
      <Card label="Unrealized PnL" value={fmtINR(unrealized)} signed={unrealized} />
      <Card label="Open Positions" value={String(openTrades.length)} />
      <Card label="Win Rate" value={`${winRate.toFixed(1)}%`} />
    </div>
  );
}

function Card({
  label,
  value,
  accent,
  signed,
}: {
  label: string;
  value: string;
  accent?: boolean;
  signed?: number;
}) {
  const color =
    signed === undefined ? "text-[var(--text)]" : signed >= 0 ? "text-[var(--green)]" : "text-[var(--red)]";
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--panel)] p-4">
      <div className="text-[10px] uppercase tracking-wide text-[var(--muted)]">{label}</div>
      <div className={`mt-1 text-xl font-mono ${accent ? "text-[var(--text)]" : color}`}>{value}</div>
    </div>
  );
}

export function fmtINR(v?: number): string {
  if (v === undefined || Number.isNaN(v)) return "—";
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(v);
}
