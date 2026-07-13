"use client";

import type { Trade } from "@/lib/types";
import { fmtINR } from "./EquityCard";

const PAPER_CAPITAL_INR = 1_00_00_000;

// Buckets closed trades by IST calendar date of exit, computing both
// the Rs amount and % return per day — same feature ported directly
// from the BTC engine's Daily PnL table.
export function DailyPnLTable({ closedTrades }: { closedTrades: Trade[] }) {
  const byDate = new Map<string, number>();
  for (const t of closedTrades) {
    if (!t.ExitAt) continue;
    const d = new Date(t.ExitAt).toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
    byDate.set(d, (byDate.get(d) ?? 0) + t.NetPnL);
  }
  const rows = Array.from(byDate.entries())
    .sort((a, b) => (a[0] < b[0] ? 1 : -1))
    .map(([date, pnlINR]) => ({ date, pnlINR, pnlPct: (pnlINR / PAPER_CAPITAL_INR) * 100 }));

  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--panel)] p-4">
      <h2 className="mb-3 text-sm font-semibold">Daily PnL</h2>
      {rows.length === 0 ? (
        <p className="text-sm text-[var(--muted)]">No closed trades yet.</p>
      ) : (
        <table className="w-full text-left text-xs">
          <thead className="text-[var(--muted)]">
            <tr>
              <th className="py-1 pr-4">Date</th>
              <th className="py-1 pr-4">PnL (₹)</th>
              <th className="py-1 pr-4">Return %</th>
            </tr>
          </thead>
          <tbody className="font-mono">
            {rows.map((r) => (
              <tr key={r.date} className="border-t border-[var(--border)]">
                <td className="py-1 pr-4">{r.date}</td>
                <td className={`py-1 pr-4 ${r.pnlINR >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}`}>
                  {fmtINR(r.pnlINR)}
                </td>
                <td className={`py-1 pr-4 ${r.pnlPct >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}`}>
                  {r.pnlPct.toFixed(3)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
