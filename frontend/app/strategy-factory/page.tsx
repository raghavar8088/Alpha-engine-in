"use client";

import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import PageHeader from "../../components/PageHeader";
import GlassPanel from "../../components/GlassPanel";
import StatusPill from "../../components/StatusPill";
import ErrorBanner from "../../components/ErrorBanner";
import EmptyState from "../../components/EmptyState";
import {
  SFRecipe,
  SFRow,
  SFSummary,
  fetchSFLibrary,
  fetchSFPositions,
  fetchSFRecipes,
  fetchSFSignals,
  fetchSFStrategy,
  fetchSFSummary,
  fetchSFTrades,
  runSFBacktest,
  runSFCycle,
} from "../../lib/api";

const REFRESH_MS = 25000;
const TIMEFRAMES = ["1m", "5m", "15m", "30m", "45m", "1h", "4h", "1d"];
const FAMILIES = [
  { key: "chart", label: "Chart Pattern" },
  { key: "candlestick", label: "Candlestick" },
  { key: "structure", label: "Price Structure" },
  { key: "indicator", label: "Indicator" },
  { key: "hybrid", label: "Multi-Condition" },
];
const GRADE_TONE: Record<number, "gain" | "loss" | "muted" | "accent" | "warn"> = {
  5: "gain", 4: "gain", 3: "accent", 2: "warn", 1: "loss", 0: "muted",
};

const inr = (v: number | null | undefined) =>
  v === null || v === undefined ? "-" : `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
const signed = (v: number | null | undefined) =>
  v === null || v === undefined ? "-" : `${v >= 0 ? "+" : ""}₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
const num = (v: number | null | undefined, dp = 2) =>
  v === null || v === undefined ? "-" : v.toFixed(dp);

export default function StrategyFactoryPage() {
  const [summary, setSummary] = useState<SFSummary | null>(null);
  const [rows, setRows] = useState<SFRow[]>([]);
  const [recipes, setRecipes] = useState<SFRecipe[]>([]);
  const [positions, setPositions] = useState<any[]>([]);
  const [trades, setTrades] = useState<any[]>([]);
  const [signals, setSignals] = useState<any[]>([]);
  const [detail, setDetail] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [family, setFamily] = useState("ALL");
  const [timeframe, setTimeframe] = useState("ALL");
  const [grade, setGrade] = useState<number | "ALL">("ALL");
  const [tab, setTab] = useState<"library" | "recipes" | "paper" | "signals">("library");

  const load = useCallback(async () => {
    try {
      const [s, lib, pos, tr, sg] = await Promise.all([
        fetchSFSummary(),
        fetchSFLibrary({
          family: family === "ALL" ? undefined : family,
          timeframe: timeframe === "ALL" ? undefined : timeframe,
          grade: grade === "ALL" ? undefined : grade,
        }),
        fetchSFPositions(),
        fetchSFTrades(80),
        fetchSFSignals(60),
      ]);
      setSummary(s);
      setRows(lib.library ?? []);
      setPositions(pos.open ?? []);
      setTrades(tr);
      setSignals(sg);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load the strategy factory");
    }
  }, [family, timeframe, grade]);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  useEffect(() => {
    if (tab === "recipes" && !recipes.length) {
      fetchSFRecipes().then((r) => setRecipes(r.recipes ?? [])).catch(() => {});
    }
  }, [tab, recipes.length]);

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

  const openDetail = async (id: string) => {
    if (detail?.strategy?.strategy_id === id) return setDetail(null);
    try {
      setDetail(await fetchSFStrategy(id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load the strategy");
    }
  };

  const graded = useMemo(
    () => Object.entries(summary?.grade_counts ?? {}).sort((a, b) => Number(b[0]) - Number(a[0])),
    [summary],
  );
  const ungraded = (summary?.strategy_count ?? 0) -
    Object.values(summary?.grade_counts ?? {}).reduce((a, b) => a + b, 0);

  return (
    <div className="page">
      <PageHeader
        crumb="Strategy Factory"
        title="Strategy Factory"
        subtitle={
          <>
            {summary?.strategy_count ?? 546} rule-based strategies composed from{" "}
            <strong>69 distinct hypotheses × 8 timeframes</strong> — chart patterns, candlesticks,
            price structure, indicators and multi-condition hybrids. Each carries its own{" "}
            <strong>₹10,00,000</strong> paper account, its own risk/reward taken from its own logic,
            and a market-regime filter. Backtests replay with next-bar fills, real costs and
            slippage, and grade 1–5 on out-of-sample survival — only grade ≥{" "}
            {summary?.min_grade_to_trade ?? 3} earns a paper allocation.
          </>
        }
        actions={
          <>
            <StatusPill label="Paper · costs charged" tone="accent" />
            <button className="btn" onClick={() => act("bt", runSFBacktest)} disabled={!!busy}>
              {busy === "bt" ? "Started…" : "Run backtest"}
            </button>
            <button className="btn" onClick={() => act("run", runSFCycle)} disabled={!!busy}>
              {busy === "run" ? "Running…" : "Run paper cycle"}
            </button>
          </>
        }
      />

      {error && <ErrorBanner message={error} onRetry={load} />}

      <div className="tiles">
        <Tile label="Strategies" value={String(summary?.strategy_count ?? 0)}
              sub={Object.entries(summary?.family_counts ?? {}).map(([k, v]) => `${k} ${v}`).join(" · ")} />
        <Tile label="Book" value={inr(summary?.initial_capital)} sub={`₹10L × ${summary?.strategy_count ?? 0}`} />
        <Tile label="Backtest rows" value={String(summary?.backtest_rows ?? 0)} sub="one per strategy × symbol" />
        <Tile label="Graded 4–5" value={String((summary?.grade_counts?.["5"] ?? 0) + (summary?.grade_counts?.["4"] ?? 0))}
              tone="gain" sub={`${ungraded} not yet backtested`} />
        <Tile label="Realised (net)" value={signed(summary?.realized_pnl)}
              tone={(summary?.realized_pnl ?? 0) >= 0 ? "gain" : "loss"} sub={`${summary?.closed_positions ?? 0} closed`} />
        <Tile label="Open" value={String(summary?.open_positions ?? 0)} sub={inr(summary?.deployed_capital) + " deployed"} />
      </div>

      <GlassPanel title="Grade distribution" note="grade 5 = production candidate · grade 1 = rejected">
        <div className="grades">
          {[5, 4, 3, 2, 1].map((g) => (
            <div className="gcell" key={g}>
              <StatusPill label={`GRADE ${g}`} tone={GRADE_TONE[g]} />
              <div className="gnum">{summary?.grade_counts?.[String(g)] ?? 0}</div>
            </div>
          ))}
          <div className="gcell">
            <StatusPill label="NOT BACKTESTED" tone="muted" />
            <div className="gnum">{ungraded}</div>
          </div>
        </div>
        <div className="gnote">
          Grading never uses win rate alone: a strategy must be profitable after costs,
          have a profit factor above 1, and <strong>survive out-of-sample</strong> on a
          chronological split. Failing out-of-sample caps it at grade 2 and it is named as
          likely overfit.
        </div>
      </GlassPanel>

      <div className="tabs">
        {(["library", "recipes", "paper", "signals"] as const).map((t) => (
          <button key={t} className={`tab ${tab === t ? "on" : ""}`} onClick={() => setTab(t)}>
            {t === "library" ? "Strategy Library" : t === "recipes" ? "The 69 Hypotheses"
              : t === "paper" ? "Paper Positions" : "Signal Feed"}
          </button>
        ))}
      </div>

      {tab === "library" && (
        <GlassPanel title="Strategy library" note={`${rows.length} shown · click a row for its rules and backtest`}>
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
              <span className="flabel">Grade</span>
              <button className={`chip ${grade === "ALL" ? "on" : ""}`} onClick={() => setGrade("ALL")}>All</button>
              {[5, 4, 3, 2, 1, 0].map((g) => (
                <button key={g} className={`chip ${grade === g ? "on" : ""}`} onClick={() => setGrade(g)}>
                  {g === 0 ? "ungraded" : g}
                </button>
              ))}
            </div>
          </div>

          {!rows.length ? (
            <EmptyState title="No strategies match this filter" note="Clear a filter, or run the backtest to grade the library." />
          ) : (
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th className="l">ID</th><th className="l">Strategy</th><th className="l">Family</th>
                    <th>TF</th><th>HTF</th><th>R:R</th><th>Trades</th><th>Win %</th><th>PF</th>
                    <th>Avg R</th><th>CAGR</th><th>Max DD</th><th>OOS net</th><th>Grade</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.slice(0, 250).map((r) => (
                    <Fragment key={r.strategy_id}>
                      <tr className={`row g${r.grade}`} onClick={() => openDetail(r.strategy_id)}>
                        <td className="l dim">{r.strategy_id}</td>
                        <td className="l sname">{r.name}{r.open_positions > 0 && <span className="dot" />}</td>
                        <td className="l"><span className="cat">{r.sub_family}</span></td>
                        <td>{r.timeframe}</td>
                        <td className="dim">{r.htf ?? "-"}</td>
                        <td>1:{num(r.target_r, 1)}</td>
                        <td>{r.bt_trades}</td>
                        <td>{r.bt_trades ? `${(r.bt_win_rate * 100).toFixed(0)}%` : "-"}</td>
                        <td>{r.bt_profit_factor === null ? "-" : num(r.bt_profit_factor)}</td>
                        <td className={r.bt_avg_r >= 0 ? "gain" : "loss"}>{r.bt_trades ? num(r.bt_avg_r) : "-"}</td>
                        <td>{r.bt_cagr_pct === null ? "-" : `${num(r.bt_cagr_pct, 1)}%`}</td>
                        <td>{r.bt_trades ? `${num(r.bt_max_dd_pct, 1)}%` : "-"}</td>
                        <td className={r.oos_net_pnl >= 0 ? "gain" : "loss"}>{r.oos_trades ? signed(r.oos_net_pnl) : "-"}</td>
                        <td><StatusPill label={r.grade ? `G${r.grade}` : "—"} tone={GRADE_TONE[r.grade]} /></td>
                      </tr>
                      {detail?.strategy?.strategy_id === r.strategy_id && (
                        <tr className="expand">
                          <td colSpan={14}><Detail d={detail} row={r} /></td>
                        </tr>
                      )}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </GlassPanel>
      )}

      {tab === "recipes" && (
        <GlassPanel title="The 69 hypotheses" note="each runs on 8 timeframes with parameters scaled to the bar size">
          <div className="recipes">
            {recipes.map((r) => (
              <div className="recipe" key={r.key}>
                <div className="rhead">
                  <span className="rname">{r.name}</span>
                  <span className="cat">{r.family}</span>
                  <span className="rr">1:{r.target_r}</span>
                </div>
                <div className="rhyp">{r.hypothesis}</div>
                <div className="rmeta">
                  confirmations: {r.confirmations.join(", ") || "none"} · regimes:{" "}
                  {r.regimes.join(", ")}
                  {r.uses_htf ? " · multi-timeframe" : ""}
                  {r.intraday_only ? " · intraday only" : ""}
                </div>
              </div>
            ))}
          </div>
        </GlassPanel>
      )}

      {tab === "paper" && (
        <GlassPanel title={`Open paper positions (${positions.length})`} note="₹10,00,000 per strategy, 1% risk per trade">
          {!positions.length ? (
            <EmptyState title="No open positions"
                        note="Only strategies graded at or above the threshold trade. Run the backtest first." />
          ) : (
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th className="l">Strategy</th><th className="l">Symbol</th><th>TF</th><th>Side</th>
                    <th>Qty</th><th>Entry</th><th>Stop</th><th>Target</th><th>R:R</th>
                    <th>Risk</th><th>Unrealised</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((p) => (
                    <tr key={p.position_id}>
                      <td className="l dim">{p.strategy_name}</td>
                      <td className="l sym">{p.symbol}</td>
                      <td>{p.timeframe}</td>
                      <td className={p.side === "BUY" ? "gain" : "loss"}>{p.side}</td>
                      <td>{p.qty}</td>
                      <td>{num(p.entry_price)}</td>
                      <td>{num(p.stoploss)}</td>
                      <td>{num(p.target)}</td>
                      <td>1:{num(p.r_multiple, 1)}</td>
                      <td className="dim">{inr(p.risk_amount)}</td>
                      <td className={p.unrealized_pnl >= 0 ? "gain" : "loss"}>{signed(p.unrealized_pnl)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {trades.length > 0 && (
            <div className="table-scroll" style={{ marginTop: 8 }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th className="l">Closed</th><th className="l">Strategy</th><th className="l">Symbol</th>
                    <th>Side</th><th>Gross</th><th>Costs</th><th>Net</th><th>R</th><th>Why</th>
                  </tr>
                </thead>
                <tbody>
                  {trades.slice(0, 40).map((t) => (
                    <tr key={t.trade_id}>
                      <td className="l dim">{new Date(t.closed_at).toLocaleString("en-IN", { dateStyle: "short", timeStyle: "short" })}</td>
                      <td className="l dim">{t.strategy_name}</td>
                      <td className="l sym">{t.symbol}</td>
                      <td className={t.side === "BUY" ? "gain" : "loss"}>{t.side}</td>
                      <td className={t.gross_pnl >= 0 ? "gain" : "loss"}>{signed(t.gross_pnl)}</td>
                      <td className="loss">-{num(t.costs)}</td>
                      <td className={t.realized_pnl >= 0 ? "gain" : "loss"}>{signed(t.realized_pnl)}</td>
                      <td className={t.r_realised >= 0 ? "gain" : "loss"}>{num(t.r_realised)}</td>
                      <td><span className="cat">{t.exit_reason}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </GlassPanel>
      )}

      {tab === "signals" && (
        <GlassPanel title="Signal feed" note="every field the alert carries">
          {!signals.length ? (
            <EmptyState title="No signals yet" note="Signals appear as graded strategies fire on live bars." />
          ) : (
            <div className="siglist">
              {signals.map((s) => (
                <div className="sig" key={s.signal_id}>
                  <div className="sighead">
                    <span className={`side ${s.side === "BUY" ? "gain" : "loss"}`}>{s.side}</span>
                    <span className="sym">{s.symbol}</span>
                    <span className="cat">{s.timeframe}</span>
                    <span className="cat">{s.pattern}</span>
                    <span className="dim">{new Date(s.created_at).toLocaleString("en-IN")}</span>
                  </div>
                  <div className="sigbody">
                    entry {num(s.entry)} · stop {num(s.stop)} · target {num(s.target)} · R:R 1:
                    {num(s.r_multiple, 1)} · risk {inr(s.risk)} · reward {inr(s.reward)} · qty {s.qty}
                    {" · "}regime {s.regime} · confidence {(s.confidence * 100).toFixed(0)}%
                  </div>
                  <div className="dim small">{(s.confirmations ?? []).join(" · ")}</div>
                </div>
              ))}
            </div>
          )}
        </GlassPanel>
      )}

      {summary?.last_notes && summary.last_notes.length > 0 && (
        <GlassPanel title="Last cycle">
          <ul className="notes">{summary.last_notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
        </GlassPanel>
      )}

      <style jsx>{`
        .page { display: flex; flex-direction: column; gap: 16px; }
        .btn { padding: 7px 14px; border-radius: 9px; font-size: 12.5px; font-weight: 600; cursor: pointer;
               border: 1px solid var(--panel-border); background: var(--panel); color: var(--text); }
        .btn:disabled { opacity: .55; cursor: default; }
        .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }
        .grades { display: flex; flex-wrap: wrap; gap: 18px; padding: 16px 20px 6px; }
        .gcell { display: flex; flex-direction: column; align-items: center; gap: 6px; }
        .gnum { font-family: var(--font-data); font-size: 20px; font-weight: 700; }
        .gnote { padding: 0 20px 16px; font-size: 11.5px; color: var(--text-muted); max-width: 900px; }
        .tabs { display: flex; gap: 6px; flex-wrap: wrap; }
        .tab { padding: 7px 14px; border-radius: 100px; font-size: 12.5px; font-weight: 600; cursor: pointer;
               border: 1px solid var(--panel-border); background: var(--panel); color: var(--text-muted); }
        .tab.on { background: var(--purple-dim); border-color: rgba(125,52,220,.24); color: var(--purple); }
        .filters { padding: 14px 20px 4px; display: flex; flex-direction: column; gap: 8px; }
        .frow { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
        .flabel { font-size: 10px; font-weight: 800; letter-spacing: .05em; text-transform: uppercase;
                  color: var(--text-muted); min-width: 70px; }
        .chip { font-size: 11.5px; font-weight: 600; padding: 4px 10px; border-radius: 100px; cursor: pointer;
                border: 1px solid var(--panel-border); background: var(--panel); color: var(--text-muted); }
        .chip.on { background: var(--purple-dim); border-color: rgba(125,52,220,.24); color: var(--purple); }
        .table-scroll { overflow-x: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; white-space: nowrap; }
        .data-table th { text-align: center; padding: 8px 9px; font-size: 9.5px; font-weight: 700; letter-spacing: .04em;
                         text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); }
        .data-table td { padding: 8px 9px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .data-table th.l, .data-table td.l { text-align: left; }
        .row { cursor: pointer; }
        .row:hover { background: var(--canvas-soft); }
        .row.g5 { background: rgba(14,159,110,.07); }
        .row.g4 { background: rgba(14,159,110,.035); }
        .sname { font-weight: 600; }
        .sym { font-weight: 700; }
        .dim { color: var(--text-muted); }
        .small { font-size: 11px; }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
        .cat { font-size: 9.5px; font-weight: 700; padding: 2px 7px; border-radius: 6px;
               background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); }
        .dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: var(--gain); margin-left: 6px; }
        .expand td { background: var(--canvas-soft); white-space: normal; text-align: left; }
        .recipes { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 12px; padding: 16px 20px; }
        .recipe { border: 1px solid var(--panel-border); border-radius: 10px; padding: 12px 14px; background: var(--panel); }
        .rhead { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
        .rname { font-size: 13px; font-weight: 700; }
        .rr { margin-left: auto; font-family: var(--font-data); font-size: 11.5px; color: var(--purple); font-weight: 700; }
        .rhyp { margin-top: 6px; font-size: 12px; color: var(--text); line-height: 1.4; }
        .rmeta { margin-top: 6px; font-size: 11px; color: var(--text-faint); }
        .siglist { display: flex; flex-direction: column; gap: 8px; padding: 16px 20px; }
        .sig { border: 1px solid var(--panel-border); border-radius: 10px; padding: 10px 12px; background: var(--panel); }
        .sighead { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; font-size: 12px; }
        .side { font-weight: 800; font-size: 10.5px; }
        .sigbody { margin-top: 5px; font-size: 12px; font-variant-numeric: tabular-nums; color: var(--text); }
        .notes { margin: 0; padding: 14px 20px 16px 38px; }
        .notes li { font-size: 12.5px; color: var(--text-muted); margin: 4px 0; }
      `}</style>
    </div>
  );
}

function Detail({ d, row }: { d: any; row: SFRow }) {
  const s = d?.strategy;
  if (!s) return null;
  return (
    <div className="det">
      <div className="dhyp"><strong>Hypothesis.</strong> {s.hypothesis}</div>
      <div className="dgrid">
        <div>
          <div className="k">Rules</div>
          <div className="v">Setup: <b>{s.detector}</b></div>
          <div className="v">Confirmations: {s.confirmations.length
            ? s.confirmations.map((c: any) => c.name).join(", ") : "none"}</div>
          <div className="v">Regimes: {s.regimes.length ? s.regimes.join(", ") : "any"}</div>
          <div className="v">Stop: structural, clamped to 0.35–6 ATR</div>
          <div className="v">Target: {s.target_r}R (or the pattern's measured move)</div>
          <div className="v">Entry timeframe {s.timeframe}{s.htf ? `, confirmed on ${s.htf}` : ""}</div>
        </div>
        <div>
          <div className="k">Grade {row.grade || "—"}</div>
          {(row.grade_reasons ?? []).map((r, i) => <div className="v" key={i}>{r}</div>)}
          {row.best_symbol && <div className="v dim">best on {row.best_symbol}</div>}
        </div>
        <div>
          <div className="k">Backtest</div>
          <div className="v">{row.bt_trades} trades · PF {row.bt_profit_factor ?? "-"} · avg R {num(row.bt_avg_r)}</div>
          <div className="v">net {signed(row.bt_net_pnl)} · DD {num(row.bt_max_dd_pct, 1)}%</div>
          <div className="v">Sharpe {row.bt_sharpe ?? "-"} · CAGR {row.bt_cagr_pct ?? "-"}%</div>
          <div className="v">out-of-sample: {row.oos_trades} trades, {signed(row.oos_net_pnl)}</div>
        </div>
      </div>
      {(d.backtests ?? []).length > 1 && (
        <div className="persym">
          <div className="k">Per symbol</div>
          {d.backtests.map((b: any) => (
            <span className="chipx" key={b.symbol}>
              {b.symbol}: G{b.grade} · {b.overall?.trades ?? 0}t · PF {b.overall?.profit_factor ?? "-"}
            </span>
          ))}
        </div>
      )}
      <style jsx>{`
        .det { padding: 12px 4px; }
        .dhyp { font-size: 12.5px; margin-bottom: 10px; }
        .dgrid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 14px; }
        .k { font-size: 10px; font-weight: 800; letter-spacing: .05em; text-transform: uppercase;
             color: var(--text-muted); margin-bottom: 5px; }
        .v { font-size: 12px; margin: 2px 0; }
        .v.dim { color: var(--text-muted); }
        .persym { margin-top: 12px; }
        .chipx { display: inline-block; font-size: 11px; padding: 3px 8px; border-radius: 6px; margin: 3px 4px 0 0;
                 background: var(--panel); border: 1px solid var(--panel-border); }
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
