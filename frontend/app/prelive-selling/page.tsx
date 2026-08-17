"use client";

import { useCallback, useEffect, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import PageHeader from "../../components/PageHeader";
import ErrorBanner from "../../components/ErrorBanner";
import LineChart from "../../components/charts/LineChart";
import {
  refreshing,
  SellingDay,
  SellingDeskStatus,
  SellingEquityPoint,
  SellingScore,
  SellingTrade,
  fetchSellingDeskDaily,
  fetchSellingDeskEquity,
  fetchSellingDeskLeaderboard,
  fetchSellingDeskStatus,
  fetchSellingDeskTrades,
} from "../../lib/api";

const REFRESH_MS = 15000;

const inr = (v: number | null | undefined) =>
  v === null || v === undefined ? "-" : v.toLocaleString("en-IN", { maximumFractionDigits: 0 });
const inr2 = (v: number | null | undefined) =>
  v === null || v === undefined ? "-" : v.toLocaleString("en-IN", { maximumFractionDigits: 2 });
const pct = (v: number | null | undefined, d = 1) =>
  v === null || v === undefined ? "-" : `${v.toFixed(d)}%`;

/** SELL legs are the risk; BUY legs are protection. Colouring them differently is the
 *  fastest way to see whether a structure is defined-risk or naked at a glance. */
function LegPills({ structure }: { structure: string }) {
  return (
    <span className="legs">
      {structure.split(" / ").map((leg, i) => (
        <span key={i} className={leg.startsWith("SELL") ? "leg sell" : "leg buy"}>
          {leg}
        </span>
      ))}
    </span>
  );
}

export default function PreLiveSellingPage() {
  const [status, setStatus] = useState<SellingDeskStatus | null>(null);
  const [scores, setScores] = useState<SellingScore[]>([]);
  const [trades, setTrades] = useState<SellingTrade[]>([]);
  const [equity, setEquity] = useState<SellingEquityPoint[]>([]);
  const [days, setDays] = useState<SellingDay[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [s, l, t, e, d] = await Promise.all([
        fetchSellingDeskStatus(),
        fetchSellingDeskLeaderboard(),
        fetchSellingDeskTrades(100),
        fetchSellingDeskEquity(500),
        fetchSellingDeskDaily(60),
      ]);
      setStatus(s);
      setScores(l);
      setTrades(t);
      setEquity(e);
      setDays(d);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load the selling desk");
    }
  }, []);

  const [isRefreshing, setIsRefreshing] = useState(false);
  const handleRefresh = useCallback(async () => {
    setIsRefreshing(true);
    try {
      await refreshing(() => load());
    } finally {
      setIsRefreshing(false);
    }
  }, [load]);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  const heartbeatAge = status?.heartbeat
    ? (Date.now() - new Date(status.heartbeat).getTime()) / 1000
    : null;
  const live = Boolean(status?.running && heartbeatAge !== null && heartbeatAge < 120);
  const todayPnl = days[0]?.net_pnl ?? 0;
  const totalPnl = status?.realized_all_time ?? 0;

  return (
    <div className="page">
      <PageHeader
        onRefresh={handleRefresh}
        refreshing={isRefreshing}
        crumb="Pre-Live"
        title="Pre-Live Desk · SELLING"
        subtitle="Strategy-selection tournament that SELLS option premium on NIFTY — EVERY registered option-selling strategy trades multi-leg credit structures at real live Dhan premiums, each on its own independent ₹10 lakh margin account at 1 lot/position (paper, capital pool entirely separate from the buying desk). Positions are held across sessions, so structures carried overnight are normal here."
      />

      {/* The two desks have opposite risk profiles and must never be mistaken for one
          another. This banner is the first thing on the page for that reason. */}
      <div className="desk-banner">
        <strong>SHORT PREMIUM.</strong> Gains are capped at the credit collected; losses on an
        uncovered short are not. Every position carries a premium stop, a strike wall and a hard
        capital backstop, and the desk stops opening new structures for the day if its loss
        crosses the circuit breaker.
      </div>

      {error && <ErrorBanner message={error} />}

      {status?.breaker_tripped && (
        <div className="breaker">
          <strong>CIRCUIT BREAKER TRIPPED</strong> — no new structures for the rest of the session.
          {status.breaker_reason ? ` ${status.breaker_reason}` : ""}
        </div>
      )}

      <div className="tiles">
        <div className="tile">
          <div className="tile-label">Engine</div>
          <div className={`tile-value ${live ? "gain" : ""}`}>{live ? "RUNNING" : "IDLE"}</div>
          <div className="tile-sub">
            {status?.heartbeat ? `beat ${Math.round(heartbeatAge ?? 0)}s ago` : "no heartbeat"}
          </div>
        </div>
        <div className="tile">
          <div className="tile-label">Equity</div>
          <div className="tile-value">₹{inr(status?.balance)}</div>
          <div className="tile-sub">from ₹{inr(status?.initial_capital)} paper</div>
        </div>
        <div className="tile">
          <div className="tile-label">Today P&amp;L</div>
          <div className={`tile-value ${todayPnl >= 0 ? "gain" : "loss"}`}>
            {todayPnl >= 0 ? "+" : ""}₹{inr(todayPnl)}
          </div>
          <div className="tile-sub">{days[0]?.session ?? "no session yet"}</div>
        </div>
        <div className="tile">
          {/* Margin, not "capital deployed": selling blocks margin and CREDITS premium,
              so deployed-capital would understate the real capital commitment ~18x on a
              naked structure. */}
          <div className="tile-label">Margin deployed</div>
          <div className="tile-value">₹{inr(status?.margin_deployed)}</div>
          <div className="tile-sub">₹{inr(status?.free_margin)} free</div>
        </div>
        <div className="tile">
          <div className="tile-label">Credit at risk</div>
          <div className="tile-value">₹{inr(status?.credit_at_risk)}</div>
          <div className="tile-sub">{status?.open_structures ?? 0} open structures</div>
        </div>
        <div className="tile">
          <div className="tile-label">Basket</div>
          <div className="tile-value">{status?.universe_size ?? 0}</div>
          <div className="tile-sub">
            {status?.universe_source?.basket_count != null
              ? `${status.universe_source.strategy_count} tested → ${status.universe_source.qualified_count} gated → ${status.universe_source.robust_count} out-of-sample → ${status.universe_source.basket_count} independent`
              : "no sweep loaded"}
          </div>
        </div>
        <div className="tile">
          <div className="tile-label">Track record</div>
          <div className={`tile-value ${totalPnl >= 0 ? "gain" : "loss"}`}>
            {totalPnl >= 0 ? "+" : ""}₹{inr(totalPnl)}
          </div>
          <div className="tile-sub">{status?.sessions_traded ?? 0} sessions</div>
        </div>
      </div>

      {equity.length > 1 && (
        <GlassPanel title="Equity">
          <LineChart
            points={equity.map((p) => ({ ts: p.ts, value: p.equity }))}
            height={200}
            formatValue={(v) => `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`}
          />
        </GlassPanel>
      )}

      <GlassPanel title={`Open structures (${status?.open_structures ?? 0})`}>
        {!status?.open_structures_detail?.length ? (
          <div className="empty">No open structures.</div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Strategy</th>
                  <th style={{ textAlign: "left" }}>Structure</th>
                  <th>Risk</th>
                  <th>Lots</th>
                  <th>Credit</th>
                  <th>Mark</th>
                  <th>Unrealised</th>
                  <th>Margin</th>
                  <th>Expiry</th>
                  <th>Opened</th>
                </tr>
              </thead>
              <tbody>
                {status.open_structures_detail.map((p) => (
                  <tr key={p.key}>
                    <td style={{ textAlign: "left" }}>{p.strategy_id}</td>
                    <td style={{ textAlign: "left" }}>
                      <LegPills structure={p.structure} />
                    </td>
                    <td>
                      <span className={`badge ${p.margin_basis === "naked_span" ? "loss" : ""}`}>
                        {p.margin_basis === "naked_span" ? "NAKED" : "DEFINED"}
                      </span>
                    </td>
                    <td>{p.lots}</td>
                    <td>₹{inr2(p.credit)}</td>
                    <td>₹{inr2(p.mark)}</td>
                    <td className={(p.unrealized ?? 0) >= 0 ? "gain" : "loss"}>
                      {(p.unrealized ?? 0) >= 0 ? "+" : ""}₹{inr(p.unrealized)}
                    </td>
                    <td>₹{inr(p.margin)}</td>
                    <td>{p.expiry ?? "-"}</td>
                    <td style={{ fontSize: 10.5 }}>
                      {p.entry_ts ? new Date(p.entry_ts).toLocaleString() : "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>

      <GlassPanel title="Strategy leaderboard">
        {!scores.length ? (
          <div className="empty">No closed trades yet.</div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Strategy</th>
                  <th>Trades</th>
                  <th className="muted-col">Win %</th>
                  <th>PF</th>
                  <th>Net P&amp;L</th>
                  <th>Allocated</th>
                </tr>
              </thead>
              <tbody>
                {scores.map((s) => (
                  <tr key={s.strategy_id}>
                    <td style={{ textAlign: "left" }}>{s.strategy_id}</td>
                    <td>{s.trades}</td>
                    {/* Shown for reference only. This desk is not judged on win rate —
                        premium selling routinely wins 80%+ while losing money. */}
                    <td className="muted-col">
                      {s.win_rate !== null ? `${(s.win_rate * 100).toFixed(1)}%` : "-"}
                    </td>
                    <td className={(s.profit_factor ?? 0) >= 1.3 ? "gain" : "loss"}>
                      {s.profit_factor ?? "-"}
                    </td>
                    <td className={s.net_pnl >= 0 ? "gain" : "loss"}>
                      {s.net_pnl >= 0 ? "+" : ""}₹{inr(s.net_pnl)}
                    </td>
                    <td>₹{inr(s.allocated_capital)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>

      <GlassPanel title="Daily P&L history">
        {!days.length ? (
          <div className="empty">No sessions recorded yet.</div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Session</th>
                  <th>Realised</th>
                  <th>Unrealised</th>
                  <th>Net</th>
                  <th>ROI</th>
                  <th>Closed</th>
                  <th>Carried</th>
                  <th>Margin</th>
                  <th>Breaker</th>
                </tr>
              </thead>
              <tbody>
                {days.map((d) => (
                  <tr key={d.session}>
                    <td>{d.session}</td>
                    <td className={d.realized_pnl >= 0 ? "gain" : "loss"}>₹{inr(d.realized_pnl)}</td>
                    <td className={d.unrealized_pnl >= 0 ? "gain" : "loss"}>
                      ₹{inr(d.unrealized_pnl)}
                    </td>
                    <td className={d.net_pnl >= 0 ? "gain" : "loss"}>
                      {d.net_pnl >= 0 ? "+" : ""}₹{inr(d.net_pnl)}
                    </td>
                    <td className={d.roi_pct >= 0 ? "gain" : "loss"}>{pct(d.roi_pct, 3)}</td>
                    <td>{d.trades}</td>
                    {/* Carrying positions overnight is expected on a swing desk, not a leak. */}
                    <td>{d.open_carried}</td>
                    <td>₹{inr(d.margin_deployed)}</td>
                    <td>
                      {d.breaker_tripped ? <span className="badge loss">TRIPPED</span> : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>

      <GlassPanel title="Recent paper trades">
        {!trades.length ? (
          <div className="empty">No closed trades yet.</div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Strategy</th>
                  <th style={{ textAlign: "left" }}>Structure</th>
                  <th>Risk</th>
                  <th>Credit</th>
                  <th>Buy-back</th>
                  <th>Lots</th>
                  <th>Held</th>
                  <th>Spot in → out</th>
                  <th>Reason</th>
                  <th>P&amp;L</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((t, i) => (
                  <tr key={`${t.key}-${t.exit_ts}-${i}`}>
                    <td style={{ textAlign: "left" }}>{t.strategy_id}</td>
                    <td style={{ textAlign: "left" }}>
                      <LegPills structure={t.structure} />
                    </td>
                    <td>
                      <span className={`badge ${t.margin_basis === "naked_span" ? "loss" : ""}`}>
                        {t.margin_basis === "naked_span" ? "NAKED" : "DEFINED"}
                      </span>
                    </td>
                    <td>₹{inr2(t.credit)}</td>
                    <td>₹{inr2(t.exit_cost)}</td>
                    <td>{t.lots}</td>
                    <td>{t.held_days}d</td>
                    <td style={{ fontSize: 10.5 }}>
                      {inr(t.entry_spot)} → {t.exit_spot ? inr(t.exit_spot) : "-"}
                    </td>
                    <td>
                      <span className={`badge ${["stop", "capital_stop"].includes(t.exit_reason) ? "loss" : ""}`}>
                        {t.exit_reason}
                      </span>
                    </td>
                    <td className={t.pnl >= 0 ? "gain" : "loss"}>
                      {t.pnl >= 0 ? "+" : ""}₹{inr(t.pnl)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>

      <style jsx>{`
        .page { display: flex; flex-direction: column; gap: 16px; }
        .desk-banner {
          padding: 10px 16px; border-radius: 8px; font-size: 12px; line-height: 1.5;
          background: var(--loss-dim); border: 1px solid rgba(217, 45, 63, 0.3);
          color: var(--text-secondary);
        }
        .breaker {
          padding: 10px 16px; border-radius: 8px; font-size: 12px; line-height: 1.5;
          background: var(--loss-dim); border: 1px solid rgba(217, 45, 63, 0.55);
        }
        .tiles {
          display: grid; gap: 12px;
          grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
        }
        .tile {
          padding: 12px 14px; border-radius: 10px;
          background: var(--panel); border: 1px solid var(--panel-border);
        }
        .tile-label {
          font-size: 10px; font-weight: 700; letter-spacing: 0.04em;
          text-transform: uppercase; color: var(--text-muted);
        }
        .tile-value {
          margin-top: 5px; font-family: var(--font-data); font-variant-numeric: tabular-nums;
          font-size: 16px; font-weight: 600;
        }
        .tile-sub { margin-top: 3px; font-size: 10.5px; color: var(--text-faint); line-height: 1.4; }
        .empty { padding: 18px 20px; font-size: 12px; color: var(--text-faint); }
        .table-scroll { overflow-x: auto; max-height: 460px; overflow-y: auto; }
        .data-table {
          width: 100%; border-collapse: collapse; font-size: 12px;
          font-variant-numeric: tabular-nums;
        }
        .data-table th {
          text-align: center; padding: 8px 10px; font-size: 10px; font-weight: 700;
          letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted);
          border-bottom: 1px solid var(--panel-border); position: sticky; top: 0;
          background: var(--panel);
        }
        .data-table td {
          padding: 7px 10px; text-align: center; border-bottom: 1px solid var(--canvas-soft);
        }
        .legs { display: inline-flex; flex-wrap: wrap; gap: 4px; }
        .leg {
          padding: 2px 6px; border-radius: 4px; font-size: 10px;
          font-family: var(--font-data); white-space: nowrap;
        }
        .leg.sell { background: var(--loss-dim); border: 1px solid rgba(217, 45, 63, 0.3); }
        .leg.buy { background: rgba(34, 170, 96, 0.12); border: 1px solid rgba(34, 170, 96, 0.3); }
        .muted-col { color: var(--text-faint); font-weight: 400; }
        .badge {
          display: inline-block; padding: 3px 8px; border-radius: 6px; font-size: 10px;
          font-weight: 700; letter-spacing: 0.05em; background: var(--canvas-soft);
          border: 1px solid var(--panel-border);
        }
        .badge.loss { background: var(--loss-dim); border-color: rgba(217, 45, 63, 0.3); }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
      `}</style>
    </div>
  );
}
