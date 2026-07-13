"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { engine } from "@/lib/engineClient";
import type { MockTradingStatus } from "@/lib/types";

const NAV_ITEMS = [
  { href: "/", label: "Dashboard", icon: "⬛" },
  { href: "/mock-trading", label: "Mock Trading", icon: "📊" },
  { href: "/backtest", label: "Backtest", icon: "🔬" },
] as const;

const statusDot: Record<string, string> = {
  MOCK_TRADING_ACTIVE: "bg-green-500",
  PRE_OPEN_READY:      "bg-amber-400",
  MARKET_CLOSED:       "bg-gray-500",
  KILL_SWITCH_ACTIVE:  "bg-red-500",
};

export function Sidebar() {
  const pathname = usePathname();
  const [status, setStatus] = useState<MockTradingStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const s = await engine.mockTradingStatus();
        if (!cancelled) setStatus(s);
      } catch {
        // engine offline — keep whatever state we have
      }
    };
    poll();
    const id = setInterval(poll, 5000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  const dotClass = status ? (statusDot[status.engine_status] ?? "bg-gray-500") : "bg-gray-700";
  const isActive = status?.mock_trading_active ?? false;

  return (
    <aside className="w-52 shrink-0 flex flex-col border-r border-[var(--border)] bg-[var(--panel)] min-h-screen">
      {/* Logo */}
      <div className="px-4 py-5 border-b border-[var(--border)]">
        <div className="text-sm font-bold tracking-tight text-white">NIFTY-PILOT</div>
        <div className="text-xs font-semibold text-blue-400 mt-0.5">SOVEREIGN</div>
        <div className="mt-2 inline-flex items-center gap-1.5 rounded-full bg-amber-900/40 px-2 py-0.5">
          <span className="text-[10px] font-semibold text-amber-400 uppercase tracking-wide">Paper Trading</span>
        </div>
      </div>

      {/* Market Status */}
      <div className="px-4 py-3 border-b border-[var(--border)]">
        <div className="flex items-center gap-2">
          <span className={`h-2 w-2 rounded-full ${dotClass} ${isActive ? "animate-pulse" : ""}`} />
          <span className="text-xs font-medium text-[var(--muted)]">
            {status?.engine_status.replace(/_/g, " ") ?? "Connecting…"}
          </span>
        </div>
        {status && (
          <div className="mt-1 text-[10px] text-[var(--muted)]">
            {status.time_ist} IST
          </div>
        )}
        {status && !status.market_open && status.next_market_open && (
          <div className="mt-1 text-[10px] text-[var(--muted)]">
            Opens {new Date(status.next_market_open).toLocaleString("en-IN", {
              timeZone: "Asia/Kolkata",
              month: "short",
              day: "numeric",
              hour: "2-digit",
              minute: "2-digit",
            })}
          </div>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-2 py-4 space-y-0.5">
        {NAV_ITEMS.map(({ href, label, icon }) => {
          const active = pathname === href || (href !== "/" && pathname.startsWith(href));
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
                active
                  ? "bg-blue-600 text-white"
                  : "text-[var(--muted)] hover:bg-[var(--border)] hover:text-white"
              }`}
            >
              <span className="text-base">{icon}</span>
              {label}
              {label === "Mock Trading" && isActive && (
                <span className="ml-auto h-1.5 w-1.5 rounded-full bg-green-400 animate-pulse" />
              )}
            </Link>
          );
        })}
      </nav>

      {/* Engine info */}
      <div className="px-4 py-3 border-t border-[var(--border)]">
        <div className="text-[10px] text-[var(--muted)] space-y-0.5">
          <div>Engine: Go 1.25</div>
          <div>Strategies: S1–S50 (50)</div>
          <div>Capital: ₹1.00Cr</div>
          <div className="text-[9px] text-[var(--border)]">Auto-detect: 09:15–15:30 IST</div>
        </div>
      </div>
    </aside>
  );
}
