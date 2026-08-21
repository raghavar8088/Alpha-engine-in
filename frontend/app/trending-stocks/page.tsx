"use client";

import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import PageHeader from "../../components/PageHeader";
import GlassPanel from "../../components/GlassPanel";
import StatusPill from "../../components/StatusPill";
import ErrorBanner from "../../components/ErrorBanner";
import EmptyState from "../../components/EmptyState";
import DeskHistory from "../../components/DeskHistory";
import {
  TSBasketRow,
  TSLibraryRow,
  TSPosition,
  TSRejections,
  TSSignal,
  TSSummary,
  addTSSymbol,
  backfillTSBars,
  fetchTSBasket,
  fetchTSLibrary,
  fetchTSPositions,
  fetchTSRecipes,
  fetchTSRejections,
  fetchTSResearch,
  fetchTSSignals,
  fetchTSStrategy,
  fetchTSSummary,
  releaseTSSymbol,
  removeTSSymbol,
  runTSBacktest,
  runTSCycle,
  runTSValidation,
  setTSBasket,
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
const STYLES = ["scalp", "intraday", "swing", "positional"];
const GRADE_TONE: Record<number, "gain" | "loss" | "muted" | "accent" | "warn"> = {
  5: "gain", 4: "gain", 3: "accent", 2: "warn", 1: "loss", 0: "loss",
};
const PILLAR_LABEL: Record<string, string> = {
  volume: "Volume", momentum: "Momentum", news: "News", price_action: "Price action",
  pattern: "Chart pattern", regime: "Market regime", liquidity: "Liquidity",
};

const inr = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
const signed = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
const num = (v: number | null | undefined, dp = 2) =>
  v === null || v === undefined ? "—" : v.toFixed(dp);
const crore = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `₹${(v / 1e7).toLocaleString("en-IN", { maximumFractionDigits: 1 })} cr`;

type Tab = "basket" | "signals" | "positions" | "notrade" | "library" | "recipes" | "history";

export default function TrendingStocksPage() {
  const [summary, setSummary] = useState<TSSummary | null>(null);
  const [basket, setBasket] = useState<TSBasketRow[]>([]);
  const [rows, setRows] = useState<TSLibraryRow[]>([]);
  const [open, setOpen] = useState<TSPosition[]>([]);
  const [closed, setClosed] = useState<TSPosition[]>([]);
  const [signals, setSignals] = useState<TSSignal[]>([]);
  const [rejections, setRejections] = useState<TSRejections | null>(null);
  const [recipes, setRecipes] = useState<any>(null);
  const [detail, setDetail] = useState<any>(null);
  const [research, setResearch] = useState<any>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("basket");
  const [draft, setDraft] = useState("");
  const [family, setFamily] = useState("ALL");
  const [timeframe, setTimeframe] = useState("ALL");
  const [style, setStyle] = useState("ALL");
  const [grade, setGrade] = useState<number | "ALL">("ALL");

  const load = useCallback(async () => {
    try {
      const [s, b, lib, pos, sg, rj] = await Promise.all([
        fetchTSSummary(),
        fetchTSBasket(),
        fetchTSLibrary({
          family: family === "ALL" ? undefined : family,
          timeframe: timeframe === "ALL" ? undefined : timeframe,
          style: style === "ALL" ? undefined : style,
          grade: grade === "ALL" ? undefined : grade,
        }),
        fetchTSPositions(),
        fetchTSSignals(120),
        fetchTSRejections(20),
      ]);
      setSummary(s);
      setBasket(b.basket ?? []);
      setRows(lib.library ?? []);
      setOpen(pos.open ?? []);
      setClosed(pos.closed ?? []);
      setSignals(sg);
      setRejections(rj);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load Trending Stocks");
    }
  }, [family, timeframe, style, grade]);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  useEffect(() => {
    if (tab === "recipes" && !recipes) {
      fetchTSRecipes().then(setRecipes).catch(() => {});
    }
  }, [tab, recipes]);

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
      setDetail(await fetchTSStrategy(id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load the strategy");
    }
  };

  const openResearch = async (symbol: string) => {
    if (research?.symbol === symbol) return setResearch(null);
    setResearch({ symbol, loading: true });
    try {
      setResearch(await fetchTSResearch(symbol));
    } catch (e) {
      setResearch({ symbol, error: e instanceof Error ? e.message : "failed" });
    }
  };

  const graded = summary?.grade_counts ?? {};
  const ungraded = (summary?.strategy_count ?? 0) -
    Object.values(graded).reduce((a, b) => a + b, 0);
  const activeBasket = basket.filter((b) => b.status === "ACTIVE");
  const quarantined = basket.filter((b) => b.status === "QUARANTINED");
  const rejectionTotal = useMemo(
    () => Object.values(rejections?.totals ?? {}).reduce((a, b) => a + b, 0),
    [rejections],
  );

  return (
    <div className="page">
      <PageHeader
        crumb="Trending Stocks"
        title="Trending Stocks"
        subtitle={
          <>
            <strong>You name the stocks; the desk trades only those, and only long.</strong>{" "}
            {summary?.strategy_count ?? 678} long-only strategies — chart patterns,
            candlesticks, price structure, indicators and multi-condition hybrids across
            all 8 timeframes — each with its own <strong>₹10,00,000</strong> paper account.
            A strategy firing is not enough: the setup must support a{" "}
            <strong>1:{summary?.gate?.min_rr ?? 6} target that the market structure can
            actually reach</strong>, and at least {summary?.gate?.min_pillars ?? 5} of 7
            research pillars — volume, momentum, news, price action, pattern, regime,
            liquidity — must support it with no veto. Every position carries the sentences
            that justified it.
          </>
        }
        actions={
          <>
            <StatusPill label="Long only · paper · costs charged" tone="accent" />
            {summary?.breaker_tripped && <StatusPill label="BREAKER TRIPPED" tone="loss" />}
            <button className="btn" onClick={() => act("bt", runTSBacktest)} disabled={!!busy}>
              {busy === "bt" ? "Started…" : "Run backtest"}
            </button>
            <button className="btn" onClick={() => act("val", runTSValidation)} disabled={!!busy}>
              {busy === "val" ? "Started…" : "Walk-forward + MC"}
            </button>
            <button className="btn" onClick={() => act("run", runTSCycle)} disabled={!!busy}>
              {busy === "run" ? "Running…" : "Run cycle"}
            </button>
          </>
        }
      />

      {error && <ErrorBanner message={error} onRetry={load} />}

      <div className="tiles">
        <Tile label="Basket" value={String(activeBasket.length)}
              sub={activeBasket.map((b) => b.symbol).slice(0, 6).join(" · ") || "no stocks named yet"} />
        <Tile label="Strategies" value={String(summary?.strategy_count ?? 0)}
              sub={`long only · ${Object.entries(summary?.family_counts ?? {}).map(([k, v]) => `${k} ${v}`).join(" · ")}`} />
        <Tile label="Book" value={inr(summary?.initial_capital)}
              sub={`₹10L × ${summary?.strategy_count ?? 0} independent accounts`} />
        <Tile label="Realised (net of costs)" value={signed(summary?.realized_pnl)}
              tone={(summary?.realized_pnl ?? 0) >= 0 ? "gain" : "loss"}
              sub={`${summary?.closed_positions ?? 0} closed · ${inr(summary?.total_costs)} paid in charges`} />
        <Tile label="Open" value={String(summary?.open_positions ?? 0)}
              sub={`${inr(summary?.deployed_capital)} deployed`} />
        <Tile label="Failed 1:6" value={String(summary?.failed_1_6_rr ?? 0)}
              tone="loss" sub="never produced a reachable 6R setup" />
      </div>

      {!!summary?.last_notes?.length && (
        <GlassPanel title="Last cycle" note={summary.last_run_at ? new Date(summary.last_run_at).toLocaleString("en-IN") : ""}>
          <ul className="notes">
            {summary.last_notes.map((n, i) => <li key={i}>{n}</li>)}
            {summary.breaker_tripped && summary.breaker_reasons.map((n, i) => (
              <li key={`b${i}`} className="loss">Breaker: {n}</li>
            ))}
          </ul>
        </GlassPanel>
      )}

      <div className="tabs">
        {([
          ["basket", `Basket (${activeBasket.length})`],
          ["signals", `Signals (${signals.length})`],
          ["positions", `Positions (${open.length} open)`],
          ["notrade", `No-Trade (${rejectionTotal.toLocaleString("en-IN")})`],
          ["library", "Strategy Library"],
          ["recipes", "The 86 Hypotheses"],
          ["history", "History"],
        ] as [Tab, string][]).map(([t, label]) => (
          <button key={t} className={`tab ${tab === t ? "on" : ""}`} onClick={() => setTab(t)}>
            {label}
          </button>
        ))}
      </div>

      {/* ---------------------------------------------------------------- BASKET */}
      {tab === "basket" && (
        <>
          <GlassPanel
            title="Name the stocks"
            note="one per line, or comma separated — the desk trades nothing else"
          >
            <div className="basketform">
              <textarea
                className="ta"
                rows={4}
                placeholder={"RELIANCE\nTITAN\nBAJFINANCE"}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
              />
              <div className="bactions">
                <button
                  className="btn primary"
                  disabled={!!busy || !draft.trim()}
                  onClick={() => act("add", async () => {
                    const tokens = draft.split(/[\n, ]+/).map((t) => t.trim()).filter(Boolean);
                    if (tokens.length === 1) await addTSSymbol(tokens[0]);
                    else await setTSBasket(draft);
                    setDraft("");
                  })}
                >
                  {busy === "add" ? "Adding…" : "Add to basket"}
                </button>
                <button
                  className="btn"
                  disabled={!!busy || !draft.trim()}
                  onClick={() => act("replace", async () => { await setTSBasket(draft); setDraft(""); })}
                >
                  Replace whole basket
                </button>
                <button className="btn" disabled={!!busy} onClick={() => act("bf", () => backfillTSBars(true))}>
                  {busy === "bf" ? "Backfilling…" : "Re-backfill bars"}
                </button>
              </div>
            </div>
            <div className="gnote">
              Adding a stock kicks off a backfill of its 1m / 5m / 15m / 1h / 1d candles from
              Angel One. That endpoint is rate-limited hard, so requests are paced at one
              every 3 seconds — coverage fills in over the next few minutes rather than
              instantly. 30m, 45m and 4h are <strong>resampled</strong> from those on the NSE
              09:15 anchor, because Angel serves no such intervals.
            </div>
          </GlassPanel>

          {!!quarantined.length && (
            <GlassPanel title="Quarantined" note="live quote disagrees with the stored bars">
              {quarantined.map((q) => (
                <div className="qrow" key={q.symbol}>
                  <div><b>{q.symbol}</b> — {q.quarantine_reason}</div>
                  <button className="btn small" disabled={!!busy}
                          onClick={() => act("rel", () => releaseTSSymbol(q.symbol))}>
                    Release
                  </button>
                </div>
              ))}
              <div className="gnote">
                The strategies read BARS and the desk fills at the LIVE price, so those two
                must describe the same instrument. An unadjusted bonus or split — routine on
                NSE — halves the price while every momentum statistic still reads
                &quot;very strong&quot;, and the desk would buy a 1:2 split at a momentum it
                never had.
              </div>
            </GlassPanel>
          )}

          <GlassPanel title="Bar coverage" note="a strategy on a red timeframe is a DATA gap, never a verdict">
            {!basket.length ? (
              <EmptyState title="The basket is empty"
                          note="Add the stocks you want traded. Nothing is scanned until you do." />
            ) : (
              <div className="table-scroll">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th className="l">Symbol</th>
                      {TIMEFRAMES.map((t) => <th key={t}>{t}</th>)}
                      <th>Open</th><th className="l">Status</th><th className="l" />
                    </tr>
                  </thead>
                  <tbody>
                    {basket.map((b) => (
                      <Fragment key={b.symbol}>
                        <tr className="row" onClick={() => openResearch(b.symbol)}>
                          <td className="l sym">{b.symbol}<div className="small dim">{b.name}</div></td>
                          {TIMEFRAMES.map((t) => {
                            const c = b.coverage?.[t];
                            const n = c?.bars ?? 0;
                            const tone = n >= 400 ? "ok" : n >= 120 ? "warn" : "bad";
                            return (
                              <td key={t} className={`cov ${tone}`}>
                                {n.toLocaleString("en-IN")}
                                {c && !c.native && <div className="small dim">from {c.derived_from}</div>}
                              </td>
                            );
                          })}
                          <td>{b.open_positions || "—"}</td>
                          <td className="l">
                            <StatusPill
                              label={b.status}
                              tone={b.status === "ACTIVE" ? "gain" : b.status === "QUARANTINED" ? "warn" : "muted"}
                            />
                          </td>
                          <td className="l">
                            <button
                              className="btn small"
                              onClick={(e) => { e.stopPropagation(); act("rm", () => removeTSSymbol(b.symbol)); }}
                            >
                              Remove
                            </button>
                          </td>
                        </tr>
                        {research?.symbol === b.symbol && (
                          <tr className="expand">
                            <td colSpan={TIMEFRAMES.length + 4}>
                              <ResearchCard r={research} />
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <div className="gnote">
              Removing a stock stops NEW entries on it. Any open position is still managed to
              its stop, target or square-off — a desk that stopped managing a book because a
              row was deleted would leave real risk untracked.
            </div>
          </GlassPanel>
        </>
      )}

      {/* --------------------------------------------------------------- SIGNALS */}
      {tab === "signals" && (
        <GlassPanel title="Signal feed" note="every signal that became a position, with the reason it was taken">
          {!signals.length ? (
            <EmptyState title="No signals yet"
                        note="Signals are only recorded when a setup clears the 1:6 gate AND the research gate. Check the No-Trade tab to see what was declined." />
          ) : (
            <div className="siglist">
              {signals.map((s) => (
                <div className="sig" key={s.signal_id}>
                  <div className="sighead">
                    <span className="side gain">LONG</span>
                    <b className="sym">{s.symbol}</b>
                    <span className="cat">{s.timeframe}{s.htf ? ` · HTF ${s.htf}` : ""}</span>
                    <span className="dim">{s.strategy_name}</span>
                    <span className="cat">{s.pattern}</span>
                    <span className="rr">1:{num(s.r_multiple, 1)}</span>
                    <span className="dim small">
                      {s.created_at ? new Date(s.created_at).toLocaleString("en-IN") : ""}
                    </span>
                  </div>
                  <div className="sigbody">
                    Entry {num(s.entry)} · Stop {num(s.stop)} · Target {num(s.target)} ·{" "}
                    Qty {s.qty} · Risk {inr(s.risk)} · Reward {inr(s.reward)} ·{" "}
                    regime {s.regime} · confidence {num(s.confidence * 100, 0)}% ·{" "}
                    {s.pillars_supporting}/7 pillars
                  </div>
                  <ul className="reasons">
                    {(s.reasons ?? []).map((r, i) => <li key={i}>{r}</li>)}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </GlassPanel>
      )}

      {/* ------------------------------------------------------------- POSITIONS */}
      {tab === "positions" && (
        <>
          <GlassPanel title="Open positions" note="click a row for the full reason and the evidence at entry">
            <PositionTable rows={open} expanded={expanded} setExpanded={setExpanded} live />
          </GlassPanel>
          <GlassPanel title="Closed positions" note="net of brokerage, STT, exchange, SEBI, stamp duty, GST and slippage">
            <PositionTable rows={closed} expanded={expanded} setExpanded={setExpanded} />
          </GlassPanel>
        </>
      )}

      {/* -------------------------------------------------------------- NO TRADE */}
      {tab === "notrade" && (
        <>
          <GlassPanel title="Why the desk did not trade"
                      note={`${rejections?.cycles ?? 0} recent scan cycles`}>
            {!rejections || !Object.keys(rejections.totals).length ? (
              <EmptyState title="Nothing recorded yet" note="Run a cycle to populate the ledger." />
            ) : (
              <div className="table-scroll">
                <table className="data-table">
                  <thead>
                    <tr><th className="l">Stage</th><th>Count</th><th className="l">What it means</th></tr>
                  </thead>
                  <tbody>
                    {Object.entries(rejections.totals).map(([stage, n]) => (
                      <tr key={stage}>
                        <td className="l"><span className="cat">{stage}</span></td>
                        <td><b>{n.toLocaleString("en-IN")}</b></td>
                        <td className="l dim wrap">{rejections.legend[stage] ?? ""}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <div className="gnote">
              &quot;No trades today&quot; and &quot;forty setups all failed the 1:6
              reachability test&quot; look identical from the outside and mean completely
              different things. Counts come from every evaluation; the samples below are the
              interesting subset — the 1:6 failures name the level or the number that blocked
              them.
            </div>
          </GlassPanel>

          {!!rejections?.samples?.length && (
            <GlassPanel title="Sampled rejections" note="the specific reason, in full">
              <div className="siglist">
                {rejections.samples.map((s, i) => (
                  <div className="sig" key={i}>
                    <div className="sighead">
                      <span className="cat">{s.stage}</span>
                      <b className="sym">{s.symbol}</b>
                      <span className="cat">{s.timeframe}</span>
                      <span className="dim">{s.strategy_id}</span>
                    </div>
                    <div className="sigbody">{s.reason}</div>
                    {s.detail && <div className="small dim wrap">{s.detail}</div>}
                  </div>
                ))}
              </div>
            </GlassPanel>
          )}

          {!!Object.keys(rejections?.backtest_rejection_totals ?? {}).length && (
            <GlassPanel title="From the last backtest sweep" note="the same stages, over history rather than today">
              <div className="grades">
                {Object.entries(rejections!.backtest_rejection_totals).map(([k, v]) => (
                  <div className="gcell" key={k}>
                    <StatusPill label={k} tone="muted" />
                    <div className="gnum">{v.toLocaleString("en-IN")}</div>
                  </div>
                ))}
              </div>
            </GlassPanel>
          )}
        </>
      )}

      {/* --------------------------------------------------------------- LIBRARY */}
      {tab === "library" && (
        <>
          <GlassPanel title="Grade distribution" note="grade 5 = production candidate · 0 = structurally ineligible">
            <div className="grades">
              {[5, 4, 3, 2, 1, 0].map((g) => (
                <div className="gcell" key={g}>
                  <StatusPill label={g === 0 ? "FAILED 1:6" : `GRADE ${g}`} tone={GRADE_TONE[g]} />
                  <div className="gnum">{graded[String(g)] ?? 0}</div>
                </div>
              ))}
              <div className="gcell">
                <StatusPill label="NOT BACKTESTED" tone="muted" />
                <div className="gnum">{ungraded}</div>
              </div>
            </div>
            <div className="gnote">
              Grading never uses win rate alone. A strategy must be profitable after real
              costs, have a profit factor above 1, and survive a chronological out-of-sample
              split. Grades 4 and 5 additionally have to hold up across{" "}
              <strong>walk-forward windows</strong>, and grade 5 needs its Monte Carlo 5th
              percentile to finish above its starting capital. A strategy that never produced
              a single reachable 1:6 setup is not graded at all — it is stamped{" "}
              <strong>FAILED — DOES NOT MEET 1:6 RISK/REWARD</strong>, which is a different
              statement from &quot;measured and found wanting&quot;.
            </div>
          </GlassPanel>

          <GlassPanel title="Strategy library" note={`${rows.length} shown · click a row for its rules and evidence`}>
            <div className="filters">
              <FilterRow label="Family" value={family} onChange={setFamily}
                         options={FAMILIES.map((f) => [f.key, f.label])} />
              <FilterRow label="Timeframe" value={timeframe} onChange={setTimeframe}
                         options={TIMEFRAMES.map((t) => [t, t])} />
              <FilterRow label="Style" value={style} onChange={setStyle}
                         options={STYLES.map((s) => [s, s])} />
              <div className="frow">
                <span className="flabel">Grade</span>
                <button className={`chip ${grade === "ALL" ? "on" : ""}`} onClick={() => setGrade("ALL")}>All</button>
                {[5, 4, 3, 2, 1, 0].map((g) => (
                  <button key={g} className={`chip ${grade === g ? "on" : ""}`} onClick={() => setGrade(g)}>
                    {g === 0 ? "failed 1:6" : g}
                  </button>
                ))}
              </div>
            </div>

            {!rows.length ? (
              <EmptyState title="No strategies match this filter"
                          note="Clear a filter, or run the backtest to grade the library." />
            ) : (
              <div className="table-scroll">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th className="l">ID</th><th className="l">Strategy</th><th className="l">Family</th>
                      <th>TF</th><th>Style</th><th>Trades</th><th>Win %</th><th>PF</th>
                      <th>Avg R</th><th>CAGR</th><th>Max DD</th><th>OOS</th><th>WF</th>
                      <th>Grade</th><th className="l">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.slice(0, 250).map((r) => (
                      <Fragment key={r.strategy_id}>
                        <tr className={`row g${r.grade ?? "x"}`} onClick={() => openDetail(r.strategy_id)}>
                          <td className="l dim">{r.strategy_id}</td>
                          <td className="l sname">
                            {r.name}{r.open_positions > 0 && <span className="dot" />}
                          </td>
                          <td className="l"><span className="cat">{r.sub_family}</span></td>
                          <td>{r.timeframe}</td>
                          <td className="dim">{r.style}</td>
                          <td>{r.bt_trades}</td>
                          <td>{r.bt_trades ? `${(r.bt_win_rate * 100).toFixed(0)}%` : "—"}</td>
                          <td>{r.bt_profit_factor ?? "—"}</td>
                          <td>{num(r.bt_avg_r)}</td>
                          <td>{r.bt_cagr_pct === null ? "—" : `${num(r.bt_cagr_pct, 1)}%`}</td>
                          <td>{num(r.bt_max_dd_pct, 1)}%</td>
                          <td className={r.oos_net_pnl >= 0 ? "gain" : "loss"}>{signed(r.oos_net_pnl)}</td>
                          <td>{r.wf_fraction === null || r.wf_fraction === undefined ? "—"
                            : `${(r.wf_fraction * 100).toFixed(0)}%`}</td>
                          <td>
                            <StatusPill
                              label={r.grade === null ? "—" : r.grade === 0 ? "FAILED" : String(r.grade)}
                              tone={GRADE_TONE[r.grade ?? 0] ?? "muted"}
                            />
                          </td>
                          <td className="l dim small">{r.failed_rr ? "no reachable 6R" : r.status ?? "untested"}</td>
                        </tr>
                        {detail?.strategy?.strategy_id === r.strategy_id && (
                          <tr className="expand">
                            <td colSpan={15}><Detail d={detail} row={r} /></td>
                          </tr>
                        )}
                      </Fragment>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </GlassPanel>
        </>
      )}

      {/* --------------------------------------------------------------- RECIPES */}
      {tab === "recipes" && (
        <>
          <GlassPanel title="The hypotheses" note={`${recipes?.count ?? 86} distinct ideas, each run on 8 charts`}>
            <div className="recipes">
              {(recipes?.recipes ?? []).map((r: any) => (
                <div className="recipe" key={r.key}>
                  <div className="rhead">
                    <span className="rname">{r.name}</span>
                    {r.new_here && <span className="cat">new here</span>}
                    <span className="rr">{r.target_r}R</span>
                  </div>
                  <div className="rhyp">{r.hypothesis}</div>
                  <div className="rmeta">
                    {r.family} · {r.sub_family} · detector <b>{r.detector}</b>
                    {r.confirmations.length ? ` · confirmed by ${r.confirmations.join(", ")}` : ""}
                    {r.uses_htf ? " · higher-timeframe filtered" : ""}
                    {r.intraday_only ? " · intraday only" : ""}
                    {" · regimes: "}{(r.regimes ?? []).join(", ")}
                  </div>
                </div>
              ))}
            </div>
          </GlassPanel>
          {!!recipes?.excluded?.length && (
            <GlassPanel title="Deliberately excluded" note="short-only hypotheses have no place on a long-only desk">
              <ul className="notes">
                {recipes.excluded.map((e: any) => <li key={e.key}><b>{e.key}</b> — {e.why}</li>)}
              </ul>
              <div className="gnote">{recipes.note}</div>
            </GlassPanel>
          )}
        </>
      )}

      {tab === "history" && <DeskHistory deskKey="trending-stocks" />}

      <style jsx>{`
        .page { display: flex; flex-direction: column; gap: 18px; }
        .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; }
        .grades { display: flex; flex-wrap: wrap; gap: 18px; padding: 16px 20px 6px; }
        .gcell { display: flex; flex-direction: column; align-items: center; gap: 6px; }
        .gnum { font-family: var(--font-data); font-size: 20px; font-weight: 700; }
        .gnote { padding: 0 20px 16px; font-size: 11.5px; color: var(--text-muted); max-width: 940px; line-height: 1.55; }
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
        .row.g0 { background: rgba(220,38,38,.05); }
        .sname { font-weight: 600; }
        .sym { font-weight: 700; }
        .dim { color: var(--text-muted); }
        .small { font-size: 11px; }
        .wrap { white-space: normal; }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
        .cat { font-size: 9.5px; font-weight: 700; padding: 2px 7px; border-radius: 6px;
               background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); }
        .dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: var(--gain); margin-left: 6px; }
        .expand td { background: var(--canvas-soft); white-space: normal; text-align: left; }
        .cov { font-variant-numeric: tabular-nums; }
        .cov.ok { color: var(--gain); }
        .cov.warn { color: #b45309; }
        .cov.bad { color: var(--loss); }
        .recipes { display: grid; grid-template-columns: repeat(auto-fit, minmax(330px, 1fr)); gap: 12px; padding: 16px 20px; }
        .recipe { border: 1px solid var(--panel-border); border-radius: 10px; padding: 12px 14px; background: var(--panel); }
        .rhead { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
        .rname { font-size: 13px; font-weight: 700; }
        .rr { margin-left: auto; font-family: var(--font-data); font-size: 11.5px; color: var(--purple); font-weight: 700; }
        .rhyp { margin-top: 6px; font-size: 12px; line-height: 1.45; }
        .rmeta { margin-top: 6px; font-size: 11px; color: var(--text-faint); }
        .siglist { display: flex; flex-direction: column; gap: 8px; padding: 16px 20px; }
        .sig { border: 1px solid var(--panel-border); border-radius: 10px; padding: 10px 12px; background: var(--panel); }
        .sighead { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; font-size: 12px; }
        .side { font-weight: 800; font-size: 10.5px; }
        .sigbody { margin-top: 5px; font-size: 12px; font-variant-numeric: tabular-nums; }
        .reasons { margin: 6px 0 0; padding-left: 18px; }
        .reasons li { font-size: 11.5px; color: var(--text-muted); margin: 2px 0; line-height: 1.45; }
        .notes { margin: 0; padding: 14px 20px 16px 38px; }
        .notes li { font-size: 12.5px; color: var(--text-muted); margin: 4px 0; }
        .basketform { padding: 16px 20px 6px; display: flex; flex-direction: column; gap: 10px; }
        .ta { width: 100%; border-radius: 10px; border: 1px solid var(--panel-border); background: var(--panel);
              padding: 10px 12px; font-family: var(--font-data); font-size: 13px; color: var(--text); resize: vertical; }
        .bactions { display: flex; gap: 8px; flex-wrap: wrap; }
        .qrow { display: flex; align-items: center; justify-content: space-between; gap: 12px;
                padding: 8px 20px; font-size: 12px; }
      `}</style>
    </div>
  );
}

function FilterRow({ label, value, onChange, options }: {
  label: string; value: string; onChange: (v: string) => void; options: [string, string][];
}) {
  return (
    <div className="frow">
      <span className="flabel">{label}</span>
      <button className={`chip ${value === "ALL" ? "on" : ""}`} onClick={() => onChange("ALL")}>All</button>
      {options.map(([k, l]) => (
        <button key={k} className={`chip ${value === k ? "on" : ""}`} onClick={() => onChange(k)}>{l}</button>
      ))}
      <style jsx>{`
        .frow { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
        .flabel { font-size: 10px; font-weight: 800; letter-spacing: .05em; text-transform: uppercase;
                  color: var(--text-muted); min-width: 70px; }
        .chip { font-size: 11.5px; font-weight: 600; padding: 4px 10px; border-radius: 100px; cursor: pointer;
                border: 1px solid var(--panel-border); background: var(--panel); color: var(--text-muted); }
        .chip.on { background: var(--purple-dim); border-color: rgba(125,52,220,.24); color: var(--purple); }
      `}</style>
    </div>
  );
}

function PositionTable({ rows, expanded, setExpanded, live }: {
  rows: TSPosition[]; expanded: string | null; setExpanded: (v: string | null) => void; live?: boolean;
}) {
  if (!rows.length) {
    return <EmptyState title={live ? "No open positions" : "Nothing closed yet"}
                       note="Positions only open when a setup clears both the 1:6 gate and the research gate." />;
  }
  return (
    <div className="table-scroll">
      <table className="data-table">
        <thead>
          <tr>
            <th className="l">Symbol</th><th className="l">Strategy</th><th>TF</th>
            <th>Entry</th><th>Stop</th><th>Target</th><th>Qty</th><th>Risk</th>
            <th>R:R</th><th>{live ? "LTP" : "Exit"}</th><th>{live ? "R now" : "Reason"}</th>
            <th>{live ? "Unrealised" : "Realised"}</th><th>Pillars</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((p) => {
            const pnl = live ? p.unrealized_pnl : p.realized_pnl;
            return (
              <Fragment key={p.position_id}>
                <tr className="row" onClick={() => setExpanded(expanded === p.position_id ? null : p.position_id)}>
                  <td className="l sym">{p.symbol}</td>
                  <td className="l sname">{p.strategy_name}<div className="small dim">{p.pattern}</div></td>
                  <td>{p.timeframe}</td>
                  <td>{p.entry_price?.toFixed(2)}</td>
                  <td className="loss">{p.stoploss?.toFixed(2)}</td>
                  <td className="gain">{p.target?.toFixed(2)}</td>
                  <td>{p.qty}</td>
                  <td>{inr(p.risk_amount)}</td>
                  <td>1:{p.r_multiple?.toFixed(1)}</td>
                  <td>{live ? p.ltp?.toFixed(2) : p.exit_price?.toFixed(2)}</td>
                  <td className="dim">{live ? (p.r_now === null || p.r_now === undefined ? "—" : `${p.r_now.toFixed(2)}R`) : p.exit_reason}</td>
                  <td className={(pnl ?? 0) >= 0 ? "gain" : "loss"}>{signed(pnl)}</td>
                  <td>{p.evidence?.supports ?? "—"}/7</td>
                </tr>
                {expanded === p.position_id && (
                  <tr className="expand">
                    <td colSpan={13}><PositionReason p={p} /></td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
      <style jsx>{`
        .table-scroll { overflow-x: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; white-space: nowrap; }
        .data-table th { text-align: center; padding: 8px 9px; font-size: 9.5px; font-weight: 700; letter-spacing: .04em;
                         text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); }
        .data-table td { padding: 8px 9px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .data-table th.l, .data-table td.l { text-align: left; }
        .row { cursor: pointer; }
        .row:hover { background: var(--canvas-soft); }
        .expand td { background: var(--canvas-soft); white-space: normal; text-align: left; }
        .sym { font-weight: 700; }
        .sname { font-weight: 600; }
        .dim { color: var(--text-muted); }
        .small { font-size: 11px; }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
      `}</style>
    </div>
  );
}

/** The reason a position was taken, exactly as it was recorded at entry. */
function PositionReason({ p }: { p: TSPosition }) {
  const f = p.feasibility ?? {};
  const tests = (f.tests ?? {}) as Record<string, any>;
  return (
    <div className="det">
      <div className="k">Why this trade was taken</div>
      <ul className="reasons">
        {(p.reasons ?? []).map((r, i) => <li key={i}>{r}</li>)}
      </ul>
      <div className="dgrid">
        <div>
          <div className="k">Research pillars</div>
          {(p.evidence?.pillars ?? []).map((pl) => (
            <div className="v" key={pl.name}>
              <span className={`vd ${pl.verdict}`}>{pl.verdict}</span>{" "}
              <b>{PILLAR_LABEL[pl.name] ?? pl.name}</b> · {pl.score.toFixed(2)}
            </div>
          ))}
        </div>
        <div>
          <div className="k">The 1:{f.min_rr ?? 6} test</div>
          <div className="v">{f.detail}</div>
          <div className="v dim">stop basis: {f.stop_basis ?? "—"}
            {tests.stop_distance_atr ? ` (${tests.stop_distance_atr} ATR)` : ""}</div>
          <div className="v dim">
            reward {tests.reward ?? "—"} vs volatility budget {tests.vol_budget ?? "—"} over{" "}
            {tests.max_hold_bars ?? "—"} bars
          </div>
          <div className="v dim">
            overhead levels between entry and target: {tests.overhead_count ?? 0}
          </div>
          <div className="v dim">
            cost drag: {tests.cost_pct_of_reward ?? "—"}% of the reward
          </div>
        </div>
        <div>
          <div className="k">Setup</div>
          <div className="v"><b>{p.pattern}</b></div>
          <div className="v">{p.detail}</div>
          {(p.confirmations ?? []).map((c, i) => <div className="v dim" key={i}>{c}</div>)}
          <div className="v dim">regime: {p.regime_primary} · confidence {(p.confidence * 100).toFixed(0)}%</div>
          <div className="v dim">style {p.style} · capital {inr(p.capital_deployed)} of ₹10,00,000</div>
        </div>
      </div>
      {!!p.evidence?.vetoes?.length && (
        <div className="v loss">Vetoes at entry: {p.evidence.vetoes.join(" | ")}</div>
      )}
      <style jsx>{`
        .det { padding: 12px 4px; }
        .dgrid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; margin-top: 10px; }
        .k { font-size: 10px; font-weight: 800; letter-spacing: .05em; text-transform: uppercase;
             color: var(--text-muted); margin-bottom: 5px; }
        .v { font-size: 12px; margin: 3px 0; line-height: 1.45; }
        .v.dim { color: var(--text-muted); }
        .v.loss { color: var(--loss); margin-top: 8px; }
        .reasons { margin: 4px 0 0; padding-left: 18px; }
        .reasons li { font-size: 12.5px; margin: 4px 0; line-height: 1.5; }
        .vd { font-size: 9.5px; font-weight: 800; text-transform: uppercase; padding: 1px 6px;
              border-radius: 5px; background: var(--canvas-soft); border: 1px solid var(--panel-border); }
        .vd.supports { color: var(--gain); }
        .vd.veto { color: var(--loss); }
        .vd.opposes { color: #b45309; }
      `}</style>
    </div>
  );
}

/** Live seven-pillar research for one basket symbol. */
function ResearchCard({ r }: { r: any }) {
  if (r?.loading) return <div className="v dim">Loading research…</div>;
  if (r?.error) return <div className="v loss">{r.error}</div>;
  if (r?.error === undefined && !r?.pillars) return <div className="v dim">No research available.</div>;
  return (
    <div className="det">
      <div className="k">
        {r.symbol} · {r.name ?? ""} · LTP {r.ltp ?? "—"} · {r.supports}/{r.pillars.length} pillars
        support {r.vetoes?.length ? `· ${r.vetoes.length} VETO` : ""}
      </div>
      {r.pillars.map((p: any) => (
        <div className="prow" key={p.name}>
          <span className={`vd ${p.verdict}`}>{p.verdict}</span>
          <b>{PILLAR_LABEL[p.name] ?? p.name}</b>
          <span className="sc">{p.score.toFixed(2)}</span>
          <span className="sent">{p.sentence}</span>
        </div>
      ))}
      <div className="v dim">{r.note}</div>
      <style jsx>{`
        .det { padding: 10px 4px; }
        .k { font-size: 11px; font-weight: 800; letter-spacing: .04em; text-transform: uppercase;
             color: var(--text-muted); margin-bottom: 8px; }
        .prow { display: grid; grid-template-columns: 78px 110px 46px 1fr; gap: 8px; align-items: start;
                font-size: 12px; padding: 4px 0; border-bottom: 1px solid var(--panel-border); }
        .sent { line-height: 1.45; }
        .sc { font-family: var(--font-data); color: var(--text-muted); }
        .v { font-size: 11.5px; margin-top: 8px; }
        .v.dim { color: var(--text-muted); }
        .v.loss { color: var(--loss); }
        .vd { font-size: 9.5px; font-weight: 800; text-transform: uppercase; padding: 1px 6px;
              border-radius: 5px; background: var(--canvas-soft); border: 1px solid var(--panel-border); }
        .vd.supports { color: var(--gain); }
        .vd.veto { color: var(--loss); }
        .vd.opposes { color: #b45309; }
      `}</style>
    </div>
  );
}

function Detail({ d, row }: { d: any; row: TSLibraryRow }) {
  const s = d?.strategy;
  if (!s) return null;
  const wf = d.validation?.[0]?.walk_forward;
  const mc = d.validation?.[0]?.monte_carlo;
  return (
    <div className="det">
      <div className="dhyp"><strong>Hypothesis.</strong> {s.hypothesis}</div>
      <div className="dgrid">
        <div>
          <div className="k">Rules</div>
          <div className="v">Direction: <b>LONG only</b></div>
          <div className="v">Setup: <b>{s.detector}</b></div>
          <div className="v">Confirmations: {s.confirmations.length
            ? s.confirmations.map((c: any) => c.name).join(", ") : "none"}</div>
          <div className="v">Regimes: {s.regimes.length ? s.regimes.join(", ") : "any"}</div>
          <div className="v">Stop: the pattern&apos;s own invalidation, clamped to 0.35–6 ATR</div>
          <div className="v">Target: {s.min_rr}R, only if the structure can reach it</div>
          <div className="v">Entry on {s.timeframe}{s.htf ? `, confirmed on ${s.htf}` : ""}</div>
        </div>
        <div>
          <div className="k">Grade {row.grade === 0 ? "— FAILED 1:6" : row.grade ?? "—"}</div>
          {(row.grade_reasons ?? []).map((r, i) => <div className="v" key={i}>{r}</div>)}
          {row.best_symbol && <div className="v dim">best on {row.best_symbol}</div>}
        </div>
        <div>
          <div className="k">Backtest</div>
          <div className="v">{row.bt_trades} trades · PF {row.bt_profit_factor ?? "—"} · avg R {num(row.bt_avg_r)}</div>
          <div className="v">net {signed(row.bt_net_pnl)} · costs {inr(row.bt_costs)} · DD {num(row.bt_max_dd_pct, 1)}%</div>
          <div className="v">Sharpe {row.bt_sharpe ?? "—"} · CAGR {row.bt_cagr_pct ?? "—"}%</div>
          <div className="v">out-of-sample: {row.oos_trades} trades, {signed(row.oos_net_pnl)}</div>
        </div>
        <div>
          <div className="k">Robustness</div>
          {wf ? (
            <>
              <div className="v">{wf.note}</div>
              {(wf.detail ?? []).map((w: any) => (
                <div className="v dim" key={w.window}>
                  window {w.window}: {w.trades} trades, {signed(w.net_pnl)}
                </div>
              ))}
            </>
          ) : <div className="v dim">Walk-forward not run yet.</div>}
          {mc ? (
            <div className="v">
              Monte Carlo: median finish {inr(mc.median_final)}, 5th percentile{" "}
              {inr(mc.p5_final)}, {(mc.prob_of_ruin * 100).toFixed(1)}% of paths hit
              −{mc.ruin_threshold_pct}%
            </div>
          ) : <div className="v dim">Monte Carlo not run yet.</div>}
        </div>
      </div>
      {(d.backtests ?? []).length > 1 && (
        <div className="persym">
          <div className="k">Per symbol</div>
          {d.backtests.map((b: any) => (
            <span className="chipx" key={b.symbol}>
              {b.symbol}: G{b.grade} · {b.overall?.trades ?? 0}t · PF {b.overall?.profit_factor ?? "—"}
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
        .v { font-size: 12px; margin: 2px 0; line-height: 1.45; }
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
