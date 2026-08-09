"use client";

import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import PageHeader from "../../components/PageHeader";
import GlassPanel from "../../components/GlassPanel";
import StatusPill from "../../components/StatusPill";
import ErrorBanner from "../../components/ErrorBanner";
import EmptyState from "../../components/EmptyState";
import {
  MomentumPosition,
  MomentumScore,
  MomentumSummary,
  MomentumTrade,
  fetchMomentumLeaderboard,
  fetchMomentumPositions,
  fetchMomentumSummary,
  fetchMomentumTrades,
  runMomentumCycle,
} from "../../lib/api";

const REFRESH_MS = 15000;

const inr = (v: number | null | undefined) =>
  v === null || v === undefined ? "-" : `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
const inr2 = (v: number | null | undefined) =>
  v === null || v === undefined ? "-" : `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
const signed = (v: number | null | undefined) =>
  v === null || v === undefined ? "-" : `${v >= 0 ? "+" : ""}₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
const num = (v: number | null | undefined, dp = 2) =>
  v === null || v === undefined ? "-" : v.toFixed(dp);

const VERDICT_TONE: Record<string, "gain" | "loss" | "muted"> = {
  READY: "gain",
  REJECTED: "loss",
  PENDING: "muted",
};

type VerdictFilter = "ALL" | "READY" | "REJECTED" | "PENDING";

export default function MomentumPage() {
  const [summary, setSummary] = useState<MomentumSummary | null>(null);
  const [board, setBoard] = useState<MomentumScore[]>([]);
  const [positions, setPositions] = useState<MomentumPosition[]>([]);
  const [trades, setTrades] = useState<MomentumTrade[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [verdictFilter, setVerdictFilter] = useState<VerdictFilter>("ALL");
  const [styleFilter, setStyleFilter] = useState<string>("ALL");
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [s, lb, pos, tr] = await Promise.all([
        fetchMomentumSummary(),
        fetchMomentumLeaderboard(),
        fetchMomentumPositions(),
        fetchMomentumTrades(60),
      ]);
      setSummary(s);
      setBoard(lb);
      setPositions(pos.open ?? []);
      setTrades(tr);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load the momentum desk");
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  const runNow = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await runMomentumCycle();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to run a cycle");
    } finally {
      setBusy(false);
    }
  };

  const styles = useMemo(() => {
    const seen = new Map<string, string>();
    board.forEach((r) => seen.set(r.style, r.style_label));
    return Array.from(seen.entries());
  }, [board]);

  const rows = useMemo(
    () =>
      board.filter(
        (r) =>
          (verdictFilter === "ALL" || r.verdict === verdictFilter) &&
          (styleFilter === "ALL" || r.style === styleFilter),
      ),
    [board, verdictFilter, styleFilter],
  );

  const ready = board.filter((r) => r.verdict === "READY");
  const regime = summary?.regime;
  const gate = summary?.promotion_gate;

  return (
    <div className="page">
      <PageHeader
        crumb="Momentum"
        title="Momentum Trading"
        subtitle={
          <>
            A pre-live gate for momentum strategies. Each of the {summary?.strategy_count ?? 37} strategies trades its
            own <strong>₹10,000 paper account</strong> on the live Angel One feed, and every fill is charged real NSE
            brokerage, STT, exchange, SEBI, stamp duty and GST plus slippage — so the P&amp;L below is what the
            strategy would actually have kept. Strategies that clear the promotion gate are the ones worth putting real
            money behind on the Live Trading desk.
          </>
        }
        actions={
          <>
            <StatusPill label="Paper · costs charged" tone="accent" />
            {summary?.paused ? (
              <StatusPill label="Entries paused" tone="warn" />
            ) : (
              <StatusPill label="Running" tone="gain" pulse />
            )}
            <button className="run-btn" onClick={runNow} disabled={busy}>
              {busy ? "Running…" : "Run cycle now"}
            </button>
          </>
        }
      />

      {error && <ErrorBanner message={error} onRetry={load} />}

      {regime && (
        <div className={`regime ${regime.ok ? "on" : "off"}`}>
          <div className="regime-head">
            <span className="regime-tag">{regime.ok ? "RISK-ON" : "RISK-OFF — no new entries"}</span>
            <span className="regime-meta">
              {regime.benchmark} {regime.close?.toLocaleString("en-IN") ?? "-"} · 200-DMA{" "}
              {regime.ma?.toLocaleString("en-IN") ?? "-"}
              {regime.index_vol !== null && regime.index_vol !== undefined ? ` · index vol ${regime.index_vol}%` : ""}
            </span>
          </div>
          <p>{regime.reason}</p>
          <p className="regime-why">
            Momentum&rsquo;s worst losses are not random — they cluster after market declines and in high-volatility
            panics (Daniel &amp; Moskowitz, <em>Momentum Crashes</em>). This gate withholds new longs in exactly that
            state. Open positions keep being managed either way.
          </p>
        </div>
      )}

      {summary?.breaker_tripped && (
        <div className="breaker">
          Daily loss breaker tripped — today&rsquo;s P&amp;L {signed(summary.today_pnl)} crossed the{" "}
          {inr(summary.daily_loss_limit)} limit. No new positions this session; open ones are still managed.
        </div>
      )}

      <div className="tiles">
        <Tile label="Desk equity" value={inr(summary?.equity)} sub={`${summary?.strategy_count ?? 0} × ₹10,000 = ${inr(summary?.initial_capital)}`} />
        <Tile label="Today P&L" value={signed(summary?.today_pnl)} tone={(summary?.today_pnl ?? 0) >= 0 ? "gain" : "loss"} sub={`Breaker at ${inr(summary?.daily_loss_limit)}`} />
        <Tile label="Realised (net of costs)" value={signed(summary?.realized_pnl)} tone={(summary?.realized_pnl ?? 0) >= 0 ? "gain" : "loss"} sub={`${summary?.closed_positions ?? 0} closed`} />
        <Tile label="Costs charged" value={inr2(summary?.total_costs)} tone="loss" sub={`+ ${summary?.slippage_bps ?? 5} bps slippage per side`} />
        <Tile label="Open" value={String(summary?.open_positions ?? 0)} sub={`${inr(summary?.deployed_capital)} deployed`} />
        <Tile label="Cleared the gate" value={String(summary?.ready_count ?? 0)} tone={(summary?.ready_count ?? 0) > 0 ? "gain" : undefined} sub={`${summary?.rejected_count ?? 0} rejected · ${summary?.pending_count ?? 0} pending`} />
      </div>

      <GlassPanel title="Promotion gate" note="what a strategy must prove before it gets real money">
        <div className="gate">
          <div className="gate-criteria">
            <Criterion label="Closed trades" value={`≥ ${gate?.min_trades ?? 20}`} why="Fewer than this and the record is noise. No verdict is not approval." />
            <Criterion label="Net P&L" value="> ₹0" why="After brokerage, STT, exchange, SEBI, stamp duty, GST and slippage." />
            <Criterion label="Profit factor" value={`> ${gate?.min_profit_factor ?? 1.2}`} why="Gross profit divided by gross loss." />
            <Criterion label="Expectancy" value="> ₹0" why="Average rupees kept per trade." />
            <Criterion label="Win rate" value={`≥ ${((gate?.min_win_rate ?? 0.3) * 100).toFixed(0)}%`} why="Deliberately low — momentum wins by asymmetry, not accuracy." />
            <Criterion label="Max drawdown" value={`≤ ${gate?.max_drawdown_pct ?? 20}%`} why="Measured peak-to-trough, not against the starting stake." />
            <Criterion label="t-statistic" value={`≥ ${gate?.min_t_stat ?? 1.5}`} why="Separates a real edge from a lucky run. A coin flip scores ~1.3." />
          </div>
          {ready.length > 0 && (
            <div className="ready-callout">
              <div className="ready-title">{ready.length} strategy{ready.length === 1 ? "" : "ies"} cleared the gate</div>
              <div className="ready-names">
                {ready.map((r) => (
                  <span key={r.strategy_id} className="ready-chip">{r.name}</span>
                ))}
              </div>
              <div className="ready-note">
                Promotion is still a manual decision — add these to the Live Trading desk deliberately, one at a time.
              </div>
            </div>
          )}
        </div>
      </GlassPanel>

      <GlassPanel
        title="Strategy leaderboard"
        note={`${rows.length} of ${board.length} shown · ₹10,000 each`}
      >
        <div className="filters">
          <div className="filter-row">
            {(["ALL", "READY", "REJECTED", "PENDING"] as VerdictFilter[]).map((v) => (
              <button key={v} className={`chip ${verdictFilter === v ? "on" : ""}`} onClick={() => setVerdictFilter(v)}>
                {v === "ALL" ? "All verdicts" : v}
              </button>
            ))}
          </div>
          <div className="filter-row">
            <button className={`chip ${styleFilter === "ALL" ? "on" : ""}`} onClick={() => setStyleFilter("ALL")}>
              All styles
            </button>
            {styles.map(([style, label]) => (
              <button key={style} className={`chip ${styleFilter === style ? "on" : ""}`} onClick={() => setStyleFilter(style)}>
                {label}
              </button>
            ))}
          </div>
        </div>

        {!rows.length ? (
          <EmptyState title="No strategies match this filter" note="Clear a filter, or wait for the desk to accrue trades." />
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th className="l">Strategy</th>
                  <th className="l">Style</th>
                  <th>Hold</th>
                  <th>Trades</th>
                  <th>Win %</th>
                  <th>PF</th>
                  <th>Expectancy</th>
                  <th>Max DD</th>
                  <th>t-stat</th>
                  <th>Costs</th>
                  <th>Net P&amp;L</th>
                  <th>Account</th>
                  <th>Verdict</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <Fragment key={r.strategy_id}>
                    <tr
                      className={`row ${r.verdict.toLowerCase()}`}
                      onClick={() => setExpanded(expanded === r.strategy_id ? null : r.strategy_id)}
                    >
                      <td className="l sname">
                        {r.name}
                        {r.open_positions > 0 && <span className="live-dot" title={`${r.open_positions} open`} />}
                      </td>
                      <td className="l"><span className="cat">{r.style_label}</span></td>
                      <td>{r.max_hold_days === 0 ? "intraday" : `${r.max_hold_days}d`}</td>
                      <td>{r.trades}</td>
                      <td>{r.trades ? `${(r.win_rate * 100).toFixed(0)}%` : "-"}</td>
                      <td>{r.profit_factor === null ? "-" : num(r.profit_factor)}</td>
                      <td className={r.expectancy >= 0 ? "gain" : "loss"}>{r.trades ? signed(r.expectancy) : "-"}</td>
                      <td>{r.trades ? `${num(r.max_drawdown_pct, 1)}%` : "-"}</td>
                      <td>{r.t_stat === null ? "-" : num(r.t_stat)}</td>
                      <td className="dim">{r.total_costs ? inr2(r.total_costs) : "-"}</td>
                      <td className={r.net_pnl >= 0 ? "gain" : "loss"}>{r.trades ? signed(r.net_pnl) : "-"}</td>
                      <td>{inr(r.allocated_capital)}</td>
                      <td><StatusPill label={r.verdict} tone={VERDICT_TONE[r.verdict]} /></td>
                    </tr>
                    {expanded === r.strategy_id && (
                      <tr className="expand">
                        <td colSpan={13}>
                          <div className="why">
                            <div className="why-rationale">{r.rationale}</div>
                            <ul>
                              {r.verdict_reasons.map((reason, i) => (
                                <li key={i}>{reason}</li>
                              ))}
                            </ul>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>

      <GlassPanel title={`Open positions (${positions.length})`} note="marked on the live feed, net of the round trip's charges">
        {!positions.length ? (
          <EmptyState title="No open positions" note="The desk opens positions during market hours as signals fire." />
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th className="l">Symbol</th>
                  <th className="l">Strategy</th>
                  <th>Qty</th>
                  <th>Entry</th>
                  <th>LTP</th>
                  <th>Target</th>
                  <th>Stop</th>
                  <th>Unrealised</th>
                  <th>%</th>
                  <th>Price from</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={p.position_id}>
                    <td className="l sym">{p.symbol}</td>
                    <td className="l dim">{p.strategy_name}</td>
                    <td>{p.qty}</td>
                    <td>{inr2(p.entry_price)}</td>
                    <td>{inr2(p.ltp)}</td>
                    <td>{inr2(p.target)}</td>
                    <td>
                      {inr2(p.stoploss)}
                      {p.stop_trailed && <span className="trail" title="Trailing stop has ratcheted up">↑</span>}
                    </td>
                    <td className={p.unrealized_pnl >= 0 ? "gain" : "loss"}>{signed(p.unrealized_pnl)}</td>
                    <td className={p.pnl_pct >= 0 ? "gain" : "loss"}>{num(p.pnl_pct, 2)}%</td>
                    <td><span className="cat">{p.ltp_source}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>

      <GlassPanel title="Closed trades" note="gross, then what the charges took">
        {!trades.length ? (
          <EmptyState title="No closed trades yet" note="Every closed trade shows gross P&L, costs and the net kept." />
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th className="l">Symbol</th>
                  <th className="l">Strategy</th>
                  <th>Qty</th>
                  <th>Entry</th>
                  <th>Exit</th>
                  <th>Gross</th>
                  <th>Costs</th>
                  <th>Net</th>
                  <th>Exit reason</th>
                  <th>Closed</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((t) => (
                  <tr key={t.trade_id}>
                    <td className="l sym">{t.symbol}</td>
                    <td className="l dim">{t.strategy_name}</td>
                    <td>{t.qty}</td>
                    <td>{inr2(t.entry_price)}</td>
                    <td>{inr2(t.exit_price)}</td>
                    <td className={t.gross_pnl >= 0 ? "gain" : "loss"}>{signed(t.gross_pnl)}</td>
                    <td className="loss">-{inr2(t.costs)}</td>
                    <td className={t.realized_pnl >= 0 ? "gain" : "loss"}>{signed(t.realized_pnl)}</td>
                    <td><span className="cat">{t.exit_reason}</span></td>
                    <td className="dim">{new Date(t.closed_at).toLocaleString("en-IN", { dateStyle: "short", timeStyle: "short" })}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>

      {summary?.last_notes && summary.last_notes.length > 0 && (
        <GlassPanel title="Last cycle" note={summary.last_run_at ? new Date(summary.last_run_at).toLocaleString("en-IN") : undefined}>
          <ul className="notes">
            {summary.last_notes.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        </GlassPanel>
      )}

      <style jsx>{`
        .page { display: flex; flex-direction: column; gap: 16px; }
        .run-btn {
          padding: 7px 14px; border-radius: 9px; font-size: 12.5px; font-weight: 600; cursor: pointer;
          border: 1px solid var(--panel-border); background: var(--panel); color: var(--text);
        }
        .run-btn:disabled { opacity: 0.55; cursor: default; }

        .regime { border-radius: 14px; padding: 14px 18px; border: 1px solid var(--panel-border); background: var(--panel); }
        .regime.on { border-color: rgba(14, 159, 110, 0.28); background: var(--gain-dim); }
        .regime.off { border-color: rgba(217, 45, 63, 0.24); background: var(--loss-dim); }
        .regime-head { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
        .regime-tag { font-size: 11px; font-weight: 800; letter-spacing: 0.06em; }
        .regime.on .regime-tag { color: var(--gain); }
        .regime.off .regime-tag { color: var(--loss); }
        .regime-meta { font-size: 11.5px; color: var(--text-muted); font-variant-numeric: tabular-nums; }
        .regime p { margin: 7px 0 0; font-size: 12.5px; color: var(--text); }
        .regime-why { color: var(--text-muted) !important; font-size: 11.5px !important; }

        .breaker {
          border-radius: 12px; padding: 12px 16px; font-size: 12.5px; font-weight: 600;
          background: var(--loss-dim); border: 1px solid rgba(217, 45, 63, 0.24); color: var(--loss);
        }

        .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }

        .gate { display: grid; grid-template-columns: 1fr; gap: 16px; padding: 16px 20px; }
        @media (min-width: 1000px) { .gate { grid-template-columns: 1.6fr 1fr; } }
        .gate-criteria { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 10px; }
        .ready-callout { border-radius: 12px; padding: 14px 16px; background: var(--gain-dim); border: 1px solid rgba(14, 159, 110, 0.24); }
        .ready-title { font-size: 13px; font-weight: 700; color: var(--gain); margin-bottom: 8px; }
        .ready-names { display: flex; flex-wrap: wrap; gap: 6px; }
        .ready-chip { font-size: 11px; font-weight: 600; padding: 3px 9px; border-radius: 6px; background: var(--panel); border: 1px solid var(--panel-border); }
        .ready-note { margin-top: 9px; font-size: 11.5px; color: var(--text-muted); }

        .filters { padding: 14px 20px 4px; display: flex; flex-direction: column; gap: 8px; }
        .filter-row { display: flex; flex-wrap: wrap; gap: 6px; }
        .chip {
          font-size: 11.5px; font-weight: 600; padding: 5px 11px; border-radius: 100px; cursor: pointer;
          border: 1px solid var(--panel-border); background: var(--panel); color: var(--text-muted);
        }
        .chip.on { background: var(--purple-dim); border-color: rgba(125, 52, 220, 0.24); color: var(--purple); }

        .table-scroll { overflow-x: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums; white-space: nowrap; }
        .data-table th { text-align: center; padding: 9px 12px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); }
        .data-table td { padding: 9px 12px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .data-table th.l, .data-table td.l { text-align: left; }
        .row { cursor: pointer; }
        .row:hover { background: var(--canvas-soft); }
        .row.ready { background: rgba(14, 159, 110, 0.05); }
        .sname { font-weight: 600; }
        .sym { font-weight: 700; }
        .dim { color: var(--text-muted); }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
        .cat { font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 6px; background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); }
        .live-dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: var(--gain); margin-left: 7px; vertical-align: middle; }
        .trail { color: var(--gain); margin-left: 4px; font-weight: 700; }
        .expand td { background: var(--canvas-soft); white-space: normal; text-align: left; }
        .why-rationale { font-size: 12px; color: var(--text); margin-bottom: 6px; }
        .why ul { margin: 0; padding-left: 18px; }
        .why li { font-size: 12px; color: var(--text-muted); margin: 2px 0; }

        .notes { margin: 0; padding: 14px 20px 16px 38px; }
        .notes li { font-size: 12.5px; color: var(--text-muted); margin: 4px 0; }
      `}</style>
    </div>
  );
}

function Tile({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "gain" | "loss";
}) {
  return (
    <div className="tile">
      <div className="t-label">{label}</div>
      <div className={`t-value ${tone ?? ""}`}>{value}</div>
      {sub && <div className="t-sub">{sub}</div>}
      <style jsx>{`
        .tile { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 14px; padding: 14px 16px; box-shadow: var(--shadow-sm); }
        .t-label { font-size: 10.5px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; color: var(--text-muted); }
        .t-value { margin-top: 7px; font-family: var(--font-data); font-variant-numeric: tabular-nums; font-size: 21px; font-weight: 600; letter-spacing: -0.2px; }
        .t-value.gain { color: var(--gain); }
        .t-value.loss { color: var(--loss); }
        .t-sub { margin-top: 4px; font-size: 11px; color: var(--text-faint); }
      `}</style>
    </div>
  );
}

function Criterion({ label, value, why }: { label: string; value: string; why: string }) {
  return (
    <div className="crit">
      <div className="c-head">
        <span className="c-label">{label}</span>
        <span className="c-value">{value}</span>
      </div>
      <div className="c-why">{why}</div>
      <style jsx>{`
        .crit { border: 1px solid var(--panel-border); border-radius: 10px; padding: 10px 12px; background: var(--canvas-soft); }
        .c-head { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
        .c-label { font-size: 11.5px; font-weight: 700; }
        .c-value { font-family: var(--font-data); font-variant-numeric: tabular-nums; font-size: 12px; font-weight: 700; color: var(--purple); }
        .c-why { margin-top: 4px; font-size: 11px; color: var(--text-muted); line-height: 1.35; }
      `}</style>
    </div>
  );
}
