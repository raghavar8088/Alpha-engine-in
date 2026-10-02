"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import DeskHistory from "../../components/DeskHistory";
import PageHeader from "../../components/PageHeader";
import ErrorBanner from "../../components/ErrorBanner";
import V2Validation from "./V2Validation";
import { AlarmBanner, EdgeReportPanel } from "./IntradayOps";
import LineChart from "../../components/charts/LineChart";
import {
  refreshing,
  IntradayDay,
  IntradayDeskStatus,
  IntradayEquityPoint,
  IntradayPosition,
  IntradayScore,
  IntradayTrade,
  LiveIntradaySummary,
  fetchIntradayDaily,
  fetchIntradayEquity,
  fetchIntradayLeaderboard,
  fetchIntradayStatus,
  fetchIntradayTrades,
  fetchLiveIntradayLeaderboard,
  fetchLiveIntradayPositions,
  fetchLiveIntradaySummary,
  fetchLiveIntradayTrades,
  fetchPatternSummary,
  fetchPatternLeaderboard,
  fetchPatternTimeframes,
  fetchPatternPositions,
  type PatternSummary,
  type PatternScore,
  type PatternTimeframeStat,
  type PatternPosition,
  fetchLiveIntradayDaily,
  fetchIntradayLabDaily,
  type DailyRoi,
  PatternBookKey,
  PatternBookSummary,
  PatternBookScore,
  PatternBookPosition,
  PatternBookTrade,
  fetchPatternBookSummary,
  fetchPatternBookLeaderboard,
  fetchPatternBookPositions,
  fetchPatternBookTrades,
} from "../../lib/api";

// The three live books are TABS rather than a dropdown because they are separate
// accounts, not a filter: switching replaces every number on the page.
type IntradayTab = "tournament" | "patterns" | "pb50k" | "pb2L" | "80k" | "30k" | "10k";
// Families as the desk names them, so a filter maps 1:1 onto the catalog.
const PAT_FAMILIES: { key: string; label: string }[] = [
  { key: "chart_pattern", label: "Chart patterns" },
  { key: "pattern", label: "Candlesticks" },
  { key: "trend", label: "Trend" },
  { key: "breakout", label: "Breakout" },
  { key: "momentum", label: "Momentum" },
  { key: "mean_reversion", label: "Mean reversion" },
];
// The pattern shortlist's two paper books. `tab` carries a "pb" prefix because "50k"
// alone would collide with the Live Intraday book keys, which are a different desk.
const PATTERN_BOOKS: { tab: "pb50k" | "pb2L"; key: PatternBookKey; label: string }[] = [
  { tab: "pb50k", key: "50k", label: "Paper Trade · ₹50k" },
  { tab: "pb2L", key: "2L", label: "Paper Trade · ₹2 lakh" },
];

const LIVE_BOOKS: { key: "80k" | "30k" | "10k"; capital: number }[] = [
  { key: "80k", capital: 80000 },
  { key: "30k", capital: 30000 },
  { key: "10k", capital: 10000 },
];

// Signed, because a return of "0.42%" and "-0.42%" must not look alike at a glance.
// Distinct from the file's existing `pct`, which formats an already-scaled percentage.
const roiPct = (v: number | null | undefined, dp = 2) =>
  `${(v ?? 0) >= 0 ? "+" : ""}${(v ?? 0).toFixed(dp)}%`;

/** Realised P&L per session, net of Angel One costs, expressed against desk capital. */
function DailyRoiPanel({ rows, capital }: { rows: DailyRoi[]; capital: number }) {
  return (
    <GlassPanel title={`Daily ROI — on ₹${capital.toLocaleString("en-IN")} desk capital`}>
      {rows.length === 0 ? (
        <div className="empty">No closed sessions yet.</div>
      ) : (
        <div className="table-scroll">
          <table className="data-table">
            <thead><tr><th style={{ textAlign: "left" }}>Date</th><th>Trades</th><th>Win %</th><th>Gross P&amp;L</th><th>Angel fees</th><th>Net P&amp;L</th><th>ROI</th></tr></thead>
            <tbody>
              {rows.map((d) => (
                <tr key={d.date}>
                  <td style={{ textAlign: "left" }}>{d.date}</td>
                  <td>{d.trades}</td>
                  <td>{(d.win_rate * 100).toFixed(1)}%</td>
                  <td className={d.gross_pnl >= 0 ? "gain" : "loss"}>{d.gross_pnl >= 0 ? "+" : ""}₹{inr(d.gross_pnl)}</td>
                  <td className="loss">−₹{inr(d.fees)}</td>
                  <td className={d.realized_pnl >= 0 ? "gain" : "loss"}>{d.realized_pnl >= 0 ? "+" : ""}₹{inr(d.realized_pnl)}</td>
                  <td className={d.roi_pct >= 0 ? "gain" : "loss"}>{roiPct(d.roi_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* styled-jsx scopes CSS to the component that declares it, and this panel is a
          component of its own — the page's .data-table rules below never reached it, so
          the table rendered with browser defaults. Same spec, declared where it applies. */}
      <style jsx>{`
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
        .data-table tbody tr:hover td { background: var(--canvas-soft); }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
      `}</style>
    </GlassPanel>
  );
}

/** Realised, unrealised and total P&L for any of this page's desks.
 *
 * Every tab's summary already carries the same three numbers against its own capital, so
 * one component serves all seven. Writing it per tab is how the same figure ends up
 * computed three slightly different ways — the tournament's ROI and a paper book's ROI
 * have to mean the same thing or the tabs cannot be compared at all.
 *
 * Each leg is shown against the SAME denominator, the desk's capital, so realised %,
 * unrealised % and total % add up. Showing unrealised against deployed capital instead
 * would read higher and would not sum.
 */
function PnlRow({
  capital, realized, unrealized, fees,
}: {
  capital: number | null | undefined;
  realized: number | null | undefined;
  unrealized: number | null | undefined;
  fees?: number | null;
}) {
  const cap = capital || 0;
  const r = realized ?? 0;
  const u = unrealized ?? 0;
  const total = r + u;
  const pc = (v: number) => (cap > 0 ? `${v >= 0 ? "+" : ""}${((v / cap) * 100).toFixed(3)}%` : "—");
  const money = (v: number) => `${v >= 0 ? "+" : "−"}₹${Math.abs(v).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
  const cls = (v: number) => (v > 0 ? "gain" : v < 0 ? "loss" : "");

  return (
    <div className="pnl-row">
      <div className="pnl-card">
        <div className="pnl-label">Realised P&amp;L</div>
        <div className={`pnl-value ${cls(r)}`}>{money(r)}</div>
        <div className={`pnl-pct ${cls(r)}`}>{pc(r)}</div>
        <div className="pnl-sub">booked on closed trades{fees != null && fees !== 0 ? `, after ₹${Math.abs(fees).toLocaleString("en-IN", { maximumFractionDigits: 0 })} costs` : ""}</div>
      </div>
      <div className="pnl-card">
        <div className="pnl-label">Unrealised P&amp;L</div>
        <div className={`pnl-value ${cls(u)}`}>{money(u)}</div>
        <div className={`pnl-pct ${cls(u)}`}>{pc(u)}</div>
        <div className="pnl-sub">open positions, marked live</div>
      </div>
      <div className="pnl-card total">
        <div className="pnl-label">Total P&amp;L</div>
        <div className={`pnl-value ${cls(total)}`}>{money(total)}</div>
        <div className={`pnl-pct ${cls(total)}`}>{pc(total)}</div>
        <div className="pnl-sub">realised + unrealised, on ₹{cap.toLocaleString("en-IN")}</div>
      </div>

      <style jsx>{`
        .pnl-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 10px; }
        .pnl-card { border: 1px solid var(--panel-border); border-radius: 12px; padding: 12px 14px;
                    background: var(--panel); }
        .pnl-card.total { background: var(--canvas-soft); border-color: rgba(125, 52, 220, 0.28); }
        .pnl-label { font-size: 10px; font-weight: 700; letter-spacing: 0.06em;
                     text-transform: uppercase; color: var(--text-faint); }
        .pnl-value { font-size: 21px; font-weight: 750; font-variant-numeric: tabular-nums;
                     margin-top: 4px; letter-spacing: -0.3px; }
        .pnl-pct { font-size: 12.5px; font-weight: 650; font-variant-numeric: tabular-nums;
                   margin-top: 1px; }
        .pnl-sub { margin-top: 4px; font-size: 10.5px; color: var(--text-faint); line-height: 1.4; }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
      `}</style>
    </div>
  );
}

/** Which desk each tab's history belongs to. The pattern desk and the two pattern books
 *  are registered server-side alongside the tournament and the Live Intraday books. */
const HISTORY_SCOPE: Record<IntradayTab, { deskKey: string; scope?: string; label: string }> = {
  tournament: { deskKey: "intraday-lab", label: "Tournament" },
  patterns: { deskKey: "pattern", label: "Pattern desk" },
  pb50k: { deskKey: "pattern-books", scope: "50k", label: "Paper Trade · ₹50k" },
  pb2L: { deskKey: "pattern-books", scope: "2L", label: "Paper Trade · ₹2 lakh" },
  "80k": { deskKey: "live-intraday", scope: "80k", label: "Live Intraday · ₹80k" },
  "30k": { deskKey: "live-intraday", scope: "30k", label: "Live Intraday · ₹30k" },
  "10k": { deskKey: "live-intraday", scope: "10k", label: "Live Intraday · ₹10k" },
};

/** What a tab shows before its data has arrived, or when it could not be loaded.
 *
 *  Without this the tiles rendered their empty defaults — "₹-", "0 strategies", "+0.00%",
 *  "IDLE" — whenever a load was slow or failed, which reads exactly like a real desk that
 *  has done nothing. A desk with no data and a desk we could not reach must never look the
 *  same. Once a tab HAS loaded, a later failed refresh keeps the last good figures on screen
 *  but marks them stale with the time they were taken. Styles live here, not in the page:
 *  styled-jsx scopes CSS to the component that declares it. */
function DataGate({
  ready, error, what, onRetry, lastOkAt, children,
}: {
  ready: boolean;
  error: string | null;
  what: string;
  onRetry: () => void;
  lastOkAt: Date | null;
  children: React.ReactNode;
}) {
  if (!ready) {
    if (error) {
      return (
        <ErrorBanner
          onRetry={onRetry}
          message={`Couldn't load ${what}. ${error} Nothing is shown rather than zeros that would look like a real, empty desk.`}
        />
      );
    }
    return (
      <div className="gate">
        Loading {what}…
        <style jsx>{`
          .gate { border: 1px dashed var(--panel-border); border-radius: 12px; padding: 22px 20px;
                  background: var(--canvas-soft); font-size: 13px; color: var(--text-muted); }
        `}</style>
      </div>
    );
  }
  return (
    <>
      {error && (
        <ErrorBanner
          onRetry={onRetry}
          message={`${lastOkAt
            ? `Showing figures from ${lastOkAt.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}`
            : "Showing earlier figures"} — the latest refresh failed, so they are not current. ${error}`}
        />
      )}
      {children}
    </>
  );
}

const REFRESH_MS = 15000;

const inr = (v: number | null | undefined) =>
  v === null || v === undefined ? "-" : v.toLocaleString("en-IN", { maximumFractionDigits: 0 });
const inr2 = (v: number | null | undefined) =>
  v === null || v === undefined ? "-" : v.toLocaleString("en-IN", { maximumFractionDigits: 2 });
const pct = (v: number | null | undefined, d = 1) =>
  v === null || v === undefined ? "-" : `${v.toFixed(d)}%`;

/** How each price was sourced. Angel is the desk's primary equity feed; a Dhan or
 *  last-bar mark is the honest fallback and is labelled so the page never implies a
 *  live Angel print when the number came from somewhere else. */
function SourcePill({ source }: { source: string | null | undefined }) {
  const label =
    source === "angel_quote" ? "ANGEL" :
    source === "dhan_quote" ? "DHAN" :
    source === "last_bar_close" ? "LAST BAR" : (source ?? "-");
  const cls = source === "angel_quote" ? "src angel" : source === "dhan_quote" ? "src dhan" : "src stale";
  return (
    <span className={cls}>
      {label}
      {/* Declared here for the same reason as DailyRoiPanel: the page's .src rules are
          scoped to the page component and never applied to this one. */}
      <style jsx>{`
        .src {
          display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 9.5px;
          font-weight: 700; letter-spacing: 0.04em; border: 1px solid var(--panel-border);
        }
        .src.angel { background: rgba(34, 170, 96, 0.12); border-color: rgba(34, 170, 96, 0.3); }
        .src.dhan { background: var(--canvas-soft); }
        .src.stale { background: var(--loss-dim); border-color: rgba(217, 45, 63, 0.3); }
      `}</style>
    </span>
  );
}

export default function IntradayStocksPage() {
  const [tab, setTab] = useState<IntradayTab>("tournament");
  const [status, setStatus] = useState<IntradayDeskStatus | null>(null);
  const [scores, setScores] = useState<IntradayScore[]>([]);
  const [trades, setTrades] = useState<IntradayTrade[]>([]);
  const [equity, setEquity] = useState<IntradayEquityPoint[]>([]);
  const [days, setDays] = useState<IntradayDay[]>([]);
  // Each data source keeps its OWN error and last-good time. They used to share one `error`,
  // so the tournament poll — which runs on every tab — cleared a failure on the Live tab
  // fifteen seconds later and the failure vanished from the screen with nothing loaded.
  const [errs, setErrs] = useState<Record<string, string | null>>({});
  const [okAt, setOkAt] = useState<Record<string, Date>>({});
  const settle = useCallback((src: string, err: string | null) => {
    setErrs((m) => ({ ...m, [src]: err }));
    if (!err) setOkAt((m) => ({ ...m, [src]: new Date() }));
  }, []);
  // One load of each kind at a time. Without this a slow backend gets a fresh batch of five
  // requests every 15 s on top of the ones it has not answered yet.
  const inflight = useRef(new Set<string>());
  const once = useCallback(async (key: string, fn: () => Promise<void>) => {
    if (inflight.current.has(key)) return;
    inflight.current.add(key);
    try {
      await fn();
    } finally {
      inflight.current.delete(key);
    }
  }, []);

  // Live Intraday desk (curated ₹80k shortlist)
  const [liveSummary, setLiveSummary] = useState<LiveIntradaySummary | null>(null);
  const [liveScores, setLiveScores] = useState<IntradayScore[]>([]);
  const [livePositions, setLivePositions] = useState<IntradayPosition[]>([]);
  const [liveTrades, setLiveTrades] = useState<IntradayTrade[]>([]);
  const [liveDaily, setLiveDaily] = useState<DailyRoi[]>([]);
  const [labDaily, setLabDaily] = useState<DailyRoi[]>([]);
  // Only the three book tabs name a book; tournament and patterns are their own
  // views, so both must fall back rather than leak a non-book value downstream.
  const liveBook: "80k" | "30k" | "10k" =
    tab === "tournament" || tab === "patterns" || tab === "pb50k" || tab === "pb2L"
      ? "80k"
      : tab;
  const isLive =
    tab !== "tournament" && tab !== "patterns" && tab !== "pb50k" && tab !== "pb2L";
  const bookCapital = LIVE_BOOKS.find((b) => b.key === liveBook)?.capital ?? 80000;

  // Pattern paper books (₹50k / ₹2L) — the shortlist at a real account's size.
  const [pbSummary, setPbSummary] = useState<PatternBookSummary | null>(null);
  const [pbBoard, setPbBoard] = useState<PatternBookScore[]>([]);
  const [pbOpen, setPbOpen] = useState<PatternBookPosition[]>([]);
  const [pbDeclined, setPbDeclined] = useState<PatternBookPosition[]>([]);
  const [pbTrades, setPbTrades] = useState<PatternBookTrade[]>([]);
  const isPatternBook = tab === "pb50k" || tab === "pb2L";
  const pbKey: PatternBookKey = tab === "pb2L" ? "2L" : "50k";

  const [patSummary, setPatSummary] = useState<PatternSummary | null>(null);
  const [patBoard, setPatBoard] = useState<PatternScore[]>([]);
  const [patFrames, setPatFrames] = useState<PatternTimeframeStat[]>([]);
  const [patOpen, setPatOpen] = useState<PatternPosition[]>([]);
  const [patTf, setPatTf] = useState<string | null>(null);
  const [patFam, setPatFam] = useState<string | null>(null);
  // Which filter a pattern load was started for. A load that finishes after the filter has
  // changed is dropped, so an old answer never paints over the view the user asked for.
  const patKey = `${patTf ?? ""}|${patFam ?? ""}`;
  const patKeyRef = useRef(patKey);
  const liveBookRef = useRef(liveBook);
  const pbKeyRef = useRef(pbKey);

  const loadPatterns = useCallback(async () => {
    try {
      const [s, lb, tf, op] = await Promise.all([
        fetchPatternSummary(),
        fetchPatternLeaderboard(patTf ?? undefined, patFam ?? undefined),
        fetchPatternTimeframes(),
        fetchPatternPositions("OPEN", patTf ?? undefined),
      ]);
      if (patKeyRef.current !== patKey) return;     // the filter changed while this ran
      setPatSummary(s); setPatBoard(lb); setPatFrames(tf); setPatOpen(op);
      settle("patterns", null);
    } catch (e) {
      if (patKeyRef.current !== patKey) return;
      settle("patterns", e instanceof Error ? e.message : "Failed to load the pattern desk");
    }
  }, [patTf, patFam, patKey, settle]);

  useEffect(() => {
    patKeyRef.current = patKey;
  }, [patKey]);

  useEffect(() => {
    if (tab !== "patterns") return;
    const run = () => once(`patterns:${patKey}`, loadPatterns);
    run();
    const id = setInterval(run, REFRESH_MS);
    return () => clearInterval(id);
  }, [tab, patKey, loadPatterns, once]);

  const loadPatternBook = useCallback(async () => {
    try {
      const [sm, lb, op, dec, tr] = await Promise.all([
        fetchPatternBookSummary(pbKey),
        fetchPatternBookLeaderboard(pbKey),
        fetchPatternBookPositions(pbKey, "OPEN"),
        fetchPatternBookPositions(pbKey, "ALL"),
        fetchPatternBookTrades(pbKey, 60),
      ]);
      if (pbKeyRef.current !== pbKey) return;       // the user switched book while this ran
      setPbSummary(sm);
      setPbBoard(lb.rows ?? []);
      setPbOpen(op);
      // Signals this book could not afford. Fetched from ALL and filtered here rather
      // than given their own endpoint — they are positions that were never taken, and
      // keeping them in the same collection is what stops one being counted twice.
      setPbDeclined((dec ?? []).filter((r) => r.status === "DECLINED"));
      setPbTrades(tr);
      settle(`book:${pbKey}`, null);
    } catch (e) {
      settle(`book:${pbKey}`, e instanceof Error ? e.message : "Failed to load the pattern paper book");
    }
  }, [pbKey, settle]);

  // A different book is a different account: hide the previous one's figures until this
  // one's arrive, rather than showing ₹50k numbers under the ₹2L tab for a refresh cycle.
  useEffect(() => {
    pbKeyRef.current = pbKey;
    setPbSummary(null);
  }, [pbKey]);

  useEffect(() => {
    if (!isPatternBook) return;
    const run = () => once(`book:${pbKey}`, loadPatternBook);
    run();
    const id = setInterval(run, REFRESH_MS);
    return () => clearInterval(id);
  }, [isPatternBook, pbKey, loadPatternBook, once]);

  const load = useCallback(async () => {
    try {
      const [s, l, t, e, d] = await Promise.all([
        fetchIntradayStatus(),
        fetchIntradayLeaderboard(),
        fetchIntradayTrades(100),
        fetchIntradayEquity(500),
        fetchIntradayDaily(60),
      ]);
      setStatus(s);
      setScores(l);
      setTrades(t);
      setEquity(e);
      setDays(d);
      setLabDaily(await fetchIntradayLabDaily(60));
      settle("tournament", null);
    } catch (err) {
      settle("tournament", err instanceof Error ? err.message : "Failed to load the intraday desk");
    }
  }, [settle]);

  const [isRefreshing, setIsRefreshing] = useState(false);
  const handleRefresh = useCallback(async () => {
    setIsRefreshing(true);
    try {
      await refreshing(() => load());
    } finally {
      setIsRefreshing(false);
    }
  }, [load]);

  const loadLive = useCallback(async () => {
    try {
      const [lb, pos, tr, dl] = await Promise.all([
        fetchLiveIntradayLeaderboard(liveBook),
        fetchLiveIntradayPositions(liveBook),
        fetchLiveIntradayTrades(100, liveBook),
        fetchLiveIntradayDaily(liveBook),
      ]);
      if (liveBookRef.current !== liveBook) return;   // the user switched book while this ran
      setLiveScores(lb);
      setLivePositions(pos.positions);
      setLiveSummary(pos.summary);
      setLiveTrades(tr);
      setLiveDaily(dl);
      settle(`live:${liveBook}`, null);
    } catch (err) {
      settle(`live:${liveBook}`, err instanceof Error ? err.message : "Failed to load the Live Intraday desk");
    }
  }, [liveBook, settle]);

  useEffect(() => {
    const run = () => once("tournament", load);
    run();
    const id = setInterval(run, REFRESH_MS);
    return () => clearInterval(id);
  }, [load, once]);

  useEffect(() => {
    liveBookRef.current = liveBook;
    setLiveSummary(null);
  }, [liveBook]);

  useEffect(() => {
    if (!isLive) return;
    const run = () => once(`live:${liveBook}`, loadLive);
    run();
    const id = setInterval(run, REFRESH_MS);
    return () => clearInterval(id);
  }, [isLive, liveBook, loadLive, once]);

  // The source behind the tab on screen — its failure is the one the banner and gate show.
  const src =
    tab === "tournament" ? "tournament" :
    tab === "patterns" ? "patterns" :
    isPatternBook ? `book:${pbKey}` : `live:${liveBook}`;
  const error = errs[src] ?? null;
  const lastOkAt = okAt[src] ?? null;

  const heartbeatAge = status?.heartbeat
    ? (Date.now() - new Date(status.heartbeat).getTime()) / 1000
    : null;
  // The scheduler ticks every ~3 min, so a heartbeat under ~4.5 min old means live.
  const live = Boolean(status?.heartbeat && heartbeatAge !== null && heartbeatAge < 270);
  const todayPnl = days[0]?.net_pnl ?? 0;
  const totalPnl = status?.realized_pnl ?? 0;
  const winners = scores.filter((s) => s.net_pnl > 0).length;
  const feedLabel =
    status?.feed_source === "angel" ? "Angel One (live)" :
    status?.feed_source === "dhan" ? "Dhan (fallback)" : "no live feed";

  return (
    <div className="page">
      <PageHeader
        onRefresh={handleRefresh}
        refreshing={isRefreshing}
        crumb="Intraday Stocks"
        title="Intraday Stocks"
        subtitle="Paper strategy-selection tournament on the 200 most-traded NSE stocks. Every strategy decides on real 15-minute, 45-minute and 1-hour bars from Angel One's live stream, trades both sides (MIS shorts included) with its own ₹10 lakh account split into five ₹2 lakh slots, and pays real Angel One costs plus slippage. Entries only between 09:45 and 14:30 IST; everything is flat by 15:05 in closing-auction (F&O) stocks and 15:12 in the rest."
      />

      <div className="tabs">
        <button className={tab === "tournament" ? "tab active" : "tab"} onClick={() => setTab("tournament")}>
          Tournament · {status?.strategy_count ?? 52} strategies
        </button>
        <button className={tab === "patterns" ? "tab active" : "tab"} onClick={() => setTab("patterns")}>
          Patterns · {patSummary?.strategy_count ?? 504}
        </button>
        {PATTERN_BOOKS.map((b) => (
          <button
            key={b.tab}
            className={tab === b.tab ? "tab active" : "tab"}
            onClick={() => setTab(b.tab)}
          >
            {b.label}
          </button>
        ))}
        {LIVE_BOOKS.map((b) => (
          <button
            key={b.key}
            className={tab === b.key ? "tab active" : "tab"}
            onClick={() => setTab(b.key)}
          >
            Live Intraday · ₹{b.key}
          </button>
        ))}
      </div>

      {tab === "tournament" && (
      <DataGate ready={!!status} error={error} what={"the tournament"} onRetry={() => once("tournament", load)} lastOkAt={lastOkAt}>
      <AlarmBanner />
      <div className="desk-banner">
        <strong>V2 — REAL INTRADAY BARS, BOTH SIDES.</strong> Each rule is evaluated once, at the
        close of its own 15m, 45m or 1h bar, and its stop and target are sized in that
        bar&rsquo;s ATR. Trend rules trade only with NIFTY&rsquo;s direction on the day; fade
        rules skip stocks that are in play. Stops and targets fill where they would really
        have triggered — found on the stream&rsquo;s minute bars, stop first when one minute
        crosses both — and every market fill pays slippage by liquidity plus Angel One&rsquo;s
        intraday costs. The record restarted on 5 Oct 2026; nothing before it is comparable.
      </div>

      {status?.paused && (
        <div className="breaker">
          <strong>NEW ENTRIES PAUSED</strong> (INTRADAY_LAB_PAUSE_ENTRIES). Every already-open
          position is still being marked, stopped, targeted and squared off normally; nothing
          new is being opened.
        </div>
      )}

      {status && status.feed_source !== "angel" && (
        <div className="feed-note">
          <strong>Feed: {feedLabel}.</strong>{" "}
          {status.feed_source === "none"
            ? "Neither Angel One nor Dhan answered the last cycle — only daily-bar swing signals can fire and marks fall back to last-bar-close. Angel One live prices flow only from the whitelisted host."
            : "Running on the Dhan fallback — Angel One live prices flow only from the whitelisted host."}
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
          <div className="tile-value">₹{inr(status?.equity)}</div>
          <div className="tile-sub">from ₹{inr(status?.initial_capital)} paper</div>
        </div>
        <div className="tile">
          <div className="tile-label">ROI</div>
          <div className={`tile-value ${(status?.roi_pct ?? 0) >= 0 ? "gain" : "loss"}`}>
            {roiPct(status?.roi_pct, 2)}
          </div>
          <div className="tile-sub">on ₹{inr(status?.initial_capital)} desk capital</div>
        </div>
        <div className="tile">
          <div className="tile-label">Today P&amp;L</div>
          <div className={`tile-value ${todayPnl >= 0 ? "gain" : "loss"}`}>
            {todayPnl >= 0 ? "+" : ""}₹{inr(todayPnl)}
          </div>
          <div className="tile-sub">{roiPct(status?.today_roi_pct)} today · {days[0]?.session ?? "no closes yet"}</div>
        </div>
        <div className="tile">
          <div className="tile-label">Angel fees paid</div>
          <div className="tile-value loss">−₹{inr(status?.total_fees)}</div>
          <div className="tile-sub">gross ₹{inr(status?.gross_realized_pnl)} before costs</div>
        </div>
        <div className="tile">
          <div className="tile-label">Deployed capital</div>
          <div className="tile-value">₹{inr(status?.deployed_capital)}</div>
          <div className="tile-sub">₹{inr(status?.available_cash)} free</div>
        </div>
        <div className="tile">
          <div className="tile-label">Open positions</div>
          <div className="tile-value">{status?.open_positions ?? 0}</div>
          <div className="tile-sub">₹{inr(status?.unrealized_pnl)} unrealised</div>
        </div>
        <div className="tile">
          <div className="tile-label">Strategies</div>
          <div className="tile-value">{status?.strategy_count ?? 0}</div>
          <div className="tile-sub">{winners} in profit · feed {status?.feed_source ?? "-"}</div>
        </div>
        <div className="tile">
          <div className="tile-label">Track record</div>
          <div className={`tile-value ${totalPnl >= 0 ? "gain" : "loss"}`}>
            {totalPnl >= 0 ? "+" : ""}₹{inr(totalPnl)}
          </div>
          <div className="tile-sub">{status?.closed_positions ?? 0} trades closed</div>
        </div>
      </div>

      <PnlRow capital={status?.initial_capital} realized={status?.realized_pnl}
              unrealized={status?.unrealized_pnl} fees={status?.total_fees} />

      {equity.length > 1 && (
        <GlassPanel title="Equity">
          <LineChart
            points={equity.map((p) => ({ ts: p.ts, value: p.equity }))}
            height={200}
            formatValue={(v) => `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`}
          />
        </GlassPanel>
      )}

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
                  <th>Side</th>
                  <th>Qty</th>
                  <th>Entry</th>
                  <th>LTP</th>
                  <th>Src</th>
                  <th>Target</th>
                  <th>Stop</th>
                  <th>Unrealised</th>
                  <th>Opened</th>
                </tr>
              </thead>
              <tbody>
                {status.open_positions_detail.map((p: IntradayPosition) => (
                  <tr key={p.position_id}>
                    <td style={{ textAlign: "left" }}>{p.display_name || p.symbol}</td>
                    <td style={{ textAlign: "left", fontSize: 11 }} title={p.fill_basis || p.rationale}>{p.strategy_name}</td>
                    <td className={p.side === "SELL" ? "loss" : "gain"} style={{ fontWeight: 700, fontSize: 11 }}>
                      {p.side === "SELL" ? "SHORT" : "LONG"}
                    </td>
                    <td>{p.qty}</td>
                    <td>₹{inr2(p.entry_price)}</td>
                    <td>₹{inr2(p.ltp)}</td>
                    <td><SourcePill source={p.ltp_source} /></td>
                    <td>{p.target != null ? `₹${inr2(p.target)}` : "close"}</td>
                    <td>₹{inr2(p.stoploss)}</td>
                    <td className={(p.unrealized_pnl ?? 0) >= 0 ? "gain" : "loss"}>
                      {(p.unrealized_pnl ?? 0) >= 0 ? "+" : ""}₹{inr(p.unrealized_pnl)}
                    </td>
                    <td style={{ fontSize: 10.5 }}>
                      {p.opened_at ? new Date(p.opened_at).toLocaleString() : "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>

      <div className="gate-note">
        <strong>Ranked by P&amp;L, judged by the gate.</strong> The top of a{" "}
        {status?.gate?.strategies_tested ?? scores.length}-strategy board is where luck
        collects: run that many and a handful finish well ahead having proved nothing. A
        strategy is only <strong>READY</strong> if its record would be surprising from a
        strategy with <em>no edge</em> — which needs a t-statistic of{" "}
        <strong>{(status?.gate?.t_threshold ?? 1.96).toFixed(2)}</strong>, not the usual
        1.96, precisely because so many were tried at once.{" "}
        {typeof status?.ready_count === "number" && (
          <>
            Currently <strong>{status.ready_count} READY</strong>,{" "}
            {status.rejected_count ?? 0} rejected, {status.pending_count ?? 0} still too
            short to judge. <em>Zero READY is the normal, honest answer</em> — it means
            nothing here has yet earned real money.
          </>
        )}
      </div>

      <GlassPanel title="Strategy leaderboard">
        {!scores.length ? (
          <div className="empty">No strategy stats yet.</div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Strategy</th>
                  <th style={{ textAlign: "left" }}>Category</th>
                  <th>Trades</th>
                  <th>Win %</th>
                  <th>PF</th>
                  <th>t-stat</th>
                  <th>Net P&amp;L</th>
                  <th>Allocated</th>
                  <th>Verdict</th>
                </tr>
              </thead>
              <tbody>
                {scores.map((s) => {
                  const bar = s.t_threshold ?? status?.gate?.t_threshold ?? 1.96;
                  const clears = (s.t_stat ?? -99) >= bar;
                  return (
                  <tr key={s.strategy_id}>
                    <td style={{ textAlign: "left" }}>{s.name}</td>
                    <td style={{ textAlign: "left" }}>
                      <span className="badge">{s.category}</span>
                    </td>
                    <td>{s.trades}</td>
                    <td>{s.trades ? `${(s.win_rate * 100).toFixed(1)}%` : "-"}</td>
                    <td>{s.profit_factor == null ? "-" : s.profit_factor.toFixed(2)}</td>
                    <td className={clears ? "gain" : ""} title={`needs ${bar.toFixed(2)}`}>
                      {s.t_stat == null ? "-" : s.t_stat.toFixed(2)}
                    </td>
                    <td className={s.net_pnl >= 0 ? "gain" : "loss"}>
                      {s.net_pnl >= 0 ? "+" : ""}₹{inr(s.net_pnl)}
                    </td>
                    <td>₹{inr(s.allocated_capital)}</td>
                    <td>
                      <span className={`badge ${s.verdict === "READY" ? "gain" : s.verdict === "REJECTED" ? "loss" : ""}`}>
                        {s.verdict ?? "—"}
                      </span>
                    </td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>

      <EdgeReportPanel />

      <V2Validation />

      <DailyRoiPanel rows={labDaily} capital={status?.initial_capital ?? 0} />

      <GlassPanel title="Recent paper trades">
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
                  <th>Reason</th>
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
                    <td>
                      <span className={`badge ${t.exit_reason === "stoploss" ? "loss" : ""}`}>
                        {t.exit_reason}
                      </span>
                    </td>
                    <td className={t.realized_pnl >= 0 ? "gain" : "loss"}>
                      {t.realized_pnl >= 0 ? "+" : ""}₹{inr(t.realized_pnl)}
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
      </DataGate>
      )}

      {tab === "patterns" && (
      <DataGate ready={!!patSummary} error={error} what={"the pattern desk"} onRetry={() => once(`patterns:${patKey}`, loadPatterns)} lastOkAt={lastOkAt}>
      <div className="desk-banner">
        <strong>PATTERN DESK · {patSummary?.template_count ?? 63} TEMPLATES × {patSummary?.timeframes?.length ?? 8} TIMEFRAMES.</strong>{" "}
        13 geometric chart patterns (head &amp; shoulders, double/triple tops, triangles,
        wedges, flags, pennants, cup &amp; handle, rounding, diamond, broadening), 10
        candlestick patterns, and 40 indicator/structure rules — each on its own{" "}
        ₹{inr(patSummary?.per_strategy_capital)}. Runs alongside the 150-strategy tournament,
        not instead of it. <strong>45m and 4h are aggregated</strong>; Angel has no native
        interval for either. Universe is capped at{" "}
        <strong>{patSummary?.universe_size ?? 25} symbols</strong> because Angel&rsquo;s candle
        endpoint rate-limits far harder than its quotes — 150 symbols × 8 timeframes would be
        1,200 requests a cycle. P&amp;L is net of real Angel One costs.
      </div>

      <div className="tiles">
        <div className="tile"><div className="tile-label">Mode</div><div className="tile-value gain">PAPER</div><div className="tile-sub">{patSummary?.enabled ? "armed · live Angel" : "disabled"}</div></div>
        <div className="tile"><div className="tile-label">Desk capital</div><div className="tile-value">₹{inr(patSummary?.initial_capital)}</div><div className="tile-sub">{patSummary?.strategy_count ?? 0} × ₹{inr(patSummary?.per_strategy_capital)}</div></div>
        <div className="tile"><div className="tile-label">Equity</div><div className="tile-value">₹{inr(patSummary?.equity)}</div><div className="tile-sub">₹{inr(patSummary?.unrealized_pnl)} unrealised</div></div>
        <div className="tile"><div className="tile-label">ROI</div><div className={`tile-value ${(patSummary?.roi_pct ?? 0) >= 0 ? "gain" : "loss"}`}>{roiPct(patSummary?.roi_pct)}</div><div className="tile-sub">on desk capital</div></div>
        <div className="tile"><div className="tile-label">Angel fees</div><div className="tile-value loss">−₹{inr(patSummary?.total_fees)}</div><div className="tile-sub">gross ₹{inr(patSummary?.gross_realized_pnl)} before costs</div></div>
        <div className="tile"><div className="tile-label">Open positions</div><div className="tile-value">{patSummary?.open_positions ?? 0}</div><div className="tile-sub">₹{inr(patSummary?.deployed_capital)} deployed</div></div>
        <div className="tile"><div className="tile-label">Closed</div><div className="tile-value">{patSummary?.closed_positions ?? 0}</div><div className="tile-sub">{(patSummary?.last_evaluated ?? 0).toLocaleString("en-IN")} evaluated last cycle</div></div>
      </div>

      <PnlRow capital={patSummary?.initial_capital} realized={patSummary?.realized_pnl}
              unrealized={patSummary?.unrealized_pnl} fees={patSummary?.total_fees} />

      {!!patSummary?.last_notes?.length && (
        <div className="feed-note">{patSummary.last_notes.join(" · ")}</div>
      )}

      <div className="tabs">
        <button className={patTf === null ? "tab active" : "tab"} onClick={() => setPatTf(null)}>All timeframes</button>
        {(patSummary?.timeframes ?? []).map((t) => (
          <button key={t.key} className={patTf === t.key ? "tab active" : "tab"} onClick={() => setPatTf(t.key)}>
            {t.key}{t.native ? "" : "*"}
          </button>
        ))}
      </div>
      <div className="tabs">
        <button className={patFam === null ? "tab active" : "tab"} onClick={() => setPatFam(null)}>All families</button>
        {PAT_FAMILIES.map((f) => (
          <button key={f.key} className={patFam === f.key ? "tab active" : "tab"} onClick={() => setPatFam(f.key)}>
            {f.label}
          </button>
        ))}
      </div>

      <GlassPanel title="Which horizon is working — every template aggregated per candle">
        <div className="table-scroll">
          <table className="data-table">
            <thead><tr><th style={{ textAlign: "left" }}>Candle</th><th>Style</th><th>Strategies</th><th>Capital</th><th>Trades</th><th>Win %</th><th>Fees</th><th>Net P&amp;L</th><th>ROI</th></tr></thead>
            <tbody>
              {patFrames.map((f) => (
                <tr key={f.timeframe}>
                  <td style={{ textAlign: "left" }}><strong>{f.label}</strong></td>
                  <td>{f.style}</td>
                  <td>{f.strategies}</td>
                  <td>₹{inr(f.capital)}</td>
                  <td>{f.trades}</td>
                  <td>{(f.win_rate * 100).toFixed(1)}%</td>
                  <td className="loss">−₹{inr(f.fees)}</td>
                  <td className={f.net_pnl >= 0 ? "gain" : "loss"}>{f.net_pnl >= 0 ? "+" : ""}₹{inr(f.net_pnl)}</td>
                  <td className={f.roi_pct >= 0 ? "gain" : "loss"}>{roiPct(f.roi_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </GlassPanel>

      <GlassPanel title={`Strategy leaderboard (${patBoard.length})`}>
        <div className="table-scroll">
          <table className="data-table">
            <thead><tr><th style={{ textAlign: "left" }}>Template</th><th>TF</th><th>Family</th><th>Style</th><th>Trades</th><th>Win %</th><th>Fees</th><th>Net P&amp;L</th><th>ROI</th></tr></thead>
            <tbody>
              {patBoard.slice(0, 200).map((r) => (
                <tr key={r.strategy_id}>
                  <td style={{ textAlign: "left" }}>{r.template}</td>
                  <td><span className="badge">{r.timeframe}</span></td>
                  <td style={{ fontSize: 11 }}>{r.family}</td>
                  <td style={{ fontSize: 11 }}>{r.style}</td>
                  <td>{r.trades}</td>
                  <td>{(r.win_rate * 100).toFixed(1)}%</td>
                  <td className="loss">−₹{inr(r.fees)}</td>
                  <td className={r.net_pnl >= 0 ? "gain" : "loss"}>{r.net_pnl >= 0 ? "+" : ""}₹{inr(r.net_pnl)}</td>
                  <td className={r.roi_pct >= 0 ? "gain" : "loss"}>{roiPct(r.roi_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </GlassPanel>

      <GlassPanel title={`Open positions (${patOpen.length})`}>
        {!patOpen.length ? (
          <div className="empty">No open positions — entries run during market hours up to 14:30 IST.</div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th style={{ textAlign: "left" }}>Template</th><th>TF</th><th>Symbol</th><th>Side</th><th>Qty</th><th>Entry</th><th>LTP</th><th>Target</th><th>Stop</th><th>Unrealised</th></tr></thead>
              <tbody>
                {patOpen.map((p) => (
                  <tr key={p.position_id}>
                    <td style={{ textAlign: "left", fontSize: 11 }}>{p.template}</td>
                    <td><span className="badge">{p.timeframe}</span></td>
                    <td>{p.symbol}</td>
                    <td><span className={p.side === "SELL" ? "badge loss" : "badge"}>{p.side}</span></td>
                    <td>{p.qty}</td>
                    <td>₹{inr2(p.entry_price)}</td>
                    <td>₹{inr2(p.ltp)}</td>
                    <td>₹{inr2(p.target)}</td>
                    <td>₹{inr2(p.stoploss)}</td>
                    <td className={(p.unrealized_pnl ?? 0) >= 0 ? "gain" : "loss"}>{(p.unrealized_pnl ?? 0) >= 0 ? "+" : ""}₹{inr(p.unrealized_pnl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>
      </DataGate>
      )}

      {isPatternBook && (
      <DataGate ready={!!pbSummary} error={error} what={"this paper book"} onRetry={() => once(`book:${pbKey}`, loadPatternBook)} lastOkAt={lastOkAt}>
      <div className="desk-banner">
        <strong>PATTERN PAPER BOOK · ₹{inr(pbSummary?.desk_capital)}.</strong> The{" "}
        <strong>{pbSummary?.strategies ?? 8} shortlisted pattern strategies</strong> run here on{" "}
        ₹{inr(pbSummary?.per_strategy_allocation)} each. Both books trade the{" "}
        <em>same signals at the same fills</em> as the Patterns desk — they mirror its entries and
        exits rather than re-scanning, so any difference between ₹50k and ₹2 lakh is caused by{" "}
        <strong>account size and nothing else</strong>. Sizing is whole shares and{" "}
        <strong>P&amp;L is net of real Angel One costs</strong>, which is the point: a near-fixed
        round-trip fee is a far heavier drag on the smaller book, and a slice that cannot buy one
        share simply does not take the trade.
      </div>

      <div className="tiles">
        <div className="tile"><div className="tile-label">Mode</div><div className="tile-value gain">PAPER</div><div className="tile-sub">{pbSummary?.enabled ? "mirrors the pattern desk" : "disabled"}</div></div>
        <div className="tile"><div className="tile-label">Desk capital</div><div className="tile-value">₹{inr(pbSummary?.desk_capital)}</div><div className="tile-sub">{pbSummary?.strategies ?? 0} × ₹{inr(pbSummary?.per_strategy_allocation)}</div></div>
        <div className="tile"><div className="tile-label">Equity</div><div className="tile-value">₹{inr2(pbSummary?.equity)}</div><div className="tile-sub">₹{inr2(pbSummary?.unrealized_pnl)} unrealised</div></div>
        <div className="tile"><div className="tile-label">ROI</div><div className={`tile-value ${(pbSummary?.roi_pct ?? 0) >= 0 ? "gain" : "loss"}`}>{roiPct(pbSummary?.roi_pct)}</div><div className="tile-sub">on ₹{inr(pbSummary?.desk_capital)} book</div></div>
        <div className="tile"><div className="tile-label">Angel fees</div><div className="tile-value loss">−₹{inr2(pbSummary?.fees)}</div><div className="tile-sub">gross ₹{inr2(pbSummary?.gross_pnl)} before costs</div></div>
        <div className="tile"><div className="tile-label">Open positions</div><div className="tile-value">{pbSummary?.open_positions ?? 0}</div><div className="tile-sub">₹{inr2(pbSummary?.deployed)} deployed</div></div>
        <div className="tile"><div className="tile-label">Closed</div><div className="tile-value">{pbSummary?.closed_positions ?? 0}</div><div className="tile-sub">₹{inr2(pbSummary?.available_cash)} cash free</div></div>
        <div className="tile">
          <div className="tile-label">Couldn&rsquo;t afford</div>
          <div className={`tile-value ${(pbSummary?.skipped_unaffordable ?? 0) > 0 ? "loss" : ""}`}>{pbSummary?.skipped_unaffordable ?? 0}</div>
          <div className="tile-sub">signals this book had to skip</div>
        </div>
      </div>

      <PnlRow capital={pbSummary?.desk_capital} realized={pbSummary?.realized_pnl}
              unrealized={pbSummary?.unrealized_pnl} fees={pbSummary?.fees} />

      <GlassPanel title={`The shortlist — ${pbSummary?.strategies ?? 8} strategies on ₹${inr(pbSummary?.per_strategy_allocation)} each`}>
        <div className="table-wrap">
          <table className="data-table">
            <thead><tr>
              <th style={{ textAlign: "left" }}>Strategy</th><th>TF</th><th>Family</th>
              <th>Slice</th><th>Trades</th><th>Win %</th><th>Fees</th><th>Net P&amp;L</th><th>ROI</th>
            </tr></thead>
            <tbody>
              {pbBoard.map((r) => (
                <tr key={r.strategy_id}>
                  <td style={{ textAlign: "left", fontSize: 11 }}>{r.template}</td>
                  <td><span className="badge">{r.timeframe}</span></td>
                  <td style={{ fontSize: 11 }}>{r.family}</td>
                  <td>₹{inr(r.allocation)}</td>
                  <td>{r.trades}</td>
                  <td>{r.trades ? `${(r.win_rate * 100).toFixed(1)}%` : "—"}</td>
                  <td className="loss">{r.fees ? `−₹${inr2(r.fees)}` : "—"}</td>
                  <td className={r.net_pnl >= 0 ? "gain" : "loss"}>{r.trades ? `${r.net_pnl >= 0 ? "+" : ""}₹${inr2(r.net_pnl)}` : "—"}</td>
                  <td className={r.roi_pct >= 0 ? "gain" : "loss"}>{r.trades ? roiPct(r.roi_pct) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="feed-note">
          ROI is on the strategy&rsquo;s own ₹{inr(pbSummary?.per_strategy_allocation)} slice, not on
          the whole book — eight slices each quoting a desk-level return would sum to eight times
          what the book actually made.
        </div>
      </GlassPanel>

      <GlassPanel title={`Open positions (${pbOpen.length})`}>
        {!pbOpen.length ? (
          <div className="feed-note">
            Nothing open. This book takes a position when the Patterns desk opens one of the
            shortlisted strategies.
          </div>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr>
                <th style={{ textAlign: "left" }}>Strategy</th><th>TF</th><th>Symbol</th><th>Side</th>
                <th>Qty</th><th>Entry</th><th>LTP</th><th>Target</th><th>Stop</th><th>Deployed</th><th>Unrealised</th>
              </tr></thead>
              <tbody>
                {pbOpen.map((p) => (
                  <tr key={p.position_id}>
                    <td style={{ textAlign: "left", fontSize: 11 }}>{p.template}</td>
                    <td><span className="badge">{p.timeframe}</span></td>
                    <td>{p.symbol}</td>
                    <td><span className={p.side === "SELL" ? "badge loss" : "badge"}>{p.side}</span></td>
                    <td>{p.qty}</td>
                    <td>₹{inr2(p.entry_price)}</td>
                    <td>₹{inr2(p.ltp)}</td>
                    <td>{p.target ? `₹${inr2(p.target)}` : "—"}</td>
                    <td>{p.stoploss ? `₹${inr2(p.stoploss)}` : "—"}</td>
                    <td>₹{inr2(p.capital_deployed)}</td>
                    <td className={(p.unrealized_pnl ?? 0) >= 0 ? "gain" : "loss"}>{(p.unrealized_pnl ?? 0) >= 0 ? "+" : ""}₹{inr2(p.unrealized_pnl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>

      {pbDeclined.length > 0 && (
        <GlassPanel title={`Signals this book could not afford (${pbDeclined.length})`}>
          <div className="feed-note">
            The Patterns desk took these on ₹10 lakh per strategy. Here the slice could not buy a
            single share, so the trade was declined rather than sized down — which is what a real
            account of this size would have done.
          </div>
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr>
                <th style={{ textAlign: "left" }}>Strategy</th><th>TF</th><th>Symbol</th>
                <th>Share price</th><th>Slice</th><th style={{ textAlign: "left" }}>Why</th>
              </tr></thead>
              <tbody>
                {pbDeclined.slice(0, 40).map((p) => (
                  <tr key={p.position_id}>
                    <td style={{ textAlign: "left", fontSize: 11 }}>{p.template}</td>
                    <td><span className="badge">{p.timeframe}</span></td>
                    <td>{p.symbol}</td>
                    <td>₹{inr2(p.entry_price)}</td>
                    <td>₹{inr(p.allocation)}</td>
                    <td style={{ textAlign: "left", fontSize: 11 }} className="loss">{p.decline_reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </GlassPanel>
      )}

      <GlassPanel title={`Closed trades (${pbTrades.length})`}>
        {!pbTrades.length ? (
          <div className="feed-note">No closed trades yet. Every close shows gross, the Angel fees taken, and the net kept.</div>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr>
                <th style={{ textAlign: "left" }}>Strategy</th><th>TF</th><th>Symbol</th><th>Side</th>
                <th>Qty</th><th>Entry</th><th>Exit</th><th>Gross</th><th>Fees</th><th>Net</th><th>Why</th><th>Closed</th>
              </tr></thead>
              <tbody>
                {pbTrades.map((t) => (
                  <tr key={t.trade_id}>
                    <td style={{ textAlign: "left", fontSize: 11 }}>{t.template}</td>
                    <td><span className="badge">{t.timeframe}</span></td>
                    <td>{t.symbol}</td>
                    <td><span className={t.side === "SELL" ? "badge loss" : "badge"}>{t.side}</span></td>
                    <td>{t.qty}</td>
                    <td>₹{inr2(t.entry_price)}</td>
                    <td>₹{inr2(t.exit_price)}</td>
                    <td className={t.gross_pnl >= 0 ? "gain" : "loss"}>{t.gross_pnl >= 0 ? "+" : ""}₹{inr2(t.gross_pnl)}</td>
                    <td className="loss">−₹{inr2(t.fees)}</td>
                    <td className={t.realized_pnl >= 0 ? "gain" : "loss"}>{t.realized_pnl >= 0 ? "+" : ""}₹{inr2(t.realized_pnl)}</td>
                    <td><span className="badge">{t.exit_reason ?? "—"}</span></td>
                    <td style={{ fontSize: 11 }}>{new Date(t.closed_at).toLocaleString("en-IN", { dateStyle: "short", timeStyle: "short" })}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>
      </DataGate>
      )}

      {isLive && (
      <DataGate ready={!!liveSummary} error={error} what={"this Live Intraday book"} onRetry={() => once(`live:${liveBook}`, loadLive)} lastOkAt={lastOkAt}>
      <div className="desk-banner">
        <strong>LIVE INTRADAY · ₹{bookCapital.toLocaleString("en-IN")} PAPER.</strong> The same 8-strategy
        shortlist runs in three books that differ only in capital — ₹80k, ₹30k and ₹10k — each strategy opening
        on ₹{inr(liveSummary?.per_strategy_allocation)} here, which is also its cap on any ONE position.
        A strategy may hold several positions at once (one per symbol) and{" "}
        <strong>reinvests its own realised profit</strong>, so deployed capital can exceed the
        ₹{inr(liveSummary?.initial_capital)} the desk opened with — what it can never exceed is current
        equity. Six are <strong>ANTI</strong> strategies: this desk places
        the <em>real reverse trade</em> (opposite side, stop/target swapped), not a computed mirror.{" "}
        <strong>P&amp;L is net of real Angel One costs</strong> — brokerage, STT, exchange and SEBI charges, stamp
        duty, GST, and a DP charge on delivery exits. On a book this small a signal must clear roughly
        ₹50 a round trip before it earns anything, which is exactly what the smaller books are here to test.
      </div>

      <div className="tiles">
        <div className="tile"><div className="tile-label">Mode</div><div className="tile-value gain">PAPER</div><div className="tile-sub">{liveSummary?.paused ? "entries paused" : "armed · live Angel feed"}</div></div>
        <div className="tile"><div className="tile-label">Equity</div><div className="tile-value">₹{inr(liveSummary?.equity)}</div><div className="tile-sub">from ₹{inr(liveSummary?.initial_capital)} ({liveSummary?.strategy_count ?? 8} × ₹{inr(liveSummary?.per_strategy_allocation)})</div></div>
        <div className="tile"><div className="tile-label">ROI</div><div className={`tile-value ${(liveSummary?.roi_pct ?? 0) >= 0 ? "gain" : "loss"}`}>{roiPct(liveSummary?.roi_pct, 2)}</div><div className="tile-sub">compounded, on the ₹{inr(liveSummary?.initial_capital)} opened with</div></div>
        <div className="tile"><div className="tile-label">Today P&amp;L</div><div className={`tile-value ${(liveSummary?.today_pnl ?? 0) >= 0 ? "gain" : "loss"}`}>{(liveSummary?.today_pnl ?? 0) >= 0 ? "+" : ""}₹{inr(liveSummary?.today_pnl)}</div><div className="tile-sub">{roiPct(liveSummary?.today_roi_pct)} today · breaker at −₹{inr(liveSummary?.daily_loss_limit)}</div></div>
        <div className="tile"><div className="tile-label">Realised P&amp;L</div><div className={`tile-value ${(liveSummary?.realized_pnl ?? 0) >= 0 ? "gain" : "loss"}`}>{(liveSummary?.realized_pnl ?? 0) >= 0 ? "+" : ""}₹{inr(liveSummary?.realized_pnl)}</div><div className="tile-sub">{liveSummary?.closed_positions ?? 0} trades closed</div></div>
        <div className="tile"><div className="tile-label">Angel fees paid</div><div className="tile-value loss">−₹{inr(liveSummary?.total_fees)}</div><div className="tile-sub">gross ₹{inr(liveSummary?.gross_realized_pnl)} before costs</div></div>
        <div className="tile"><div className="tile-label">Open positions</div><div className="tile-value">{liveSummary?.open_positions ?? 0}</div><div className="tile-sub">₹{inr(liveSummary?.unrealized_pnl)} unrealised</div></div>
        <div className="tile"><div className="tile-label">Deployed</div><div className="tile-value">₹{inr(liveSummary?.deployed_capital)}</div><div className="tile-sub">of ₹{inr(liveSummary?.equity)} equity · ₹{inr(liveSummary?.available_cash)} free</div></div>
        <div className="tile"><div className="tile-label">Strategies</div><div className="tile-value">{liveSummary?.strategy_count ?? 0}</div><div className="tile-sub">max ₹{inr(liveSummary?.position_notional)} per position, {liveSummary?.open_positions ?? 0} open now</div></div>
      </div>

      <PnlRow capital={liveSummary?.initial_capital} realized={liveSummary?.realized_pnl}
              unrealized={liveSummary?.unrealized_pnl} fees={liveSummary?.total_fees} />

      <GlassPanel title="Selected strategies">
        {!liveScores.length ? (
          <div className="empty">Loading the shortlist…</div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th style={{ textAlign: "left" }}>Strategy</th><th style={{ textAlign: "left" }}>Category</th><th>Trades</th><th>Win %</th><th>Net P&amp;L</th><th>Account</th></tr></thead>
              <tbody>
                {liveScores.map((s) => (
                  <tr key={s.strategy_id}>
                    <td style={{ textAlign: "left" }}>{s.is_anti && <span className="badge anti">ANTI</span>} {s.name}</td>
                    <td style={{ textAlign: "left" }}><span className="badge">{s.category}</span></td>
                    <td>{s.trades}</td>
                    <td>{s.trades ? `${(s.win_rate * 100).toFixed(1)}%` : "-"}</td>
                    <td className={s.net_pnl >= 0 ? "gain" : "loss"}>{s.net_pnl >= 0 ? "+" : ""}₹{inr(s.net_pnl)}</td>
                    <td>₹{inr(s.allocated_capital)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>

      <DailyRoiPanel rows={liveDaily} capital={bookCapital} />

      <GlassPanel title={`Open positions (${liveSummary?.open_positions ?? 0})`}>
        {!livePositions.filter((p) => p.status === "OPEN").length ? (
          <div className="empty">No open positions yet — the desk takes new entries until 14:30 IST and is flat by the close.</div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th style={{ textAlign: "left" }}>Symbol</th><th style={{ textAlign: "left" }}>Strategy</th><th>Side</th><th>Qty</th><th>Entry</th><th>LTP</th><th>Src</th><th>Target</th><th>Stop</th><th>Unrealised</th></tr></thead>
              <tbody>
                {livePositions.filter((p) => p.status === "OPEN").map((p) => (
                  <tr key={p.position_id}>
                    <td style={{ textAlign: "left" }}>{p.symbol}</td>
                    <td style={{ textAlign: "left", fontSize: 11 }}>{p.strategy_name}</td>
                    <td><span className={p.side === "SELL" ? "badge loss" : "badge"}>{p.side}</span></td>
                    <td>{p.qty}</td>
                    <td>₹{inr2(p.entry_price)}</td>
                    <td>₹{inr2(p.ltp)}</td>
                    <td><SourcePill source={p.ltp_source} /></td>
                    <td>₹{inr2(p.target)}</td>
                    <td>₹{inr2(p.stoploss)}</td>
                    <td className={(p.unrealized_pnl ?? 0) >= 0 ? "gain" : "loss"}>{(p.unrealized_pnl ?? 0) >= 0 ? "+" : ""}₹{inr(p.unrealized_pnl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>

      <GlassPanel title="Recent paper trades">
        {!liveTrades.length ? (
          <div className="empty">No closed trades yet.</div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th style={{ textAlign: "left" }}>Symbol</th><th style={{ textAlign: "left" }}>Strategy</th><th>Side</th><th>Qty</th><th>Entry</th><th>Exit</th><th>Reason</th><th>P&amp;L</th><th>Closed</th></tr></thead>
              <tbody>
                {liveTrades.map((t, i) => (
                  <tr key={`${t.trade_id}-${i}`}>
                    <td style={{ textAlign: "left" }}>{t.symbol}</td>
                    <td style={{ textAlign: "left", fontSize: 11 }}>{t.strategy_name}</td>
                    <td>{t.side}</td>
                    <td>{t.qty}</td>
                    <td>₹{inr2(t.entry_price)}</td>
                    <td>₹{inr2(t.exit_price)}</td>
                    <td><span className={`badge ${t.exit_reason === "stoploss" ? "loss" : ""}`}>{t.exit_reason}</span></td>
                    <td className={t.realized_pnl >= 0 ? "gain" : "loss"}>{t.realized_pnl >= 0 ? "+" : ""}₹{inr(t.realized_pnl)}</td>
                    <td style={{ fontSize: 10.5 }}>{t.closed_at ? new Date(t.closed_at).toLocaleString() : "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>
      </DataGate>
      )}

      {/* History must answer for the desk you are LOOKING at. It was pinned to
          "intraday-lab", so all seven tabs showed the tournament's history — including the
          pattern desk and the four paper books, which have their own capital and their own
          trades and were never the thing on screen. */}
      <DeskHistory
        deskKey={HISTORY_SCOPE[tab].deskKey}
        scope={HISTORY_SCOPE[tab].scope}
        title={`History — ${HISTORY_SCOPE[tab].label}`}
      />

      <style jsx>{`
        .page { display: flex; flex-direction: column; gap: 16px; }
        .tabs { display: flex; gap: 8px; flex-wrap: wrap; }
        .tab { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); padding: 9px 16px; border-radius: 9px; font-size: 12.5px; font-weight: 600; cursor: pointer; }
        .tab.active { background: var(--purple-dim); border-color: rgba(125, 52, 220, 0.3); color: var(--purple); }
        .badge.anti { background: var(--purple-dim); border-color: rgba(125, 52, 220, 0.3); color: var(--purple); margin-right: 4px; }
        .desk-banner {
          padding: 10px 16px; border-radius: 8px; font-size: 12px; line-height: 1.5;
          background: var(--canvas-soft); border: 1px solid var(--panel-border);
          color: var(--text-secondary);
        }
        .feed-note {
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
        .gate-note { border-radius: 12px; padding: 12px 16px; font-size: 12.5px; line-height: 1.55;
                     background: var(--canvas-soft); border: 1px solid var(--panel-border);
                     color: var(--text-muted); }
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
        .badge {
          display: inline-block; padding: 3px 8px; border-radius: 6px; font-size: 10px;
          font-weight: 700; letter-spacing: 0.05em; background: var(--canvas-soft);
          border: 1px solid var(--panel-border);
        }
        .badge.loss { background: var(--loss-dim); border-color: rgba(217, 45, 63, 0.3); }
        .src {
          display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 9.5px;
          font-weight: 700; letter-spacing: 0.04em; border: 1px solid var(--panel-border);
        }
        .src.angel { background: rgba(34, 170, 96, 0.12); border-color: rgba(34, 170, 96, 0.3); }
        .src.dhan { background: var(--canvas-soft); }
        .src.stale { background: var(--loss-dim); border-color: rgba(217, 45, 63, 0.3); }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
      `}</style>
    </div>
  );
}
