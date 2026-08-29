"use client";

/**
 * Stock Screener — momentum, sector rotation, chart patterns and tradable setups.
 *
 * The five tabs answer five different questions and are deliberately not merged:
 *   Momentum  which stocks are strongest today / this week / this month / this half-year
 *   Sectors   where money is rotating, and which stocks inside a sector are driving it
 *   Patterns  which charts have formed a shape, on daily and weekly candles
 *   Setups    what is actually tradable right now, priced net of real Angel One costs
 *   Chartink  a delayed SECOND OPINION from outside — labelled as such, never mixed in
 *   Analysis  ask about NAMED stocks, rather than waiting for a screen to surface them
 *   Sweep     every stock at an all-time high, with an account of what the nets missed
 *   Sources   which feeds answered — so a data outage never reads as a quiet market
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import PageHeader from "../../components/PageHeader";
import GlassPanel from "../../components/GlassPanel";
import ErrorBanner from "../../components/ErrorBanner";
import EmptyState from "../../components/EmptyState";
import StatusPill from "../../components/StatusPill";
import Skeleton from "../../components/Skeleton";
import RankedBars, { RankedBarRow } from "../../components/charts/RankedBars";
import Sparkline from "../../components/Sparkline";
import SectorSpread from "../../components/charts/SectorSpread";
import ChartinkPanel from "../../components/ChartinkPanel";
import StockAnalysis from "../../components/StockAnalysis";
import AnalysedStocks from "../../components/AnalysedStocks";
import {
  refreshing,
  fetchScreenerConfig, fetchScreenerSummary, fetchScreenerMomentum,
  fetchScreenerDetail, fetchScreenerSectors, fetchScreenerSectorDetail,
  fetchScreenerPatterns, fetchScreenerSetups, fetchScreenerSources, refreshScreener,
  ScreenerConfig, ScreenerSummary, ScreenerMomentumBoard, ScreenerMomentumRow,
  ScreenerDetail, ScreenerSectorBoard, ScreenerSectorDetail, ScreenerPatternBoard,
  ScreenerSetupBoard, ScreenerSources,
  fetchScreenerVolume, fetchScreenerPaperSummary, fetchScreenerPaperPositions,
  runScreenerPaperCycle,
  ScreenerVolumeBoard, ScreenerPaperSummary, ScreenerPaperPositions,
} from "../../lib/api";

type Tab = "momentum" | "sectors" | "volume" | "patterns" | "setups" | "paper" | "chartink" | "analysis" | "athsweep" | "sources";
const TABS: { key: Tab; label: string }[] = [
  { key: "momentum", label: "Momentum" },
  { key: "sectors", label: "Sectors" },
  { key: "volume", label: "Volume" },
  { key: "patterns", label: "Chart Patterns" },
  { key: "setups", label: "Setups" },
  { key: "paper", label: "Paper Desk" },
  { key: "chartink", label: "Chartink" },
  { key: "analysis", label: "Stock Analysis" },
  { key: "athsweep", label: "Analysed Stocks" },
  { key: "sources", label: "Sources" },
];

/** Colour + fill for the five price-volume states.
 *
 * Deliberately THREE hues, not five. Five categorical hues cannot be made
 * colourblind-safe alongside a fixed gain-green and loss-red — every warm hue collapses
 * onto red under deuteranopia (measured: amber vs red is ΔE 3.9, well under the ΔE 8
 * target). These states are not five competing identities anyway; they are two polarities
 * with a confirmed/unconfirmed second dimension, so that dimension is carried by FILL vs
 * OUTLINE and the hue count drops to three, which does validate. Every state also ships
 * its text label, so colour is never load-bearing on its own. */
const VOLUME_STATE_STYLE: Record<string, { tone: string; filled: boolean }> = {
  accumulation: { tone: "gain", filled: true },
  weak_rally: { tone: "gain", filled: false },
  distribution: { tone: "loss", filled: true },
  selling_dried: { tone: "loss", filled: false },
  churn: { tone: "accent", filled: true },
  unknown: { tone: "muted", filled: false },
};

const REFRESH_MS = 60000;

const pct = (v: number | null | undefined, dp = 2) =>
  v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(dp)}%`;
const num = (v: number | null | undefined, dp = 2) =>
  v === null || v === undefined ? "—" : v.toLocaleString("en-IN", { maximumFractionDigits: dp });
const money = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
const cls = (v: number | null | undefined) =>
  v === null || v === undefined ? "" : v > 0 ? "gain" : v < 0 ? "loss" : "";

/** Pretty name for a paper-desk family, falling back to the raw key if config has not
 *  arrived yet — the table must render before /config resolves. */
function familyLabel(cfg: ScreenerConfig | null, key: string): string {
  return cfg?.paper_families.find((f) => f.key === key)?.label
    ?? key.replace("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

const ROTATION_TONE: Record<string, "gain" | "loss" | "warn" | "accent" | "muted"> = {
  leading: "gain", improving: "accent", weakening: "warn", lagging: "loss", unknown: "muted",
};

export default function StockScreenerPage() {
  const [cfg, setCfg] = useState<ScreenerConfig | null>(null);
  const [index, setIndex] = useState<string>("");
  const [tab, setTab] = useState<Tab>("momentum");
  const [horizon, setHorizon] = useState("1d");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const [summary, setSummary] = useState<ScreenerSummary | null>(null);
  const [board, setBoard] = useState<ScreenerMomentumBoard | null>(null);
  const [sectors, setSectors] = useState<ScreenerSectorBoard | null>(null);
  const [sectorDetail, setSectorDetail] = useState<ScreenerSectorDetail | null>(null);
  const [patterns, setPatterns] = useState<ScreenerPatternBoard | null>(null);
  const [setups, setSetups] = useState<ScreenerSetupBoard | null>(null);
  const [sources, setSources] = useState<ScreenerSources | null>(null);
  const [detail, setDetail] = useState<ScreenerDetail | null>(null);
  const [detailFor, setDetailFor] = useState<string | null>(null);
  const [volume, setVolume] = useState<ScreenerVolumeBoard | null>(null);
  const [paper, setPaper] = useState<ScreenerPaperSummary | null>(null);
  const [paperPos, setPaperPos] = useState<ScreenerPaperPositions | null>(null);
  const [volWindow, setVolWindow] = useState("1d");
  const [volState, setVolState] = useState("");
  const [paperView, setPaperView] = useState<"OPEN" | "CLOSED">("OPEN");
  const [paperFamily, setPaperFamily] = useState("");
  const [sectorHorizon, setSectorHorizon] = useState("1m");
  const sectorPanelRef = useRef<HTMLDivElement | null>(null);
  // Which sector we have already scrolled to. Without this the panel would yank the page
  // back to itself every time the horizon buttons inside it re-fetch, which is jarring
  // when you are already looking at it.
  const scrolledFor = useRef<string | null>(null);

  const [filter, setFilter] = useState("");
  const [sectorFilter, setSectorFilter] = useState("");
  const [patTimeframe, setPatTimeframe] = useState("1d");
  const [patState, setPatState] = useState("");
  const [patFamily, setPatFamily] = useState("chart");
  const [patDirection, setPatDirection] = useState("bullish");
  const [setupKind, setSetupKind] = useState("intraday");

  // ── config, once ──────────────────────────────────────────────────────────
  useEffect(() => {
    fetchScreenerConfig()
      .then((c) => { setCfg(c); setIndex(c.default_index); })
      .catch((e) => setError(e.message));
  }, []);

  // ── per-tab loaders ───────────────────────────────────────────────────────
  const load = useCallback(async () => {
    if (!index) return;
    setBusy(true);
    try {
      const jobs: Promise<unknown>[] = [
        fetchScreenerSummary(index).then(setSummary),
      ];
      if (tab === "momentum") {
        jobs.push(fetchScreenerMomentum(horizon, index, sectorFilter || undefined, 200).then(setBoard));
      } else if (tab === "sectors") {
        jobs.push(fetchScreenerSectors(index).then(setSectors));
      } else if (tab === "patterns") {
        jobs.push(fetchScreenerPatterns({
          index, timeframe: patTimeframe, state: patState || undefined,
          family: patFamily || undefined, direction: patDirection || undefined, limit: 400,
        }).then(setPatterns));
      } else if (tab === "setups") {
        jobs.push(fetchScreenerSetups(setupKind, index, 60).then(setSetups));
      } else if (tab === "volume") {
        jobs.push(fetchScreenerVolume(volWindow, index, volState || undefined, 120).then(setVolume));
      } else if (tab === "paper") {
        jobs.push(fetchScreenerPaperSummary().then(setPaper));
        jobs.push(fetchScreenerPaperPositions(paperView, paperFamily || undefined, 200).then(setPaperPos));
      } else if (tab === "sources") {
        jobs.push(fetchScreenerSources(index).then(setSources));
      }
      await Promise.all(jobs);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [index, tab, horizon, sectorFilter, patTimeframe, patState, patFamily, patDirection,
      setupKind, volWindow, volState, paperView, paperFamily]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const id = setInterval(() => { load(); }, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  // Bring the drill-down into view when a NEW sector is opened. The panel renders below a
  // long table, so without this a click appeared to do nothing at all.
  useEffect(() => {
    if (!sectorDetail) {
      scrolledFor.current = null;
      return;
    }
    if (scrolledFor.current === sectorDetail.sector) return;
    scrolledFor.current = sectorDetail.sector;
    const reduce = typeof window !== "undefined"
      && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    sectorPanelRef.current?.scrollIntoView({
      behavior: reduce ? "auto" : "smooth",
      block: "start",
    });
  }, [sectorDetail]);

  const handleRefresh = async () => {
    setIsRefreshing(true);
    try { await refreshing(load); } finally { setIsRefreshing(false); }
  };

  const handleHardRefresh = async () => {
    setIsRefreshing(true);
    try { await refreshScreener(index); await refreshing(load); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setIsRefreshing(false); }
  };

  const openDetail = async (symbol: string) => {
    setDetailFor(symbol); setDetail(null);
    try { setDetail(await fetchScreenerDetail(symbol, index)); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); setDetailFor(null); }
  };

  // Takes the horizon explicitly and defaults to the SECTORS tab's own selector, not the
  // Momentum tab's. Reading `horizon` here meant clicking a sector on the "This Month"
  // chart silently opened its "Today" drill-down — the numbers in the panel then had
  // nothing to do with the bar that was clicked.
  const openSector = async (sector: string, forHorizon?: string) => {
    setSectorDetail(null);
    try {
      setSectorDetail(await fetchScreenerSectorDetail(sector, forHorizon ?? sectorHorizon, index));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const rows = useMemo(() => {
    const f = filter.trim().toLowerCase();
    const rs = board?.rows ?? [];
    if (!f) return rs;
    return rs.filter((r) =>
      r.symbol.toLowerCase().includes(f) ||
      (r.name || "").toLowerCase().includes(f) ||
      (r.sector || "").toLowerCase().includes(f));
  }, [board, filter]);

  const sectorNames = useMemo(
    () => Array.from(new Set((sectors?.sectors ?? []).map((s) => s.sector))).sort(),
    [sectors]);

  return (
    <div className="page">
      <PageHeader
        crumb="Stock Screener"
        title="Stock Screener"
        subtitle="Momentum across day, week, month and six months — with why each stock is trending, which sector the money is rotating into, what shapes the daily and weekly charts have formed, and which of it is actually tradable after real Angel One costs."
        onRefresh={handleRefresh}
        refreshing={isRefreshing}
        actions={
          <button className="hard-refresh" onClick={handleHardRefresh} disabled={isRefreshing}
            title="Recompute every horizon, rescan patterns, and re-capture NSE. Slower than Refresh.">
            Recompute all
          </button>
        }
      />

      {/* ── controls ─────────────────────────────────────────────────────── */}
      <div className="controls">
        <div className="index-tabs">
          {(cfg?.indices ?? []).map((ix) => (
            <button key={ix.key} className={index === ix.key ? "tab active" : "tab"}
              onClick={() => setIndex(ix.key)}>{ix.label}</button>
          ))}
        </div>
        <div className="right-controls">
          {summary?.market_open !== null && summary?.market_open !== undefined && (
            <StatusPill label={summary.market_open ? "Market Open" : "Market Closed"}
              tone={summary.market_open ? "gain" : "muted"} pulse={summary.market_open} />
          )}
          {summary && (
            <StatusPill label={summary.quotes_live ? "Live quotes" : "Last close"}
              tone={summary.quotes_live ? "accent" : "warn"} />
          )}
        </div>
      </div>

      {error && <ErrorBanner message={error} onRetry={load} />}

      {/* ── breadth strip ────────────────────────────────────────────────── */}
      {summary && (
        <div className="breadth">
          <Metric label="Advances / Declines"
            value={`${summary.advances} / ${summary.declines}`}
            tone={summary.advances >= summary.declines ? "gain" : "loss"}
            note={summary.advance_decline_ratio !== null ? `${summary.advance_decline_ratio}× ratio` : undefined} />
          <Metric label="Above 20 DMA" value={summary.above_sma20.pct !== null ? `${summary.above_sma20.pct}%` : "—"}
            note={`${summary.above_sma20.n} of ${summary.above_sma20.of}`} />
          <Metric label="Above 50 DMA" value={summary.above_sma50.pct !== null ? `${summary.above_sma50.pct}%` : "—"}
            note={`${summary.above_sma50.n} of ${summary.above_sma50.of}`} />
          <Metric label="Above 200 DMA" value={summary.above_sma200.pct !== null ? `${summary.above_sma200.pct}%` : "—"}
            note={`${summary.above_sma200.n} of ${summary.above_sma200.of}`} />
          <Metric label="52w Highs / Lows" value={`${summary.new_52w_highs} / ${summary.new_52w_lows}`}
            tone={summary.new_52w_highs >= summary.new_52w_lows ? "gain" : "loss"} />
          <Metric label={summary.benchmark.symbol}
            value={pct(summary.benchmark.returns["1d"])}
            tone={(summary.benchmark.returns["1d"] ?? 0) >= 0 ? "gain" : "loss"}
            note={`1M ${pct(summary.benchmark.returns["1m"])}`} />
          <Metric label="Above VWAP" value="n/a"
            note="intraday measure — not stored" muted />
        </div>
      )}

      {/* ── tabs ─────────────────────────────────────────────────────────── */}
      <div className="tabbar">
        {TABS.map((t) => (
          <button key={t.key} className={tab === t.key ? "tabb active" : "tabb"}
            onClick={() => setTab(t.key)}>{t.label}</button>
        ))}
        {busy && <span className="busy">loading…</span>}
      </div>

      {/* ══ MOMENTUM ═══════════════════════════════════════════════════════ */}
      {tab === "momentum" && (
        <>
          <div className="subcontrols">
            <div className="seg">
              {(cfg?.horizons ?? []).map((h) => (
                <button key={h.key} className={horizon === h.key ? "segb active" : "segb"}
                  onClick={() => setHorizon(h.key)}
                  title={`${h.sessions} trading session${h.sessions > 1 ? "s" : ""}`}>{h.label}</button>
              ))}
            </div>
            <div className="right-controls">
              <select className="sel" value={sectorFilter} onChange={(e) => setSectorFilter(e.target.value)}>
                <option value="">All sectors</option>
                {sectorNames.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              <input className="filter" value={filter} onChange={(e) => setFilter(e.target.value)}
                placeholder="Filter by symbol, name or sector…" />
            </div>
          </div>

          {board && (
            <div className="note">
              <b>{board.label}</b> · {board.count} stocks with a {board.horizon_label.toLowerCase()} reading ·
              benchmark {board.benchmark.symbol} {pct(board.benchmark.returns[horizon])} ·
              coverage {board.coverage.with_history}/{board.coverage.symbols} ({board.coverage.pct}%)
              have the {board.coverage.sessions_needed} sessions this horizon needs.
              {!board.benchmark.available && " Benchmark bars are missing, so relative-strength columns read as unavailable rather than zero."}
            </div>
          )}

          <GlassPanel>
            {!board ? (
              <TableSkeleton />
            ) : rows.length === 0 ? (
              <EmptyState title="Nothing matched"
                note="The universe loaded, but every stock was filtered out by the current sector or text filter." />
            ) : (
              <div className="tablewrap">
                <table>
                  <thead>
                    <tr>
                      <th>#</th><th className="l">Stock</th><th className="l">Sector</th><th>LTP</th>
                      <th className="hl">{board?.horizon_label}</th>
                      <th>1D</th><th>1W</th><th>1M</th><th>6M</th>
                      <th title="Return minus the index return, in percentage points">RS idx</th>
                      <th title="Return minus its own sector's return">RS sec</th>
                      <th title="Last session volume vs its own 20-day average">Vol ×</th>
                      <th title="Share of sessions in this window that closed up">Consist</th>
                      <th title="Share of the last month held above the 9 EMA">9EMA</th>
                      <th title="Distance from the 52-week high">52w H</th>
                      <th className="l">Why</th>
                      <th>Score</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.symbol} onClick={() => openDetail(r.symbol)} className="clickable"
                        title={r.why_summary}>
                        <td className="dim">{r.rank}</td>
                        <td className="l"><b>{r.symbol}</b><div className="sub">{r.name}</div></td>
                        <td className="l dim">{r.sector}</td>
                        <td>{num(r.ltp)}</td>
                        <td className="spark">
                          {r.spark && r.spark.length > 1
                            ? <Sparkline values={r.spark} />
                            : <span className="dim">—</span>}
                        </td>
                        <td className={`hl ${cls(r.return_pct)}`}><b>{pct(r.return_pct)}</b></td>
                        <td className={cls(r.returns["1d"])}>{pct(r.returns["1d"], 1)}</td>
                        <td className={cls(r.returns["1w"])}>{pct(r.returns["1w"], 1)}</td>
                        <td className={cls(r.returns["1m"])}>{pct(r.returns["1m"], 1)}</td>
                        <td className={cls(r.returns["6m"])}>{pct(r.returns["6m"], 1)}</td>
                        <td className={cls(r.rs_index)}>{r.rs_index === null ? "—" : r.rs_index.toFixed(1)}</td>
                        <td className={cls(r.rs_sector)}>{r.rs_sector === null ? "—" : r.rs_sector.toFixed(1)}</td>
                        <td className={r.volume_x && r.volume_x >= 2 ? "gain" : ""}>
                          {r.volume_x === null ? "—" : `${r.volume_x.toFixed(1)}×`}</td>
                        <td>{r.consistency === null ? "—" : `${r.consistency.toFixed(0)}%`}</td>
                        <td>{r.ema9_hold_pct === null ? "—" : `${r.ema9_hold_pct.toFixed(0)}%`}</td>
                        <td className={r.pct_from_52w_high !== null && r.pct_from_52w_high >= -2 ? "gain" : ""}>
                          {pct(r.pct_from_52w_high, 1)}</td>
                        <td className="l">
                          <div className="chips">
                            {r.why.length === 0
                              ? <span className="chip t0">unexplained</span>
                              : r.why.map((c) => <span key={c.code} className={`chip t${c.tier}`}>{c.label}</span>)}
                          </div>
                        </td>
                        <td><b>{r.score === null ? "—" : r.score.toFixed(0)}</b></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </GlassPanel>
        </>
      )}

      {/* ══ SECTORS ════════════════════════════════════════════════════════ */}
      {tab === "sectors" && (
        <>
          {sectors && <div className="note"><b>Basis.</b> {sectors.basis}. NSE&rsquo;s own sectoral
            indices are cap-weighted and use a different taxonomy, so the two are never merged
            into one number.</div>}
          <GlassPanel title="Sector performance, ranked"
            note={cfg?.horizons.find((h) => h.key === sectorHorizon)?.label}>
            <div className="seg small">
              {(cfg?.horizons ?? []).map((h) => (
                <button key={h.key} className={sectorHorizon === h.key ? "segb active" : "segb"}
                  onClick={() => setSectorHorizon(h.key)}>{h.label}</button>
              ))}
            </div>
            {!sectors ? <TableSkeleton /> : (
              <RankedBars
                labelWidth={170}
                onSelect={(sector) => openSector(sector)}
                rows={[...(sectors.sectors ?? [])]
                  .filter((x) => x.returns[sectorHorizon] !== null && x.returns[sectorHorizon] !== undefined)
                  .sort((a, b) => (b.returns[sectorHorizon] ?? 0) - (a.returns[sectorHorizon] ?? 0))
                  .map((x): RankedBarRow => ({
                    key: x.sector,
                    label: x.sector,
                    sublabel: `${x.count} name${x.count === 1 ? "" : "s"} · ${x.breadth[sectorHorizon]?.toFixed(0) ?? "—"}% up`,
                    value: x.returns[sectorHorizon] ?? null,
                    muted: x.thin,
                    badge: { text: x.rotation, tone: ROTATION_TONE[x.rotation] ?? "muted" },
                    tooltip: `${x.sector}: ${x.returns[sectorHorizon]?.toFixed(2)}% over this horizon
`
                      + `${x.breadth[sectorHorizon]?.toFixed(0)}% of its ${x.count} names are up
`
                      + `Rotation: ${x.rotation}${x.thin ? " (too few names to be reliable)" : ""}
`
                      + `Click to see what is driving it`,
                  }))}
              />
            )}
            <div className="note small">
              Bars run right for a gain and left for a loss from the centre line, and every bar
              carries its own value — the colour reinforces the sign, it never carries it alone.
              Sectors marked <b>thin</b> have too few constituents for the average to mean much.
            </div>
          </GlassPanel>

          <GlassPanel title="Best and worst name in every sector"
            note="widest spread first">
            {!sectors ? <TableSkeleton /> : (
              <SectorSpread
                onSelectSector={(sec) => openSector(sec)}
                onSelectSymbol={(sym) => openDetail(sym)}
                rows={(sectors.sectors ?? []).map((x) => ({
                  sector: x.sector,
                  count: x.count,
                  thin: x.thin,
                  leader: x.leaders?.[sectorHorizon] ?? null,
                  laggard: x.laggards?.[sectorHorizon] ?? null,
                  sectorReturn: x.returns[sectorHorizon] ?? null,
                }))}
              />
            )}
            <div className="note small">
              Each row spans that sector&rsquo;s worst name to its best over{" "}
              {(cfg?.horizons.find((h) => h.key === sectorHorizon)?.label ?? "").toLowerCase()},
              on one shared scale. A <b>narrow</b> span means the sector really is moving
              together and can be traded as a sector; a <b>wide</b> one means the average is
              two different stories filed under one label. Click a sector to drill in, or a
              dot to open that stock.
            </div>
          </GlassPanel>

          <GlassPanel title="Sector rotation">
            {!sectors ? <TableSkeleton /> : (
              <div className="tablewrap">
                <table>
                  <thead>
                    <tr>
                      <th className="l">Sector</th><th>Names</th>
                      <th>1D</th><th>1W</th><th>1M</th><th>6M</th>
                      <th title="Share of the sector's names that are up over the selected horizon">Breadth</th>
                      <th title="Rank over 6 months minus rank over 1 week — positive means it is climbing">Rank Δ</th>
                      <th>Rotation</th>
                      <th className="l">Leader</th><th className="l">Laggard</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sectors.sectors.map((s) => (
                      <tr key={s.sector} className="clickable"
                        onClick={() => openSector(s.sector)}>
                        <td className="l"><b className="seclink">{s.sector}</b>{s.thin && <span className="thin"> thin</span>}</td>
                        <td className="dim">{s.count}</td>
                        <td className={cls(s.returns["1d"])}>{pct(s.returns["1d"], 1)}</td>
                        <td className={cls(s.returns["1w"])}>{pct(s.returns["1w"], 1)}</td>
                        <td className={cls(s.returns["1m"])}><b>{pct(s.returns["1m"], 1)}</b></td>
                        <td className={cls(s.returns["6m"])}>{pct(s.returns["6m"], 1)}</td>
                        <td>{s.breadth[sectorHorizon] == null ? "—" : `${s.breadth[sectorHorizon]!.toFixed(0)}%`}</td>
                        <td className={cls(s.rank_change)}>
                          {s.rank_change === null ? "—" : (s.rank_change > 0 ? `▲ ${s.rank_change}` : s.rank_change < 0 ? `▼ ${Math.abs(s.rank_change)}` : "—")}</td>
                        <td><StatusPill label={s.rotation} tone={ROTATION_TONE[s.rotation] ?? "muted"} /></td>
                        <td className="l dim">
                          {/* stopPropagation: the row itself opens the SECTOR, so without it
                              a click on the stock would open both, and the sector panel would
                              scroll the drawer out from under you. */}
                          <span className="symlink"
                            onClick={(e) => {
                              e.stopPropagation();
                              const sym = s.leaders?.[sectorHorizon]?.symbol;
                              if (sym) openDetail(sym);
                            }}
                            title={`Open ${s.leaders?.[sectorHorizon]?.symbol}`}>
                            {s.leaders?.[sectorHorizon]?.symbol}
                          </span>{" "}
                          <span className="gain">{pct(s.leaders?.[sectorHorizon]?.return_pct, 1)}</span>
                        </td>
                        <td className="l dim">
                          <span className="symlink"
                            onClick={(e) => {
                              e.stopPropagation();
                              const sym = s.laggards?.[sectorHorizon]?.symbol;
                              if (sym) openDetail(sym);
                            }}
                            title={`Open ${s.laggards?.[sectorHorizon]?.symbol}`}>
                            {s.laggards?.[sectorHorizon]?.symbol}
                          </span>{" "}
                          <span className="loss">{pct(s.laggards?.[sectorHorizon]?.return_pct, 1)}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </GlassPanel>

          {sectorDetail && (
            <div ref={sectorPanelRef} className="sector-panel">
            <GlassPanel title={`${sectorDetail.sector} — ${sectorDetail.horizon_label}`}>
              <button className="panel-close" onClick={() => setSectorDetail(null)}
                title="Close this sector">✕</button>
              <div className="shaperow">
                <StatusPill
                  label={`${sectorDetail.shape} move`}
                  tone={sectorDetail.shape === "broad" ? "gain"
                      : sectorDetail.shape === "narrow" ? "warn"
                      : sectorDetail.shape === "thin" ? "muted" : "accent"} />
                <span className="shapemeta">
                  {sectorDetail.breadth_pct}% of names up · top two are{" "}
                  {sectorDetail.top2_share_pct}% of the move
                </span>
              </div>
              <div className="drivers">
                {sectorDetail.drivers.map((d, i) => <div key={i} className="driver">{d}</div>)}
              </div>
              <div className="seg small">
                {(cfg?.horizons ?? []).map((h) => (
                  <button key={h.key} className={sectorDetail.horizon === h.key ? "segb active" : "segb"}
                    onClick={() => { setSectorHorizon(h.key); openSector(sectorDetail.sector, h.key); }}>
                    {h.label}</button>
                ))}
              </div>
              <h4>Every name in the sector, ranked</h4>
              <RankedBars
                labelWidth={140}
                onSelect={(sym) => openDetail(sym)}
                rows={(sectorDetail.constituents ?? []).map((c): RankedBarRow => ({
                  key: c.symbol,
                  label: c.symbol,
                  sublabel: c.name ?? undefined,
                  value: c.return_pct ?? null,
                  tooltip: `${c.symbol}: ${c.return_pct?.toFixed(2)}% over ${sectorDetail.horizon_label.toLowerCase()}`
                    + (c.volume_x ? `
Volume ${c.volume_x.toFixed(1)}x its average` : "")
                    + `
Click for the full reason stack`,
                }))}
              />

              <h4>Who is driving it — contribution to the sector move</h4>
              <div className="tablewrap">
                <table>
                  <thead><tr><th className="l">Stock</th><th>LTP</th><th>Return</th>
                    <th title="Share of the sector's turnover">Weight</th>
                    <th title="Return × weight — its share of the sector's move">Contribution</th>
                    <th>Vol ×</th></tr></thead>
                  <tbody>
                    {sectorDetail.contributions.map((c) => (
                      <tr key={c.symbol} className="clickable" onClick={() => openDetail(c.symbol)}>
                        <td className="l"><b>{c.symbol}</b><div className="sub">{c.name}</div></td>
                        <td>{num(c.ltp)}</td>
                        <td className={cls(c.return_pct)}>{pct(c.return_pct, 1)}</td>
                        <td className="dim">{c.weight_pct.toFixed(1)}%</td>
                        <td className={cls(c.contribution_pp)}><b>{c.contribution_pp.toFixed(2)} pp</b></td>
                        <td>{c.volume_x === null ? "—" : `${c.volume_x.toFixed(1)}×`}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="note small">{sectorDetail.note}</div>
            </GlassPanel>
            </div>
          )}
        </>
      )}

      {/* ══ PATTERNS ═══════════════════════════════════════════════════════ */}
      {tab === "patterns" && (
        <>
          <div className="subcontrols">
            <div className="seg">
              {(cfg?.timeframes ?? []).map((t) => (
                <button key={t.key} className={patTimeframe === t.key ? "segb active" : "segb"}
                  onClick={() => setPatTimeframe(t.key)}>{t.label}</button>
              ))}
            </div>
            <div className="right-controls">
              <select className="sel" value={patFamily} onChange={(e) => setPatFamily(e.target.value)}>
                <option value="">All families</option>
                <option value="chart">Chart patterns</option>
                <option value="candlestick">Candlesticks</option>
                <option value="structure">Price structure</option>
              </select>
              <select className="sel" value={patState} onChange={(e) => setPatState(e.target.value)}>
                <option value="">Triggered + Forming</option>
                <option value="TRIGGERED">Triggered only</option>
                <option value="FORMING">Forming only</option>
              </select>
              <select className="sel" value={patDirection} onChange={(e) => setPatDirection(e.target.value)}>
                <option value="">Both directions</option>
                <option value="bullish">Bullish</option>
                <option value="bearish">Bearish</option>
              </select>
            </div>
          </div>

          {patterns && (
            <div className="note">
              <b>{patterns.count}</b> hits over {patterns.scanned} stocks —{" "}
              <b className="gain">{patterns.triggered}</b> triggered (price has closed through
              the pattern&rsquo;s boundary) and <b className="warn">{patterns.forming}</b> forming
              (shape complete, boundary intact — the Trigger column is the level that would
              confirm it). Scan took {patterns.elapsed_s}s and made no broker calls.
              {patTimeframe === "1w" && (
                <> Weekly coverage: {patterns.weekly_coverage.with_enough_weekly_bars}/
                  {patterns.weekly_coverage.symbols} ({patterns.weekly_coverage.pct}%) have enough
                  history. {patterns.weekly_coverage.note}</>
              )}
            </div>
          )}

          <GlassPanel>
            {!patterns ? (
              <TableSkeleton />
            ) : patterns.rows.length === 0 ? (
              <EmptyState title="No pattern hits" note="Try widening the filters, or the other timeframe." />
            ) : (
              <div className="tablewrap">
                <table>
                  <thead><tr>
                    <th className="l">Stock</th><th className="l">Sector</th><th className="l">Pattern</th>
                    <th>TF</th><th>State</th><th>Dir</th>
                    <th>Entry</th><th>Trigger</th><th>Stop</th><th>Target</th>
                    <th>R:R</th><th>Conf</th><th className="l">Rationale</th>
                  </tr></thead>
                  <tbody>
                    {patterns.rows.map((p, i) => (
                      <tr key={`${p.symbol}-${p.template}-${p.timeframe}-${i}`} className="clickable"
                        onClick={() => openDetail(p.symbol)}>
                        <td className="l"><b>{p.symbol}</b></td>
                        <td className="l dim">{p.sector}</td>
                        <td className="l">{p.pattern}<div className="sub">{p.family_label}</div></td>
                        <td className="dim">{p.timeframe_label}</td>
                        <td><span className={p.state === "TRIGGERED" ? "state trig" : "state form"}>{p.state}</span></td>
                        <td className={p.direction === "bullish" ? "gain" : "loss"}>{p.side}</td>
                        <td>{num(p.entry)}</td>
                        <td>{p.trigger_level === null ? "—" : <b>{num(p.trigger_level)}</b>}</td>
                        <td className="loss">{num(p.stoploss)}</td>
                        <td className="gain">{num(p.target)}</td>
                        <td><b>{p.reward_risk === null ? "—" : `${p.reward_risk}×`}</b></td>
                        <td className="dim">{(p.confidence * 100).toFixed(0)}%</td>
                        <td className="l sub wide">{p.rationale}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </GlassPanel>
        </>
      )}

      {/* ══ SETUPS ═════════════════════════════════════════════════════════ */}
      {tab === "setups" && (
        <>
          <div className="subcontrols">
            <div className="seg">
              {(cfg?.setup_kinds ?? []).map((k) => (
                <button key={k} className={setupKind === k ? "segb active" : "segb"}
                  onClick={() => setSetupKind(k)}>{k[0].toUpperCase() + k.slice(1)}</button>
              ))}
            </div>
          </div>

          {setups && (
            <div className="note">
              <b>{setups.qualified}</b> of {setups.universe} stocks pass the {setups.kind} gate;{" "}
              <b className="gain">{setups.worth_taking}</b> clear their costs at{" "}
              {money(setups.capital_per_trade)} per trade. {setups.note}
            </div>
          )}

          <GlassPanel>
            {!setups ? (
              <TableSkeleton />
            ) : setups.rows.length === 0 ? (
              <EmptyState title="No setups today"
                note="Nothing passed this mode's gate. That is a real answer, not an error." />
            ) : (
              <div className="tablewrap">
                <table>
                  <thead><tr>
                    <th className="l">Stock</th><th className="l">Sector</th><th>LTP</th><th>Return</th>
                    <th>Entry</th><th>Stop</th><th>Target</th><th>Qty</th>
                    <th title="Reward:risk before costs">Gross R:R</th>
                    <th title="Reward:risk after real Angel One charges on both legs">Net R:R</th>
                    <th>Product</th><th className="l">Why</th><th className="l">Pattern</th>
                  </tr></thead>
                  <tbody>
                    {setups.rows.map((s) => (
                      <tr key={s.symbol} className={s.plan.worth_taking ? "clickable" : "clickable faded"}
                        onClick={() => openDetail(s.symbol)}
                        title={s.plan.blocked_reason || s.plan.basis}>
                        <td className="l"><b>{s.symbol}</b><div className="sub">{s.name}</div></td>
                        <td className="l dim">{s.sector}</td>
                        <td>{num(s.ltp)}</td>
                        <td className={cls(s.return_pct)}>{pct(s.return_pct, 1)}</td>
                        <td>{num(s.plan.entry)}</td>
                        <td className="loss">{num(s.plan.stop)} <span className="sub">{pct(s.plan.stop_pct, 1)}</span></td>
                        <td className="gain">{num(s.plan.target)} <span className="sub">{pct(s.plan.target_pct, 1)}</span></td>
                        <td className="dim">{s.plan.qty}</td>
                        <td className="dim">{s.plan.gross_rr ?? "—"}×</td>
                        <td className={s.plan.worth_taking ? "gain" : "loss"}>
                          <b>{s.plan.net_rr ?? "—"}×</b>
                          {!s.plan.tradable && <div className="sub">gapped past</div>}
                        </td>
                        <td className="dim">{s.plan.product}</td>
                        <td className="l">
                          <div className="chips">
                            {s.why.map((c) => <span key={c.code} className={`chip t${c.tier}`}>{c.label}</span>)}
                          </div>
                        </td>
                        <td className="l sub">
                          {s.plan.confirming_patterns.length === 0 ? "—"
                            : s.plan.confirming_patterns.map((p) => `${p.pattern} (${p.state})`).join(", ")}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </GlassPanel>
        </>
      )}

      {/* ══ VOLUME ═════════════════════════════════════════════════════════ */}
      {tab === "volume" && (
        <>
          <div className="subcontrols">
            <div className="seg">
              {(cfg?.volume_windows ?? []).map((w) => (
                <button key={w.key} className={volWindow === w.key ? "segb active" : "segb"}
                  onClick={() => setVolWindow(w.key)}
                  title={w.sessions + " trading session(s)"}>{w.label}</button>
              ))}
            </div>
            <div className="right-controls">
              <select className="sel" value={volState} onChange={(e) => setVolState(e.target.value)}>
                <option value="">All price-volume states</option>
                {(cfg?.volume_states ?? []).map((st) => (
                  <option key={st.key} value={st.key}>{st.label}</option>
                ))}
              </select>
            </div>
          </div>

          {volume && (
            <>
              <div className="note">
                <b>{volume.count}</b> stocks trading at {volume.min_volume_ratio}x or more of their
                own average volume over {volume.window_label.toLowerCase()}. Volume on its own means
                little — what matters is whether price went anywhere on it, which is the{" "}
                <b>state</b> column. {volume.delivery_note}
              </div>
              <div className="statestrip">
                {(cfg?.volume_states ?? []).map((st) => {
                  const n = volume.by_state[st.key] ?? 0;
                  const sty = VOLUME_STATE_STYLE[st.key] ?? VOLUME_STATE_STYLE.unknown;
                  return (
                    <div key={st.key}
                      className={"statecard " + sty.tone + (sty.filled ? " filled" : "") + (volState === st.key ? " on" : "")}
                      onClick={() => setVolState(volState === st.key ? "" : st.key)}
                      title={st.text}>
                      <div className="scount">{n}</div>
                      <div className="slabel">{st.label}</div>
                      <div className="stext">{st.text}</div>
                    </div>
                  );
                })}
              </div>
            </>
          )}

          <GlassPanel>
            {!volume ? <TableSkeleton /> : volume.rows.length === 0 ? (
              <EmptyState title="No unusual volume"
                note="Nothing is trading meaningfully above its own average over this window." />
            ) : (
              <div className="tablewrap">
                <table>
                  <thead><tr>
                    <th className="l">Stock</th><th className="l">Sector</th><th>LTP</th>
                    <th>Return</th>
                    <th title="Volume this window vs the same number of sessions before it">Vol ×</th>
                    <th title="Share of volume taken to demat, against this stock's own average">Delivery</th>
                    <th>State</th>
                    <th title="Where the next level is, and how that level was derived">Next target</th>
                    <th className="l">Why the volume is there</th>
                  </tr></thead>
                  <tbody>
                    {volume.rows.map((v) => {
                      const sty = VOLUME_STATE_STYLE[v.state] ?? VOLUME_STATE_STYLE.unknown;
                      return (
                        <tr key={v.symbol} className="clickable" onClick={() => openDetail(v.symbol)}>
                          <td className="l"><b>{v.symbol}</b><div className="sub">{v.name}</div></td>
                          <td className="l dim">{v.sector}</td>
                          <td>{num(v.ltp)}</td>
                          <td className={cls(v.return_pct)}>{pct(v.return_pct, 1)}</td>
                          <td className={v.volume_ratio >= 3 ? "gain" : ""}><b>{v.volume_ratio.toFixed(1)}×</b></td>
                          <td>
                            {v.delivery_pct === null ? <span className="dim">n/a</span> : (
                              <>
                                <b className={v.delivery_ratio && v.delivery_ratio >= 1.3 ? "gain"
                                  : v.delivery_ratio && v.delivery_ratio <= 0.7 ? "loss" : ""}>
                                  {v.delivery_pct.toFixed(0)}%
                                </b>
                                {v.delivery_avg !== null && <div className="sub">avg {v.delivery_avg.toFixed(0)}%</div>}
                              </>
                            )}
                          </td>
                          <td>
                            <span className={"vstate " + sty.tone + (sty.filled ? " filled" : "")}
                              title={v.state_text}>{v.state_label}</span>
                            {/* Delivery contradicting the price-volume reading is the more
                                important fact, so it sits next to the label rather than
                                three columns away in the reason list. */}
                            {v.delivery_conflict && (
                              <div className="conflict" title={v.delivery_conflict}>
                                ⚠ delivery disagrees
                              </div>
                            )}
                          </td>
                          <td>
                            {v.target.target === null ? <span className="dim">—</span> : (
                              <>
                                <b>{num(v.target.target)}</b>
                                <div className={"sub strength-" + v.target.strength}>
                                  {pct(v.target.upside_pct, 1)} · {v.target.method}
                                </div>
                              </>
                            )}
                          </td>
                          <td className="l sub wide">
                            {v.reasons.length === 0
                              ? <span className="dim">Volume is elevated with nothing else corroborating it</span>
                              : v.reasons.slice(0, 3).map((r, i) => <div key={i}>• {r}</div>)}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </GlassPanel>
        </>
      )}

      {/* ══ PAPER DESK ═════════════════════════════════════════════════════ */}
      {tab === "paper" && (
        <>
          {paper && (
            <div className="note">
              Every signal this module publishes is taken as a paper trade at its own published
              price and managed to its own stop and target, with real Angel One costs charged on
              exit. Five separate books, one per signal kind, so they can be compared rather than
              averaged into a number that hides which one worked. <b>{paper.total_trades}</b> closed
              trades · <b className={paper.total_net_pnl >= 0 ? "gain" : "loss"}>{money(paper.total_net_pnl)}</b>{" "}
              net across {money(paper.total_capital)} · {money(paper.total_fees)} paid in costs.
            </div>
          )}

          <GlassPanel title="Which kind of signal actually makes money"
            note={paper ? money(paper.per_trade_capital) + " per trade" : undefined}>
            {!paper ? <TableSkeleton /> : (
              <>
                <RankedBars
                  unit=""
                  labelWidth={150}
                  onSelect={(f) => setPaperFamily(paperFamily === f ? "" : f)}
                  emptyNote="No closed trades yet — the desk needs a few sessions before it can rank anything."
                  rows={paper.families
                    .filter((f) => f.trades > 0)
                    .map((f): RankedBarRow => ({
                      key: f.family,
                      label: f.label,
                      sublabel: f.trades + " trades · " + (f.win_rate?.toFixed(0) ?? "—") + "% won · PF " + (f.profit_factor ?? "—"),
                      value: f.net_pnl,
                      tooltip: f.label + ": net " + f.net_pnl.toFixed(0) + " after " + f.fees.toFixed(0) + " in costs\n"
                        + f.wins + "W / " + f.losses + "L · expectancy " + (f.expectancy ?? "—") + " per trade\n"
                        + "average " + (f.avg_r ?? "—") + "R · " + f.product + " cost schedule",
                    }))}
                />
                <div className="tablewrap">
                  <table>
                    <thead><tr>
                      <th className="l">Signal family</th><th>Open</th><th>Trades</th><th>Win %</th>
                      <th title="Gross profit divided by gross loss — above 1 means it makes money">PF</th>
                      <th title="Average net rupees per trade">Expectancy</th>
                      <th title="Average multiple of the risk taken">Avg R</th>
                      <th>Costs paid</th><th>Net P&amp;L</th><th>ROI</th><th>Schedule</th>
                    </tr></thead>
                    <tbody>
                      {paper.families.map((f) => (
                        <tr key={f.family}
                          className={paperFamily === f.family ? "clickable sel" : "clickable"}
                          onClick={() => setPaperFamily(paperFamily === f.family ? "" : f.family)}>
                          <td className="l"><b>{f.label}</b></td>
                          <td className="dim">{f.open_positions}</td>
                          <td className="dim">{f.trades}</td>
                          <td>{f.win_rate === null ? "—" : f.win_rate + "%"}</td>
                          <td>{f.profit_factor ?? "—"}</td>
                          <td className={cls(f.expectancy)}>{f.expectancy === null ? "—" : money(f.expectancy)}</td>
                          <td className={cls(f.avg_r)}>{f.avg_r ?? "—"}</td>
                          <td className="dim">{money(f.fees)}</td>
                          <td className={cls(f.net_pnl)}><b>{money(f.net_pnl)}</b></td>
                          <td className={cls(f.roi_pct)}>{pct(f.roi_pct, 2)}</td>
                          <td className="dim">{f.product}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="note small">{paper.note}</div>
              </>
            )}
          </GlassPanel>

          <div className="subcontrols">
            <div className="seg">
              {(["OPEN", "CLOSED"] as const).map((v) => (
                <button key={v} className={paperView === v ? "segb active" : "segb"}
                  onClick={() => setPaperView(v)}>{v === "OPEN" ? "Open positions" : "Closed trades"}</button>
              ))}
            </div>
            <div className="right-controls">
              {paperFamily && (
                <button className="toggle on" onClick={() => setPaperFamily("")}>
                  {familyLabel(cfg, paperFamily)} only ✕
                </button>
              )}
              <button className="hard-refresh" disabled={busy} onClick={async () => {
                setBusy(true);
                try { await runScreenerPaperCycle(index); await refreshing(load); }
                catch (e) { setError(e instanceof Error ? e.message : String(e)); }
                finally { setBusy(false); }
              }}>Run a cycle now</button>
            </div>
          </div>

          <GlassPanel>
            {!paperPos ? <TableSkeleton /> : paperPos.rows.length === 0 ? (
              <EmptyState
                title={paperView === "OPEN" ? "No open paper positions" : "No closed trades yet"}
                note={paperView === "OPEN"
                  ? "Nothing currently qualifies, or the desk has not run since the last close."
                  : "A trade is recorded only once it hits its stop, its target, or its holding limit."} />
            ) : (
              <div className="tablewrap">
                <table>
                  <thead><tr>
                    <th className="l">Stock</th><th>Family</th><th>Entry</th><th>Stop</th><th>Target</th>
                    <th>Qty</th>
                    {paperView === "OPEN"
                      ? <><th>LTP</th><th>Unrealised</th><th>To target</th><th>To stop</th></>
                      : <><th>Exit</th><th>Reason</th><th>Net P&amp;L</th><th>R</th></>}
                    <th className="l">Signal that opened it</th>
                  </tr></thead>
                  <tbody>
                    {paperPos.rows.map((r) => (
                      <tr key={r.position_id} className="clickable" onClick={() => openDetail(r.symbol)}>
                        <td className="l"><b>{r.symbol}</b><div className="sub">{r.sector}</div></td>
                        <td className="dim">{familyLabel(cfg, r.family)}</td>
                        <td>{num(r.entry)}</td>
                        <td className="loss">{num(r.stop)}</td>
                        <td className="gain">{num(r.target)}</td>
                        <td className="dim">{r.qty}</td>
                        {paperView === "OPEN" ? (
                          <>
                            <td>{r.ltp ? num(r.ltp) : "—"}</td>
                            <td className={cls(r.unrealised_net)}>
                              <b>{r.unrealised_net === undefined ? "—" : money(r.unrealised_net)}</b>
                              {r.return_pct !== undefined && <div className="sub">{pct(r.return_pct, 1)}</div>}
                            </td>
                            <td className="dim">{r.to_target_pct === undefined ? "—" : pct(r.to_target_pct, 1)}</td>
                            <td className="dim">{r.to_stop_pct === undefined ? "—" : pct(r.to_stop_pct, 1)}</td>
                          </>
                        ) : (
                          <>
                            <td>{r.exit ? num(r.exit) : "—"}</td>
                            <td><span className={"exitr " + (r.exit_reason || "").toLowerCase()}>{r.exit_reason}</span></td>
                            <td className={cls(r.net_pnl)}>
                              <b>{r.net_pnl === undefined ? "—" : money(r.net_pnl)}</b>
                              {r.fees !== undefined && <div className="sub">after {money(r.fees)} costs</div>}
                            </td>
                            <td className={cls(r.r_multiple)}>{r.r_multiple ?? "—"}</td>
                          </>
                        )}
                        <td className="l sub wide">{r.pattern || r.signal_reason || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </GlassPanel>
        </>
      )}

      {/* ══ SOURCES ════════════════════════════════════════════════════════ */}
      {tab === "chartink" && <ChartinkPanel cfg={cfg?.chartink} />}

      {/* Symbol-driven, so it stays out of the shared index/horizon loader entirely. */}
      {tab === "analysis" && <StockAnalysis />}

      {tab === "athsweep" && <AnalysedStocks />}

      {tab === "sources" && (
        <GlassPanel title="Where every number comes from"
          note={sources ? `checked ${new Date(sources.checked_at).toLocaleTimeString()}` : undefined}>
          {!sources ? <TableSkeleton /> : (
            <div className="feeds">
              {sources.feeds.map((f) => (
                <div key={f.name} className="feed">
                  <div className="feedhead">
                    <span className={`dot ${f.ok === true ? "ok" : f.ok === false ? "bad" : "unk"}`} />
                    <b>{f.name}</b>
                    <span className="role">{f.role}</span>
                  </div>
                  <div className="detail">{f.detail}</div>
                  {f.endpoints && (
                    <div className="eps">
                      {Object.entries(f.endpoints).map(([k, v]) => (
                        <div key={k} className={v.ok ? "ep ok" : "ep bad"}>
                          {k}: {v.ok ? "ok" : v.error}
                        </div>
                      ))}
                      {Object.keys(f.endpoints).length === 0 && <div className="ep unk">not attempted yet this process</div>}
                    </div>
                  )}
                  {f.verified && (
                    <div className="eps">
                      {Object.entries(f.verified).map(([k, v]) => (
                        <div key={k} className="ep unk"><b>{k}</b>: {v}</div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </GlassPanel>
      )}

      {/* ══ STOCK DRAWER ═══════════════════════════════════════════════════ */}
      {detailFor && (
        <div className="scrim" onClick={() => { setDetailFor(null); setDetail(null); }}>
          <div className="drawer" onClick={(e) => e.stopPropagation()}>
            <div className="drawerhead">
              <div>
                <h2>{detailFor}</h2>
                {detail && <div className="sub">{detail.name} · {detail.sector} · {detail.belongs_to} · ₹{num(detail.ltp)}</div>}
              </div>
              <button className="close" onClick={() => { setDetailFor(null); setDetail(null); }}>✕</button>
            </div>

            {!detail ? <TableSkeleton /> : (
              <div className="drawerbody">
                <h4>Across the four horizons</h4>
                <div className="hgrid">
                  {Object.entries(detail.horizons).map(([k, h]) => (
                    <div key={k} className="hcard">
                      <div className="hlabel">{h.label}</div>
                      <div className={`hval ${cls(h.return_pct)}`}>{pct(h.return_pct, 1)}</div>
                      <div className="sub">
                        vs index {h.rs_index === null ? "—" : `${h.rs_index > 0 ? "+" : ""}${h.rs_index.toFixed(1)}`}
                        {h.sector_rank && ` · sector rank ${h.sector_rank}`}
                      </div>
                    </div>
                  ))}
                </div>

                <h4>Why it is moving</h4>
                {Object.entries(detail.horizons).map(([k, h]) => (
                  <div key={k} className="reasonblock">
                    <div className="rhead">{h.label} — <span className={`char ${h.character}`}>{h.character}</span></div>
                    <div className="rsummary">{h.summary}</div>
                    {h.reasons.length > 0 && (
                      <ul className="rlist">
                        {h.reasons.map((r) => (
                          <li key={r.code}>
                            <span className={`tier t${r.tier}`}>T{r.tier}</span> {r.text}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                ))}

                <h4>Chart patterns</h4>
                {detail.patterns.length === 0 ? (
                  <div className="sub">No pattern shapes detected on the daily or weekly chart.</div>
                ) : (
                  <div className="tablewrap">
                    <table>
                      <thead><tr><th className="l">Pattern</th><th>TF</th><th>State</th><th>Entry</th>
                        <th>Trigger</th><th>Stop</th><th>Target</th><th>R:R</th></tr></thead>
                      <tbody>
                        {detail.patterns.map((p, i) => (
                          <tr key={i}>
                            <td className="l">{p.pattern}</td>
                            <td className="dim">{p.timeframe_label}</td>
                            <td><span className={p.state === "TRIGGERED" ? "state trig" : "state form"}>{p.state}</span></td>
                            <td>{num(p.entry)}</td>
                            <td>{p.trigger_level === null ? "—" : num(p.trigger_level)}</td>
                            <td className="loss">{num(p.stoploss)}</td>
                            <td className="gain">{num(p.target)}</td>
                            <td>{p.reward_risk === null ? "—" : `${p.reward_risk}×`}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                <h4>Trade plans — net of real Angel One costs</h4>
                <div className="plangrid">
                  {detail.trade_plans.map((p) => (
                    <div key={p.kind} className={p.worth_taking ? "plan good" : "plan"}>
                      <div className="planhead">
                        <b>{p.label}</b>
                        <span className="sub">{p.horizon}</span>
                      </div>
                      <div className="planrow"><span>Entry</span><b>{num(p.entry)}</b></div>
                      <div className="planrow"><span>Stop</span><b className="loss">{num(p.stop)} ({pct(p.stop_pct, 1)})</b></div>
                      <div className="planrow"><span>Target</span><b className="gain">{num(p.target)} ({pct(p.target_pct, 1)})</b></div>
                      <div className="planrow"><span>Qty @ {money(p.capital_used)}</span><b>{p.qty}</b></div>
                      <div className="planrow"><span>Gross R:R</span><b>{p.gross_rr ?? "—"}×</b></div>
                      <div className="planrow hi"><span>Net R:R</span>
                        <b className={p.worth_taking ? "gain" : "loss"}>{p.net_rr ?? "—"}×</b></div>
                      <div className="planrow"><span>Cost to target</span>
                        <b>{p.cost_win ? money(Number(p.cost_win.total)) : "—"} ({p.product})</b></div>
                      <div className="planbasis">{p.basis}</div>
                      <div className="planbasis"><b>Exit:</b> {p.exit_rule}</div>
                      {p.blocked_reason && <div className="blocked">{p.blocked_reason}</div>}
                    </div>
                  ))}
                </div>

                <div className="note small"><b>News.</b> {detail.narrative.reason}</div>
              </div>
            )}
          </div>
        </div>
      )}

      <style jsx>{`
        .page { display: flex; flex-direction: column; gap: 16px; }
        .controls, .subcontrols { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
        .index-tabs, .seg { display: flex; gap: 4px; background: var(--canvas-soft); padding: 4px; border-radius: 10px; border: 1px solid var(--panel-border); }
        .tab, .segb { border: 0; background: transparent; padding: 7px 14px; border-radius: 7px; font-size: 13px; font-weight: 600; color: var(--text-muted); cursor: pointer; }
        .tab.active, .segb.active { background: var(--panel); color: var(--text); box-shadow: var(--shadow-sm); }
        .seg.small { margin: 10px 0; display: inline-flex; }
        .right-controls { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
        .filter, .sel { padding: 8px 12px; border-radius: 9px; border: 1px solid var(--panel-border); background: var(--panel); font-size: 13px; color: var(--text); min-width: 150px; }
        .hard-refresh { padding: 7px 13px; border-radius: 9px; border: 1px solid var(--panel-border); background: var(--panel); font-size: 12px; font-weight: 600; color: var(--text-muted); cursor: pointer; }
        .hard-refresh:hover:not(:disabled) { border-color: var(--purple); color: var(--purple); }
        .hard-refresh:disabled { opacity: .5; cursor: default; }

        .breadth { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; }

        .tabbar { display: flex; gap: 2px; border-bottom: 1px solid var(--panel-border); align-items: center; }
        .tabb { border: 0; background: transparent; padding: 10px 16px; font-size: 13.5px; font-weight: 600; color: var(--text-muted); cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -1px; }
        .tabb.active { color: var(--purple); border-bottom-color: var(--purple); }
        .busy { margin-left: auto; font-size: 12px; color: var(--text-faint); }

        .note { font-size: 12.5px; color: var(--text-muted); line-height: 1.6; background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 10px; padding: 10px 14px; }
        .note.small { font-size: 11.5px; margin-top: 12px; }

        .tablewrap { overflow-x: auto; }
        td.spark { width: 92px; min-width: 92px; padding: 2px 8px; }
        table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
        th, td { padding: 8px 10px; text-align: right; white-space: nowrap; border-bottom: 1px solid var(--panel-border); font-variant-numeric: tabular-nums; }
        th { font-size: 11px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: .04em; position: sticky; top: 0; background: var(--panel); }
        th.l, td.l { text-align: left; }
        th.hl, td.hl { background: var(--purple-dim); }
        td.dim { color: var(--text-muted); }
        .sub { font-size: 10.5px; color: var(--text-faint); font-weight: 400; white-space: normal; }
        td.wide { max-width: 340px; white-space: normal; }
        tr.clickable { cursor: pointer; }
        tr.clickable:hover td { background: var(--canvas-soft); }
        tr.faded td { opacity: .55; }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
        .warn { color: var(--warn); }
        .thin { font-size: 10px; color: var(--warn); font-weight: 600; }
        .seclink { color: var(--purple); }
        tr:hover .seclink { text-decoration: underline; }
        .symlink { color: var(--purple); font-weight: 600; cursor: pointer; }
        .symlink:hover { text-decoration: underline; }
        /* scroll-margin keeps the panel's heading clear of the viewport edge when the
           click scrolls it into view. */
        .sector-panel { position: relative; scroll-margin-top: 16px; }
        .shaperow { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
        .shapemeta { font-size: 11.5px; color: var(--text-muted); }
        .panel-close { position: absolute; top: 14px; right: 16px; border: 0; background: var(--canvas-soft); width: 26px; height: 26px; border-radius: 7px; cursor: pointer; color: var(--text-muted); font-size: 12px; z-index: 2; }
        .panel-close:hover { background: var(--panel-border); color: var(--text); }

        .chips { display: flex; gap: 4px; flex-wrap: wrap; }
        .chip { font-size: 10px; font-weight: 600; padding: 2px 7px; border-radius: 20px; white-space: nowrap; }
        .chip.t1 { background: var(--gain-dim); color: var(--gain); }
        .chip.t2 { background: var(--purple-dim); color: var(--purple); }
        .chip.t3 { background: var(--accent-dim); color: var(--accent); }
        .chip.t0 { background: var(--canvas-soft); color: var(--text-faint); }

        .state { font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 4px; letter-spacing: .03em; }
        .state.trig { background: var(--gain-dim); color: var(--gain); }
        .state.form { background: var(--warn-dim); color: var(--warn); }

        .drivers { display: flex; flex-direction: column; gap: 6px; margin-bottom: 8px; }
        .driver { font-size: 13px; color: var(--text); padding: 8px 12px; background: var(--canvas-soft); border-radius: 8px; border-left: 3px solid var(--purple); }
        h4 { font-size: 12px; text-transform: uppercase; letter-spacing: .06em; color: var(--text-muted); margin: 18px 0 8px; }

        .feeds { display: flex; flex-direction: column; gap: 12px; }
        .feed { border: 1px solid var(--panel-border); border-radius: 10px; padding: 12px 14px; }
        .feedhead { display: flex; align-items: center; gap: 8px; font-size: 13.5px; }
        .role { font-size: 11.5px; color: var(--text-faint); }
        .dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
        .dot.ok { background: var(--gain); }
        .dot.bad { background: var(--loss); }
        .dot.unk { background: var(--text-faint); }
        .detail { font-size: 12.5px; color: var(--text-muted); margin-top: 5px; line-height: 1.55; }
        .eps { margin-top: 7px; display: flex; flex-direction: column; gap: 3px; }
        .ep { font-size: 11px; font-family: ui-monospace, monospace; color: var(--text-muted); }
        .ep.ok { color: var(--gain); }
        .ep.bad { color: var(--loss); }

        .scrim { position: fixed; inset: 0; background: rgba(18,16,28,.42); z-index: 90; display: flex; justify-content: flex-end; }
        .drawer { width: min(940px, 100%); height: 100%; background: var(--panel); overflow-y: auto; padding: 22px 26px 60px; box-shadow: var(--shadow-lg); }
        .drawerhead { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; border-bottom: 1px solid var(--panel-border); padding-bottom: 14px; }
        .drawerhead h2 { margin: 0; font-size: 22px; }
        .close { border: 0; background: var(--canvas-soft); width: 30px; height: 30px; border-radius: 8px; cursor: pointer; color: var(--text-muted); font-size: 14px; }
        .drawerbody { padding-top: 4px; }

        .hgrid { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px; }
        .hcard { border: 1px solid var(--panel-border); border-radius: 10px; padding: 10px 12px; }
        .hlabel { font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: .05em; }
        .hval { font-size: 20px; font-weight: 700; margin: 3px 0; font-variant-numeric: tabular-nums; }

        .reasonblock { border-left: 2px solid var(--panel-border); padding: 8px 0 8px 14px; margin-bottom: 10px; }
        .rhead { font-size: 12px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: .04em; }
        .char { font-weight: 700; }
        .char.rotation { color: var(--purple); }
        .char.breakout { color: var(--gain); }
        .char.momentum { color: var(--gain); }
        .char.fundamental { color: var(--accent); }
        .char.short-covering { color: var(--warn); }
        .char.unexplained { color: var(--text-faint); }
        .rsummary { font-size: 13px; margin: 5px 0; line-height: 1.6; }
        .rlist { margin: 6px 0 0; padding-left: 0; list-style: none; display: flex; flex-direction: column; gap: 4px; }
        .rlist li { font-size: 12.5px; color: var(--text-muted); line-height: 1.5; }
        .tier { font-size: 9.5px; font-weight: 700; padding: 1px 5px; border-radius: 3px; margin-right: 6px; }
        .tier.t1 { background: var(--gain-dim); color: var(--gain); }
        .tier.t2 { background: var(--purple-dim); color: var(--purple); }
        .tier.t3 { background: var(--accent-dim); color: var(--accent); }

        .plangrid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 12px; }
        .plan { border: 1px solid var(--panel-border); border-radius: 12px; padding: 14px; }
        .plan.good { border-color: var(--gain); background: var(--gain-dim); }
        .planhead { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px; }
        .planrow { display: flex; justify-content: space-between; font-size: 12.5px; padding: 3px 0; gap: 10px; }
        .planrow span { color: var(--text-muted); }
        .planrow.hi { border-top: 1px solid var(--panel-border); margin-top: 5px; padding-top: 7px; font-size: 14px; }
        .planbasis { font-size: 11px; color: var(--text-faint); line-height: 1.5; margin-top: 8px; }
        .blocked { font-size: 11.5px; color: var(--loss); background: var(--loss-dim); padding: 7px 9px; border-radius: 7px; margin-top: 8px; line-height: 1.5; }

        /* ── volume: price-volume state cards ──────────────────────────────
           Three hues, not five. Confirmed states are FILLED and unconfirmed ones are
           OUTLINED, so the confirmed/unconfirmed axis survives colourblindness — five
           categorical hues alongside a fixed gain-green and loss-red cannot be made
           CVD-safe (amber collapses onto red at deltaE 3.9 under deuteranopia). */
        .statestrip { display: grid; grid-template-columns: repeat(auto-fit, minmax(165px, 1fr)); gap: 8px; }
        .statecard { border: 1px solid var(--panel-border); border-radius: 11px; padding: 10px 12px; cursor: pointer; background: var(--panel); border-left-width: 3px; }
        .statecard:hover { border-color: var(--panel-border-hover); }
        .statecard.on { box-shadow: 0 0 0 2px var(--purple-dim); }
        .statecard.gain { border-left-color: var(--gain); }
        .statecard.loss { border-left-color: var(--loss); }
        .statecard.accent { border-left-color: var(--purple); }
        .statecard.muted { border-left-color: var(--text-faint); }
        .statecard.filled.gain { background: var(--gain-dim); }
        .statecard.filled.loss { background: var(--loss-dim); }
        .statecard.filled.accent { background: var(--purple-dim); }
        .scount { font-size: 20px; font-weight: 700; font-variant-numeric: tabular-nums; }
        .slabel { font-size: 11.5px; font-weight: 600; margin-top: 1px; }
        .stext { font-size: 10px; color: var(--text-faint); line-height: 1.35; margin-top: 3px; }

        .vstate { font-size: 10px; font-weight: 700; padding: 3px 8px; border-radius: 20px; white-space: nowrap; border: 1px solid transparent; }
        .vstate.gain { color: var(--gain); border-color: var(--gain); }
        .vstate.loss { color: var(--loss); border-color: var(--loss); }
        .vstate.accent { color: var(--purple); border-color: var(--purple); }
        .vstate.muted { color: var(--text-muted); border-color: var(--panel-border); }
        .vstate.filled.gain { background: var(--gain-dim); }
        .vstate.filled.loss { background: var(--loss-dim); }
        .vstate.filled.accent { background: var(--purple-dim); }
        .conflict { font-size: 9.5px; font-weight: 600; color: var(--warn); margin-top: 3px; white-space: nowrap; cursor: help; }

        /* How a target was derived is part of the target. A 3xATR projection is
           arithmetic on volatility, not a level, and must not look like one. */
        .strength-strong { color: var(--gain); }
        .strength-moderate { color: var(--text-muted); }
        .strength-weak { color: var(--text-faint); font-style: italic; }
        .strength-none { color: var(--text-faint); }

        .exitr { font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 4px; }
        .exitr.target { background: var(--gain-dim); color: var(--gain); }
        .exitr.stop { background: var(--loss-dim); color: var(--loss); }
        .exitr.squareoff { background: var(--warn-dim); color: var(--warn); }
        .exitr.time { background: var(--canvas-soft); color: var(--text-muted); }

        tr.sel td { background: var(--purple-dim); }
        .toggle { padding: 7px 13px; border-radius: 9px; border: 1px solid var(--panel-border); background: var(--panel); font-size: 12px; font-weight: 600; color: var(--text-muted); cursor: pointer; }
        .toggle.on { border-color: var(--purple); color: var(--purple); background: var(--purple-dim); }
      `}</style>
    </div>
  );
}

/** Shown while a tab's first request is in flight.
 *
 * This exists because of a real misread: the momentum table rendered its "Nothing to show"
 * empty state whenever `board` was null, which is also true for the second or two before the
 * first response lands. A cold load therefore looked exactly like a module with no data, and
 * was reported as a bug when the API was answering correctly the whole time. Loading and
 * empty are different states and must never share a rendering. */
function TableSkeleton() {
  return (
    <div className="tskel" aria-busy="true" aria-label="Loading">
      {Array.from({ length: 7 }).map((_, i) => (
        <div className="trow" key={i}>
          <Skeleton height={13} width="18%" />
          <Skeleton height={13} width="26%" />
          <Skeleton height={13} width="12%" />
          <Skeleton height={13} width="12%" />
          <Skeleton height={13} width="22%" />
        </div>
      ))}
      <style jsx>{`
        .tskel { display: flex; flex-direction: column; gap: 10px; padding: 14px 4px; }
        .trow { display: flex; gap: 14px; align-items: center; }
      `}</style>
    </div>
  );
}

function Metric({ label, value, note, tone, muted }: {
  label: string; value: string; note?: string;
  tone?: "gain" | "loss"; muted?: boolean;
}) {
  return (
    <div className={muted ? "metric muted" : "metric"}>
      <div className="ml">{label}</div>
      <div className={`mv ${tone ?? ""}`}>{value}</div>
      {note && <div className="mn">{note}</div>}
      <style jsx>{`
        .metric { border: 1px solid var(--panel-border); border-radius: 11px; padding: 10px 13px; background: var(--panel); }
        .metric.muted { opacity: .6; }
        .ml { font-size: 10.5px; text-transform: uppercase; letter-spacing: .05em; color: var(--text-muted); }
        .mv { font-size: 18px; font-weight: 700; margin-top: 3px; font-variant-numeric: tabular-nums; }
        .mv.gain { color: var(--gain); }
        .mv.loss { color: var(--loss); }
        .mn { font-size: 10.5px; color: var(--text-faint); margin-top: 2px; }
      `}</style>
    </div>
  );
}
