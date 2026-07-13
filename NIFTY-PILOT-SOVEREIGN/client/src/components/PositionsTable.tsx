"use client";

import type { Trade } from "@/lib/types";
import { fmtINR } from "./EquityCard";

export function PositionsTable({ trades, title }: { trades: Trade[]; title: string }) {
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--panel)] p-4">
      <h2 className="mb-3 text-sm font-semibold">{title}</h2>
      {trades.length === 0 ? (
        <p className="text-sm text-[var(--muted)]">No trades.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="text-[var(--muted)]">
              <tr>
                <th className="py-1 pr-4">Strategy</th>
                <th className="py-1 pr-4">Underlying</th>
                <th className="py-1 pr-4">Dir</th>
                <th className="py-1 pr-4">Instr</th>
                <th className="py-1 pr-4">Entry</th>
                <th className="py-1 pr-4">SL</th>
                <th className="py-1 pr-4">TP</th>
                <th className="py-1 pr-4">Exit</th>
                <th className="py-1 pr-4">Net PnL</th>
              </tr>
            </thead>
            <tbody className="font-mono">
              {trades.map((t) => (
                <tr key={t.ID} className="border-t border-[var(--border)]">
                  <td className="py-1 pr-4">{t.Strategy}</td>
                  <td className="py-1 pr-4">{t.Underlying}</td>
                  <td className={`py-1 pr-4 ${t.Direction === "LONG" ? "text-[var(--green)]" : "text-[var(--red)]"}`}>
                    {t.Direction}
                  </td>
                  <td className="py-1 pr-4">{t.Instrument}</td>
                  <td className="py-1 pr-4">{t.EntryPrice?.toFixed(2)}</td>
                  <td className="py-1 pr-4">{t.StopLoss?.toFixed(2)}</td>
                  <td className="py-1 pr-4">{t.TakeProfit?.toFixed(2)}</td>
                  <td className="py-1 pr-4">{t.ExitPrice ? t.ExitPrice.toFixed(2) : "—"}</td>
                  <td className={`py-1 pr-4 ${t.NetPnL >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}`}>
                    {t.Status === "CLOSED" ? fmtINR(t.NetPnL) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
