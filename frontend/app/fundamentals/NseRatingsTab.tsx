"use client";

/** NSE Stock Ratings: every NSE-listed company on one table, in three kinds of column that
 *  are never mixed: what the stock IS (the rating), what it DID (historical returns, risk)
 *  and what MIGHT happen (forward estimates, which are ranges and say so).
 *
 * Filtering, sorting and paging all happen on the server: 2,600-odd rows of fifty columns is
 * too much to ship on every keystroke. The drawer recomputes one company from its cached
 * screener.in page, so what it shows is the calculation the row came from. A company without
 * enough data says "Insufficient Data" and why, and so does an estimate that cannot be made.
 */

import { useCallback, useEffect, useMemo, useRef, useState, type RefObject } from "react";
import GlassPanel from "../../components/GlassPanel";
import { GRADE_COLOR, GRADE_ORDER, GradeKey } from "../../lib/api";
import {
  Estimate,
  EstimateHorizon,
  EstimateValidation,
  NseRatingDetail,
  NseRatingRow,
  NseRatingsPage,
  NseRatingsQuery,
  NseRatingsSummary,
  NseRefreshWhat,
  OverallKey,
  RatingPartKey,
  fetchNseRatingDetail,
  fetchNseRatings,
  fetchNseRatingsExport,
  fetchNseRatingsSummary,
  refreshNseRating,
  runNseRatingsRefresh,
} from "../../lib/nseRatings";
import TvExport from "./TvExport";
import { TvItem } from "./tradingview";

const GREY = "#8a8a99";
const PAGE_SIZES = [25, 50, 100, 200];
const PREFS_KEY = "nseRatings.view.v2";
const POLL_MS = 15000;
const HORIZONS: { key: EstimateHorizon; label: string; long: string }[] = [
  { key: "1d", label: "1D", long: "1 day" },
  { key: "1w", label: "1W", long: "1 week" },
  { key: "1m", label: "1M", long: "1 month" },
  { key: "3m", label: "3M", long: "3 months" },
];
const PARTS: { key: RatingPartKey; label: string; short: string }[] = [
  { key: "quality", label: "Fundamentals (quality)", short: "Quality" },
  { key: "growth", label: "Growth", short: "Growth" },
  { key: "quarter", label: "Quarterly results", short: "Quarterly" },
  { key: "valuation", label: "Valuation", short: "Valuation" },
  { key: "strength", label: "Financial strength", short: "Strength" },
  { key: "momentum", label: "Price momentum", short: "Momentum" },
];

type Section = "company" | "rating" | "fundamentals" | "returns" | "risk" | "estimates" | "source";
const SECTIONS: { key: Section; label: string }[] = [
  { key: "company", label: "Company" },
  { key: "rating", label: "Stock rating" },
  { key: "fundamentals", label: "Fundamentals & latest quarter" },
  { key: "returns", label: "Historical returns" },
  { key: "risk", label: "Risk & liquidity" },
  { key: "estimates", label: "Forward estimates · not guarantees" },
  { key: "source", label: "Source" },
];

interface Col {
  key: string;
  label: string;
  section: Section;
  sort?: string;
  /** The direction a first click sorts in. Lower is better for P/E, debt and risk. */
  first?: "asc" | "desc";
  num?: boolean;
  title?: string;
  fixed?: boolean;
}

const COLS: Col[] = [
  { key: "stock", label: "Stock", section: "company", sort: "name", first: "asc", fixed: true },
  { key: "sector", label: "Sector", section: "company", sort: "sector", first: "asc" },
  { key: "index", label: "Nifty index", section: "company", sort: "index", first: "asc" },

  { key: "overall", label: "Rating", section: "rating", sort: "overall",
    title: "25% quality + 20% growth + 15% quarterly results + 15% valuation + 15% financial strength + 10% price momentum" },
  { key: "c_quarter", label: "Quarterly", section: "rating", sort: "quarter",
    title: "The latest quarter against the same quarter a year earlier (the Rate tab's quarter score)" },
  { key: "c_quality", label: "Quality", section: "rating", sort: "c_quality",
    title: "Return on capital, margins, cash conversion and ownership pillars" },
  { key: "c_valuation", label: "Valuation", section: "rating", sort: "c_valuation",
    title: "P/E and PEG, blended with P/E against the sector median" },
  { key: "c_growth", label: "Growth", section: "rating", sort: "c_growth",
    title: "3-5 year sales and profit growth, blended with the P&L-record score" },
  { key: "c_strength", label: "Strength", section: "rating", sort: "c_strength",
    title: "Debt against net worth and interest cover; not scored for lenders" },
  { key: "c_momentum", label: "Momentum", section: "rating", sort: "c_momentum",
    title: "Percentile across NSE of the 12-1 month return, 6-month return and closeness to the 52-week high" },
  { key: "why", label: "Why this rating", section: "rating" },

  { key: "qlabel", label: "Latest qtr", section: "fundamentals", sort: "latest_quarter" },
  { key: "rev", label: "Revenue", section: "fundamentals", sort: "revenue", num: true, title: "Latest quarter, ₹ crore" },
  { key: "rev_yoy", label: "Rev YoY", section: "fundamentals", sort: "rev_yoy", num: true },
  { key: "rev_qoq", label: "Rev QoQ", section: "fundamentals", sort: "rev_qoq", num: true,
    title: "Shown, never scored: most Indian businesses are seasonal" },
  { key: "np", label: "Net profit", section: "fundamentals", sort: "profit", num: true, title: "Latest quarter, ₹ crore" },
  { key: "np_yoy", label: "NP YoY", section: "fundamentals", sort: "np_yoy", num: true },
  { key: "np_qoq", label: "NP QoQ", section: "fundamentals", sort: "np_qoq", num: true },
  { key: "roce", label: "ROCE", section: "fundamentals", sort: "roce", num: true },
  { key: "roe", label: "ROE", section: "fundamentals", sort: "roe", num: true },
  { key: "de", label: "Debt/Eq", section: "fundamentals", sort: "de", num: true, first: "asc" },
  { key: "opm", label: "OPM", section: "fundamentals", sort: "opm", num: true, title: "Operating margin, latest year" },
  { key: "sales_cagr", label: "Sales 3y", section: "fundamentals", sort: "sales_cagr", num: true,
    title: "Compounded sales growth a year over 3 years (5 where 3 is not published)" },
  { key: "profit_cagr", label: "Profit 3y", section: "fundamentals", sort: "profit_cagr", num: true },
  { key: "pe", label: "P/E", section: "fundamentals", sort: "pe", num: true, first: "asc" },
  { key: "pe_rel", label: "P/E vs sector", section: "fundamentals", sort: "pe_rel", num: true, first: "asc",
    title: "P/E divided by the sector's median P/E (sectors with 8+ profitable peers)" },
  { key: "pb", label: "P/B", section: "fundamentals", sort: "pb", num: true, first: "asc" },
  { key: "promoter", label: "Promoter", section: "fundamentals", sort: "promoter", num: true },
  { key: "mcap", label: "M-cap", section: "fundamentals", sort: "mcap", num: true },
  { key: "fund", label: "7-pillar score", section: "fundamentals", sort: "fundamentals",
    title: "The Rate tab's own seven-pillar fundamentals score" },
  { key: "pnl", label: "P&L record", section: "fundamentals", sort: "pnl" },

  { key: "r1d", label: "1D", section: "returns", sort: "r1d", num: true },
  { key: "r1w", label: "1W", section: "returns", sort: "r1w", num: true },
  { key: "r1m", label: "1M", section: "returns", sort: "r1m", num: true },
  { key: "r2m", label: "2M", section: "returns", sort: "r2m", num: true },
  { key: "r3m", label: "3M", section: "returns", sort: "r3m", num: true },
  { key: "r6m", label: "6M", section: "returns", sort: "r6m", num: true },
  { key: "r1y", label: "1Y", section: "returns", sort: "r1y", num: true },
  { key: "r2y", label: "2Y", section: "returns", sort: "r2y", num: true },
  { key: "r5y", label: "5Y", section: "returns", sort: "r5y", num: true },
  { key: "r1y_vs_n500", label: "1Y vs Nifty 500", section: "returns", sort: "r1y_vs_n500", num: true,
    title: "1-year return minus the Nifty 500's, in percentage points" },
  { key: "r1y_vs_sector", label: "1Y vs sector", section: "returns", sort: "r1y_vs_sector", num: true,
    title: "1-year return minus the sector median, in percentage points" },

  { key: "vol", label: "Volatility", section: "risk", sort: "vol", num: true, first: "asc",
    title: "Annualised standard deviation of daily returns over the last year" },
  { key: "mdd", label: "Max drawdown", section: "risk", sort: "mdd", num: true,
    title: "Largest fall from a peak within the last year" },
  { key: "beta", label: "Beta", section: "risk", sort: "beta", num: true, first: "asc",
    title: "Sensitivity of daily returns to the Nifty 500 over the last year" },
  { key: "from_high", label: "From 52w high", section: "risk", sort: "from_high", num: true },
  { key: "from_ath", label: "From all-time high", section: "risk", sort: "from_ath", num: true,
    title: "Latest close against the stock's all-time high (its full price history back to listing). \"New high\" = a new all-time high in the latest session" },
  { key: "liquidity", label: "Traded/day", section: "risk", sort: "liquidity", num: true,
    title: "Median daily traded value over the last 3 months; no-trade days count as zero" },
  { key: "deliv", label: "Delivery", section: "risk", sort: "deliv", num: true,
    title: "Average delivery % over the last 20 sessions it traded" },

  { key: "e1d", label: "1 day", section: "estimates", sort: "e1d", num: true },
  { key: "e1w", label: "1 week", section: "estimates", sort: "e1w", num: true },
  { key: "e1m", label: "1 month", section: "estimates", sort: "e1m", num: true },
  { key: "e3m", label: "3 months", section: "estimates", sort: "e3m", num: true },

  { key: "source", label: "Source · read", section: "source", sort: "updated" },
];

const ALL_KEYS = COLS.map((c) => c.key);
const PRESETS: { key: string; label: string; cols: string[] }[] = [
  { key: "overview", label: "Overview", cols: ["stock", "sector", "index", "overall", "c_quarter", "c_quality",
    "c_valuation", "c_growth", "c_strength", "c_momentum", "why", "qlabel", "rev_yoy", "np_yoy", "pe", "pe_rel",
    "mcap", "r1d", "r1w", "r1m", "r3m", "r1y", "r5y", "vol", "mdd", "liquidity", "e1w", "e1m", "e3m", "source"] },
  { key: "rating", label: "Ratings", cols: ["stock", "sector", "index", "overall", "c_quarter", "c_quality",
    "c_valuation", "c_growth", "c_strength", "c_momentum", "why", "qlabel", "source"] },
  { key: "fundamentals", label: "Fundamentals", cols: ["stock", "sector", "overall", ...COLS.filter((c) => c.section === "fundamentals").map((c) => c.key)] },
  { key: "returns", label: "Returns & risk", cols: ["stock", "sector", "index", "overall",
    ...COLS.filter((c) => c.section === "returns" || c.section === "risk").map((c) => c.key)] },
  { key: "estimates", label: "Estimates", cols: ["stock", "sector", "overall", "r1m", "r3m", "r1y", "vol", "liquidity",
    "e1d", "e1w", "e1m", "e3m"] },
  { key: "all", label: "Everything", cols: ALL_KEYS },
];

const SERIES_NOTE: Record<string, string> = {
  BE: "BE series: trade-for-trade, every trade settles by delivery",
  BZ: "BZ series: NSE flags it for non-compliance with listing rules",
};

function tone(key?: string | null): string {
  if (!key || key === "insufficient" || key === "unrated") return GREY;
  return GRADE_COLOR[key as GradeKey] ?? GREY;
}

/** A 0-10 component score's colour, on the same ramp as the grades. */
function scoreTone(s: number | null | undefined): string {
  if (s === null || s === undefined) return GREY;
  if (s >= 9) return GRADE_COLOR.explosive;
  if (s >= 8.4) return GRADE_COLOR.extraordinary;
  if (s >= 7.8) return GRADE_COLOR.excellent;
  if (s >= 7) return GRADE_COLOR["very-good"];
  if (s >= 6.2) return GRADE_COLOR.good;
  if (s >= 5.4) return GRADE_COLOR["above-average"];
  if (s >= 4.6) return GRADE_COLOR.average;
  if (s >= 3.4) return GRADE_COLOR["below-average"];
  return GRADE_COLOR.worst;
}

function toDate(s?: string | null): Date | null {
  if (!s) return null;
  // Mongo hands back naive UTC datetimes; a bare date is a calendar day.
  const iso = s.length === 10 ? `${s}T00:00:00` : /[zZ]$|[+-]\d\d:?\d\d$/.test(s) ? s : `${s}Z`;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

const day = (s?: string | null) =>
  toDate(s)?.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) ?? "—";
const shortDay = (s?: string | null) =>
  toDate(s)?.toLocaleDateString("en-IN", { day: "numeric", month: "short" }) ?? "—";
const stamp = (s?: string | null) =>
  toDate(s)?.toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) ?? "—";

function crore(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  if (Math.abs(v) >= 100000) return `₹${(v / 100000).toFixed(2)}L Cr`;
  return `₹${v.toLocaleString("en-IN", { maximumFractionDigits: Math.abs(v) < 100 ? 1 : 0 })} Cr`;
}
/** The all-time-high quick filters shown under the column presets, in this order. */
const ATH_CHIPS: { key: string; label: string }[] = [
  { key: "new", label: "New all-time high" },
  { key: "2", label: "Within 2%" },
  { key: "5", label: "Within 5%" },
  { key: "10", label: "Within 10%" },
  { key: "25", label: "Within 25%" },
];
const athText = (r: NseRatingRow) =>
  r.from_ath == null ? "—" : r.ath_new ? "New high" : `${r.from_ath.toFixed(1)}%`;
function athTitle(r: NseRatingRow): string {
  if (r.ath == null) return "All-time high not known yet: no full-history high is stored for this stock";
  const since = r.ath_basis === "listing" ? ", its whole history since listing" : "";
  return `All-time high ${rupees(r.ath)} on ${day(r.ath_date)}${since}`;
}
const rupees = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `₹${v.toLocaleString("en-IN", { maximumFractionDigits: v < 100 ? 2 : 0 })}`;
const signed = (v: number | null | undefined, d = 1) =>
  v === null || v === undefined ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(d)}%`;
const pts = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(1)} pts`;
const fixed = (v: number | null | undefined, d = 1, suffix = "") =>
  v === null || v === undefined ? "—" : `${v.toFixed(d)}${suffix}`;
const dir = (v: number | null | undefined) =>
  v === null || v === undefined || v === 0 ? "" : v > 0 ? "up" : "down";

function Pill({ score, tier, k, title, strong = false }: {
  score: number | null | undefined;
  tier?: string | null;
  k?: string | null;
  title?: string | null;
  strong?: boolean;
}) {
  if (score === null || score === undefined) return <span className="nsr-dash">—</span>;
  const c = tone(k);
  return (
    <span
      className={`nsr-pill${strong ? " nsr-pill-strong" : ""}`}
      style={strong ? { background: c, borderColor: c } : { borderColor: c, color: c }}
      title={title || tier || ""}
    >
      <b>{score.toFixed(1)}</b> {tier}
    </span>
  );
}

function Score({ s, title }: { s: number | null | undefined; title?: string }) {
  if (s === null || s === undefined) return <span className="nsr-dash" title={title ?? "no data"}>—</span>;
  return (
    <span className="nsr-score" style={{ color: scoreTone(s), borderColor: scoreTone(s) }} title={title}>
      {s.toFixed(1)}
    </span>
  );
}

function estTitle(e: Estimate, h: string): string {
  return `${h} estimate (not a guarantee). Bear ${signed(e.bear)} (${rupees(e.bear_px)}) · base ${signed(e.base)} `
    + `(${rupees(e.base_px)}) · bull ${signed(e.bull)} (${rupees(e.bull_px)}). 1-in-20 downside ${signed(e.down)} `
    + `(${rupees(e.down_px)}). Confidence ${e.conf}: ${e.conf_why}.`;
}

interface Prefs {
  cols?: string[];
  pageSize?: number;
}

/** A second horizontal scrollbar ABOVE a scrolling box, moving in step with the box's own bar (which stays at the
 *  bottom). The strip's range is made equal to the box's even when the box also shows a vertical scrollbar, and it
 *  re-measures whenever the table inside changes width (columns picked, a new page). Hidden when nothing overflows. */
function TopScrollbar({ target }: { target: RefObject<HTMLDivElement | null> }) {
  const barRef = useRef<HTMLDivElement>(null);
  const [inner, setInner] = useState(0);
  const [overflows, setOverflows] = useState(false);

  useEffect(() => {
    const box = target.current;
    const bar = barRef.current;
    if (!box || !bar) return;
    const measure = () => {
      const range = box.scrollWidth - box.clientWidth;
      setOverflows(range > 1);
      setInner(bar.clientWidth + Math.max(0, range));
      bar.scrollLeft = box.scrollLeft;
    };
    const fromBox = () => {
      if (Math.abs(bar.scrollLeft - box.scrollLeft) > 0.5) bar.scrollLeft = box.scrollLeft;
    };
    const fromBar = () => {
      if (Math.abs(box.scrollLeft - bar.scrollLeft) > 0.5) box.scrollLeft = bar.scrollLeft;
    };
    box.addEventListener("scroll", fromBox, { passive: true });
    bar.addEventListener("scroll", fromBar, { passive: true });
    const ro = new ResizeObserver(measure);
    ro.observe(box);
    if (box.firstElementChild) ro.observe(box.firstElementChild);
    measure();
    return () => {
      box.removeEventListener("scroll", fromBox);
      bar.removeEventListener("scroll", fromBar);
      ro.disconnect();
    };
  }, [target]);

  useEffect(() => {          // after the strip re-renders at a new width, line it up with the table again
    const box = target.current;
    const bar = barRef.current;
    if (box && bar) bar.scrollLeft = box.scrollLeft;
  }, [inner, target]);

  return (
    <div ref={barRef} className={`nsr-topscroll${overflows ? "" : " off"}`} aria-hidden="true">
      <div style={{ width: inner }} />
    </div>
  );
}

function readPrefs(): Prefs {
  try {
    const raw = window.localStorage.getItem(PREFS_KEY);
    return raw ? (JSON.parse(raw) as Prefs) : {};
  } catch {
    return {}; // storage blocked: the defaults stand
  }
}

export default function NseRatingsTab() {
  const [summary, setSummary] = useState<NseRatingsSummary | null>(null);
  const [data, setData] = useState<NseRatingsPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [index, setIndex] = useState("");
  const [sector, setSector] = useState("");
  const [ratings, setRatings] = useState<OverallKey[]>([]);
  const [quarter, setQuarter] = useState("");
  const [dataFilter, setDataFilter] = useState("");
  const [liquidity, setLiquidity] = useState("");
  const [vol, setVol] = useState("");
  const [conf, setConf] = useState("");
  const [ath, setAth] = useState("");
  const [sort, setSort] = useState("overall");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [cols, setCols] = useState<Set<string>>(new Set(PRESETS[0].cols));
  const [pickerOpen, setPickerOpen] = useState(false);
  const [showMethod, setShowMethod] = useState(false);
  const [openSym, setOpenSym] = useState<string | null>(null);
  const [exportItems, setExportItems] = useState<TvItem[] | null>(null);
  const [exporting, setExporting] = useState(false);
  const [refreshWhat, setRefreshWhat] = useState<NseRefreshWhat>("due");
  const [triggering, setTriggering] = useState(false);

  const reqId = useRef(0);
  const lastDone = useRef(0);
  const prefsLoaded = useRef(false);
  const tableBoxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const p = readPrefs();
    if (Array.isArray(p.cols) && p.cols.length) setCols(new Set(p.cols.filter((k) => ALL_KEYS.includes(k))));
    if (p.pageSize && PAGE_SIZES.includes(p.pageSize)) setPageSize(p.pageSize);
    prefsLoaded.current = true;
  }, []);
  useEffect(() => {
    if (!prefsLoaded.current) return;
    try {
      window.localStorage.setItem(PREFS_KEY, JSON.stringify({ cols: [...cols], pageSize }));
    } catch {
      /* not worth surfacing */
    }
  }, [cols, pageSize]);

  useEffect(() => {
    const t = setTimeout(() => {
      setSearch((prev) => {
        const next = searchInput.trim();
        if (next !== prev) setPage(1);
        return next;
      });
    }, 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  const query: NseRatingsQuery = useMemo(
    () => ({
      search: search || undefined,
      index: index || undefined,
      sector: sector || undefined,
      ratings: ratings.length ? ratings : undefined,
      quarter: quarter || undefined,
      data: dataFilter || undefined,
      liquidity: liquidity || undefined,
      vol: vol || undefined,
      conf: conf || undefined,
      ath: ath || undefined,
      sort,
      order,
      page,
      pageSize,
    }),
    [search, index, sector, ratings, quarter, dataFilter, liquidity, vol, conf, ath, sort, order, page, pageSize],
  );

  const load = useCallback(async () => {
    const id = ++reqId.current;
    setLoading(true);
    try {
      const res = await fetchNseRatings(query);
      if (id !== reqId.current) return;
      setData(res);
      setError(null);
    } catch (e) {
      if (id === reqId.current) setError(e instanceof Error ? e.message : "Could not load the table.");
    } finally {
      if (id === reqId.current) setLoading(false);
    }
  }, [query]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    setExportItems(null);
  }, [search, index, sector, ratings, quarter, dataFilter, liquidity, vol, conf, ath]);

  const loadSummary = useCallback(async () => {
    try {
      const s = await fetchNseRatingsSummary();
      setSummary(s);
      return s;
    } catch {
      return null; // the header is a convenience; the table still works without it
    }
  }, []);

  useEffect(() => {
    loadSummary();
  }, [loadSummary]);

  const running = !!summary?.status?.running;
  useEffect(() => {
    if (!running) return;
    const t = setInterval(async () => {
      const s = await loadSummary();
      const done = s?.status?.done ?? 0;
      if (!s?.status?.running || done - lastDone.current >= 20) {
        lastDone.current = done;
        load();
      }
    }, POLL_MS);
    return () => clearInterval(t);
  }, [running, loadSummary, load]);

  const setFilter = <T,>(setter: (v: T) => void) => (v: T) => {
    setter(v);
    setPage(1);
  };

  const pickAth = (k: string) => {
    const next = ath === k ? "" : k;
    setFilter(setAth)(next);
    if (next && !cols.has("from_ath")) setCols((prev) => new Set([...prev, "from_ath"]));
  };

  const onSort = (c: Col) => {
    if (!c.sort) return;
    if (sort === c.sort) setOrder((o) => (o === "asc" ? "desc" : "asc"));
    else {
      setSort(c.sort);
      setOrder(c.first ?? "desc");
    }
    setPage(1);
  };

  const toggleRating = (k: OverallKey) => {
    setRatings((prev) => (prev.includes(k) ? prev.filter((x) => x !== k) : [...prev, k]));
    setPage(1);
  };

  const clearFilters = () => {
    setSearchInput("");
    setSearch("");
    setIndex("");
    setSector("");
    setRatings([]);
    setQuarter("");
    setDataFilter("");
    setLiquidity("");
    setVol("");
    setConf("");
    setAth("");
    setPage(1);
  };

  const toggleCol = (k: string) =>
    setCols((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      next.add("stock");
      return next;
    });
  const toggleSection = (s: Section, on: boolean) =>
    setCols((prev) => {
      const next = new Set(prev);
      COLS.filter((c) => c.section === s && !c.fixed).forEach((c) => (on ? next.add(c.key) : next.delete(c.key)));
      next.add("stock");
      return next;
    });

  const buildExport = async () => {
    setExporting(true);
    try {
      const res = await fetchNseRatingsExport(query);
      setExportItems(res.rows.map((r) => ({ symbol: r.symbol, group: r.ovr_key || "insufficient" })));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not build the list.");
    } finally {
      setExporting(false);
    }
  };

  const trigger = async () => {
    setTriggering(true);
    setNotice(null);
    try {
      const r = await runNseRatingsRefresh(refreshWhat);
      setNotice(r.started ? "Refresh started. Progress appears above and the table reloads as rows change."
        : r.reason || "The refresh did not start.");
      setTimeout(loadSummary, 2000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start the refresh.");
    } finally {
      setTriggering(false);
    }
  };

  const counts = summary?.counts ?? {};
  const st = summary?.status;
  const jobs = summary?.jobs;
  const market = jobs?.returns;
  const validation = summary?.estimates?.validation ?? {};
  const visible = COLS.filter((c) => c.fixed || cols.has(c.key));
  const rows = data?.rows ?? [];
  const total = data?.total ?? 0;
  const filtersOn = !!(search || index || sector || ratings.length || quarter || dataFilter || liquidity || vol || conf || ath);
  const bestFirst: OverallKey[] = [...GRADE_ORDER].reverse();
  const testPeriod = Object.values(validation)[0]?.period;
  const read = summary?.fundamentals_read;

  const sectionNote: Record<Section, string> = {
    company: "",
    rating: read?.first ? `fundamentals read ${shortDay(read.first)} – ${shortDay(read.last)}` : "",
    fundamentals: "screener.in",
    returns: market?.as_of ? `to the ${day(market.as_of)} close` : "",
    risk: market?.as_of ? `1 year to ${shortDay(market.as_of)}` : "",
    estimates: market?.as_of ? `from the ${shortDay(market.as_of)} close${testPeriod ? ` · validated ${testPeriod}` : ""}` : "",
    source: "",
  };

  // Consecutive visible columns of one section share a header cell.
  const bands: { section: Section; span: number }[] = [];
  for (const c of visible) {
    const last = bands[bands.length - 1];
    if (last && last.section === c.section) last.span += 1;
    else bands.push({ section: c.section, span: 1 });
  }

  const estCell = (r: NseRatingRow, hk: EstimateHorizon, long: string) => {
    const e = r.est?.[hk];
    if (!e || e.status !== "ok") {
      return <span className="nsr-na" title={e?.reason ? `Insufficient data: ${e.reason}` : "No estimate yet"}>Insufficient data</span>;
    }
    return (
      <span className="nsr-est" title={estTitle(e, long)}>
        <b className={dir(e.base)}>{signed(e.base)}</b>
        <span className="nsr-range">{signed(e.bear, 1)} … {signed(e.bull, 1)}</span>
        <span className={`nsr-conf ${e.conf}`}>{e.conf}</span>
      </span>
    );
  };

  const cell = (r: NseRatingRow, c: Col) => {
    const parts = r.rating_parts ?? {};
    switch (c.key) {
      case "stock":
        return (
          <td key={c.key} className="nsr-stick nsr-l">
            <div className="nsr-nm">{r.name || r.screener_name || r.symbol}</div>
            <div className="nsr-sym">
              {r.symbol}
              {r.series && r.series !== "EQ" && (
                <span className="nsr-ser" title={SERIES_NOTE[r.series] ?? r.series}>{r.series}</span>
              )}
              {r.is_lender && <span className="nsr-ser" title="Scored as a lender">lender</span>}
            </div>
          </td>
        );
      case "sector":
        return (
          <td key={c.key} className="nsr-l nsr-secw">
            <div className="nsr-clip">{r.sector || "—"}</div>
            {r.industry && r.industry !== r.sector && <div className="nsr-sub nsr-clip">{r.industry}</div>}
          </td>
        );
      case "index":
        return <td key={c.key} className="nsr-l nsr-idx">{r.index_label || "—"}</td>;
      case "overall":
        return (
          <td key={c.key}>
            {r.overall === null || r.ovr_status === "insufficient" ? (
              <span className="nsr-pill nsr-ins" title={(r.ovr_reasons ?? []).join("; ")}>Insufficient Data</span>
            ) : (
              <Pill score={r.overall} tier={r.ovr_tier} k={r.ovr_key} title={r.ovr_formula} strong />
            )}
          </td>
        );
      case "c_quarter":
        return <td key={c.key}><Score s={parts.quarter} title={r.q_tier ?? undefined} /></td>;
      case "c_quality":
        return <td key={c.key}><Score s={parts.quality} /></td>;
      case "c_valuation":
        return <td key={c.key}><Score s={parts.valuation} /></td>;
      case "c_growth":
        return <td key={c.key}><Score s={parts.growth} /></td>;
      case "c_strength":
        return <td key={c.key}><Score s={parts.strength} title={r.is_lender ? "Not scored for lenders" : undefined} /></td>;
      case "c_momentum":
        return (
          <td key={c.key}>
            <Score s={parts.momentum} title={r.mom_pct != null ? `${r.mom_pct.toFixed(0)}th percentile of NSE` : undefined} />
          </td>
        );
      case "why": {
        const text = r.ovr_explain || (r.ovr_status === "insufficient"
          ? `Insufficient Data: ${(r.ovr_reasons ?? []).join("; ")}.` : r.explain?.text || "—");
        return (
          <td key={c.key} className="nsr-l nsr-whyw">
            <div className="nsr-why" title={text}>{text}</div>
          </td>
        );
      }
      case "qlabel":
        return (
          <td key={c.key} className="nsr-l">
            <span className="nsr-q">{r.qlabel || "—"}</span>
            {r.pending ? (
              <span className="nsr-tag nsr-tag-pend"
                title={(r.tflags ?? []).find((f) => f.k === "pending")?.t ?? "New results are out"}>new results · queued</span>
            ) : r.freshness === "outdated" ? (
              <span className={`nsr-tag ${(r.behind ?? 0) >= 2 ? "nsr-tag-bad" : "nsr-tag-warn"}`}
                title={(r.tflags ?? []).find((f) => f.k === "outdated")?.t ?? ""}>{r.behind} qtr overdue</span>
            ) : r.freshness === "due" ? (
              <span className="nsr-tag" title={`${r.next_q} results due by ${day(r.next_due)}`}>
                {r.next_q?.slice(0, 3)} due {shortDay(r.next_due)}
              </span>
            ) : r.freshness === "current" ? (
              <span className="nsr-ok" title="The newest quarter that has ended is in this rating">✓</span>
            ) : null}
          </td>
        );
      case "rev":
        return <td key={c.key} className="nsr-n">{crore(r.rev)}</td>;
      case "rev_yoy":
        return <td key={c.key} className={`nsr-n ${dir(r.rev_yoy)}`}>{signed(r.rev_yoy)}</td>;
      case "rev_qoq":
        return <td key={c.key} className={`nsr-n ${dir(r.rev_qoq)}`}>{signed(r.rev_qoq)}</td>;
      case "np":
        return (
          <td key={c.key} className={`nsr-n ${r.np !== null && r.np < 0 ? "down" : ""}`}>
            {crore(r.np)}
            {r.np_flag === "distorted" && <span className="nsr-warnmark" title={r.np_note ?? ""}> ⚠</span>}
          </td>
        );
      case "np_yoy":
      case "np_qoq": {
        const v = c.key === "np_yoy" ? r.np_yoy : r.np_qoq;
        const tag = c.key === "np_yoy" ? "YoY:" : "QoQ:";
        const note = (r.np_note ?? "").split("; ").find((x) => x.startsWith(tag));
        if (v === null && note) return <td key={c.key} className="nsr-n nsr-nm-cell" title={note.slice(5)}>n/m</td>;
        return <td key={c.key} className={`nsr-n ${dir(v)}`}>{signed(v)}</td>;
      }
      case "roce":
        return (
          <td key={c.key} className="nsr-n" title={r.is_lender ? "Not meaningful for a lender: see ROE" : undefined}>
            {r.is_lender ? "n/a" : fixed(r.roce, 1, "%")}
          </td>
        );
      case "roe":
        return <td key={c.key} className="nsr-n">{fixed(r.roe, 1, "%")}</td>;
      case "de":
        return (
          <td key={c.key} className="nsr-n" title={r.is_lender ? "Borrowing is a lender's raw material" : undefined}>
            {r.is_lender ? "n/a" : fixed(r.de, 2)}
          </td>
        );
      case "opm":
        return (
          <td key={c.key} className="nsr-n">
            {r.is_lender ? (r.net_margin != null ? `${r.net_margin.toFixed(0)}% net` : "n/a") : fixed(r.opm, 0, "%")}
          </td>
        );
      case "sales_cagr":
        return <td key={c.key} className={`nsr-n ${dir(r.sales_cagr)}`}>{signed(r.sales_cagr, 0)}</td>;
      case "profit_cagr":
        return <td key={c.key} className={`nsr-n ${dir(r.profit_cagr)}`}>{signed(r.profit_cagr, 0)}</td>;
      case "pe":
        return <td key={c.key} className="nsr-n">{fixed(r.pe, 1)}</td>;
      case "pe_rel":
        return (
          <td key={c.key} className="nsr-n"
            title={r.pe_sector_med != null ? `Sector median P/E ${r.pe_sector_med.toFixed(1)}` : "Fewer than 8 profitable peers"}>
            {r.pe_rel != null ? `${r.pe_rel.toFixed(2)}×` : "—"}
          </td>
        );
      case "pb":
        return <td key={c.key} className="nsr-n">{fixed(r.pb, 1)}</td>;
      case "promoter":
        return (
          <td key={c.key} className="nsr-n"
            title={r.no_promoter && r.institutional != null ? `No promoter group; institutions hold ${r.institutional.toFixed(0)}%` : undefined}>
            {r.no_promoter ? "none" : fixed(r.promoter, 1, "%")}
          </td>
        );
      case "mcap":
        return <td key={c.key} className="nsr-n">{crore(r.mcap)}</td>;
      case "fund":
        return <td key={c.key}><Pill score={r.fund} tier={r.fund_tier} k={r.fund_key} /></td>;
      case "pnl":
        return <td key={c.key}><Pill score={r.pnl} tier={r.pnl_tier} k={r.pnl_key} /></td>;
      case "r1d": case "r1w": case "r1m": case "r2m": case "r3m": case "r6m": case "r1y": case "r2y": case "r5y": {
        const v = r[c.key as "r1d"];
        const notes = [...(r.ret_notes ?? []), ...(r.ret_check ? [r.ret_check] : [])];
        return (
          <td key={c.key} className={`nsr-n ${dir(v)}`}
            title={`To the ${day(r.ret_asof)} close${notes.length ? `. ${notes.join(". ")}` : ""}`}>
            {signed(v)}
            {notes.length > 0 && v != null && <span className="nsr-warnmark"> *</span>}
          </td>
        );
      }
      case "r1y_vs_n500":
        return <td key={c.key} className={`nsr-n ${dir(r.r1y_vs_n500)}`}>{pts(r.r1y_vs_n500)}</td>;
      case "r1y_vs_sector":
        return <td key={c.key} className={`nsr-n ${dir(r.r1y_vs_sector)}`}>{pts(r.r1y_vs_sector)}</td>;
      case "vol":
        return <td key={c.key} className="nsr-n">{fixed(r.vol_1y, 0, "%")}</td>;
      case "mdd":
        return <td key={c.key} className="nsr-n down">{r.mdd_1y != null ? `${r.mdd_1y.toFixed(0)}%` : "—"}</td>;
      case "beta":
        return <td key={c.key} className="nsr-n">{fixed(r.beta_1y, 2)}</td>;
      case "from_high":
        return <td key={c.key} className="nsr-n">{r.from_high != null ? `${r.from_high.toFixed(0)}%` : "—"}</td>;
      case "from_ath":
        return (
          <td key={c.key} className={`nsr-n${r.ath_new ? " nsr-athnew" : ""}`} title={athTitle(r)}>{athText(r)}</td>
        );
      case "liquidity":
        return (
          <td key={c.key} className="nsr-n" title={r.notrade_3m != null ? `No trade on ${r.notrade_3m.toFixed(0)}% of the last 63 sessions` : undefined}>
            {r.tv_3m == null ? "—" : r.tv_3m >= 1 ? `₹${r.tv_3m.toFixed(r.tv_3m >= 100 ? 0 : 1)} Cr` : `₹${(r.tv_3m * 100).toFixed(0)} L`}
          </td>
        );
      case "deliv":
        return <td key={c.key} className="nsr-n">{fixed(r.deliv_20d, 0, "%")}</td>;
      case "e1d": case "e1w": case "e1m": case "e3m": {
        const hk = c.key.slice(1) as EstimateHorizon;
        return <td key={c.key} className="nsr-n nsr-estw">{estCell(r, hk, HORIZONS.find((h) => h.key === hk)?.long ?? hk)}</td>;
      }
      case "source":
        return (
          <td key={c.key} className="nsr-l nsr-src">
            {r.source_url ? (
              <a href={r.source_url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>screener.in</a>
            ) : (
              <span>screener.in</span>
            )}
            {r.basis && <span className="nsr-sub"> · {r.basis === "standalone" ? "standalone" : "consol."}</span>}
            <div className="nsr-sub">
              {r.fetch_error ? <span className="down" title={r.fetch_error}>read failed</span>
                : r.fetched_at ? `read ${day(r.fetched_at)}` : "not read yet"}
            </div>
          </td>
        );
      default:
        return <td key={c.key} />;
    }
  };

  return (
    <div className="nsr">
      {error && <div className="nsr-warn" role="alert">{error}</div>}
      {notice && <div className="nsr-notice">{notice}</div>}

      <GlassPanel title="NSE Stock Ratings" note={market?.as_of ? `Prices to the ${day(market.as_of)} close` : undefined}>
        <p className="nsr-lede">
          Every company on NSE&rsquo;s mainboard list, in three kinds of column that are kept apart:
          the <b>stock rating</b> (what the business and its price trend look like today), the{" "}
          <b>historical returns</b> (what the stock did) and the <b>forward estimates</b> (the range of
          what it might do, from its own volatility, validated against what actually happened). The
          estimates are ranges, not predictions or advice. Where the data cannot support a number, the
          row says <b>Insufficient Data</b> and why.
        </p>
        <div className="nsr-tiles">
          <Tile label="Listed stocks" value={counts.listed} />
          <Tile label="Rated" value={counts.rated} />
          <Tile label="Insufficient Data" value={counts.insufficient} muted />
          <Tile label="Latest quarter in" value={counts.fresh_current} />
          <Tile label="New results, refresh queued" value={counts.pending} accent />
          <Tile label="Past a filing deadline" value={counts.fresh_outdated} muted />
        </div>
        {market?.indices && (
          <div className="nsr-indices">
            {Object.entries(market.indices).map(([nm, rr]) => (
              <span key={nm} className="nsr-ix">
                <b>{nm}</b>
                {(["r1d", "r1m", "r1y"] as const).map((k) => (
                  <span key={k} className={dir(rr[k])}>{k.slice(1).toUpperCase()} {signed(rr[k])}</span>
                ))}
              </span>
            ))}
          </div>
        )}
        <div className="nsr-jobs">
          <span>Company list <b>{stamp(jobs?.universe?.at)}</b></span>
          <span>Results meetings checked <b>{stamp(jobs?.meetings?.at)}</b></span>
          <span>Fundamentals read <b>{read?.first ? `${day(read.first)} – ${day(read.last)}` : "—"}</b></span>
          <span>Prices, returns &amp; estimates <b>{market?.as_of ? `to the ${day(market.as_of)} close` : "not computed yet"}</b></span>
          {jobs?.errors && Object.entries(jobs.errors).map(([k, v]) => (
            <span key={k} className="down" title={v}>{k} failed: {v.slice(0, 90)}</span>
          ))}
        </div>
        {st && (st.running || st.finished_at) && (
          <div className="nsr-prog">
            {st.running && st.queue > 0 && st.step === "refresh" && (
              <div className="nsr-bar">
                <div className="nsr-fill" style={{ width: `${Math.min(100, (st.done / Math.max(1, st.queue)) * 100)}%` }} />
              </div>
            )}
            <div className="nsr-progtext">
              {st.running
                ? st.step === "refresh"
                  ? <>Reading screener.in: <b>{st.done}</b> of <b>{st.queue}</b> due{st.current ? <>, now <b>{st.current}</b></> : null}</>
                  : <>Working: <b>{st.step ?? "starting"}</b>{st.note ? ` (${st.note})` : ""}</>
                : <>Last refresh finished {stamp(st.finished_at)}: {st.ok} read, {st.failed} failed{st.queue > st.done ? `, ${st.queue - st.done} still due` : ""}</>}
              {st.note && st.step === "refresh" && <span className="nsr-sub"> · {st.note}</span>}
              {!st.running && st.note && <span className="nsr-sub"> · {st.note}</span>}
            </div>
          </div>
        )}
        <div className="nsr-run">
          <select value={refreshWhat} onChange={(e) => setRefreshWhat(e.target.value as NseRefreshWhat)} aria-label="What to refresh">
            <option value="due">Refresh what is due</option>
            <option value="meetings">Re-check results meetings (100 days)</option>
            <option value="returns">Recompute prices, returns &amp; estimates</option>
            <option value="universe">Re-read NSE company and index lists</option>
            <option value="rebuild">Rebuild every row from stored pages</option>
          </select>
          <button className="nsr-btn" onClick={trigger} disabled={triggering || running}>
            {running ? "Refresh running…" : triggering ? "Starting…" : "Run now"}
          </button>
          <button className="nsr-ghost" onClick={() => setShowMethod((v) => !v)}>
            {showMethod ? "Hide method" : "How ratings & estimates work"}
          </button>
          <span className="nsr-hint">Runs by itself every 15 minutes; prices and estimates update after each day&rsquo;s close.</span>
        </div>
      </GlassPanel>

      {showMethod && summary && <Methodology summary={summary} />}

      <GlassPanel title="Filters">
        <div className="nsr-filters">
          <label className="nsr-grow">
            <span>Search</span>
            <input value={searchInput} onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Company name or NSE symbol" aria-label="Search by company or symbol" />
          </label>
          <label>
            <span>Nifty index</span>
            <select value={index} onChange={(e) => setFilter(setIndex)(e.target.value)}>
              <option value="">Any</option>
              {(summary?.indices ?? []).map((i) => <option key={i.key} value={i.key}>{i.label} ({i.count})</option>)}
            </select>
          </label>
          <label>
            <span>Sector</span>
            <select value={sector} onChange={(e) => setFilter(setSector)(e.target.value)}>
              <option value="">Any</option>
              {(summary?.sectors ?? []).map((s) => <option key={s.key} value={s.key}>{s.key} ({s.count})</option>)}
            </select>
          </label>
          <label>
            <span>Quarterly performance</span>
            <select value={quarter} onChange={(e) => setFilter(setQuarter)(e.target.value)}>
              <option value="">Any</option>
              {(summary?.quarter_filters ?? []).map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
            </select>
          </label>
          <label>
            <span>Liquidity</span>
            <select value={liquidity} onChange={(e) => setFilter(setLiquidity)(e.target.value)}>
              <option value="">Any</option>
              {(summary?.liquidity_filters ?? []).map((f) => <option key={f.key} value={f.key}>{f.label} ({f.count})</option>)}
            </select>
          </label>
          <label>
            <span>Volatility</span>
            <select value={vol} onChange={(e) => setFilter(setVol)(e.target.value)}>
              <option value="">Any</option>
              {(summary?.vol_filters ?? []).map((f) => <option key={f.key} value={f.key}>{f.label} ({f.count})</option>)}
            </select>
          </label>
          {summary?.ath_filters && (
            <label>
              <span>All-time high</span>
              <select value={ath} onChange={(e) => setFilter(setAth)(e.target.value)}>
                <option value="">Any</option>
                {summary.ath_filters.map((f) => <option key={f.key} value={f.key}>{f.label} ({f.count})</option>)}
              </select>
            </label>
          )}
          <label>
            <span>1-month estimate</span>
            <select value={conf} onChange={(e) => setFilter(setConf)(e.target.value)}>
              <option value="">Any confidence</option>
              {(summary?.conf_filters ?? []).map((f) => <option key={f.key} value={f.key}>{f.label} ({f.count})</option>)}
            </select>
          </label>
          <label>
            <span>Data</span>
            <select value={dataFilter} onChange={(e) => setFilter(setDataFilter)(e.target.value)}>
              <option value="">Any</option>
              {(summary?.data_filters ?? []).map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
            </select>
          </label>
          <label>
            <span>Rows</span>
            <select value={pageSize} onChange={(e) => setFilter(setPageSize)(Number(e.target.value))}>
              {PAGE_SIZES.map((n) => <option key={n} value={n}>{n} a page</option>)}
            </select>
          </label>
        </div>

        <div className="nsr-chips" role="group" aria-label="Stock rating">
          <span className="nsr-chiplabel">Stock rating</span>
          {bestFirst.map((g) => {
            const on = ratings.includes(g);
            const c = tone(g);
            return (
              <button key={g} className={`nsr-chip${on ? " on" : ""}`} aria-pressed={on}
                style={on ? { background: c, borderColor: c, color: "#fff" } : { borderColor: c, color: c }}
                onClick={() => toggleRating(g)}>
                {g.replace("-", " ")}{summary?.ratings?.[g] ? ` ${summary.ratings[g]}` : ""}
              </button>
            );
          })}
          <button className={`nsr-chip${ratings.includes("insufficient") ? " on" : ""}`}
            aria-pressed={ratings.includes("insufficient")}
            style={ratings.includes("insufficient") ? { background: GREY, borderColor: GREY, color: "#fff" } : { borderColor: GREY, color: GREY }}
            onClick={() => toggleRating("insufficient")}>
            Insufficient Data{summary?.ratings?.insufficient ? ` ${summary.ratings.insufficient}` : ""}
          </button>
          {filtersOn && <button className="nsr-clear" onClick={clearFilters}>clear all filters</button>}
        </div>
      </GlassPanel>

      <GlassPanel
        title={`${total.toLocaleString("en-IN")} stocks`}
        note={loading ? "loading…" : data ? `page ${data.page} of ${data.pages} · click a row for the full analysis` : undefined}
        onRefresh={() => { load(); loadSummary(); }}
        refreshing={loading}
      >
        <div className="nsr-tvbar">
          <div className="nsr-presets" role="group" aria-label="Column presets">
            <span className="nsr-chiplabel">Columns</span>
            {PRESETS.map((p) => {
              const on = p.cols.length === cols.size && p.cols.every((k) => cols.has(k));
              return (
                <button key={p.key} className={`nsr-preset${on ? " on" : ""}`} onClick={() => setCols(new Set(p.cols))}>
                  {p.label}
                </button>
              );
            })}
            <button className="nsr-ghost nsr-small" onClick={() => setPickerOpen((v) => !v)} aria-expanded={pickerOpen}>
              {pickerOpen ? "Done" : `Choose columns (${visible.length})`}
            </button>
          </div>
          {exportItems ? (
            <TvExport items={exportItems} name={`NSE ratings ${new Date().toISOString().slice(0, 10)}`}
              groupOrder={[...bestFirst, "insufficient"]} sectionsLabel="sections by stock rating" />
          ) : (
            <button className="nsr-ghost" onClick={buildExport} disabled={exporting || !total}>
              {exporting ? "Building…" : `TradingView list of all ${total.toLocaleString("en-IN")} filtered`}
            </button>
          )}
        </div>

        {summary?.ath_filters && (
          <div className="nsr-presets nsr-athbar" role="group" aria-label="All-time high filter">
            <span className="nsr-chiplabel">All-time high</span>
            {ATH_CHIPS.map((c) => {
              const n = summary.ath_filters?.find((f) => f.key === c.key)?.count;
              return (
                <button key={c.key} className={`nsr-preset${ath === c.key ? " on" : ""}`} aria-pressed={ath === c.key}
                  onClick={() => pickAth(c.key)}>
                  {c.label}{n != null ? ` · ${n.toLocaleString("en-IN")}` : ""}
                </button>
              );
            })}
            {ath && (
              <button className="nsr-ghost nsr-small" onClick={() => setFilter(setAth)("")}>Clear</button>
            )}
          </div>
        )}

        {pickerOpen && (
          <div className="nsr-picker">
            {SECTIONS.map((s) => {
              const list = COLS.filter((c) => c.section === s.key && !c.fixed);
              if (!list.length) return null;
              const allOn = list.every((c) => cols.has(c.key));
              return (
                <fieldset key={s.key} className={`nsr-pick nsr-sec-${s.key}`}>
                  <legend>
                    <label className="nsr-check">
                      <input type="checkbox" checked={allOn} onChange={() => toggleSection(s.key, !allOn)} />
                      <b>{s.label}</b>
                    </label>
                  </legend>
                  {list.map((c) => (
                    <label key={c.key} className="nsr-check" title={c.title}>
                      <input type="checkbox" checked={cols.has(c.key)} onChange={() => toggleCol(c.key)} />
                      {c.label}
                    </label>
                  ))}
                </fieldset>
              );
            })}
          </div>
        )}

        <TopScrollbar target={tableBoxRef} />
        <div className="nsr-tablewrap" ref={tableBoxRef}>
          <table className="nsr-table">
            <thead>
              <tr className="nsr-bands">
                {bands.map((b, i) => (
                  <th key={`${b.section}-${i}`} colSpan={b.span}
                    className={`nsr-band nsr-sec-${b.section}${b.section === "company" ? " nsr-stick" : ""}`}>
                    {SECTIONS.find((s) => s.key === b.section)?.label}
                    {sectionNote[b.section] && <span className="nsr-bandnote">{sectionNote[b.section]}</span>}
                  </th>
                ))}
              </tr>
              <tr>
                {visible.map((c) => (
                  <th key={c.key}
                    className={`nsr-sec-${c.section}${c.key === "stock" ? " nsr-stick" : ""}${c.num ? " nsr-n" : ["stock", "sector", "index", "qlabel", "why", "source"].includes(c.key) ? " nsr-l" : ""}`}
                    title={c.title}
                    aria-sort={c.sort && sort === c.sort ? (order === "asc" ? "ascending" : "descending") : undefined}>
                    {c.sort ? (
                      <button className="nsr-sort" onClick={() => onSort(c)}>
                        {c.label}
                        <span className="nsr-arrow">{sort === c.sort ? (order === "asc" ? "▲" : "▼") : ""}</span>
                      </button>
                    ) : c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.symbol} tabIndex={0}
                  className={r.ovr_status === "insufficient" ? "nsr-row-ins" : ""}
                  onClick={() => setOpenSym(r.symbol)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      setOpenSym(r.symbol);
                    }
                  }}
                  aria-label={`Open the analysis of ${r.name || r.symbol}`}>
                  {visible.map((c) => cell(r, c))}
                </tr>
              ))}
              {!rows.length && !loading && (
                <tr>
                  <td colSpan={visible.length} className="nsr-empty">
                    {counts.listed === 0 || !summary
                      ? "The table is being built: the refresher reads NSE's company list, results meetings and prices, then fills rows from the ratings already stored."
                      : "No stock matches these filters."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {data && data.pages > 1 && (
          <div className="nsr-pager">
            <button className="nsr-ghost" onClick={() => setPage(1)} disabled={page <= 1}>« First</button>
            <button className="nsr-ghost" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1}>‹ Prev</button>
            <span>Page {data.page} of {data.pages}</span>
            <button className="nsr-ghost" onClick={() => setPage((p) => Math.min(data.pages, p + 1))} disabled={page >= data.pages}>Next ›</button>
            <button className="nsr-ghost" onClick={() => setPage(data.pages)} disabled={page >= data.pages}>Last »</button>
          </div>
        )}
      </GlassPanel>

      {openSym && (
        <RatingDrawer symbol={openSym} indices={market?.indices} onClose={() => setOpenSym(null)}
          onRefreshed={() => { load(); loadSummary(); }} />
      )}

      <style jsx global>{`
        .nsr-warn {
          margin-bottom: 12px;
          font-size: 12.5px;
          color: var(--warn);
          background: rgba(224, 122, 44, 0.08);
          border: 1px solid rgba(224, 122, 44, 0.3);
          border-radius: 9px;
          padding: 10px 12px;
        }
        .nsr-notice {
          margin-bottom: 12px;
          font-size: 12.5px;
          color: var(--text-muted);
          background: var(--canvas-soft);
          border: 1px solid var(--panel-border);
          border-radius: 9px;
          padding: 10px 12px;
        }
        .nsr-lede {
          margin: 0 0 14px;
          font-size: 13px;
          line-height: 1.6;
          color: var(--text-muted);
          max-width: 980px;
        }
        .nsr-tiles {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
          gap: 10px;
          margin-bottom: 12px;
        }
        .nsr-tile {
          border: 1px solid var(--panel-border);
          border-radius: 10px;
          padding: 10px 12px;
          background: var(--canvas-soft);
        }
        .nsr-tile b {
          display: block;
          font-size: 20px;
          font-family: var(--font-display);
          font-variant-numeric: tabular-nums;
        }
        .nsr-tile span {
          font-size: 11px;
          color: var(--text-faint);
        }
        .nsr-tile.muted b {
          color: var(--text-muted);
        }
        .nsr-tile.accent b {
          color: var(--purple);
        }
        .nsr-indices {
          display: flex;
          gap: 8px;
          flex-wrap: wrap;
          margin-bottom: 10px;
        }
        .nsr-ix {
          display: inline-flex;
          gap: 8px;
          align-items: baseline;
          border: 1px solid var(--panel-border);
          border-radius: 8px;
          padding: 5px 10px;
          font-size: 11.5px;
          font-variant-numeric: tabular-nums;
          color: var(--text-muted);
        }
        .nsr-ix b {
          color: var(--text);
          font-weight: 650;
        }
        .nsr-jobs {
          display: flex;
          gap: 16px;
          flex-wrap: wrap;
          font-size: 11.5px;
          color: var(--text-faint);
        }
        .nsr-jobs b {
          color: var(--text-muted);
          font-weight: 600;
        }
        .nsr-prog {
          margin-top: 12px;
        }
        .nsr-bar {
          height: 6px;
          background: var(--panel-border);
          border-radius: 4px;
          overflow: hidden;
          margin-bottom: 6px;
        }
        .nsr-fill {
          height: 100%;
          background: var(--purple);
          transition: width 0.4s ease;
        }
        .nsr-progtext {
          font-size: 12px;
          color: var(--text-muted);
        }
        .nsr-run {
          display: flex;
          gap: 10px;
          align-items: center;
          flex-wrap: wrap;
          margin-top: 14px;
        }
        .nsr select,
        .nsr input:not([type="checkbox"]) {
          border: 1px solid var(--panel-border);
          border-radius: 9px;
          padding: 8px 10px;
          font-size: 12.5px;
          background: var(--canvas-soft);
          color: var(--text);
          min-width: 0;
        }
        .nsr-btn {
          background: var(--purple);
          color: #fff;
          border: none;
          border-radius: 9px;
          padding: 9px 16px;
          font-weight: 650;
          font-size: 12.5px;
          cursor: pointer;
        }
        .nsr-btn:disabled {
          opacity: 0.55;
          cursor: default;
        }
        .nsr-ghost {
          background: var(--canvas-soft);
          border: 1px solid var(--panel-border);
          color: var(--text-muted);
          border-radius: 9px;
          padding: 8px 13px;
          font-size: 12.5px;
          font-weight: 600;
          cursor: pointer;
        }
        .nsr-ghost:disabled {
          opacity: 0.5;
          cursor: default;
        }
        .nsr-small {
          padding: 5px 10px;
          font-size: 11.5px;
        }
        .nsr-hint {
          font-size: 11.5px;
          color: var(--text-faint);
        }
        .nsr-filters {
          display: flex;
          gap: 12px;
          flex-wrap: wrap;
        }
        .nsr-filters label {
          display: flex;
          flex-direction: column;
          gap: 4px;
          min-width: 140px;
        }
        .nsr-filters label.nsr-grow {
          flex: 1 1 220px;
        }
        .nsr-filters label > span,
        .nsr-chiplabel {
          font-size: 10.5px;
          color: var(--text-faint);
          text-transform: uppercase;
          letter-spacing: 0.4px;
        }
        .nsr-chips {
          display: flex;
          gap: 6px;
          flex-wrap: wrap;
          align-items: center;
          margin-top: 14px;
        }
        .nsr-chiplabel {
          margin-right: 4px;
        }
        .nsr-chip {
          border: 1px solid;
          background: none;
          border-radius: 20px;
          padding: 4px 11px;
          font-size: 11px;
          font-weight: 650;
          cursor: pointer;
          text-transform: capitalize;
        }
        .nsr-clear {
          border: none;
          background: none;
          color: var(--text-faint);
          font-size: 11px;
          cursor: pointer;
          text-decoration: underline;
        }
        .nsr-check {
          display: inline-flex;
          align-items: center;
          gap: 5px;
          font-size: 12px;
          color: var(--text-muted);
          cursor: pointer;
        }
        .nsr-tvbar {
          display: flex;
          gap: 12px;
          flex-wrap: wrap;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 12px;
        }
        .nsr-presets {
          display: flex;
          gap: 6px;
          flex-wrap: wrap;
          align-items: center;
        }
        .nsr-preset {
          border: 1px solid var(--panel-border);
          background: var(--canvas-soft);
          color: var(--text-muted);
          border-radius: 20px;
          padding: 4px 11px;
          font-size: 11.5px;
          font-weight: 600;
          cursor: pointer;
        }
        .nsr-preset.on {
          background: var(--purple);
          border-color: var(--purple);
          color: #fff;
        }
        .nsr-picker {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
          gap: 10px;
          margin-bottom: 12px;
        }
        .nsr-pick {
          border: 1px solid var(--panel-border);
          border-radius: 10px;
          padding: 8px 12px 10px;
          display: flex;
          flex-direction: column;
          gap: 5px;
          margin: 0;
        }
        .nsr-pick legend {
          padding: 0 4px;
        }
        .nsr-athbar {
          margin: -4px 0 12px;
        }
        .nsr-athnew {
          color: var(--gain) !important;
          font-weight: 700;
        }
        .nsr-topscroll {
          overflow-x: auto;
          overflow-y: hidden;
          margin: 0 1px 4px;
        }
        .nsr-topscroll > div {
          height: 1px;
        }
        .nsr-topscroll.off {
          visibility: hidden;
          height: 0;
          margin-bottom: 0;
        }
        .nsr-tablewrap {
          overflow: auto;
          max-height: 72vh;
          border: 1px solid var(--panel-border);
          border-radius: 10px;
        }
        .nsr-table {
          border-collapse: separate;
          border-spacing: 0;
          width: 100%;
          font-size: 12px;
        }
        .nsr-table th,
        .nsr-table td {
          padding: 8px 10px;
          text-align: center;
          border-bottom: 1px solid var(--panel-border);
          white-space: nowrap;
          background: var(--panel);
        }
        .nsr-table thead tr:nth-child(2) th {
          position: sticky;
          top: 31px;
          z-index: 2;
          font-size: 10.5px;
          text-transform: uppercase;
          letter-spacing: 0.4px;
          color: var(--text-faint);
          font-weight: 600;
          background: var(--canvas-soft);
        }
        .nsr-table th.nsr-band {
          position: sticky;
          top: 0;
          z-index: 2;
          height: 31px;
          box-sizing: border-box;
          text-align: left;
          font-size: 11px;
          font-weight: 700;
          color: var(--text);
          background: var(--canvas-soft);
          border-left: 1px solid var(--panel-border);
          border-top: 3px solid var(--panel-border);
        }
        .nsr-bandnote {
          margin-left: 8px;
          font-size: 10.5px;
          font-weight: 500;
          color: var(--text-faint);
        }
        .nsr-table th.nsr-sec-rating {
          border-top-color: var(--purple);
        }
        .nsr-table th.nsr-sec-returns,
        .nsr-table th.nsr-sec-risk {
          border-top-color: var(--gain);
        }
        .nsr-table th.nsr-sec-estimates {
          border-top-color: var(--warn);
        }
        .nsr-table th.nsr-sec-estimates,
        .nsr-table td.nsr-estw {
          background: color-mix(in srgb, var(--warn) 5%, var(--panel));
        }
        .nsr-table .nsr-l {
          text-align: left;
        }
        .nsr-table .nsr-n {
          text-align: right;
          font-variant-numeric: tabular-nums;
        }
        .nsr-table .nsr-stick {
          position: sticky;
          left: 0;
          z-index: 1;
          min-width: 180px;
          max-width: 230px;
          box-shadow: 1px 0 0 var(--panel-border);
        }
        .nsr-table th.nsr-stick {
          z-index: 3;
        }
        .nsr-table tbody tr {
          cursor: pointer;
        }
        .nsr-table tbody tr:hover td,
        .nsr-table tbody tr:focus-visible td {
          background: var(--canvas-soft);
        }
        .nsr-table tbody tr:focus-visible {
          outline: 2px solid var(--purple);
          outline-offset: -2px;
        }
        .nsr-row-ins td {
          color: var(--text-muted);
        }
        .nsr-sort {
          background: none;
          border: none;
          padding: 0;
          font: inherit;
          color: inherit;
          text-transform: inherit;
          letter-spacing: inherit;
          cursor: pointer;
        }
        .nsr-arrow {
          display: inline-block;
          width: 10px;
          margin-left: 3px;
          color: var(--purple);
        }
        .nsr-nm {
          font-weight: 650;
          font-size: 12.5px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .nsr-sym {
          font-size: 10.5px;
          color: var(--text-faint);
          display: flex;
          gap: 5px;
          align-items: center;
        }
        .nsr-ser {
          border: 1px solid var(--panel-border);
          border-radius: 6px;
          padding: 0 5px;
          font-size: 9.5px;
          font-weight: 650;
          color: var(--text-muted);
        }
        .nsr-sub {
          font-size: 10.5px;
          color: var(--text-faint);
        }
        .nsr-clip {
          max-width: 170px;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .nsr-idx {
          font-size: 11.5px;
          color: var(--text-muted);
        }
        .nsr-pill {
          display: inline-flex;
          align-items: baseline;
          gap: 5px;
          border: 1px solid;
          border-radius: 20px;
          padding: 2px 9px;
          font-size: 10.5px;
          font-weight: 600;
          white-space: nowrap;
        }
        .nsr-pill b {
          font-size: 12px;
        }
        .nsr-pill-strong {
          color: #fff;
        }
        .nsr-ins {
          border-color: #8a8a99;
          color: #8a8a99;
          border-style: dashed;
        }
        .nsr-score {
          display: inline-block;
          min-width: 34px;
          border: 1px solid;
          border-radius: 7px;
          padding: 1px 6px;
          font-weight: 700;
          font-variant-numeric: tabular-nums;
        }
        .nsr-dash {
          color: var(--text-faint);
        }
        .nsr-q {
          font-weight: 600;
          margin-right: 6px;
        }
        .nsr-tag {
          display: inline-block;
          border: 1px solid var(--panel-border);
          border-radius: 6px;
          padding: 0 6px;
          font-size: 10px;
          color: var(--text-faint);
        }
        .nsr-tag-pend {
          border-color: var(--purple);
          color: var(--purple);
          background: var(--purple-dim);
        }
        .nsr-tag-warn {
          border-color: var(--warn);
          color: var(--warn);
        }
        .nsr-tag-bad {
          border-color: var(--loss);
          color: var(--loss);
        }
        .nsr-ok {
          color: var(--gain);
          font-weight: 700;
        }
        .nsr-warnmark {
          color: var(--warn);
          cursor: help;
        }
        .nsr-nm-cell {
          color: var(--text-faint);
          cursor: help;
        }
        .nsr .up {
          color: var(--gain);
        }
        .nsr .down {
          color: var(--loss);
        }
        .nsr-whyw {
          white-space: normal !important;
          min-width: 260px;
          max-width: 360px;
        }
        .nsr-why {
          display: -webkit-box;
          -webkit-line-clamp: 2;
          -webkit-box-orient: vertical;
          overflow: hidden;
          font-size: 11.5px;
          line-height: 1.45;
          color: var(--text-muted);
        }
        .nsr-est {
          display: inline-flex;
          flex-direction: column;
          align-items: flex-end;
          gap: 1px;
          cursor: help;
          line-height: 1.25;
        }
        .nsr-range {
          font-size: 10.5px;
          color: var(--text-faint);
        }
        .nsr-conf {
          font-size: 9.5px;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.3px;
          color: var(--text-faint);
        }
        .nsr-conf.high {
          color: var(--gain);
        }
        .nsr-conf.medium {
          color: var(--warn);
        }
        .nsr-conf.low {
          color: var(--loss);
        }
        .nsr-na {
          font-size: 10.5px;
          color: var(--text-faint);
          cursor: help;
        }
        .nsr-src a {
          color: var(--purple);
        }
        .nsr-empty {
          text-align: center !important;
          white-space: normal !important;
          color: var(--text-faint);
          padding: 28px 16px !important;
          font-size: 12.5px;
        }
        .nsr-pager {
          display: flex;
          gap: 8px;
          align-items: center;
          justify-content: center;
          flex-wrap: wrap;
          margin-top: 12px;
          font-size: 12px;
          color: var(--text-muted);
        }
        .nsm-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
          gap: 14px;
        }
        .nsm-card {
          border: 1px solid var(--panel-border);
          border-radius: 10px;
          padding: 12px 14px;
        }
        .nsm-card h4 {
          margin: 0 0 8px;
          font-size: 13px;
        }
        .nsm-weights {
          display: flex;
          gap: 6px;
          flex-wrap: wrap;
          margin-bottom: 8px;
        }
        .nsm-w {
          border: 1px solid var(--panel-border);
          border-radius: 8px;
          padding: 5px 9px;
          display: flex;
          flex-direction: column;
          font-size: 10.5px;
          color: var(--text-faint);
        }
        .nsm-w b {
          font-size: 14px;
          color: var(--text);
          font-family: var(--font-display);
        }
        .nsm-card ul {
          margin: 0;
          padding-left: 16px;
        }
        .nsm-card li,
        .nsm-card p {
          font-size: 12px;
          color: var(--text-muted);
          line-height: 1.55;
          margin: 0 0 5px;
        }
        .nsm-val {
          border-collapse: collapse;
          width: 100%;
          font-size: 11.5px;
          font-variant-numeric: tabular-nums;
          margin-top: 6px;
        }
        .nsm-val th,
        .nsm-val td {
          padding: 5px 6px;
          text-align: right;
          border-bottom: 1px solid var(--panel-border);
        }
        .nsm-val th:first-child,
        .nsm-val td:first-child {
          text-align: left;
        }
        .nsm-val th {
          font-size: 10.5px;
          color: var(--text-faint);
          font-weight: 600;
        }
        @media (max-width: 760px) {
          .nsr-filters label {
            min-width: 0;
            flex: 1 1 140px;
          }
          .nsr-table .nsr-stick {
            min-width: 140px;
            max-width: 160px;
          }
          .nsr-tablewrap {
            max-height: none;
          }
        }
      `}</style>
    </div>
  );
}

function Tile({ label, value, muted = false, accent = false }: {
  label: string;
  value: number | undefined;
  muted?: boolean;
  accent?: boolean;
}) {
  return (
    <div className={`nsr-tile${muted ? " muted" : ""}${accent ? " accent" : ""}`}>
      <b>{value === undefined ? "—" : value.toLocaleString("en-IN")}</b>
      <span>{label}</span>
    </div>
  );
}

function pctOf(v?: number) {
  return v === undefined || v === null ? "—" : `${(v * 100).toFixed(1)}%`;
}

/** The rules behind all three kinds of column, and how the estimates fared when tested. */
function Methodology({ summary }: { summary: NseRatingsSummary }) {
  const m = summary.methodology;
  const est = summary.estimates;
  const val = est?.validation ?? {};
  return (
    <GlassPanel title="How ratings, returns and estimates work" tint="lavender">
      <div className="nsm-grid">
        <div className="nsm-card">
          <h4>Stock rating</h4>
          <div className="nsm-weights">
            {Object.entries(m.rating_weights ?? {}).map(([k, w]) => (
              <div key={k} className="nsm-w"><b>{Math.round(w * 100)}%</b>{m.rating_labels?.[k] ?? k}</div>
            ))}
          </div>
          <ul>{(m.rules ?? []).slice(0, 4).map((r) => <li key={r}>{r}</li>)}</ul>
        </div>
        <div className="nsm-card">
          <h4>Data, freshness and historical returns</h4>
          <ul>{(m.rules ?? []).slice(4).map((r) => <li key={r}>{r}</li>)}</ul>
        </div>
        <div className="nsm-card">
          <h4>Forward estimates: ranges, not predictions</h4>
          <p>{est?.method ?? "The estimate calibration is not installed yet."}</p>
          {est?.signals && <p>{est.signals}</p>}
          {Object.keys(val).length > 0 && (
            <table className="nsm-val">
              <thead>
                <tr><th>Horizon</th><th>80% range held</th><th>Below 1-in-20</th><th>Outcomes</th><th>Bar</th></tr>
              </thead>
              <tbody>
                {HORIZONS.map((h) => {
                  const v: EstimateValidation | undefined = val[h.key];
                  if (!v) return null;
                  return (
                    <tr key={h.key}>
                      <td>{h.long}</td>
                      <td>{pctOf(v.coverage_80)} <span className="nsr-sub">(80%)</span></td>
                      <td>{pctOf(v.below_p05)} <span className="nsr-sub">(5%)</span></td>
                      <td>{v.n?.toLocaleString("en-IN") ?? "—"}</td>
                      <td className={v.passed ? "up" : "down"}>{v.passed ? "passed" : "missed"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
          {Object.values(val)[0]?.period && (
            <p className="nsr-sub">Hold-out test {Object.values(val)[0]?.period}; fitted on the two years before it and never refitted on it.</p>
          )}
        </div>
        <div className="nsm-card">
          <h4>Sources</h4>
          <ul>{Object.entries(summary.sources).map(([k, v]) => <li key={k}><b>{k.replace("_", " ")}</b>: {v}</li>)}</ul>
        </div>
      </div>
    </GlassPanel>
  );
}

/** One company's full analysis: how the rating was built, what the stock did, the estimate
 *  ranges with their confidence, and the statements, all from the page the row came from. */
function RatingDrawer({ symbol, indices, onClose, onRefreshed }: {
  symbol: string;
  indices?: Record<string, Record<string, number | null>>;
  onClose: () => void;
  onRefreshed: () => void;
}) {
  const [d, setD] = useState<NseRatingDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    let live = true;
    setD(null);
    setErr(null);
    fetchNseRatingDetail(symbol)
      .then((x) => live && setD(x))
      .catch((e) => live && setErr(e instanceof Error ? e.message : "Could not load the analysis."));
    return () => {
      live = false;
    };
  }, [symbol]);

  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [onClose]);

  const refresh = async () => {
    setBusy(true);
    setErr(null);
    try {
      const x = await refreshNseRating(symbol);
      setD(x);
      if (x.refresh && !x.refresh.ok) setErr(`screener.in: ${x.refresh.error}`);
      onRefreshed();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "The refresh failed.");
    } finally {
      setBusy(false);
    }
  };

  const r = d?.row;
  const flags = [...(r?.tflags ?? []), ...(r?.sflags ?? [])];
  const st = d?.statements;
  const periods = (st?.quarters_periods ?? []).slice(-8);
  const offset = (st?.quarters_periods ?? []).length - periods.length;
  const lines = st
    ? ["Sales", "Revenue", "Operating Profit", "Financing Profit", "OPM %", "Financing Margin %", "Other Income", "Net Profit"]
        .filter((n) => st.quarters[n])
    : [];
  const val = d?.estimate_validation ?? {};
  const n500 = indices?.["Nifty 500"];
  const RET: { key: "r1d" | "r1w" | "r1m" | "r2m" | "r3m" | "r6m" | "r1y" | "r2y" | "r5y"; label: string }[] = [
    { key: "r1d", label: "1 day" }, { key: "r1w", label: "1 week" }, { key: "r1m", label: "1 month" },
    { key: "r2m", label: "2 months" }, { key: "r3m", label: "3 months" }, { key: "r6m", label: "6 months" },
    { key: "r1y", label: "1 year" }, { key: "r2y", label: "2 years" }, { key: "r5y", label: "5 years" },
  ];

  return (
    <div className="nsd-scrim" onClick={onClose}>
      <aside className="nsd" role="dialog" aria-modal="true" aria-labelledby="nsd-title" onClick={(e) => e.stopPropagation()}>
        <div className="nsd-head">
          <div className="nsd-who">
            <div id="nsd-title" className="nsd-name">{r?.name || r?.screener_name || symbol}</div>
            <div className="nsd-meta">
              {symbol}
              {r?.series ? ` · ${r.series} series` : ""}
              {r?.index_label ? ` · ${r.index_label}` : ""}
              {r?.sector ? ` · ${r.sector}` : ""}
              {r?.industry && r.industry !== r.sector ? ` / ${r.industry}` : ""}
              {r?.ret_close ? ` · ${rupees(r.ret_close)} on ${shortDay(r.ret_asof)}` : ""}
            </div>
          </div>
          <button ref={closeRef} className="nsd-x" onClick={onClose} aria-label="Close the analysis">×</button>
        </div>

        {!d && !err && <div className="nsd-loading">Loading the stored analysis…</div>}
        {err && <div className="nsd-err" role="alert">{err}</div>}

        {r && (
          <div className="nsd-body">
            <section className="nsd-sec nsd-band-rating">
              <h4>Stock rating</h4>
              <div className="nsd-ovr">
                <div className="nsd-big" style={{ background: tone(r.ovr_key) }}>
                  {r.overall === null ? "—" : r.overall.toFixed(1)}
                </div>
                <div>
                  <div className="nsd-tier" style={{ color: tone(r.ovr_key) }}>
                    {r.ovr_status === "insufficient" ? "Insufficient Data" : r.ovr_tier}
                  </div>
                  <div className="nsd-formula">{r.ovr_formula ?? "No rating: the filings cannot support one."}</div>
                </div>
              </div>
              {r.ovr_status === "insufficient" ? (
                <ul className="nsd-list">{(r.ovr_reasons ?? []).map((x) => <li key={x}>{x}</li>)}</ul>
              ) : (
                <>
                  <div className="nsd-comps">
                    {PARTS.map((p) => {
                      const comp = (r.ovr_components ?? []).find((c) => c.key === p.key);
                      const s = r.rating_parts?.[p.key];
                      return (
                        <div key={p.key} className="nsd-comp">
                          <span className="nsd-cl">{p.label}</span>
                          <span className="nsd-cw">{comp ? `${Math.round(comp.eff * 100)}% of the rating` : "not scored"}</span>
                          <span className="nsd-cs">{s == null ? "—" : `${s.toFixed(1)}/10`}</span>
                          <div className="nsd-cbar"><div style={{ width: `${(s ?? 0) * 10}%`, background: scoreTone(s) }} /></div>
                        </div>
                      );
                    })}
                  </div>
                  {r.ovr_explain && <p className="nsd-line">{r.ovr_explain}</p>}
                </>
              )}
            </section>

            <section className="nsd-sec nsd-band-est">
              <h4>Forward estimates <span className="nsd-tag">estimates, not guarantees</span></h4>
              <p className="nsd-small">
                Ranges from the stock&rsquo;s own volatility around India&rsquo;s long-run market drift, from the{" "}
                {day(r.est_asof)} close. Bear and bull bound the 80% range; the downside is a 1-in-20 bad outcome.
              </p>
              <table className="nsd-ret">
                <thead>
                  <tr><th>Horizon</th><th>Bear</th><th>Base</th><th>Bull</th><th>1-in-20 downside</th><th>Confidence</th></tr>
                </thead>
                <tbody>
                  {HORIZONS.map((h) => {
                    const e = r.est?.[h.key];
                    if (!e || e.status !== "ok") {
                      return (
                        <tr key={h.key}>
                          <td>{h.long}</td>
                          <td colSpan={5} className="nsd-adj">Insufficient data{e?.reason ? `: ${e.reason}` : ""}</td>
                        </tr>
                      );
                    }
                    return (
                      <tr key={h.key}>
                        <td>{h.long}</td>
                        <td className={dir(e.bear)}>{signed(e.bear)}<div className="nsd-px">{rupees(e.bear_px)}</div></td>
                        <td className={dir(e.base)}>{signed(e.base)}<div className="nsd-px">{rupees(e.base_px)}</div></td>
                        <td className={dir(e.bull)}>{signed(e.bull)}<div className="nsd-px">{rupees(e.bull_px)}</div></td>
                        <td className="down">{signed(e.down)}<div className="nsd-px">{rupees(e.down_px)}</div></td>
                        <td title={e.conf_why}><span className={`nsr-conf ${e.conf}`}>{e.conf}</span></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {HORIZONS.some((h) => r.est?.[h.key]?.status === "ok") && (
                <p className="nsd-small">
                  {HORIZONS.map((h) => {
                    const v = val[h.key];
                    return v?.coverage_80 != null ? `${h.long}: the 80% range held ${(v.coverage_80 * 100).toFixed(0)}% of the time` : null;
                  }).filter(Boolean).join(" · ")}{Object.values(val)[0]?.period ? ` (hold-out ${Object.values(val)[0]?.period}).` : "."}
                  {" "}{r.est?.["1m"]?.conf_why ? `Confidence: ${r.est["1m"].conf_why}.` : ""}
                </p>
              )}
            </section>

            <section className="nsd-sec nsd-band-ret">
              <h4>Historical returns <span className="nsd-tag">to the {day(r.ret_asof)} close</span></h4>
              <table className="nsd-ret">
                <thead><tr><th>Period</th><th>Stock</th><th>Nifty 500</th><th>vs Nifty 500</th></tr></thead>
                <tbody>
                  {RET.map((x) => {
                    const v = r[x.key];
                    const b = n500?.[x.key] ?? null;
                    return (
                      <tr key={x.key}>
                        <td>{x.label}</td>
                        <td className={dir(v)}>{signed(v)}</td>
                        <td className={dir(b)}>{signed(b)}</td>
                        <td className={dir(v != null && b != null ? v - b : null)}>{v != null && b != null ? pts(v - b) : "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <p className="nsd-small">
                {r.r1y_vs_sector != null ? `1-year return ${pts(r.r1y_vs_sector)} against the ${r.sector} median; ` : ""}
                {r.r3m_vs_sector != null ? `3-month ${pts(r.r3m_vs_sector)}. ` : ""}
                Price returns on closes adjusted for bonuses, splits and consolidations; dividends are not included.
                {r.screener_1y != null && ` screener.in's own 1-year figure when the page was read: ${signed(r.screener_1y, 0)}.`}
              </p>
              {[...(r.ret_notes ?? []), ...(r.ret_check ? [r.ret_check] : [])].map((n) => (
                <p key={n} className="nsd-small nsd-warnline">{n}</p>
              ))}
            </section>

            <section className="nsd-sec">
              <h4>Risk &amp; liquidity <span className="nsd-tag">last year</span></h4>
              <div className="nsd-kv">
                <span>Volatility <b>{fixed(r.vol_1y, 0, "%")}</b></span>
                <span>Max drawdown <b className="down">{r.mdd_1y != null ? `${r.mdd_1y.toFixed(0)}%` : "—"}</b></span>
                <span>Beta to Nifty 500 <b>{fixed(r.beta_1y, 2)}</b></span>
                <span>From 52-week high <b>{r.from_high != null ? `${r.from_high.toFixed(0)}%` : "—"}</b></span>
                <span>From all-time high <b title={athTitle(r)}>{athText(r)}</b></span>
                <span>Traded per day <b>{r.tv_3m != null ? `₹${r.tv_3m.toFixed(1)} Cr` : "—"}</b></span>
                <span>No-trade sessions <b>{r.notrade_3m != null ? `${r.notrade_3m.toFixed(0)}%` : "—"}</b></span>
                <span>Delivery <b>{fixed(r.deliv_20d, 0, "%")}</b></span>
                <span>Momentum percentile <b>{r.mom_pct != null ? `${r.mom_pct.toFixed(0)}th` : "—"}</b></span>
              </div>
            </section>

            {flags.length > 0 && (
              <section className="nsd-sec">
                <h4>Data checks</h4>
                <ul className="nsd-flags">
                  {flags.map((f) => (
                    <li key={f.k + f.t} className={`nsd-flag ${f.lvl}`}>
                      <span className="nsd-fi">{f.lvl === "bad" ? "✕" : f.lvl === "warn" ? "!" : "i"}</span>
                      {f.t}
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {r.explain && r.ovr_status !== "insufficient" && (
              <section className="nsd-sec">
                <h4>Strengths, weaknesses and risks</h4>
                <div className="nsd-sw">
                  <div><b className="up">Strengths</b>
                    <ul>{r.explain.strengths.length ? r.explain.strengths.map((x) => <li key={x}>{x}</li>) : <li className="nsd-none">none above 7.5/10</li>}</ul></div>
                  <div><b className="down">Weaknesses</b>
                    <ul>{r.explain.weaknesses.length ? r.explain.weaknesses.map((x) => <li key={x}>{x}</li>) : <li className="nsd-none">none at or below 5/10</li>}</ul></div>
                  <div><b className="nsd-riskh">Risks</b>
                    <ul>{r.explain.risks.length ? r.explain.risks.map((x) => <li key={x}>{x}</li>) : <li className="nsd-none">none flagged by the filings</li>}</ul></div>
                </div>
                {d?.brief && <p className="nsd-brief">{d.brief}</p>}
              </section>
            )}

            {d?.results && (
              <section className="nsd-sec">
                <h4>
                  Latest quarter{d.results.latest_quarter ? `: ${d.results.latest_quarter}` : ""}
                  {d.results.comparison_quarter ? ` against ${d.results.comparison_quarter}` : ""}
                  <span className="nsd-grade" style={{ color: tone(d.results.grade_key) }}>
                    {d.results.score === null ? "not rated" : `${d.results.score.toFixed(1)} · ${d.results.tier}`}
                  </span>
                </h4>
                <p className="nsd-line">{d.results.headline}</p>
                {d.results.signals.length > 0 && (
                  <div className="nsd-sig">
                    {d.results.signals.map((s) => (
                      <div key={s.label} className={`nsd-sg ${s.tone}`} title={s.detail}><span>{s.label}</span><b>{s.value}</b></div>
                    ))}
                  </div>
                )}
                {periods.length > 0 && lines.length > 0 && (
                  <div className="nsd-tscroll">
                    <table className="nsd-stmt">
                      <thead><tr><th className="nsd-sl">₹ Cr</th>{periods.map((p) => <th key={p}>{p}</th>)}</tr></thead>
                      <tbody>
                        {lines.map((n) => (
                          <tr key={n}>
                            <td className="nsd-sl">{n}</td>
                            {periods.map((p, i) => {
                              const v = st?.quarters[n]?.[offset + i];
                              return (
                                <td key={p} className={v !== null && v !== undefined && v < 0 ? "down" : ""}>
                                  {v === null || v === undefined ? "—" : n.includes("%") ? `${v.toFixed(0)}%`
                                    : v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}
                                </td>
                              );
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            )}

            {d?.rating && (
              <section className="nsd-sec">
                <h4>
                  The seven fundamentals pillars
                  <span className="nsd-grade" style={{ color: tone(d.rating.grade_key) }}>
                    {d.rating.score === null ? "not rated" : `${d.rating.score.toFixed(1)} · ${d.rating.grade}`}
                  </span>
                </h4>
                {d.rating.pillars.map((p) => (
                  <div key={p.pillar} className="nsd-pillar">
                    <div className="nsd-prow">
                      <span className="nsd-pl">{p.label}</span>
                      <span className="nsd-pw">{Math.round((p.effective_weight ?? p.weight) * 100)}% of the 7-pillar score</span>
                      <span className="nsd-ps">{p.score.toFixed(1)}/10</span>
                    </div>
                    <div className="nsd-cbar"><div style={{ width: `${p.score * 10}%`, background: scoreTone(p.score) }} /></div>
                    <div className="nsd-pr">{p.reason}</div>
                  </div>
                ))}
                {d.rating.skipped.length > 0 && (
                  <p className="nsd-small"><b>Not scored:</b> {d.rating.skipped.map((s) => `${s.label} (${s.why})`).join("; ")}</p>
                )}
              </section>
            )}

            {d?.pnl && (
              <section className="nsd-sec">
                <h4>
                  P&amp;L record
                  <span className="nsd-grade" style={{ color: tone(d.pnl.grade_key) }}>
                    {d.pnl.score === null ? "not rated" : `${d.pnl.score.toFixed(1)} · ${d.pnl.tier}`}
                  </span>
                </h4>
                <p className="nsd-line">{d.pnl.headline}</p>
                {d.pnl.signals.length > 0 && (
                  <div className="nsd-sig">
                    {d.pnl.signals.map((s) => (
                      <div key={s.label} className={`nsd-sg ${s.tone}`} title={s.detail}><span>{s.label}</span><b>{s.value}</b></div>
                    ))}
                  </div>
                )}
              </section>
            )}

            <section className="nsd-sec">
              <h4>Source</h4>
              <p className="nsd-small">
                Fundamentals and statements:{" "}
                {r.source_url ? <a href={r.source_url} target="_blank" rel="noreferrer">screener.in</a> : "screener.in"}
                {r.basis ? ` (${r.basis})` : ""}, read {stamp(r.fetched_at)}.
                {r.last_meeting && ` Last results board meeting on NSE: ${day(r.last_meeting)}.`}
                {r.next_meeting && ` Next: ${day(r.next_meeting)}.`}
                {" "}Prices: NSE end-of-day bhavcopy, to the {day(r.ret_asof)} close. Index and sector: niftyindices.com and NSE.
              </p>
              {d?.about && <p className="nsd-small nsd-about">{d.about}</p>}
              <button className="nsr-btn" onClick={refresh} disabled={busy}>
                {busy ? "Reading screener.in…" : "Read screener.in again now"}
              </button>
            </section>
          </div>
        )}
      </aside>

      <style jsx global>{`
        .nsd-scrim {
          position: fixed;
          inset: 0;
          background: var(--scrim, rgba(20, 15, 35, 0.4));
          z-index: 1000;
          display: flex;
          justify-content: flex-end;
        }
        .nsd {
          width: min(760px, 100vw);
          height: 100%;
          overflow-y: auto;
          background: var(--panel);
          color: var(--text);
          box-shadow: var(--shadow-lg);
          border-left: 1px solid var(--panel-border);
        }
        .nsd-head {
          position: sticky;
          top: 0;
          z-index: 2;
          display: flex;
          gap: 12px;
          align-items: flex-start;
          justify-content: space-between;
          padding: 16px 20px 12px;
          background: var(--panel);
          border-bottom: 1px solid var(--panel-border);
        }
        .nsd-name {
          font-size: 17px;
          font-weight: 750;
        }
        .nsd-meta {
          font-size: 12px;
          color: var(--text-faint);
          margin-top: 2px;
        }
        .nsd-x {
          border: 1px solid var(--panel-border);
          background: var(--canvas-soft);
          color: var(--text-muted);
          width: 32px;
          height: 32px;
          border-radius: 8px;
          font-size: 18px;
          line-height: 1;
          cursor: pointer;
          flex: 0 0 auto;
        }
        .nsd-loading,
        .nsd-err {
          padding: 18px 20px;
          font-size: 13px;
          color: var(--text-muted);
        }
        .nsd-err {
          color: var(--warn);
        }
        .nsd-body {
          padding: 6px 20px 28px;
        }
        .nsd-sec {
          padding: 14px 0;
          border-bottom: 1px solid var(--panel-border);
        }
        .nsd-sec:last-child {
          border-bottom: none;
        }
        .nsd-band-rating {
          border-left: 3px solid var(--purple);
          padding-left: 12px;
        }
        .nsd-band-est {
          border-left: 3px solid var(--warn);
          padding-left: 12px;
        }
        .nsd-band-ret {
          border-left: 3px solid var(--gain);
          padding-left: 12px;
        }
        .nsd-sec h4 {
          margin: 0 0 8px;
          font-size: 13.5px;
          display: flex;
          gap: 10px;
          align-items: baseline;
          flex-wrap: wrap;
        }
        .nsd-tag {
          font-size: 10.5px;
          font-weight: 600;
          color: var(--text-faint);
          border: 1px solid var(--panel-border);
          border-radius: 6px;
          padding: 0 6px;
        }
        .nsd-grade {
          font-size: 12px;
          font-weight: 700;
        }
        .nsd-ovr {
          display: flex;
          gap: 14px;
          align-items: center;
        }
        .nsd-big {
          width: 62px;
          height: 62px;
          border-radius: 14px;
          color: #fff;
          font-size: 22px;
          font-weight: 800;
          display: flex;
          align-items: center;
          justify-content: center;
          font-family: var(--font-display);
          flex: 0 0 auto;
        }
        .nsd-tier {
          font-size: 15px;
          font-weight: 750;
        }
        .nsd-formula {
          font-size: 12px;
          color: var(--text-muted);
          margin-top: 2px;
          font-variant-numeric: tabular-nums;
        }
        .nsd-comps {
          margin-top: 12px;
        }
        .nsd-comp {
          display: grid;
          grid-template-columns: 1fr auto auto;
          gap: 4px 12px;
          align-items: baseline;
          margin-bottom: 8px;
          font-size: 12.5px;
        }
        .nsd-cl {
          font-weight: 650;
        }
        .nsd-cw {
          color: var(--text-faint);
          font-size: 11px;
        }
        .nsd-cs {
          font-weight: 700;
          font-variant-numeric: tabular-nums;
        }
        .nsd-cbar {
          grid-column: 1 / -1;
          height: 5px;
          border-radius: 3px;
          background: var(--panel-border);
          overflow: hidden;
          margin: 4px 0 2px;
        }
        .nsd-cbar > div {
          height: 100%;
          border-radius: 3px;
        }
        .nsd-list {
          margin: 10px 0 0;
          padding-left: 18px;
          font-size: 12.5px;
          color: var(--text-muted);
          line-height: 1.55;
        }
        .nsd-kv {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
          gap: 6px 14px;
          font-size: 12px;
          color: var(--text-muted);
        }
        .nsd-kv b {
          color: var(--text);
          font-variant-numeric: tabular-nums;
          margin-left: 4px;
        }
        .nsd-flags {
          list-style: none;
          margin: 0;
          padding: 0;
          display: flex;
          flex-direction: column;
          gap: 6px;
        }
        .nsd-flag {
          display: flex;
          gap: 8px;
          align-items: flex-start;
          font-size: 12.5px;
          line-height: 1.5;
          color: var(--text-muted);
        }
        .nsd-fi {
          flex: 0 0 18px;
          height: 18px;
          border-radius: 50%;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          font-size: 10.5px;
          font-weight: 800;
          border: 1px solid var(--panel-border);
          color: var(--text-faint);
        }
        .nsd-flag.warn .nsd-fi {
          border-color: var(--warn);
          color: var(--warn);
        }
        .nsd-flag.bad .nsd-fi {
          border-color: var(--loss);
          color: var(--loss);
        }
        .nsd-sw {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 14px;
        }
        .nsd-sw b {
          font-size: 12px;
        }
        .nsd-sw ul {
          margin: 6px 0 0;
          padding-left: 16px;
        }
        .nsd-sw li {
          font-size: 12px;
          color: var(--text-muted);
          line-height: 1.45;
          margin-bottom: 4px;
        }
        .nsd-riskh {
          color: var(--warn);
        }
        .nsd-none {
          color: var(--text-faint);
          font-style: italic;
          list-style: none;
          margin-left: -16px;
        }
        .nsd-brief,
        .nsd-line {
          font-size: 12.5px;
          color: var(--text-muted);
          line-height: 1.6;
          margin: 10px 0 0;
        }
        .nsd-sig {
          display: flex;
          gap: 8px;
          flex-wrap: wrap;
          margin-top: 10px;
        }
        .nsd-sg {
          border: 1px solid var(--panel-border);
          border-radius: 9px;
          padding: 6px 11px;
          display: flex;
          flex-direction: column;
          gap: 1px;
          cursor: help;
        }
        .nsd-sg span {
          font-size: 10.5px;
          color: var(--text-faint);
        }
        .nsd-sg b {
          font-size: 12.5px;
        }
        .nsd-sg.good {
          border-color: var(--gain);
        }
        .nsd-sg.good b {
          color: var(--gain);
        }
        .nsd-sg.bad {
          border-color: var(--loss);
        }
        .nsd-sg.bad b {
          color: var(--loss);
        }
        .nsd-tscroll {
          overflow-x: auto;
          margin-top: 12px;
          border: 1px solid var(--panel-border);
          border-radius: 9px;
        }
        .nsd-stmt,
        .nsd-ret {
          border-collapse: collapse;
          width: 100%;
          font-size: 11.5px;
          white-space: nowrap;
        }
        .nsd-stmt th,
        .nsd-stmt td,
        .nsd-ret th,
        .nsd-ret td {
          padding: 6px 9px;
          text-align: right;
          border-bottom: 1px solid var(--panel-border);
          font-variant-numeric: tabular-nums;
          vertical-align: top;
        }
        .nsd-stmt th,
        .nsd-ret th {
          font-size: 10.5px;
          color: var(--text-faint);
          font-weight: 600;
          background: var(--canvas-soft);
        }
        .nsd-px {
          font-size: 10.5px;
          color: var(--text-faint);
        }
        .nsd-sl {
          text-align: left !important;
          position: sticky;
          left: 0;
          background: var(--panel);
        }
        th.nsd-sl {
          background: var(--canvas-soft);
        }
        .nsd-ret td:first-child,
        .nsd-ret th:first-child,
        .nsd-ret .nsd-adj {
          text-align: left;
        }
        .nsd-adj {
          white-space: normal;
          color: var(--text-muted);
          font-size: 11px;
        }
        .nsd-pillar {
          margin-bottom: 12px;
        }
        .nsd-prow {
          display: flex;
          gap: 10px;
          align-items: baseline;
        }
        .nsd-pl {
          font-weight: 650;
          font-size: 12.5px;
        }
        .nsd-pw {
          flex: 1 1 auto;
          font-size: 11px;
          color: var(--text-faint);
        }
        .nsd-ps {
          font-weight: 700;
          font-size: 12.5px;
        }
        .nsd-pr {
          font-size: 12px;
          color: var(--text-muted);
          line-height: 1.5;
        }
        .nsd-small {
          font-size: 11.5px;
          color: var(--text-faint);
          line-height: 1.55;
          margin: 8px 0 0;
        }
        .nsd-small a {
          color: var(--purple);
        }
        .nsd-warnline {
          color: var(--warn);
        }
        .nsd-about {
          margin-bottom: 12px;
        }
        .nsd .up {
          color: var(--gain);
        }
        .nsd .down {
          color: var(--loss);
        }
        @media (max-width: 640px) {
          .nsd-sw {
            grid-template-columns: 1fr;
          }
          .nsd-head,
          .nsd-body {
            padding-left: 16px;
            padding-right: 16px;
          }
        }
      `}</style>
    </div>
  );
}
