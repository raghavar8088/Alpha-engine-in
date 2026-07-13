"use client";

import { useEffect, useState } from "react";
import { engine } from "@/lib/engineClient";
import type { EquitySnapshot, HealthSnapshot, MarketSnapshot, StrategyStatus, Trade } from "@/lib/types";
import { Header } from "@/components/Header";
import { EquityCard } from "@/components/EquityCard";
import { PositionsTable } from "@/components/PositionsTable";
import { DailyPnLTable } from "@/components/DailyPnLTable";
import { StrategyLeaderboard } from "@/components/StrategyLeaderboard";
import { GreeksSummary, MarginBar } from "@/components/GreeksAndMargin";

const POLL_MS = 5000;

export default function DashboardPage() {
  const [health, setHealth] = useState<HealthSnapshot>();
  const [equity, setEquity] = useState<EquitySnapshot>();
  const [positions, setPositions] = useState<Trade[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [strategies, setStrategies] = useState<StrategyStatus[]>([]);
  const [market, setMarket] = useState<MarketSnapshot>();
  const [error, setError] = useState<string>();

  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const [h, e, p, t, s, m] = await Promise.all([
          engine.health(),
          engine.equity(),
          engine.positions(),
          engine.trades(),
          engine.strategies(),
          engine.market(),
        ]);
        if (cancelled) return;
        setHealth(h);
        setEquity(e);
        setPositions(p ?? []);
        setTrades(t ?? []);
        setStrategies(s ?? []);
        setMarket(m);
        setError(undefined);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "engine unreachable");
      }
    }
    poll();
    const id = setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  return (
    <main className="min-h-screen">
      <Header
        health={health}
        niftySpot={market?.nifty_spot}
        bankNiftySpot={market?.banknifty_spot}
        indiaVIX={market?.india_vix}
        title="Dashboard"
      />
      <div className="mx-auto max-w-7xl space-y-6 px-6 py-6">
        {error && (
          <div className="rounded-lg border border-[var(--red)] bg-[var(--panel)] p-3 text-sm text-[var(--red)]">
            Engine unreachable: {error}. Showing last known state — start the Go engine on :8090 to connect.
          </div>
        )}
        <EquityCard equity={equity} openTrades={positions} closedTrades={trades} />
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <MarginBar equity={equity} />
          <GreeksSummary />
        </div>
        <PositionsTable trades={positions} title="Open Positions" />
        <PositionsTable trades={trades} title="Closed Trades" />
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <DailyPnLTable closedTrades={trades} />
          <StrategyLeaderboard strategies={strategies} />
        </div>
      </div>
    </main>
  );
}
