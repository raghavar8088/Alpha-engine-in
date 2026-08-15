"use client";

import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import PageHeader from "../../components/PageHeader";
import GlassPanel from "../../components/GlassPanel";
import StatusPill from "../../components/StatusPill";
import ErrorBanner from "../../components/ErrorBanner";
import EmptyState from "../../components/EmptyState";
import {
  CommodityCoverage,
  CommodityPosition,
  CommodityScore,
  CommoditySummary,
  CommodityTrade,
  CommodityUniverseRow,
  fetchCommodityBars,
  fetchCommodityLeaderboard,
  fetchCommodityPositions,
  fetchCommoditySummary,
  fetchCommodityTrades,
  fetchCommodityUniverse,
  refreshCommodityBars,
  runCommodityCycle,
} from "../../lib/api";

const REFRESH_MS = 20000;
const TIMEFRAMES = ["1m", "5m", "15m", "30m", "45m", "1h", "4h", "1d"];
const FAMILIES: { key: string; label: string }[] = [
  { key: "chart", label: "Chart Pattern" },
  { key: "candlestick", label: "Candlestick" },
  { key: "structure", label: "Price Structure" },
];

const inr = (v: number | null | undefined) =>
  v === null || v === undefined ? "-" : `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
const inr2 = (v: number | null | undefined) =>
  v === null || v === undefined ? "-" : `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
const signed = (v: number | null | undefined) =>
  v === null || v === undefined ? "-" : `${v >= 0 ? "+" : ""}₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
const num = (v: number | null | undefined, dp = 2) => (v === null || v === undefined ? "-" : v.toFixed(dp));

const VERDICT_TONE: Record<string, "gain" | "loss" | "muted"> = {
  READY: "gain", REJECTED: "loss", PENDING: "muted",
};

export default function CommodityPage() {
  const [summary, setSummary] = useState<CommoditySummary | null>(null);
  const [board, setBoard] = useState<CommodityScore[]>([]);
  const [positions, setPositions] = useState<CommodityPosition[]>([]);
  const [trades, setTrades] = useState<CommodityTrade[]>([]);
  const [universe, setUniverse] = useState<CommodityUniverseRow[]>([]);
  const [coverage, setCoverage] = useState<CommodityCoverage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [family, setFamily] = useState<string>("ALL");
  const [timeframe, setTimeframe] = useState<string>("ALL");
  const [verdict, setVerdict] = useState<string>("ALL");
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [s, lb, pos, tr, uni, bars] = await Promise.all([
        fetchCommoditySummary(),
        fetchCommodityLeaderboard({
          family: family === "ALL" ? undefined : family,
          timeframe: timeframe === "ALL" ? undefined : timeframe,
          verdict: verdict === "ALL" ? undefined : verdict,
        }),
        fetchCommodityPositions(),
        fetchCommodityTrades(60),
        fetchCommodityUniverse(),
        fetchCommodityBars(),
      ]);
      setSummary(s);
      setBoard(lb.leaderboard ?? []);
      setPositions(pos.open ?? []);
      setTrades(tr);
      setUniverse(uni);
      setCoverage(bars.coverage);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load the commodity desk");
    }
  }, [family, timeframe, verdict]);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  const act = async (label: string, fn: () => Promise<unknown>) => {
    if (busy) return;
    setBusy(label);
    try {
      await fn();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : `${label} failed`);
    } finally {
      setBusy(null);
    }
  };

  const gate = summary?.promotion_gate;
  const ready = board.filter((r) => r.verdict === "READY");
  const storeRows = useMemo(() => {
    if (!coverage) return [];
    return coverage.symbols.map((s) => ({
      symbol: s,
      counts: coverage.bars[s] || {},
      latest: coverage.latest_bar_ist[s] ?? null,
    }));
  }, [coverage]);

  return (
    <div className="page">
      <PageHeader
        crumb="Commodity Trading"
        title="Commodity Trading"
        subtitle={
          <>
            {summary?.strategy_count ?? 311} pattern strategies — 39 templates (chart, candlestick and
            price-structure) across 8 timeframes — each on its own <strong>₹10,00,000 paper account</strong>,
            trading the front-month MCX futures on live Angel One prices. Fills are charged real MCX
            brokerage, CTT, exchange, SEBI, stamp duty and GST plus slippage, so a pattern has to beat its
            own costs before it counts as an edge.
          </>
        }
        actions={
          <>
            <StatusPill label="Paper · costs charged" tone="accent" />
            {summary?.market_open ? (
              <StatusPill label="MCX open" tone="gain" pulse />
            ) : (
              <StatusPill label="MCX closed" tone="muted" />
            )}
            <button className="btn" onClick={() => act("bars", refreshCommodityBars)} disabled={!!busy}>
              {busy === "bars" ? "Fetching…" : "Refresh bars"}
            </button>
            <button className="btn" onClick={() => act("run", runCommodityCycle)} disabled={!!busy}>
              {busy === "run" ? "Running…" : "Run cycle"}
            </button>
          </>
        }
      />

      {error && <ErrorBanner message={error} onRetry={load} />}

      {summary?.breaker_tripped && (
        <div className="breaker">
          Daily loss breaker tripped — today&rsquo;s P&amp;L {signed(summary.today_pnl)} crossed the{" "}
          {inr(summary.daily_loss_limit)} limit. No new positions; open ones still managed.
        </div>
      )}

      <div className="tiles">
        <Tile label="Desk equity" value={inr(summary?.equity)} sub={`${summary?.strategy_count ?? 0} × ₹10L = ${inr(summary?.initial_capital)}`} />
        <Tile label="Today P&L" value={signed(summary?.today_pnl)} tone={(summary?.today_pnl ?? 0) >= 0 ? "gain" : "loss"} />
        <Tile label="Realised (net)" value={signed(summary?.realized_pnl)} tone={(summary?.realized_pnl ?? 0) >= 0 ? "gain" : "loss"} sub={`${summary?.closed_positions ?? 0} closed`} />
        <Tile label="MCX charges paid" value={inr2(summary?.total_costs)} tone="loss" sub={`+ ${summary?.slippage_bps ?? 5} bps slippage/side`} />
        <Tile label="Open" value={String(summary?.open_positions ?? 0)} sub={`${inr(summary?.deployed_capital)} deployed`} />
        <Tile label="Cleared the gate" value={String(summary?.ready_count ?? 0)} tone={(summary?.ready_count ?? 0) > 0 ? "gain" : undefined} sub={`${summary?.rejected_count ?? 0} rejected · ${summary?.pending_count ?? 0} pending`} />
      </div>

      <GlassPanel title="Contracts traded" note="front-month MCX futures, refreshed from the instrument master">
        {!universe.length ? (
          <EmptyState title="No contracts resolved" note="No unexpired MCX front-month futures with an Angel token are on file." />
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th className="l">Underlying</th><th className="l">Contract</th><th>Expiry</th>
                  <th>Tick</th>{TIMEFRAMES.map((t) => <th key={t}>{t}</th>)}<th>Latest bar (IST)</th>
                </tr>
              </thead>
              <tbody>
                {universe.map((u) => {
                  const row = storeRows.find((r) => r.symbol === u.underlying);
                  return (
                    <tr key={u.symbol}>
                      <td className="l sym">{u.underlying}</td>
                      <td className="l dim">{u.symbol}</td>
                      <td>{u.expiry}</td>
                      <td>{u.tick_size}</td>
                      {TIMEFRAMES.map((t) => {
                        const n = row?.counts?.[t];
                        const derived = ["30m", "45m", "4h"].includes(t);
                        return (
                          <td key={t} className={n ? "" : derived ? "dim" : "loss"}>
                            {derived ? "↩" : n ?? 0}
                          </td>
                        );
                      })}
                      <td className="dim">{row?.latest ? new Date(row.latest).toLocaleString("en-IN") : "-"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <div className="legend">
              ↩ = derived by resampling at read time (Angel serves only 1m / 5m / 15m / 1h / 1d, so 30m,
              45m and 4h are aggregated from their parent, anchored to the 09:00 session open).
            </div>
          </div>
        )}
      </GlassPanel>

      <GlassPanel title="Promotion gate" note="what a pattern must prove before real money">
        <div className="gate">
          <Criterion label="Closed trades" value={`≥ ${gate?.min_trades ?? 30}`} why="Below this the record is noise. No verdict is not approval." />
          <Criterion label="Net P&L" value="> ₹0" why="After MCX brokerage, CTT, exchange, SEBI, stamp duty, GST and slippage." />
          <Criterion label="Profit factor" value={`> ${gate?.min_profit_factor ?? 1.2}`} why="Gross profit divided by gross loss." />
          <Criterion label="Expectancy" value="> ₹0" why="Average rupees kept per trade." />
          <Criterion label="Win rate" value={`≥ ${((gate?.min_win_rate ?? 0.3) * 100).toFixed(0)}%`} why="Deliberately low — breakouts win by asymmetry." />
          <Criterion label="Max drawdown" value={`≤ ${gate?.max_drawdown_pct ?? 20}%`} why="Measured peak-to-trough, not against the opening stake." />
          <Criterion label="t-statistic" value={`≥ ${gate?.min_t_stat ?? 1.5}`} why="Separates a real edge from a lucky run." />
        </div>
        {ready.length > 0 && (
          <div className="ready">
            <b>{ready.length} strategy{ready.length === 1 ? "" : "ies"} cleared the gate:</b>{" "}
            {ready.slice(0, 12).map((r) => r.name).join(", ")}
            {ready.length > 12 ? " …" : ""}
          </div>
        )}
      </GlassPanel>

      <GlassPanel title="Strategy leaderboard" note={`${board.length} shown · ₹10L each`}>
        <div className="filters">
          <div className="frow">
            <span className="flabel">Family</span>
            <button className={`chip ${family === "ALL" ? "on" : ""}`} onClick={() => setFamily("ALL")}>All</button>
            {FAMILIES.map((f) => (
              <button key={f.key} className={`chip ${family === f.key ? "on" : ""}`} onClick={() => setFamily(f.key)}>{f.label}</button>
            ))}
          </div>
          <div className="frow">
            <span className="flabel">Timeframe</span>
            <button className={`chip ${timeframe === "ALL" ? "on" : ""}`} onClick={() => setTimeframe("ALL")}>All</button>
            {TIMEFRAMES.map((t) => (
              <button key={t} className={`chip ${timeframe === t ? "on" : ""}`} onClick={() => setTimeframe(t)}>{t}</button>
            ))}
          </div>
          <div className="frow">
            <span className="flabel">Verdict</span>
            {["ALL", "READY", "REJECTED", "PENDING"].map((v) => (
              <button key={v} className={`chip ${verdict === v ? "on" : ""}`} onClick={() => setVerdict(v)}>{v}</button>
            ))}
          </div>
        </div>

        {!board.length ? (
          <EmptyState title="No strategies match this filter" note="Clear a filter, or wait for the desk to accrue trades." />
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th className="l">Strategy</th><th className="l">Family</th><th>TF</th><th>Trades</th>
                  <th>Win %</th><th>PF</th><th>Expectancy</th><th>Max DD</th><th>t-stat</th>
                  <th>Costs</th><th>Net P&amp;L</th><th>Verdict</th>
                </tr>
              </thead>
              <tbody>
                {board.slice(0, 200).map((r) => (
                  <Fragment key={r.strategy_id}>
                    <tr className={`row ${r.verdict.toLowerCase()}`} onClick={() => setExpanded(expanded === r.strategy_id ? null : r.strategy_id)}>
                      <td className="l sname">{r.name}{r.open_positions > 0 && <span className="dot" />}</td>
                      <td className="l"><span className="cat">{r.family_label}</span></td>
                      <td>{r.timeframe}</td>
                      <td>{r.trades}</td>
                      <td>{r.trades ? `${(r.win_rate * 100).toFixed(0)}%` : "-"}</td>
                      <td>{r.profit_factor === null ? "-" : num(r.profit_factor)}</td>
                      <td className={r.expectancy >= 0 ? "gain" : "loss"}>{r.trades ? signed(r.expectancy) : "-"}</td>
                      <td>{r.trades ? `${num(r.max_drawdown_pct, 1)}%` : "-"}</td>
                      <td>{r.t_stat === null ? "-" : num(r.t_stat)}</td>
                      <td className="dim">{r.total_costs ? inr2(r.total_costs) : "-"}</td>
                      <td className={r.net_pnl >= 0 ? "gain" : "loss"}>{r.trades ? signed(r.net_pnl) : "-"}</td>
                      <td><StatusPill label={r.verdict} tone={VERDICT_TONE[r.verdict]} /></td>
                    </tr>
                    {expanded === r.strategy_id && (
                      <tr className="expand">
                        <td colSpan={12}>
                          <ul>{r.verdict_reasons.map((x, i) => <li key={i}>{x}</li>)}</ul>
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

      <GlassPanel title={`Open positions (${positions.length})`} note="marked on live MCX prices, net of the round trip's charges">
        {!positions.length ? (
          <EmptyState title="No open positions" note="Patterns are evaluated every couple of minutes while MCX is open (09:00–23:30 IST)." />
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th className="l">Contract</th><th className="l">Pattern</th><th>TF</th><th>Side</th>
                  <th>Qty</th><th>Entry</th><th>LTP</th><th>Target</th><th>Stop</th>
                  <th>Bars held</th><th>Unrealised</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={p.position_id}>
                    <td className="l sym">{p.symbol}</td>
                    <td className="l dim">{p.pattern}</td>
                    <td>{p.timeframe}</td>
                    <td className={p.side === "BUY" ? "gain" : "loss"}>{p.side}</td>
                    <td>{p.qty}</td>
                    <td>{inr2(p.entry_price)}</td>
                    <td>{inr2(p.ltp)}</td>
                    <td>{inr2(p.target)}</td>
                    <td>{inr2(p.stoploss)}</td>
                    <td className="dim">{p.bars_held}/{p.max_hold_bars}</td>
                    <td className={p.unrealized_pnl >= 0 ? "gain" : "loss"}>{signed(p.unrealized_pnl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>

      <GlassPanel title="Closed trades" note="gross, then what the MCX charges took">
        {!trades.length ? (
          <EmptyState title="No closed trades yet" note="Every close shows gross P&L, charges and the net kept." />
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th className="l">Contract</th><th className="l">Pattern</th><th>TF</th><th>Side</th>
                  <th>Entry</th><th>Exit</th><th>Gross</th><th>Costs</th><th>Net</th><th>Why</th><th>Closed</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((t) => (
                  <tr key={t.trade_id}>
                    <td className="l sym">{t.symbol}</td>
                    <td className="l dim">{t.pattern}</td>
                    <td>{t.timeframe}</td>
                    <td className={t.side === "BUY" ? "gain" : "loss"}>{t.side}</td>
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
        <GlassPanel title="Last cycle" note={`${summary.last_evaluated?.toLocaleString("en-IN") ?? 0} evaluations`}>
          <ul className="notes">{summary.last_notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
        </GlassPanel>
      )}

      <style jsx>{`
        .page { display: flex; flex-direction: column; gap: 16px; }
        .btn { padding: 7px 14px; border-radius: 9px; font-size: 12.5px; font-weight: 600; cursor: pointer;
               border: 1px solid var(--panel-border); background: var(--panel); color: var(--text); }
        .btn:disabled { opacity: 0.55; cursor: default; }
        .breaker { border-radius: 12px; padding: 12px 16px; font-size: 12.5px; font-weight: 600;
                   background: var(--loss-dim); border: 1px solid rgba(217,45,63,.24); color: var(--loss); }
        .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }
        .gate { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 10px; padding: 16px 20px; }
        .ready { padding: 0 20px 16px; font-size: 12.5px; color: var(--gain); }
        .filters { padding: 14px 20px 4px; display: flex; flex-direction: column; gap: 8px; }
        .frow { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
        .flabel { font-size: 10px; font-weight: 800; letter-spacing: .05em; text-transform: uppercase;
                  color: var(--text-muted); min-width: 66px; }
        .chip { font-size: 11.5px; font-weight: 600; padding: 4px 10px; border-radius: 100px; cursor: pointer;
                border: 1px solid var(--panel-border); background: var(--panel); color: var(--text-muted); }
        .chip.on { background: var(--purple-dim); border-color: rgba(125,52,220,.24); color: var(--purple); }
        .table-scroll { overflow-x: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums; white-space: nowrap; }
        .data-table th { text-align: center; padding: 9px 10px; font-size: 10px; font-weight: 700; letter-spacing: .04em;
                         text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); }
        .data-table td { padding: 9px 10px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .data-table th.l, .data-table td.l { text-align: left; }
        .row { cursor: pointer; }
        .row:hover { background: var(--canvas-soft); }
        .row.ready { background: rgba(14,159,110,.05); }
        .sname { font-weight: 600; }
        .sym { font-weight: 700; }
        .dim { color: var(--text-muted); }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
        .cat { font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 6px;
               background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); }
        .dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: var(--gain); margin-left: 7px; }
        .expand td { background: var(--canvas-soft); white-space: normal; text-align: left; }
        .expand ul { margin: 0; padding-left: 18px; }
        .expand li { font-size: 12px; color: var(--text-muted); margin: 2px 0; }
        .legend { padding: 10px 20px 14px; font-size: 11.5px; color: var(--text-faint); white-space: normal; }
        .notes { margin: 0; padding: 14px 20px 16px 38px; }
        .notes li { font-size: 12.5px; color: var(--text-muted); margin: 4px 0; }
      `}</style>
    </div>
  );
}

function Tile({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "gain" | "loss" }) {
  return (
    <div className="tile">
      <div className="t-label">{label}</div>
      <div className={`t-value ${tone ?? ""}`}>{value}</div>
      {sub && <div className="t-sub">{sub}</div>}
      <style jsx>{`
        .tile { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 14px;
                padding: 14px 16px; box-shadow: var(--shadow-sm); }
        .t-label { font-size: 10.5px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase; color: var(--text-muted); }
        .t-value { margin-top: 7px; font-family: var(--font-data); font-variant-numeric: tabular-nums;
                   font-size: 21px; font-weight: 600; letter-spacing: -.2px; }
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
      <div className="c-head"><span className="c-label">{label}</span><span className="c-value">{value}</span></div>
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
