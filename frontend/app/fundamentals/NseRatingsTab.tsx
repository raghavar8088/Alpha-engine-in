"use client";

/** NSE Stock Ratings: every NSE-listed company on one table, rated by this module's own rules.
 *
 * Filtering, sorting and paging all happen on the server: 2,600-odd rows of thirty columns is
 * too much to ship on every keystroke. The drawer recomputes one company from its cached
 * screener.in page, so what it shows is the calculation the row's numbers came from, not a
 * second opinion. The page never claims more than the data supports: a company without enough
 * data says "Insufficient Data" and why, rather than wearing a number.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import { GRADE_COLOR, GRADE_ORDER, GradeKey } from "../../lib/api";
import {
  NseRatingDetail,
  NseRatingRow,
  NseRatingsPage,
  NseRatingsQuery,
  NseRatingsSummary,
  NseRefreshWhat,
  OverallKey,
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
const PREFS_KEY = "nseRatings.view.v1";
const POLL_MS = 15000;

type Group = "quarter" | "metrics" | "returns" | "notes" | "source";
const GROUPS: { key: Group; label: string }[] = [
  { key: "quarter", label: "Latest quarter" },
  { key: "metrics", label: "Key metrics" },
  { key: "returns", label: "Returns" },
  { key: "notes", label: "Explanation" },
  { key: "source", label: "Source" },
];

interface Col {
  key: string;
  label: string;
  group: Group | null;
  sort?: string;
  /** The direction a first click sorts in. Lower is better for P/E and debt. */
  first?: "asc" | "desc";
  num?: boolean;
  title?: string;
}

const COLS: Col[] = [
  { key: "stock", label: "Stock", group: null, sort: "name", first: "asc" },
  { key: "sector", label: "Sector", group: null, sort: "sector", first: "asc" },
  { key: "index", label: "Nifty index", group: null, sort: "index", first: "asc" },
  { key: "overall", label: "Overall", group: null, sort: "overall",
    title: "70% fundamentals + 15% latest quarter + 15% P&L record" },
  { key: "fund", label: "Fundamentals", group: null, sort: "fundamentals",
    title: "The seven-pillar score, exactly as the Rate tab computes it" },
  { key: "quarter", label: "Quarter", group: null, sort: "quarter",
    title: "The latest quarter against the same quarter a year earlier" },
  { key: "pnl", label: "P&L record", group: null, sort: "pnl",
    title: "The multi-year profit & loss record on its own" },
  { key: "qlabel", label: "Latest qtr", group: "quarter", sort: "latest_quarter" },
  { key: "rev", label: "Revenue", group: "quarter", sort: "revenue", num: true,
    title: "Latest quarter, ₹ crore" },
  { key: "rev_yoy", label: "Rev YoY", group: "quarter", sort: "rev_yoy", num: true },
  { key: "rev_qoq", label: "Rev QoQ", group: "quarter", sort: "rev_qoq", num: true,
    title: "Shown, never scored: most Indian businesses are seasonal" },
  { key: "np", label: "Net profit", group: "quarter", sort: "profit", num: true,
    title: "Latest quarter, ₹ crore" },
  { key: "np_yoy", label: "NP YoY", group: "quarter", sort: "np_yoy", num: true },
  { key: "np_qoq", label: "NP QoQ", group: "quarter", sort: "np_qoq", num: true },
  { key: "roce", label: "ROCE", group: "metrics", sort: "roce", num: true },
  { key: "roe", label: "ROE", group: "metrics", sort: "roe", num: true },
  { key: "de", label: "Debt/Eq", group: "metrics", sort: "de", num: true, first: "asc" },
  { key: "opm", label: "OPM", group: "metrics", sort: "opm", num: true,
    title: "Operating margin, latest year" },
  { key: "sales_cagr", label: "Sales 3y", group: "metrics", sort: "sales_cagr", num: true,
    title: "Compounded sales growth a year, over 3 years (5 where 3 is not published)" },
  { key: "profit_cagr", label: "Profit 3y", group: "metrics", sort: "profit_cagr", num: true,
    title: "Compounded profit growth a year, over 3 years (5 where 3 is not published)" },
  { key: "pe", label: "P/E", group: "metrics", sort: "pe", num: true, first: "asc" },
  { key: "promoter", label: "Promoter", group: "metrics", sort: "promoter", num: true },
  { key: "mcap", label: "M-cap", group: "metrics", sort: "mcap", num: true },
  { key: "r3m", label: "3M", group: "returns", sort: "r3m", num: true,
    title: "Price return over 3 months, adjusted for bonuses and splits" },
  { key: "r6m", label: "6M", group: "returns", sort: "r6m", num: true },
  { key: "r1y", label: "1Y", group: "returns", sort: "r1y", num: true },
  { key: "r2y", label: "2Y", group: "returns", sort: "r2y", num: true },
  { key: "why", label: "Why this rating", group: "notes" },
  { key: "source", label: "Source · read", group: "source", sort: "updated" },
];

const SERIES_NOTE: Record<string, string> = {
  BE: "BE series: trade-for-trade, every trade settles by delivery",
  BZ: "BZ series: NSE flags it for non-compliance with listing rules",
};

function tone(key?: string | null): string {
  if (!key || key === "insufficient" || key === "unrated") return GREY;
  return GRADE_COLOR[key as GradeKey] ?? GREY;
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
const signed = (v: number | null | undefined, d = 1) =>
  v === null || v === undefined ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(d)}%`;
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
  const [sort, setSort] = useState("overall");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [groups, setGroups] = useState<Record<Group, boolean>>({
    quarter: true, metrics: true, returns: true, notes: true, source: true,
  });
  const [showMethod, setShowMethod] = useState(false);
  const [openSym, setOpenSym] = useState<string | null>(null);
  const [exportItems, setExportItems] = useState<TvItem[] | null>(null);
  const [exporting, setExporting] = useState(false);
  const [refreshWhat, setRefreshWhat] = useState<NseRefreshWhat>("due");
  const [triggering, setTriggering] = useState(false);

  const reqId = useRef(0);
  const lastDone = useRef(0);

  // Which column groups are showing is a per-viewer convenience: remembered when the
  // browser allows it, and the page works the same when it does not.
  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(PREFS_KEY);
      if (!raw) return;
      const v = JSON.parse(raw);
      if (v && typeof v.groups === "object") setGroups((g) => ({ ...g, ...v.groups }));
      if (PAGE_SIZES.includes(v?.pageSize)) setPageSize(v.pageSize);
    } catch {
      /* storage blocked or unreadable: the defaults stand */
    }
  }, []);
  useEffect(() => {
    try {
      window.localStorage.setItem(PREFS_KEY, JSON.stringify({ groups, pageSize }));
    } catch {
      /* not worth surfacing */
    }
  }, [groups, pageSize]);

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
      sort,
      order,
      page,
      pageSize,
    }),
    [search, index, sector, ratings, quarter, dataFilter, sort, order, page, pageSize],
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

  // A TradingView list built for one set of filters must not be offered for another.
  useEffect(() => {
    setExportItems(null);
  }, [search, index, sector, ratings, quarter, dataFilter]);

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
    setPage(1);
  };

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
  const visible = COLS.filter((c) => !c.group || groups[c.group]);
  const rows = data?.rows ?? [];
  const total = data?.total ?? 0;
  const filtersOn = !!(search || index || sector || ratings.length || quarter || dataFilter);
  const bestFirst: OverallKey[] = [...GRADE_ORDER].reverse();

  const cell = (r: NseRatingRow, c: Col) => {
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
              <span className="nsr-pill nsr-ins" title={(r.ovr_reasons ?? []).join("; ")}>
                Insufficient Data
              </span>
            ) : (
              <Pill score={r.overall} tier={r.ovr_tier} k={r.ovr_key} title={r.ovr_formula} strong />
            )}
          </td>
        );
      case "fund":
        return <td key={c.key}><Pill score={r.fund} tier={r.fund_tier} k={r.fund_key} /></td>;
      case "quarter":
        return <td key={c.key}><Pill score={r.quarter} tier={r.q_tier} k={r.q_key} /></td>;
      case "pnl":
        return <td key={c.key}><Pill score={r.pnl} tier={r.pnl_tier} k={r.pnl_key} /></td>;
      case "qlabel":
        return (
          <td key={c.key} className="nsr-l">
            <span className="nsr-q">{r.qlabel || "—"}</span>
            {r.pending ? (
              <span className="nsr-tag nsr-tag-pend"
                title={(r.tflags ?? []).find((f) => f.k === "pending")?.t ?? "New results are out"}>
                new results · queued
              </span>
            ) : r.freshness === "outdated" ? (
              <span className={`nsr-tag ${(r.behind ?? 0) >= 2 ? "nsr-tag-bad" : "nsr-tag-warn"}`}
                title={(r.tflags ?? []).find((f) => f.k === "outdated")?.t ?? ""}>
                {r.behind} qtr overdue
              </span>
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
        if (v === null && note) {
          return (
            <td key={c.key} className="nsr-n nsr-nm-cell" title={note.slice(5)}>n/m</td>
          );
        }
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
          <td key={c.key} className="nsr-n"
            title={r.is_lender && r.net_margin != null ? `Lender: net margin ${r.net_margin.toFixed(0)}%` : undefined}>
            {r.is_lender ? (r.net_margin != null ? `${r.net_margin.toFixed(0)}% net` : "n/a") : fixed(r.opm, 0, "%")}
          </td>
        );
      case "sales_cagr":
        return <td key={c.key} className={`nsr-n ${dir(r.sales_cagr)}`}>{signed(r.sales_cagr, 0)}</td>;
      case "profit_cagr":
        return <td key={c.key} className={`nsr-n ${dir(r.profit_cagr)}`}>{signed(r.profit_cagr, 0)}</td>;
      case "pe":
        return <td key={c.key} className="nsr-n">{fixed(r.pe, 1)}</td>;
      case "promoter":
        return (
          <td key={c.key} className="nsr-n"
            title={r.no_promoter && r.institutional != null ? `No promoter group; institutions hold ${r.institutional.toFixed(0)}%` : undefined}>
            {r.no_promoter ? "none" : fixed(r.promoter, 1, "%")}
          </td>
        );
      case "mcap":
        return <td key={c.key} className="nsr-n">{crore(r.mcap)}</td>;
      case "r3m":
      case "r6m":
      case "r1y":
      case "r2y": {
        const v = r[c.key as "r3m" | "r6m" | "r1y" | "r2y"];
        const notes = [...(r.ret_notes ?? []), ...(r.ret_check ? [r.ret_check] : [])];
        return (
          <td key={c.key} className={`nsr-n ${dir(v)}`}
            title={`As of the ${day(r.ret_asof)} close${notes.length ? `. ${notes.join(". ")}` : ""}`}>
            {signed(v)}
            {notes.length > 0 && v !== null && <span className="nsr-warnmark"> *</span>}
          </td>
        );
      }
      case "why": {
        const text = r.ovr_status === "insufficient"
          ? `Insufficient Data: ${(r.ovr_reasons ?? []).join("; ")}.`
          : r.explain?.text || "—";
        return (
          <td key={c.key} className="nsr-l nsr-whyw">
            <div className="nsr-why" title={text}>{text}</div>
          </td>
        );
      }
      case "source":
        return (
          <td key={c.key} className="nsr-l nsr-src">
            {r.source_url ? (
              <a href={r.source_url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>
                screener.in
              </a>
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

      <GlassPanel title="NSE Stock Ratings" note={jobs?.returns?.as_of ? `Prices as of the ${day(jobs.returns.as_of)} close` : undefined}>
        <p className="nsr-lede">
          Every company on NSE&rsquo;s mainboard list, in the EQ, BE and BZ series, rated with this
          module&rsquo;s own seven pillars, quarterly-results read and P&amp;L record, and read
          again from screener.in when NSE lists a results board meeting. Where the filings cannot
          carry a rating, the row says <b>Insufficient Data</b> and why. A research aid over
          public filings, not investment advice.
        </p>
        <div className="nsr-tiles">
          <Tile label="Listed stocks" value={counts.listed} />
          <Tile label="Rated" value={counts.rated} />
          <Tile label="Insufficient Data" value={counts.insufficient} muted />
          <Tile label="Latest quarter in" value={counts.fresh_current} />
          <Tile label="New results, refresh queued" value={counts.pending} accent />
          <Tile label="Past a filing deadline" value={counts.fresh_outdated} muted />
        </div>
        <div className="nsr-jobs">
          <span>Company list <b>{stamp(jobs?.universe?.at)}</b></span>
          <span>Results meetings checked <b>{stamp(jobs?.meetings?.at)}</b></span>
          <span>Returns <b>{jobs?.returns?.as_of ? `as of ${day(jobs.returns.as_of)}` : "not computed yet"}</b></span>
          {jobs?.errors && Object.entries(jobs.errors).map(([k, v]) => (
            <span key={k} className="down" title={v}>{k} failed: {v.slice(0, 90)}</span>
          ))}
        </div>
        {st && (st.running || st.finished_at) && (
          <div className="nsr-prog">
            {st.running && st.queue > 0 && (
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
          <select value={refreshWhat} onChange={(e) => setRefreshWhat(e.target.value as NseRefreshWhat)}
            aria-label="What to refresh">
            <option value="due">Refresh what is due</option>
            <option value="meetings">Re-check results meetings (100 days)</option>
            <option value="returns">Recompute returns</option>
            <option value="universe">Re-read NSE company and index lists</option>
            <option value="rebuild">Rebuild every row from stored pages</option>
          </select>
          <button className="nsr-btn" onClick={trigger} disabled={triggering || running}>
            {running ? "Refresh running…" : triggering ? "Starting…" : "Run now"}
          </button>
          <button className="nsr-ghost" onClick={() => setShowMethod((v) => !v)}>
            {showMethod ? "Hide method" : "How the rating is built"}
          </button>
          <span className="nsr-hint">Runs by itself every 15 minutes; this only starts it sooner.</span>
        </div>
      </GlassPanel>

      {showMethod && summary && (
        <GlassPanel title="How the rating is built" tint="lavender">
          <div className="nsr-weights">
            {Object.entries(summary.methodology.overall_weights).map(([k, w]) => (
              <div key={k} className="nsr-w">
                <b>{Math.round(w * 100)}%</b>
                <span>{k === "fundamentals" ? "Fundamentals (7 pillars)" : k === "quarter" ? "Latest quarter" : "P&L record"}</span>
              </div>
            ))}
          </div>
          <ul className="nsr-rules">
            {summary.methodology.rules.map((r) => <li key={r}>{r}</li>)}
          </ul>
          <div className="nsr-sources">
            {Object.entries(summary.sources).map(([k, v]) => (
              <span key={k}><b>{k.replace("_", " ")}</b>: {v}</span>
            ))}
          </div>
        </GlassPanel>
      )}

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
              {(summary?.indices ?? []).map((i) => (
                <option key={i.key} value={i.key}>{i.label} ({i.count})</option>
              ))}
            </select>
          </label>
          <label>
            <span>Sector</span>
            <select value={sector} onChange={(e) => setFilter(setSector)(e.target.value)}>
              <option value="">Any</option>
              {(summary?.sectors ?? []).map((s) => (
                <option key={s.key} value={s.key}>{s.key} ({s.count})</option>
              ))}
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

        <div className="nsr-chips" role="group" aria-label="Overall rating">
          <span className="nsr-chiplabel">Overall rating</span>
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
            style={ratings.includes("insufficient") ? { background: GREY, borderColor: GREY, color: "#fff" }
              : { borderColor: GREY, color: GREY }}
            onClick={() => toggleRating("insufficient")}>
            Insufficient Data{summary?.ratings?.insufficient ? ` ${summary.ratings.insufficient}` : ""}
          </button>
          {filtersOn && <button className="nsr-clear" onClick={clearFilters}>clear all filters</button>}
        </div>

        <div className="nsr-groups">
          <span className="nsr-chiplabel">Columns</span>
          {GROUPS.map((g) => (
            <label key={g.key} className="nsr-check">
              <input type="checkbox" checked={groups[g.key]}
                onChange={() => setGroups((prev) => ({ ...prev, [g.key]: !prev[g.key] }))} />
              {g.label}
            </label>
          ))}
        </div>
      </GlassPanel>

      <GlassPanel
        title={`${total.toLocaleString("en-IN")} stocks`}
        note={loading ? "loading…" : data ? `page ${data.page} of ${data.pages} · click a row for the full analysis` : undefined}
        onRefresh={() => { load(); loadSummary(); }}
        refreshing={loading}
      >
        <div className="nsr-tvbar">
          {exportItems ? (
            <TvExport items={exportItems}
              name={`NSE ratings ${new Date().toISOString().slice(0, 10)}`}
              groupOrder={[...bestFirst, "insufficient"]}
              sectionsLabel="sections by overall rating" />
          ) : (
            <button className="nsr-ghost" onClick={buildExport} disabled={exporting || !total}>
              {exporting ? "Building…" : `TradingView list of all ${total.toLocaleString("en-IN")} filtered`}
            </button>
          )}
        </div>

        <div className="nsr-tablewrap">
          <table className="nsr-table">
            <thead>
              <tr>
                {visible.map((c) => (
                  <th key={c.key}
                    className={`${c.key === "stock" ? "nsr-stick " : ""}${c.num ? "nsr-n" : c.key === "stock" || c.key === "sector" || c.key === "index" || c.key === "qlabel" || c.key === "why" || c.key === "source" ? "nsr-l" : ""}`}
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
                      ? "The table is being built: the refresher reads NSE's company list, results meetings and prices, then fills rows from the ratings already stored. It starts a few minutes after the backend does."
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
        <RatingDrawer symbol={openSym} onClose={() => setOpenSym(null)}
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
          max-width: 920px;
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
        .nsr-hint {
          font-size: 11.5px;
          color: var(--text-faint);
        }
        .nsr-weights {
          display: flex;
          gap: 8px;
          flex-wrap: wrap;
          margin-bottom: 12px;
        }
        .nsr-w {
          border: 1px solid var(--panel-border);
          border-radius: 9px;
          padding: 8px 12px;
          display: flex;
          flex-direction: column;
          gap: 2px;
        }
        .nsr-w b {
          font-size: 16px;
          font-family: var(--font-display);
        }
        .nsr-w span {
          font-size: 11px;
          color: var(--text-faint);
        }
        .nsr-rules {
          margin: 0 0 10px;
          padding-left: 18px;
        }
        .nsr-rules li {
          font-size: 12.5px;
          color: var(--text-muted);
          line-height: 1.55;
          margin-bottom: 5px;
        }
        .nsr-sources {
          display: flex;
          flex-direction: column;
          gap: 3px;
          font-size: 11.5px;
          color: var(--text-faint);
        }
        .nsr-sources b {
          text-transform: capitalize;
          color: var(--text-muted);
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
        .nsr-chips,
        .nsr-groups {
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
          margin-right: 8px;
          cursor: pointer;
        }
        .nsr-tvbar {
          margin-bottom: 12px;
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
        .nsr-table th {
          position: sticky;
          top: 0;
          z-index: 2;
          font-size: 10.5px;
          text-transform: uppercase;
          letter-spacing: 0.4px;
          color: var(--text-faint);
          font-weight: 600;
          background: var(--canvas-soft);
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

/** One company's full analysis: the overall's arithmetic, every pillar's reason, the
 *  quarter's signals and the statements, all recomputed from the page the row came from. */
function RatingDrawer({ symbol, onClose, onRefreshed }: {
  symbol: string;
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
            </div>
          </div>
          <button ref={closeRef} className="nsd-x" onClick={onClose} aria-label="Close the analysis">×</button>
        </div>

        {!d && !err && <div className="nsd-loading">Loading the stored analysis…</div>}
        {err && <div className="nsd-err" role="alert">{err}</div>}

        {r && (
          <div className="nsd-body">
            <section className="nsd-sec">
              <div className="nsd-ovr">
                <div className="nsd-big" style={{ background: tone(r.ovr_key) }}>
                  {r.overall === null ? "—" : r.overall.toFixed(1)}
                </div>
                <div>
                  <div className="nsd-tier" style={{ color: tone(r.ovr_key) }}>
                    {r.ovr_status === "insufficient" ? "Insufficient Data" : `${r.ovr_tier} overall`}
                  </div>
                  <div className="nsd-formula">
                    {r.ovr_formula ?? "No rating: the filings cannot support one."}
                  </div>
                </div>
              </div>
              {r.ovr_status === "insufficient" ? (
                <ul className="nsd-list">
                  {(r.ovr_reasons ?? []).map((x) => <li key={x}>{x}</li>)}
                </ul>
              ) : (
                <div className="nsd-comps">
                  {(r.ovr_components ?? []).map((c) => (
                    <div key={c.key} className="nsd-comp">
                      <span className="nsd-cl">{c.label}</span>
                      <span className="nsd-cw">{Math.round(c.eff * 100)}% of the overall</span>
                      <span className="nsd-cs">{c.score.toFixed(1)}/10</span>
                      <div className="nsd-cbar"><div style={{ width: `${c.score * 10}%`, background: tone(c.key === "fundamentals" ? r.fund_key : c.key === "quarter" ? r.q_key : r.pnl_key) }} /></div>
                    </div>
                  ))}
                  {(r.ovr_components ?? []).length < 3 && (
                    <p className="nsd-small">
                      A grade with no data is left out and its weight shared over the others; it is never scored as zero.
                    </p>
                  )}
                </div>
              )}
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
                  <div>
                    <b className="up">Strengths</b>
                    <ul>{r.explain.strengths.length ? r.explain.strengths.map((x) => <li key={x}>{x}</li>) : <li className="nsd-none">none above 7.5/10</li>}</ul>
                  </div>
                  <div>
                    <b className="down">Weaknesses</b>
                    <ul>{r.explain.weaknesses.length ? r.explain.weaknesses.map((x) => <li key={x}>{x}</li>) : <li className="nsd-none">none at or below 5/10</li>}</ul>
                  </div>
                  <div>
                    <b className="nsd-riskh">Risks</b>
                    <ul>{r.explain.risks.length ? r.explain.risks.map((x) => <li key={x}>{x}</li>) : <li className="nsd-none">none flagged by the filings</li>}</ul>
                  </div>
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
                      <div key={s.label} className={`nsd-sg ${s.tone}`} title={s.detail}>
                        <span>{s.label}</span>
                        <b>{s.value}</b>
                      </div>
                    ))}
                  </div>
                )}
                <div className="nsd-qnums">
                  <span>Revenue <b>{crore(r.rev)}</b> ({signed(r.rev_yoy)} YoY, {signed(r.rev_qoq)} QoQ)</span>
                  <span>Net profit <b>{crore(r.np)}</b> ({r.np_yoy === null ? "n/m" : signed(r.np_yoy)} YoY, {r.np_qoq === null ? "n/m" : signed(r.np_qoq)} QoQ)</span>
                  {r.np_note && <span className="nsd-small">{r.np_note}</span>}
                </div>
                {periods.length > 0 && lines.length > 0 && (
                  <div className="nsd-tscroll">
                    <table className="nsd-stmt">
                      <thead>
                        <tr>
                          <th className="nsd-sl">₹ Cr</th>
                          {periods.map((p) => <th key={p}>{p}</th>)}
                        </tr>
                      </thead>
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
                  Fundamentals: the seven pillars
                  <span className="nsd-grade" style={{ color: tone(d.rating.grade_key) }}>
                    {d.rating.score === null ? "not rated" : `${d.rating.score.toFixed(1)} · ${d.rating.grade}`}
                  </span>
                </h4>
                {d.rating.pillars.map((p) => (
                  <div key={p.pillar} className="nsd-pillar">
                    <div className="nsd-prow">
                      <span className="nsd-pl">{p.label}</span>
                      <span className="nsd-pw">{Math.round((p.effective_weight ?? p.weight) * 100)}% of the score</span>
                      <span className="nsd-ps">{p.score.toFixed(1)}/10</span>
                    </div>
                    <div className="nsd-cbar"><div style={{ width: `${p.score * 10}%`, background: p.score >= 7 ? "var(--gain)" : p.score >= 5 ? "var(--warn)" : "var(--loss)" }} /></div>
                    <div className="nsd-pr">{p.reason}</div>
                  </div>
                ))}
                {d.rating.skipped.length > 0 && (
                  <p className="nsd-small">
                    <b>Not scored:</b> {d.rating.skipped.map((s) => `${s.label} (${s.why})`).join("; ")}
                  </p>
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
                      <div key={s.label} className={`nsd-sg ${s.tone}`} title={s.detail}>
                        <span>{s.label}</span>
                        <b>{s.value}</b>
                      </div>
                    ))}
                  </div>
                )}
              </section>
            )}

            <section className="nsd-sec">
              <h4>Price returns</h4>
              <table className="nsd-ret">
                <thead>
                  <tr><th>Period</th><th>From</th><th>Close then</th><th>Adjusted for</th><th>Return</th></tr>
                </thead>
                <tbody>
                  {(["r3m", "r6m", "r1y", "r2y"] as const).map((k) => {
                    const det = r.ret_detail?.[k];
                    const v = r[k];
                    return (
                      <tr key={k}>
                        <td>{k.slice(1).toUpperCase()}</td>
                        <td>{day(det?.date)}</td>
                        <td>{det?.close ? `₹${det.close.toLocaleString("en-IN")}` : "—"}</td>
                        <td className="nsd-adj">
                          {det?.reason ? det.reason
                            : [...(det?.adjusted ?? []), ...(det?.unadjusted ?? []).map((u) => `not: ${u}`)].join("; ") || "nothing needed"}
                        </td>
                        <td className={dir(v)}>{signed(v)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <p className="nsd-small">
                Price returns to the {day(r.ret_asof)} close{r.ret_close ? ` of ₹${r.ret_close.toLocaleString("en-IN")}` : ""},
                from NSE&rsquo;s end-of-day bhavcopy. Bonuses, splits and consolidations are adjusted
                for; dividends are not added back.
                {r.screener_1y != null && ` screener.in's own 1-year figure when the page was read: ${signed(r.screener_1y, 0)}.`}
              </p>
              {[...(r.ret_notes ?? []), ...(r.ret_check ? [r.ret_check] : [])].map((n) => (
                <p key={n} className="nsd-small nsd-warnline">{n}</p>
              ))}
            </section>

            <section className="nsd-sec">
              <h4>Source</h4>
              <p className="nsd-small">
                Fundamentals and statements:{" "}
                {r.source_url ? <a href={r.source_url} target="_blank" rel="noreferrer">screener.in</a> : "screener.in"}
                {r.basis ? ` (${r.basis})` : ""}, read {stamp(r.fetched_at)}.
                {r.last_meeting && ` Last results board meeting on NSE: ${day(r.last_meeting)}.`}
                {r.next_meeting && ` Next: ${day(r.next_meeting)}.`}
                {" "}Index and sector: niftyindices.com and NSE. Prices: NSE bhavcopy.
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
          width: min(720px, 100vw);
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
        .nsd-sec h4 {
          margin: 0 0 8px;
          font-size: 13.5px;
          display: flex;
          gap: 10px;
          align-items: baseline;
          flex-wrap: wrap;
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
        .nsd-line {
          margin-top: 0;
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
        .nsd-qnums {
          display: flex;
          flex-direction: column;
          gap: 3px;
          margin-top: 12px;
          font-size: 12.5px;
          color: var(--text-muted);
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
        }
        .nsd-stmt th,
        .nsd-ret th {
          font-size: 10.5px;
          color: var(--text-faint);
          font-weight: 600;
          background: var(--canvas-soft);
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
        .nsd-ret .nsd-adj,
        .nsd-ret th:nth-child(4) {
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
