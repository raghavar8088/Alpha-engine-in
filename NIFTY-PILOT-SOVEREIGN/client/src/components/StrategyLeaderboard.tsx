"use client";

import Link from "next/link";
import type { StrategyStatus } from "@/lib/types";

const statusColor = {
  PROBATION: "bg-gray-800 text-gray-400",
  PENDING:   "bg-amber-900/50 text-amber-400",
  ACTIVE:    "bg-green-900/50 text-green-400",
  DEMOTED:   "bg-red-900/50 text-red-400",
};

function compositeScore(s: StrategyStatus): number {
  const sharpeNorm = Math.min(1, Math.max(0, s.last_window_sharpe / 3));
  const wrNorm     = Math.min(1, Math.max(0, s.last_window_winrate / 0.70));
  return Math.round((sharpeNorm * 0.70 + wrNorm * 0.30) * 100) / 10;
}

export function StrategyLeaderboard({ strategies }: { strategies: StrategyStatus[] }) {
  const scored = strategies
    .map(s => ({ ...s, score: compositeScore(s) }))
    .sort((a, b) => b.score - a.score);

  const approved = scored.filter(s => s.status === "ACTIVE" || s.status === "PENDING");

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--panel)] p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold">Strategy Leaderboard</h2>
        <Link href="/mock-trading?tab=leaderboard" className="text-xs text-blue-400 hover:text-blue-300">
          Full Leaderboard →
        </Link>
      </div>

      {/* Quick stats */}
      <div className="flex gap-4 mb-4 text-xs">
        <div>
          <span className="text-[var(--muted)]">Total Strategies </span>
          <span className="font-bold text-white">{scored.length}</span>
        </div>
        <div>
          <span className="text-[var(--muted)]">Approved </span>
          <span className="font-bold text-green-400">{approved.length}</span>
        </div>
        <div>
          <span className="text-[var(--muted)]">Min WinRate </span>
          <span className="font-bold text-white">40%</span>
        </div>
      </div>

      {scored.length === 0 ? (
        <p className="text-sm text-[var(--muted)]">No strategy data yet — strategies will appear after first validation window (30 trades).</p>
      ) : (
        <table className="w-full text-left text-xs">
          <thead className="text-[var(--muted)]">
            <tr>
              <th className="py-1.5 pr-3">#</th>
              <th className="py-1.5 pr-3">Strategy</th>
              <th className="py-1.5 pr-3">Status</th>
              <th className="py-1.5 pr-3">Sharpe</th>
              <th className="py-1.5 pr-3">Win Rate</th>
              <th className="py-1.5 pr-3">Score</th>
              <th className="py-1.5">MT</th>
            </tr>
          </thead>
          <tbody className="font-mono">
            {scored.slice(0, 15).map((s, i) => (
              <tr key={s.strategy} className="border-t border-[var(--border)]">
                <td className="py-1.5 pr-3 text-[var(--muted)]">{i + 1}</td>
                <td className="py-1.5 pr-3 text-[10px]">{s.strategy.split("_").slice(0, 2).join("_")}</td>
                <td className="py-1.5 pr-3">
                  <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${statusColor[s.status]}`}>
                    {s.status}
                  </span>
                </td>
                <td className={`py-1.5 pr-3 ${s.last_window_sharpe >= 0.6 ? "text-[var(--green)]" : "text-[var(--muted)]"}`}>
                  {s.last_window_sharpe.toFixed(2)}
                </td>
                <td className={`py-1.5 pr-3 ${s.last_window_winrate >= 0.4 ? "text-[var(--green)]" : "text-[var(--red)]"}`}>
                  {(s.last_window_winrate * 100).toFixed(1)}%
                </td>
                <td className="py-1.5 pr-3 font-bold">{s.score.toFixed(1)}</td>
                <td className="py-1.5">
                  {(s.status === "ACTIVE" || s.status === "PENDING")
                    ? <span className="text-[var(--green)] text-[10px]">✓</span>
                    : <span className="text-[var(--muted)] text-[10px]">–</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {scored.length > 15 && (
        <div className="mt-3 text-xs text-[var(--muted)] text-center">
          +{scored.length - 15} more strategies ·{" "}
          <Link href="/mock-trading" className="text-blue-400 hover:text-blue-300">View all in Mock Trading</Link>
        </div>
      )}
    </div>
  );
}
