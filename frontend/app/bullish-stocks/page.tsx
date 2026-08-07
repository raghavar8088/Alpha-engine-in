"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import PageHeader from "../../components/PageHeader";
import GlassPanel from "../../components/GlassPanel";
import ErrorBanner from "../../components/ErrorBanner";
import { BullishStockRow, BullishStocksScreen, fetchBullishStocks } from "../../lib/api";

const INDICES = [
  { key: "nifty50", label: "Nifty 50" },
  { key: "nifty100", label: "Nifty 100" },
  { key: "nifty250", label: "Nifty 250" },
  { key: "nifty500", label: "Nifty 500" },
];
const REFRESH_MS = 30000;

const inr = (v: number | null | undefined) =>
  v === null || v === undefined ? "-" : v.toLocaleString("en-IN", { maximumFractionDigits: 2 });
const pct = (v: number | null | undefined) =>
  v === null || v === undefined ? "-" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;

// ---- sortable columns (click a header to sort, exactly like Stocks Range) ----------
type SortKey =
  | "symbol" | "fno_enabled" | "belongs_to" | "sector" | "ltp" | "change_1d_pct"
  | "ema9_days" | "pct_from_52w_high" | "pct_from_ath" | "rsi" | "macd" | "vol_x_avg"
  | "ret_3m" | "score" | "revenue_growth" | "earnings_growth" | "profit_margin" | "roe"
  | "debt_to_equity" | "held_institutions" | "fundamental_score"
  | "entry" | "stop_loss" | "target" | "trail_stop";
type SortState = { key: SortKey; dir: "asc" | "desc" } | null;

const COLS: { key: SortKey; label: string; left?: boolean; title?: string }[] = [
  { key: "symbol", label: "Stock", left: true },
  { key: "fno_enabled", label: "F&O", title: "Has listed futures/options — tradable in the F&O segment" },
  { key: "belongs_to", label: "Belongs to" },
  { key: "sector", label: "Sector", left: true },
  { key: "ltp", label: "LTP" },
  { key: "change_1d_pct", label: "1D %" },
  { key: "ema9_days", label: "9EMA d", title: "Consecutive sessions closed above the 9 EMA" },
  { key: "pct_from_ath", label: "vs ATH", title: "Distance from the all-time high (full Angel history)" },
  { key: "pct_from_52w_high", label: "vs 52W H", title: "Distance from the 52-week high" },
  { key: "rsi", label: "RSI" },
  { key: "macd", label: "MACD" },
  { key: "vol_x_avg", label: "Vol ×", title: "Last session volume vs its 20-day average" },
  { key: "ret_3m", label: "3M %" },
  { key: "score", label: "Tech", title: "How many of the 9 technical signals are firing" },
  { key: "revenue_growth", label: "Rev gr", title: "Revenue growth, YoY (Yahoo)" },
  { key: "earnings_growth", label: "PAT gr", title: "Earnings growth, YoY (Yahoo)" },
  { key: "profit_margin", label: "Margin", title: "Net profit margin (Yahoo)" },
  { key: "roe", label: "ROE" },
  { key: "debt_to_equity", label: "D/E", title: "Debt to equity, % (lower is better)" },
  { key: "held_institutions", label: "Inst %", title: "Institutional holding (Yahoo)" },
  { key: "fundamental_score", label: "Fund", title: "How many of the 6 fundamental checks pass" },
  { key: "entry", label: "Entry" },
  { key: "stop_loss", label: "SL −10%" },
  { key: "target", label: "Target +10%" },
  { key: "trail_stop", label: "Trail SL", title: "10% below the 20-day running high — trails up as the stock advances" },
];
const TEXT_KEYS: SortKey[] = ["symbol", "sector"];
const defaultDir = (k: SortKey): "asc" | "desc" => (TEXT_KEYS.includes(k) ? "asc" : "desc");

const BELONGS_RANK: Record<string, number> = { "Nifty 50": 0, "Nifty 100": 1, "Nifty 250": 2, "Nifty 500": 3 };

function sortValue(r: BullishStockRow, key: SortKey): number | string | null {
  switch (key) {
    case "symbol": return r.symbol;
    case "fno_enabled": return r.fno_enabled ? 1 : 0;
    case "belongs_to": return r.belongs_to != null ? BELONGS_RANK[r.belongs_to] ?? null : null;
    case "sector": return r.sector;
    case "macd": return r.macd != null && r.macd_signal != null ? r.macd - r.macd_signal : null;
    default: return (r[key] as number | null) ?? null;
  }
}

function sortRows(rs: BullishStockRow[], sort: SortState): BullishStockRow[] {
  const arr = [...rs];
  if (!sort) return arr; // server order: strongest score first, then closest to the 52W high
  const { key, dir } = sort;
  arr.sort((a, b) => {
    const va = sortValue(a, key);
    const vb = sortValue(b, key);
    if (va == null && vb == null) return 0;
    if (va == null) return 1;   // missing values always sink to the bottom
    if (vb == null) return -1;
    const d = typeof va === "string" ? va.localeCompare(vb as string) : va - (vb as number);
    return dir === "asc" ? d : -d;
  });
  return arr;
}

/** The nine technical signals behind the score, for the row tooltip. */
function signalSummary(r: BullishStockRow): string {
  const s: [string, boolean][] = [
    ["1 month above 9 EMA", r.sig_ema9],
    ["Above 50 & 200 DMA (50>200)", r.sig_ma_stack],
    ["At / near 52-week high", r.sig_near_high],
    ["At / near ALL-TIME high", r.sig_all_time_high],
    ["Higher highs & higher lows", r.sig_structure],
    ["RSI above 50", r.sig_rsi],
    ["MACD positive crossover", r.sig_macd],
    ["Volume breakout", r.sig_volume],
    ["Outperforming index & sector", r.sig_outperform],
  ];
  return s.map(([label, on]) => `${on ? "✓" : "·"} ${label}`).join("\n");
}

/** The six fundamental checks, for the Fund column tooltip. */
function fundamentalSummary(r: BullishStockRow): string {
  if (!r.fundamentals_known) return "No fundamentals available from Yahoo for this symbol";
  const s: [string, boolean | undefined][] = [
    ["Revenue growing ≥5% YoY", r.fund_revenue],
    ["Earnings growing ≥5% YoY", r.fund_earnings],
    ["Net margin ≥5%", r.fund_margin],
    ["Debt/equity ≤150%", r.fund_debt],
    ["ROE ≥12%", r.fund_roe],
    ["Institutional holding ≥5%", r.fund_holding],
  ];
  const lines = s.map(([label, on]) => `${on ? "✓" : "·"} ${label}`);
  if (r.analyst_rec) lines.push(`— analysts: ${r.analyst_rec.replace("_", " ")}`);
  if (r.held_insiders != null) lines.push(`— promoter/insider holding: ${r.held_insiders.toFixed(1)}%`);
  return lines.join("\n");
}

export default function BullishStocksPage() {
  const [index, setIndex] = useState("nifty500");
  const [data, setData] = useState<BullishStocksScreen | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [fnoOnly, setFnoOnly] = useState(false);
  const [sort, setSort] = useState<SortState>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await fetchBullishStocks(index, showAll));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to run the bullish screen");
    } finally {
      setLoading(false);
    }
  }, [index, showAll]);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  const rows = useMemo(() => {
    const f = filter.trim().toLowerCase();
    let rs = data?.rows ?? [];
    if (fnoOnly) rs = rs.filter((r) => r.fno_enabled);
    if (f) {
      rs = rs.filter(
        (r) => r.symbol.toLowerCase().includes(f) || (r.name || "").toLowerCase().includes(f) || (r.sector || "").toLowerCase().includes(f),
      );
    }
    return sortRows(rs, sort);
  }, [data, filter, fnoOnly, sort]);

  const toggleSort = (key: SortKey) =>
    setSort((s) => {
      if (!s || s.key !== key) return { key, dir: defaultDir(key) };
      // second click flips the direction; third click clears back to the server order
      if (s.dir === defaultDir(key)) return { key, dir: defaultDir(key) === "asc" ? "desc" : "asc" };
      return null;
    });

  const fnoCount = rows.filter((r) => r.fno_enabled).length;
  const perfect = rows.filter((r) => r.score === r.max_score).length;
  const atAth = rows.filter((r) => r.sig_all_time_high).length;

  return (
    <div className="page">
      <PageHeader
        crumb="Bullish Stocks"
        title="Bullish Stocks"
        subtitle="Stocks in a sustained uptrend — making higher highs and higher lows, pressed against their all-time high, and holding above the 9 EMA for a month or more, with the 50/200 DMA stack, RSI, MACD, volume and relative strength confirming, and revenue growth, margins, debt, ROE and institutional holding checked underneath. Plan on every row: enter at the live price, 10% stop, 10% first target, and trail the stop 10% below the running high."
      />

      <div className="controls">
        <div className="index-tabs">
          {INDICES.map((ix) => (
            <button
              key={ix.key}
              className={index === ix.key ? "tab active" : "tab"}
              onClick={() => { setFilter(""); setIndex(ix.key); }}
            >
              {ix.label}
            </button>
          ))}
        </div>
        <div className="right-controls">
          <button className={fnoOnly ? "toggle on" : "toggle"} onClick={() => setFnoOnly((v) => !v)}>
            F&amp;O only
          </button>
          <button
            className={showAll ? "toggle on" : "toggle"}
            onClick={() => setShowAll((v) => !v)}
            title="Include stocks that fail one or more of the four core conditions, with their score"
          >
            Show near-misses
          </button>
          <input className="filter" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter by symbol, name or sector…" />
        </div>
      </div>

      {error && <ErrorBanner message={error} />}

      <div className="stat-row">
        <span>{data?.label ?? "—"}: <b className="gain">{rows.length}</b> {showAll ? "screened" : "bullish"}</span>
        <span><b>{fnoCount}</b> F&amp;O enabled</span>
        <span><b>{perfect}</b> with every technical signal</span>
        <span><b className="gain">{atAth}</b> at an all-time high</span>
        {data?.benchmark_ret_3m != null && (
          <span className="muted">benchmark {data.benchmark} 3M {pct(data.benchmark_ret_3m)}</span>
        )}
        {loading && <span className="muted">refreshing…</span>}
      </div>

      {data && (
        <div className="note">
          {data.fundamentals_available ? (
            <>
              <b>Coverage.</b> Fundamentals graded for <b>{data.fundamentals_graded}</b> of {data.screened} screened
              stocks (Yahoo, refreshed daily); all-time highs backfilled for <b>{data.ath_available}</b>. Stocks Yahoo
              has no data for show <b>n/a</b> and are never dropped for it. {data.unscreened_note}
            </>
          ) : (
            <>
              <b>Fundamentals still loading.</b> The daily Yahoo refresh has not completed yet, so only the technical
              screen is scoring right now — rows will show <b>n/a</b> under the fundamental columns until it lands.
              All-time highs backfilled for <b>{data.ath_available}</b> of {data.screened}. {data.unscreened_note}
            </>
          )}
        </div>
      )}

      <GlassPanel title={showAll ? "Screened stocks" : "Bullish stocks"}>
        {!rows.length ? (
          <div className="empty">
            {loading ? "Loading…" : "No stock currently passes every core condition. Try “Show near-misses”, or a wider index."}
          </div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  {COLS.map((c) => {
                    const active = sort?.key === c.key;
                    return (
                      <th
                        key={c.key}
                        className="sortable"
                        style={c.left ? { textAlign: "left" } : undefined}
                        onClick={() => toggleSort(c.key)}
                        title={c.title ?? "Sort"}
                      >
                        <span className="th-inner">
                          {c.label}
                          <span className="arrows">
                            <span className={active && sort?.dir === "asc" ? "on" : ""}>▲</span>
                            <span className={active && sort?.dir === "desc" ? "on" : ""}>▼</span>
                          </span>
                        </span>
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.symbol} className={r.fno_enabled ? "fno" : ""}>
                    <td style={{ textAlign: "left" }}>
                      <div className="stock-cell">
                        <span className={r.fno_enabled ? "sym fno-sym" : "sym"}>{r.symbol}</span>
                        <span className="nm">{r.name}</span>
                      </div>
                    </td>
                    <td>{r.fno_enabled ? <span className="fno-badge">F&amp;O</span> : <span className="muted">—</span>}</td>
                    <td><span className="badge">{r.belongs_to || "—"}</span></td>
                    <td style={{ textAlign: "left" }} className="sector">{r.sector}</td>
                    <td className="ltp">₹{inr(r.ltp)}</td>
                    <td className={(r.change_1d_pct ?? 0) >= 0 ? "gain" : "loss"}>{pct(r.change_1d_pct)}</td>
                    <td className={r.sig_ema9 ? "gain" : "muted"}>{r.ema9_days}</td>
                    <td
                      className={r.pct_from_ath == null ? "muted" : r.sig_all_time_high ? "gain" : ""}
                      title={r.all_time_high != null
                        ? `All-time high ₹${inr(r.all_time_high)}${r.all_time_high_date ? ` on ${r.all_time_high_date}` : ""}`
                        : "All-time high not backfilled yet for this symbol"}
                    >
                      {r.pct_from_ath == null ? "—" : pct(r.pct_from_ath)}
                    </td>
                    <td className={r.sig_near_high ? "gain" : ""}>{pct(r.pct_from_52w_high)}</td>
                    <td className={r.sig_rsi ? "gain" : "loss"}>{r.rsi == null ? "-" : r.rsi.toFixed(1)}</td>
                    <td className={r.sig_macd ? "gain" : "muted"}>{r.macd == null ? "-" : r.macd.toFixed(2)}</td>
                    <td className={r.sig_volume ? "gain" : "muted"}>{r.vol_x_avg == null ? "-" : `${r.vol_x_avg.toFixed(2)}×`}</td>
                    <td className={r.sig_outperform ? "gain" : (r.ret_3m ?? 0) >= 0 ? "" : "loss"}>{pct(r.ret_3m)}</td>
                    <td title={signalSummary(r)}>
                      <span className={r.score === r.max_score ? "score full" : r.qualified ? "score ok" : "score"}>
                        {r.score}/{r.max_score}
                      </span>
                    </td>
                    <td className={r.fund_revenue ? "gain" : r.revenue_growth == null ? "muted" : ""}>{pct(r.revenue_growth)}</td>
                    <td className={r.fund_earnings ? "gain" : r.earnings_growth == null ? "muted" : ""}>{pct(r.earnings_growth)}</td>
                    <td className={r.fund_margin ? "gain" : r.profit_margin == null ? "muted" : ""}>{pct(r.profit_margin)}</td>
                    <td className={r.fund_roe ? "gain" : r.roe == null ? "muted" : ""}>{pct(r.roe)}</td>
                    <td className={r.debt_to_equity == null ? "muted" : r.fund_debt ? "gain" : "loss"}>
                      {r.debt_to_equity == null ? "—" : r.debt_to_equity.toFixed(0)}
                    </td>
                    <td className={r.fund_holding ? "gain" : r.held_institutions == null ? "muted" : ""}>{pct(r.held_institutions)}</td>
                    <td title={fundamentalSummary(r)}>
                      {!r.fundamentals_known ? (
                        <span className="score">n/a</span>
                      ) : (
                        <span className={
                          r.fundamental_score === r.fundamental_max ? "score full"
                            : r.fundamentally_ok ? "score ok" : "score weak"
                        }>
                          {r.fundamental_score}/{r.fundamental_max}
                        </span>
                      )}
                    </td>
                    <td className="plan">₹{inr(r.entry)}</td>
                    <td className="plan loss">₹{inr(r.stop_loss)}</td>
                    <td className="plan gain">₹{inr(r.target)}</td>
                    <td className="plan">₹{inr(r.trail_stop)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>

      <style jsx>{`
        .page { display: flex; flex-direction: column; gap: 16px; }
        .controls { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
        .index-tabs { display: flex; gap: 8px; flex-wrap: wrap; }
        .right-controls { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; flex: 1; justify-content: flex-end; }
        .tab { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); padding: 9px 16px; border-radius: 9px; font-size: 12.5px; font-weight: 600; cursor: pointer; }
        .tab.active { background: var(--purple-dim); border-color: rgba(125, 52, 220, 0.3); color: var(--purple); }
        .toggle { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); padding: 9px 14px; border-radius: 9px; font-size: 12.5px; font-weight: 600; cursor: pointer; }
        .toggle.on { background: var(--gain-dim); border-color: rgba(14, 159, 110, 0.35); color: var(--gain); }
        .filter { background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 9px; padding: 9px 14px; font-size: 13px; min-width: 240px; max-width: 320px; }
        .note { padding: 10px 14px; border-radius: 9px; background: var(--canvas-soft); border: 1px solid var(--panel-border); font-size: 12px; line-height: 1.55; color: var(--text-muted); }
        .stat-row { display: flex; gap: 20px; font-size: 12.5px; color: var(--text-muted); flex-wrap: wrap; }
        .empty { padding: 24px 20px; font-size: 13px; color: var(--text-faint); }
        .table-scroll { overflow-x: auto; max-height: 640px; overflow-y: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; white-space: nowrap; }
        .data-table th { text-align: center; padding: 9px 12px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); position: sticky; top: 0; background: var(--panel); }
        .data-table th.sortable { cursor: pointer; user-select: none; }
        .data-table th.sortable:hover { color: var(--purple); }
        .th-inner { display: inline-flex; align-items: center; gap: 3px; }
        .arrows { display: inline-flex; flex-direction: column; line-height: 6px; font-size: 7px; color: var(--text-faint); }
        .arrows .on { color: var(--purple); }
        .data-table td { padding: 8px 12px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        tr.fno { background: rgba(14, 159, 110, 0.07); }
        .stock-cell { display: flex; flex-direction: column; }
        .sym { font-weight: 700; }
        .sym.fno-sym { color: var(--gain); }
        .nm { font-size: 10.5px; color: var(--text-faint); max-width: 200px; overflow: hidden; text-overflow: ellipsis; }
        .sector { font-size: 11px; color: var(--text-muted); }
        .ltp { font-weight: 700; }
        .badge { display: inline-block; padding: 2px 7px; border-radius: 6px; font-size: 10px; font-weight: 700; background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); }
        .fno-badge { display: inline-block; padding: 2px 7px; border-radius: 6px; font-size: 10px; font-weight: 800; background: var(--gain-dim); color: var(--gain); }
        .score { display: inline-block; padding: 2px 8px; border-radius: 6px; font-size: 10.5px; font-weight: 800; background: var(--canvas-soft); color: var(--text-muted); }
        .score.ok { background: var(--gain-dim); color: var(--gain); }
        .score.full { background: var(--gain); color: #fff; }
        .score.weak { background: var(--loss-dim); color: var(--loss); }
        .plan { font-weight: 600; }
        .muted { color: var(--text-faint); }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
        @media (max-width: 720px) { .filter { max-width: none; } .right-controls { justify-content: flex-start; } }
      `}</style>

      {/* Wide 25-column table — break out of the app's centered 1320px content column
          for this page only, exactly as Stocks Range does. styled-jsx global styles are
          injected on mount and removed on navigate-away, so other pages stay centered. */}
      <style jsx global>{`
        .app-main { max-width: none !important; margin-left: 0 !important; margin-right: 0 !important; }
      `}</style>
    </div>
  );
}
