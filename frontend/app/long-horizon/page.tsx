"use client";

import { useCallback, useEffect, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import PageHeader from "../../components/PageHeader";
import ErrorBanner from "../../components/ErrorBanner";
import LineChart from "../../components/charts/LineChart";
import {
  refreshing,
  LongHorizonEquityPoint,
  LongHorizonScore,
  LongHorizonStatus,
  LongHorizonSweep,
  LongHorizonTrade,
  fetchLongHorizonEquity,
  fetchLongHorizonLeaderboard,
  fetchLongHorizonStatus,
  fetchLongHorizonSweep,
  fetchLongHorizonTrades,
  runLongHorizonSweep,
} from "../../lib/api";

const REFRESH_MS = 30000;

const inr = (v: number | null | undefined) =>
  v === null || v === undefined ? "-" : v.toLocaleString("en-IN", { maximumFractionDigits: 0 });
const inr2 = (v: number | null | undefined) =>
  v === null || v === undefined ? "-" : v.toLocaleString("en-IN", { maximumFractionDigits: 2 });

export default function LongHorizonPage() {
  const [status, setStatus] = useState<LongHorizonStatus | null>(null);
  const [scores, setScores] = useState<LongHorizonScore[]>([]);
  const [trades, setTrades] = useState<LongHorizonTrade[]>([]);
  const [equity, setEquity] = useState<LongHorizonEquityPoint[]>([]);
  const [sweep, setSweep] = useState<LongHorizonSweep | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [runningSweep, setRunningSweep] = useState(false);

  const load = useCallback(async () => {
    try {
      const [s, l, t, e, sw] = await Promise.all([
        fetchLongHorizonStatus(),
        fetchLongHorizonLeaderboard(),
        fetchLongHorizonTrades(100),
        fetchLongHorizonEquity(500),
        fetchLongHorizonSweep(),
      ]);
      setStatus(s);
      setScores(l);
      setTrades(t);
      setEquity(e);
      setSweep(sw);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load the long-horizon desk");
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

  const handleSweep = async () => {
    setRunningSweep(true);
    try {
      await runLongHorizonSweep();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sweep failed");
    } finally {
      setRunningSweep(false);
    }
  };

  const heartbeatAge = status?.heartbeat
    ? (Date.now() - new Date(status.heartbeat).getTime()) / 1000
    : null;
  // This desk only acts once a day (see long_horizon_scheduler.py); a day-old heartbeat
  // is healthy here, unlike a tick-driven desk.
  const live = Boolean(status?.heartbeat && heartbeatAge !== null && heartbeatAge < 36 * 3600);
  const totalPnl = status?.realized ?? 0;

  return (
    <div className="page">
      <PageHeader
        onRefresh={handleRefresh}
        refreshing={isRefreshing}
        crumb="Long-Horizon"
        title="Long-Horizon Factor Desk"
        subtitle="Paper desk that holds cross-sectional momentum/low-vol/reversal baskets for months, not days — the low-turnover construction that survives real NSE transaction costs where 1-5 day holds did not. Rebalances once per holding cycle (3-12 months) on a strategy's own qualified basket."
      />

      <div className="desk-banner">
        <strong>WHY THIS DESK IS DIFFERENT.</strong> The Intraday Stocks desk&rsquo;s 50 short-hold
        strategies lost 16/16 after real NSE costs (~₹11/trade gross edge vs ~₹132/trade of
        charges). Every strategy here holds for months and trades a ranked TOP-K basket, not one
        name at a time — diversification is what keeps drawdown survivable, cost amortization is
        what keeps the edge real. Only strategies that qualified on BOTH a training period and a
        held-back test period, and that aren&rsquo;t a near-duplicate of another survivor, are traded.
      </div>

      {error && <ErrorBanner message={error} />}

      {status?.note && (
        <div className="feed-note">
          <strong>{status.note}</strong> — run a sweep below to populate the qualified basket.
        </div>
      )}

      <div className="tiles">
        <div className="tile">
          <div className="tile-label">Engine</div>
          <div className={`tile-value ${live ? "gain" : ""}`}>{live ? "ACTIVE" : "IDLE"}</div>
          <div className="tile-sub">
            {status?.heartbeat ? `last pass ${new Date(status.heartbeat).toLocaleString()}` : "no heartbeat"}
          </div>
        </div>
        <div className="tile">
          <div className="tile-label">Equity</div>
          <div className="tile-value">₹{inr(status?.equity)}</div>
          <div className="tile-sub">from ₹{inr(status?.initial_capital)} paper</div>
        </div>
        <div className="tile">
          <div className="tile-label">Deployed</div>
          <div className="tile-value">₹{inr(status?.deployed)}</div>
          <div className="tile-sub">₹{inr(status?.unrealized)} unrealised</div>
        </div>
        <div className="tile">
          <div className="tile-label">Qualified basket</div>
          <div className="tile-value">{status?.basket_size ?? 0}</div>
          <div className="tile-sub">
            {sweep
              ? `${sweep.strategy_count} tested → ${sweep.qualified_count} gated → ${sweep.robust_count} out-of-sample → ${sweep.basket_count} independent`
              : "no sweep run yet"}
          </div>
        </div>
        <div className="tile">
          <div className="tile-label">Open positions</div>
          <div className="tile-value">{status?.open_positions ?? 0}</div>
          <div className="tile-sub">{status?.trades_closed ?? 0} trades closed</div>
        </div>
        <div className="tile">
          <div className="tile-label">Track record</div>
          <div className={`tile-value ${totalPnl >= 0 ? "gain" : "loss"}`}>
            {totalPnl >= 0 ? "+" : ""}₹{inr(totalPnl)}
          </div>
          <div className="tile-sub">realised, all time</div>
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

      <GlassPanel
        title="Factor sweep"
        note={sweep ? `latest: ${new Date(sweep.created_at).toLocaleString()}` : undefined}
      >
        <div className="sweep-row">
          <button className="run-btn" onClick={handleSweep} disabled={runningSweep}>
            {runningSweep ? "Running sweep…" : "Run sweep now"}
          </button>
          <span className="sweep-hint">
            Chronological train/test split, cross-sectional top-K basket, overlap de-dup — a
            strategy only enters the qualified basket if it clears the gate on BOTH halves
            independently and isn&rsquo;t a near-duplicate of one already kept.
          </span>
        </div>
        {sweep && sweep.results.length > 0 && (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Strategy</th>
                  <th style={{ textAlign: "left" }}>Family</th>
                  <th>Hold</th>
                  <th>Train PF</th>
                  <th>Test PF</th>
                  <th>Test Net ₹</th>
                  <th>Verdict</th>
                </tr>
              </thead>
              <tbody>
                {sweep.results.map((r) => (
                  <tr key={r.strategy_id}>
                    <td style={{ textAlign: "left" }}>{r.name}</td>
                    <td style={{ textAlign: "left", fontSize: 11 }}>{r.family}</td>
                    <td>{r.max_hold_days}d</td>
                    <td>{r.train_metrics.profit_factor ?? "-"}</td>
                    <td>{r.test_metrics.profit_factor ?? "-"}</td>
                    <td className={(r.test_metrics.net_pnl ?? 0) >= 0 ? "gain" : "loss"}>
                      {inr(r.test_metrics.net_pnl)}
                    </td>
                    <td>
                      {r.in_basket ? (
                        <span className="badge gain-badge">IN BASKET</span>
                      ) : r.duplicate_of ? (
                        <span className="badge">duplicate</span>
                      ) : (
                        <span className="badge loss">not qualified</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>

      <GlassPanel title={`Open positions (${status?.open_positions ?? 0})`}>
        {!status?.open_positions_detail?.length ? (
          <div className="empty">No open positions.</div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Symbol</th>
                  <th style={{ textAlign: "left" }}>Strategy</th>
                  <th>Qty</th>
                  <th>Entry</th>
                  <th>LTP</th>
                  <th>Unrealised</th>
                  <th>Opened</th>
                </tr>
              </thead>
              <tbody>
                {status.open_positions_detail.map((p, i) => (
                  <tr key={`${p.symbol}-${p.strategy_id}-${i}`}>
                    <td style={{ textAlign: "left" }}>{p.symbol}</td>
                    <td style={{ textAlign: "left", fontSize: 11 }}>{p.strategy_name}</td>
                    <td>{p.qty}</td>
                    <td>₹{inr2(p.entry_price)}</td>
                    <td>₹{inr2(p.ltp)}</td>
                    <td className={(p.unrealized_pnl ?? 0) >= 0 ? "gain" : "loss"}>
                      {(p.unrealized_pnl ?? 0) >= 0 ? "+" : ""}₹{inr(p.unrealized_pnl)}
                    </td>
                    <td style={{ fontSize: 10.5 }}>
                      {p.opened_at ? new Date(p.opened_at).toLocaleDateString() : "-"}
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
                  <th style={{ textAlign: "left" }}>Category</th>
                  <th>Trades</th>
                  <th>Win %</th>
                  <th>Net P&amp;L</th>
                  <th>Allocated</th>
                </tr>
              </thead>
              <tbody>
                {scores.map((s) => (
                  <tr key={s.strategy_id}>
                    <td style={{ textAlign: "left" }}>{s.name}</td>
                    <td style={{ textAlign: "left" }}>
                      <span className="badge">{s.category}</span>
                    </td>
                    <td>{s.trades}</td>
                    <td>{s.trades ? `${(s.win_rate * 100).toFixed(1)}%` : "-"}</td>
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

      <GlassPanel title="Recent closed trades">
        {!trades.length ? (
          <div className="empty">No closed trades yet.</div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Symbol</th>
                  <th style={{ textAlign: "left" }}>Strategy</th>
                  <th>Qty</th>
                  <th>Entry</th>
                  <th>Exit</th>
                  <th>P&amp;L</th>
                  <th>Closed</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((t, i) => (
                  <tr key={`${t.trade_id}-${i}`}>
                    <td style={{ textAlign: "left" }}>{t.symbol}</td>
                    <td style={{ textAlign: "left", fontSize: 11 }}>{t.strategy_name}</td>
                    <td>{t.qty}</td>
                    <td>₹{inr2(t.entry_price)}</td>
                    <td>₹{inr2(t.exit_price)}</td>
                    <td className={t.net_pnl >= 0 ? "gain" : "loss"}>
                      {t.net_pnl >= 0 ? "+" : ""}₹{inr(t.net_pnl)}
                    </td>
                    <td style={{ fontSize: 10.5 }}>
                      {t.closed_at ? new Date(t.closed_at).toLocaleString() : "-"}
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
          background: var(--canvas-soft); border: 1px solid var(--panel-border);
          color: var(--text-secondary);
        }
        .feed-note {
          padding: 10px 16px; border-radius: 8px; font-size: 12px; line-height: 1.5;
          background: var(--loss-dim); border: 1px solid rgba(217, 45, 63, 0.3);
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
        .sweep-row {
          display: flex; align-items: center; gap: 14px; padding: 16px 20px;
          flex-wrap: wrap;
        }
        .run-btn {
          padding: 9px 18px; border-radius: 8px; border: none; cursor: pointer;
          background: var(--purple, #6c4fd8); color: white; font-weight: 600; font-size: 13px;
        }
        .run-btn:disabled { opacity: 0.6; cursor: not-allowed; }
        .sweep-hint { font-size: 11.5px; color: var(--text-faint); max-width: 520px; line-height: 1.4; }
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
        .badge {
          display: inline-block; padding: 3px 8px; border-radius: 6px; font-size: 10px;
          font-weight: 700; letter-spacing: 0.05em; background: var(--canvas-soft);
          border: 1px solid var(--panel-border);
        }
        .badge.loss { background: var(--loss-dim); border-color: rgba(217, 45, 63, 0.3); }
        .badge.gain-badge { background: rgba(34, 170, 96, 0.12); border-color: rgba(34, 170, 96, 0.3); color: var(--gain); }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
      `}</style>
    </div>
  );
}
