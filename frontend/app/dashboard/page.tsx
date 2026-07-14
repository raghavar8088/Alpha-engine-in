"use client";

import { useEffect, useRef, useState } from "react";
import { fetchLatestMarketData, fetchMarketDataHistory, MarketDataSnapshot } from "@/lib/api";
import { useMarketDataSocket } from "@/lib/useMarketDataSocket";
import StatCard from "@/components/StatCard";
import GlassPanel from "@/components/GlassPanel";
import StatusPill from "@/components/StatusPill";
import FlashOnChange from "@/components/FlashOnChange";
import PageHeader from "@/components/PageHeader";
import Skeleton from "@/components/Skeleton";
import ErrorBanner from "@/components/ErrorBanner";
import EmptyState from "@/components/EmptyState";

function isMarketOpenIST(): boolean {
  const now = new Date();
  const istMinutes = (now.getUTCHours() * 60 + now.getUTCMinutes() + 330) % 1440;
  const day = now.getUTCDay();
  const isWeekday = day >= 1 && day <= 5;
  return isWeekday && istMinutes >= 9 * 60 + 15 && istMinutes <= 15 * 60 + 30;
}

export default function DashboardPage() {
  const [initialRows, setInitialRows] = useState<MarketDataSnapshot[]>([]);
  const [history, setHistory] = useState<Record<string, number[]>>({});
  const seededSymbols = useRef(new Set<string>());
  const [marketOpen, setMarketOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = (showLoading = true) => {
    if (showLoading) {
      setError(null);
      setLoading(true);
    }
    fetchLatestMarketData()
      .then((rows) => {
        setError(null);
        setInitialRows(rows);
        rows.forEach((row) => {
          if (seededSymbols.current.has(row.symbol)) return;
          seededSymbols.current.add(row.symbol);
          fetchMarketDataHistory(row.symbol, 30)
            .then((points) => {
              setHistory((prev) => ({ ...prev, [row.symbol]: points.map((p) => p.price) }));
            })
            .catch(() => {});
        });
      })
      .catch((e) => {
        // Only surface an error on the initial load; a failed background poll
        // should leave the last good snapshot on screen rather than blanking it.
        if (showLoading) setError(e instanceof Error ? e.message : "Failed to load market data");
      })
      .finally(() => {
        if (showLoading) setLoading(false);
      });
  };

  useEffect(() => {
    setMarketOpen(isMarketOpenIST());
    load();
    // Poll is the live-update path in same-origin proxy mode (Vercel production
    // has no reachable WebSocket); on local dev the socket also updates in between.
    const timer = setInterval(() => load(false), 7000);
    return () => clearInterval(timer);
  }, []);

  const rows = useMarketDataSocket(initialRows);

  useEffect(() => {
    setHistory((prev) => {
      const next = { ...prev };
      let changed = false;
      for (const row of rows) {
        const arr = next[row.symbol];
        if (!arr || arr[arr.length - 1] === row.price) continue;
        next[row.symbol] = [...arr, row.price].slice(-30);
        changed = true;
      }
      return changed ? next : prev;
    });
  }, [rows]);

  return (
    <div>
      <PageHeader
        crumb="Market Data"
        title="Live Market Data"
        subtitle="NSE public indices feed · refreshes every ~7s"
        actions={
          <StatusPill
            label={marketOpen ? "Market Open" : "Market Closed"}
            tone={marketOpen ? "gain" : "muted"}
            pulse={marketOpen}
          />
        }
      />

      {error && (
        <div style={{ marginBottom: 20 }}>
          <ErrorBanner message={error} onRetry={load} />
        </div>
      )}

      {loading && !error && (
        <div className="stat-grid">
          {Array.from({ length: 4 }).map((_, i) => (
            <div className="skeleton-card" key={i}>
              <Skeleton height={11} width="50%" style={{ marginBottom: 12 }} />
              <Skeleton height={25} width="70%" style={{ marginBottom: 10 }} />
              <Skeleton height={12} width="40%" style={{ marginBottom: 12 }} />
              <Skeleton height={34} width="100%" />
            </div>
          ))}
        </div>
      )}

      {!loading && !error && rows.length === 0 && (
        <GlassPanel>
          <EmptyState title="No market data yet" note="The feed hasn't reported any symbols yet — check the market-data-service is running." />
        </GlassPanel>
      )}

      {rows.length > 0 && (
        <>
          <div className="stat-grid">
            {rows.map((row, i) => (
              <StatCard
                key={row.symbol}
                label={row.symbol}
                price={row.price.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                change={row.change}
                pctChange={row.pct_change}
                sparklineValues={history[row.symbol] ?? [row.price, row.price]}
                index={i}
              />
            ))}
          </div>

          <GlassPanel title="All Symbols" note={`${rows.length} symbol${rows.length === 1 ? "" : "s"}`}>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Price</th>
                    <th>Change</th>
                    <th>% Change</th>
                    <th>Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => {
                    const up = (row.change ?? 0) >= 0;
                    return (
                      <tr key={row.symbol}>
                        <td className="sym-cell">{row.symbol}</td>
                        <td className="num">
                          <FlashOnChange value={row.price.toFixed(2)}>{row.price.toFixed(2)}</FlashOnChange>
                        </td>
                        <td className={`num ${up ? "up" : "down"}`}>{row.change !== null ? row.change.toFixed(2) : "-"}</td>
                        <td className={`num ${up ? "up" : "down"}`}>
                          {row.pct_change !== null ? `${row.pct_change.toFixed(2)}%` : "-"}
                        </td>
                        <td className="updated-cell">{new Date(row.updated_at).toLocaleTimeString()}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </GlassPanel>
        </>
      )}

      <style jsx>{`
        .skeleton-card {
          background: var(--panel);
          border: 1px solid var(--panel-border);
          border-radius: 16px;
          padding: 18px 18px 14px;
          box-shadow: var(--shadow-sm);
        }
        .stat-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
          gap: 14px;
          margin-bottom: 34px;
        }
        .table-scroll {
          overflow-x: auto;
        }
        table {
          width: 100%;
          border-collapse: collapse;
          min-width: 640px;
        }
        th {
          text-align: left;
          font-size: 11px;
          letter-spacing: 0.06em;
          text-transform: uppercase;
          color: var(--text-faint);
          font-weight: 600;
          padding: 12px 20px;
          border-bottom: 1px solid var(--panel-border);
        }
        td {
          padding: 13px 20px;
          font-size: 13.5px;
          border-bottom: 1px solid var(--panel-border);
        }
        tbody tr:hover {
          background: var(--canvas-soft);
        }
        tbody tr:last-child td {
          border-bottom: none;
        }
        .sym-cell {
          font-weight: 600;
        }
        .num {
          font-family: var(--font-data);
          font-variant-numeric: tabular-nums;
        }
        .num.up {
          color: var(--gain);
        }
        .num.down {
          color: var(--loss);
        }
        .updated-cell {
          color: var(--text-faint);
          font-family: var(--font-data);
          font-variant-numeric: tabular-nums;
          font-size: 12px;
        }
      `}</style>
    </div>
  );
}
