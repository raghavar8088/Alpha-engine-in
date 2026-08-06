"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import PageHeader from "../../components/PageHeader";
import GlassPanel from "../../components/GlassPanel";
import ErrorBanner from "../../components/ErrorBanner";
import {
  StockRangeRow,
  StockRangeSetResult,
  StockSearchResult,
  StocksRangeUniverse,
  fetchStocksRangeUniverse,
  getStockRange,
  searchStocksRange,
  setStockRange,
} from "../../lib/api";

const INDICES = [
  { key: "nifty50", label: "Nifty 50" },
  { key: "nifty100", label: "Nifty 100" },
  { key: "nifty250", label: "Nifty 250" },
  { key: "nifty500", label: "Nifty 500" },
];
const REFRESH_MS = 30000;

const inr = (v: number | null | undefined) =>
  v === null || v === undefined ? "-" : v.toLocaleString("en-IN", { maximumFractionDigits: 2 });
const signed = (v: number | null | undefined) =>
  v === null || v === undefined ? "-" : `${v >= 0 ? "+" : ""}${v.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
const pct = (v: number | null | undefined) =>
  v === null || v === undefined ? "-" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;

function Trend({ t }: { t: string | null }) {
  if (!t) return <span className="muted">-</span>;
  const cls = t === "Up" ? "trend up" : t === "Down" ? "trend down" : "trend flat";
  return <span className={cls}>{t}</span>;
}

// ---- sortable columns (click a header to sort, like the leaderboard tables) --------
type SortKey =
  | "symbol" | "belongs_to" | "sector" | "ltp"
  | "change_1d" | "change_1d_pct" | "change_1w" | "change_1w_pct"
  | "stock_trend" | "sector_trend" | "buy_price" | "range_move_pct" | "zone";
type SortState = { key: SortKey; dir: "asc" | "desc" } | null;

const COLS: { key: SortKey; label: string; left?: boolean }[] = [
  { key: "symbol", label: "Stock", left: true },
  { key: "belongs_to", label: "Belongs to" },
  { key: "sector", label: "Sector", left: true },
  { key: "ltp", label: "LTP" },
  { key: "change_1d", label: "1D" },
  { key: "change_1d_pct", label: "1D %" },
  { key: "change_1w", label: "1W" },
  { key: "change_1w_pct", label: "1W %" },
  { key: "stock_trend", label: "Stock trend" },
  { key: "sector_trend", label: "Sector trend" },
  { key: "buy_price", label: "Buy range" },
  { key: "range_move_pct", label: "Range" },
  { key: "zone", label: "Zone" },
];
// numeric/ranked columns default to descending (biggest first); text columns ascending
const NUMERIC_KEYS: SortKey[] = [
  "belongs_to", "ltp", "change_1d", "change_1d_pct", "change_1w", "change_1w_pct",
  "stock_trend", "sector_trend", "buy_price", "range_move_pct", "zone",
];
const defaultDir = (k: SortKey): "asc" | "desc" => (NUMERIC_KEYS.includes(k) ? "desc" : "asc");

const BELONGS_RANK: Record<string, number> = { "Nifty 50": 0, "Nifty 100": 1, "Nifty 250": 2, "Nifty 500": 3 };
const trendRank = (t: string | null): number | null =>
  t === "Up" ? 3 : t === "Sideways" || t === "Flat" ? 2 : t === "Down" ? 1 : null;

function sortValue(r: StockRangeRow, key: SortKey): number | string | null {
  switch (key) {
    case "symbol": return r.symbol;
    case "belongs_to": return r.belongs_to != null ? BELONGS_RANK[r.belongs_to] ?? null : null;
    case "sector": return r.sector;
    case "ltp": return r.ltp;
    case "change_1d": return r.change_1d;
    case "change_1d_pct": return r.change_1d_pct;
    case "change_1w": return r.change_1w;
    case "change_1w_pct": return r.change_1w_pct;
    case "stock_trend": return trendRank(r.stock_trend);
    case "sector_trend": return trendRank(r.sector_trend);
    case "buy_price": return r.buy_price;
    case "range_move_pct": return r.range_move_pct;
    case "zone": return r.buy_price == null ? null : r.in_buy_zone ? 2 : 1;
  }
}

function sortRows(rs: StockRangeRow[], sort: SortState): StockRangeRow[] {
  const arr = [...rs];
  if (!sort) {
    // Default view: stocks you've set a buy range for float to the top; within each
    // group the server order (tightest index, then symbol) is kept (Array.sort is stable).
    arr.sort((a, b) => (b.buy_price != null ? 1 : 0) - (a.buy_price != null ? 1 : 0));
    return arr;
  }
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

export default function StocksRangePage() {
  const [index, setIndex] = useState("nifty50");
  const [data, setData] = useState<StocksRangeUniverse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [dialogFor, setDialogFor] = useState<string | null | undefined>(undefined); // undefined=closed, null=new, string=prefill
  const [sort, setSort] = useState<SortState>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await fetchStocksRangeUniverse(index));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load the stock universe");
    } finally {
      setLoading(false);
    }
  }, [index]);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  const rows = useMemo(() => {
    const f = filter.trim().toLowerCase();
    const rs = data?.rows ?? [];
    const filtered = !f
      ? rs
      : rs.filter(
          (r) => r.symbol.toLowerCase().includes(f) || (r.name || "").toLowerCase().includes(f) || (r.sector || "").toLowerCase().includes(f),
        );
    return sortRows(filtered, sort);
  }, [data, filter, sort]);

  // Global search: the filter box searches the WHOLE Nifty 50/100/250/500 universe, not
  // just the list that happens to be selected. If what you typed isn't in the current
  // list but exists in a broader one (e.g. ABB is a Nifty 100 name while Nifty 50 is
  // showing), jump to the tightest index that contains it so the row appears.
  useEffect(() => {
    const f = filter.trim();
    if (!f || loading) return;
    const lf = f.toLowerCase();
    const hasLocal = (data?.rows ?? []).some(
      (r) => r.symbol.toLowerCase().includes(lf) || (r.name || "").toLowerCase().includes(lf) || (r.sector || "").toLowerCase().includes(lf),
    );
    if (hasLocal) return;
    let cancelled = false;
    const h = setTimeout(() => {
      searchStocksRange(f)
        .then((res) => {
          if (cancelled || !res.length) return;
          const target = res[0].tightest_index;
          if (target && target !== index) setIndex(target);
        })
        .catch(() => {});
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(h);
    };
  }, [filter, data, loading, index]);

  const toggleSort = (key: SortKey) =>
    setSort((s) => {
      if (!s || s.key !== key) return { key, dir: defaultDir(key) };
      // second click flips the direction; third click clears back to the default
      // (buy-range-set stocks first).
      if (s.dir === defaultDir(key)) return { key, dir: defaultDir(key) === "asc" ? "desc" : "asc" };
      return null;
    });

  const inZone = rows.filter((r) => r.in_buy_zone).length;
  const withRange = rows.filter((r) => r.buy_price != null).length;

  const onSaved = (r: StockRangeSetResult) => {
    setDialogFor(undefined);
    setNotice(
      r.previous != null
        ? `${r.symbol} buy range updated to ₹${inr(r.buy_price)} (was ₹${inr(r.previous)}, ${pct(r.pct_diff)})`
        : `${r.symbol} buy range set to ₹${inr(r.buy_price)}`,
    );
    load();
  };

  return (
    <div className="page">
      <PageHeader
        crumb="Stocks Range"
        title="Stocks Range"
        subtitle="A watch-table of the Nifty 50 / 100 / 250 / 500 universe on live Angel One prices — LTP, 1-day and 1-week change, sector and stock trend. Set your own manual buy price per stock; when the live price is within ±10% of it, the stock lights up as a BUY ZONE."
        actions={<button className="add-cta" onClick={() => setDialogFor(null)}>+ Add Range</button>}
      />

      <div className="controls">
        <div className="index-tabs">
          {INDICES.map((ix) => (
            <button
              key={ix.key}
              className={index === ix.key ? "tab active" : "tab"}
              // Clicking a tab is a deliberate "show me this whole list" — clear any
              // leftover search so the full index shows (and the auto-switch, which
              // fires from the effect not a click, doesn't yank you back).
              onClick={() => { setFilter(""); setIndex(ix.key); }}
            >
              {ix.label}
            </button>
          ))}
        </div>
        <input className="filter" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter by symbol, name or sector…" />
      </div>

      {error && <ErrorBanner message={error} />}
      {notice && <div className="notice">{notice}</div>}

      <div className="stat-row">
        <span>{data?.label ?? "—"}: <b>{rows.length}</b> stocks</span>
        <span><b className="gain">{inZone}</b> in buy zone</span>
        <span><b>{withRange}</b> with a buy range set</span>
        {loading && <span className="muted">refreshing…</span>}
      </div>

      <GlassPanel title="Stocks">
        {!rows.length ? (
          <div className="empty">{loading ? "Loading…" : "No stocks match this filter."}</div>
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
                        title="Sort"
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
                  <tr key={r.symbol} className={r.in_buy_zone ? "in-zone" : ""}>
                    <td style={{ textAlign: "left" }}>
                      <div className="stock-cell">
                        <span className="sym">{r.symbol}</span>
                        <span className="nm">{r.name}</span>
                      </div>
                    </td>
                    <td><span className="badge">{r.belongs_to}</span></td>
                    <td style={{ textAlign: "left" }} className="sector">{r.sector}</td>
                    <td className="ltp">₹{inr(r.ltp)}</td>
                    <td className={(r.change_1d ?? 0) >= 0 ? "gain" : "loss"}>{signed(r.change_1d)}</td>
                    <td className={(r.change_1d_pct ?? 0) >= 0 ? "gain" : "loss"}>{pct(r.change_1d_pct)}</td>
                    <td className={(r.change_1w ?? 0) >= 0 ? "gain" : "loss"}>{signed(r.change_1w)}</td>
                    <td className={(r.change_1w_pct ?? 0) >= 0 ? "gain" : "loss"}>{pct(r.change_1w_pct)}</td>
                    <td><Trend t={r.stock_trend} /></td>
                    <td><Trend t={r.sector_trend} /></td>
                    <td>
                      <button className={r.buy_price != null ? "range-btn set" : "range-btn"} onClick={() => setDialogFor(r.symbol)}>
                        {r.buy_price != null ? `₹${inr(r.buy_price)}` : "+ Set"}
                      </button>
                    </td>
                    <td className={r.range_move_pct == null ? "muted" : r.range_move_pct >= 0 ? "gain" : "loss"}>
                      {r.range_move_pct == null ? "—" : pct(r.range_move_pct)}
                    </td>
                    <td>
                      {r.buy_price == null ? (
                        <span className="muted">—</span>
                      ) : r.in_buy_zone ? (
                        <span className="zone-yes">● BUY ZONE</span>
                      ) : (
                        <span className="zone-no">out</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>

      {dialogFor !== undefined && (
        <AddRangeDialog prefill={dialogFor} onClose={() => setDialogFor(undefined)} onSaved={onSaved} />
      )}

      <style jsx>{`
        .page { display: flex; flex-direction: column; gap: 16px; }
        .add-cta { background: linear-gradient(145deg, var(--accent), var(--accent-hover)); color: #241404; font-weight: 700; font-size: 13px; border: none; border-radius: 10px; padding: 10px 18px; cursor: pointer; }
        .controls { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
        .index-tabs { display: flex; gap: 8px; flex-wrap: wrap; }
        .tab { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); padding: 9px 16px; border-radius: 9px; font-size: 12.5px; font-weight: 600; cursor: pointer; }
        .tab.active { background: var(--purple-dim); border-color: rgba(125, 52, 220, 0.3); color: var(--purple); }
        .filter { background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 9px; padding: 9px 14px; font-size: 13px; min-width: 260px; flex: 1; max-width: 360px; }
        .notice { padding: 10px 14px; border-radius: 9px; background: var(--canvas-soft); border: 1px solid var(--panel-border); font-size: 12.5px; }
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
        tr.in-zone { background: rgba(14, 159, 110, 0.07); }
        .stock-cell { display: flex; flex-direction: column; }
        .sym { font-weight: 700; }
        .nm { font-size: 10.5px; color: var(--text-faint); max-width: 200px; overflow: hidden; text-overflow: ellipsis; }
        .sector { font-size: 11px; color: var(--text-muted); }
        .ltp { font-weight: 700; }
        .badge { display: inline-block; padding: 2px 7px; border-radius: 6px; font-size: 10px; font-weight: 700; background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); }
        .trend { display: inline-block; padding: 2px 8px; border-radius: 6px; font-size: 10.5px; font-weight: 700; }
        .trend.up { background: var(--gain-dim); color: var(--gain); }
        .trend.down { background: var(--loss-dim); color: var(--loss); }
        .trend.flat { background: var(--canvas-soft); color: var(--text-muted); }
        .range-btn { background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 7px; padding: 5px 10px; font-size: 11.5px; font-weight: 700; cursor: pointer; color: var(--text-muted); }
        .range-btn.set { color: var(--purple); border-color: rgba(125, 52, 220, 0.3); background: var(--purple-dim); }
        .zone-yes { color: var(--gain); font-weight: 800; font-size: 11px; }
        .zone-no { color: var(--text-faint); font-size: 11px; }
        .muted { color: var(--text-faint); }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
        @media (max-width: 720px) { .filter { max-width: none; } }
      `}</style>

      {/* This is a wide 13-column table. Break out of the app's centered 1320px
          content column (which left a big gutter beside the sidebar and pushed the
          last "Zone" column off-screen) and use the full width — but ONLY while this
          page is mounted. styled-jsx global styles are injected on mount and removed
          on navigate-away, so every other page keeps the centered layout. */}
      <style jsx global>{`
        .app-main { max-width: none !important; margin-left: 0 !important; margin-right: 0 !important; }
      `}</style>
    </div>
  );
}

function AddRangeDialog({
  prefill,
  onClose,
  onSaved,
}: {
  prefill: string | null;
  onClose: () => void;
  onSaved: (r: StockRangeSetResult) => void;
}) {
  const [query, setQuery] = useState(prefill ?? "");
  const [results, setResults] = useState<StockSearchResult[]>([]);
  const [selected, setSelected] = useState<string | null>(prefill);
  const [price, setPrice] = useState("");
  const [existing, setExisting] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!selected) {
      setExisting(null);
      return;
    }
    getStockRange(selected).then((r) => setExisting(r.buy_price)).catch(() => setExisting(null));
  }, [selected]);

  useEffect(() => {
    if (selected) return;
    const q = query.trim();
    if (!q) {
      setResults([]);
      return;
    }
    const h = setTimeout(() => {
      searchStocksRange(q).then(setResults).catch(() => setResults([]));
    }, 250);
    return () => clearTimeout(h);
  }, [query, selected]);

  const newPrice = parseFloat(price) || 0;
  const pctDiff = existing && newPrice ? (newPrice / existing - 1) * 100 : null;

  const submit = async () => {
    if (!selected) {
      setErr("Pick a stock first");
      return;
    }
    if (newPrice <= 0) {
      setErr("Enter a positive buy price");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      onSaved(await setStockRange(selected, newPrice));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to save");
      setBusy(false);
    }
  };

  return (
    <div className="scrim" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="head">
          <div className="title">{prefill ? `Buy range · ${prefill}` : "Add buy range"}</div>
          <button className="x" onClick={onClose}>&times;</button>
        </div>

        {!selected ? (
          <div className="field">
            <label>Search stock (name or symbol)</label>
            <input autoFocus value={query} onChange={(e) => setQuery(e.target.value)} placeholder="e.g. RELIANCE or Reliance" />
            {results.length > 0 && (
              <div className="results">
                {results.map((r) => (
                  <button key={r.symbol} className="result" onClick={() => { setSelected(r.symbol); setQuery(r.symbol); }}>
                    <span className="rsym">{r.symbol}</span>
                    <span className="rname">{r.name}</span>
                    <span className="rbel">{r.belongs_to}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : (
          <>
            <div className="picked">
              <b>{selected}</b>
              {!prefill && <button className="change" onClick={() => { setSelected(null); setQuery(""); setResults([]); setExisting(null); }}>change</button>}
            </div>
            {existing != null && (
              <div className="existing">
                Current buy range: <b>₹{inr(existing)}</b>
                {pctDiff != null && <span className={pctDiff >= 0 ? "gain" : "loss"}> · your new price is {pctDiff >= 0 ? "+" : ""}{pctDiff.toFixed(2)}%</span>}
              </div>
            )}
            <div className="field">
              <label>{existing != null ? "New buy price (₹)" : "Buy price (₹)"}</label>
              <input type="number" min={0} step="0.05" autoFocus value={price} onChange={(e) => setPrice(e.target.value)} placeholder="single price, e.g. 1300" />
            </div>
            {err && <div className="err">{err}</div>}
            <button className="submit" onClick={submit} disabled={busy}>
              {busy ? "Saving…" : existing != null ? "Overwrite buy range" : "Save buy range"}
            </button>
          </>
        )}
      </div>

      <style jsx>{`
        .scrim { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.5); display: flex; align-items: flex-start; justify-content: center; z-index: 50; padding: 8vh 16px 16px; overflow-y: auto; }
        .modal { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 16px; padding: 20px; width: 100%; max-width: 440px; display: flex; flex-direction: column; gap: 14px; }
        .head { display: flex; justify-content: space-between; align-items: center; }
        .title { font-family: var(--font-display); font-weight: 800; font-size: 16px; }
        .x { background: none; border: none; font-size: 26px; line-height: 1; color: var(--text-muted); cursor: pointer; padding: 0 4px; }
        .field { display: flex; flex-direction: column; gap: 6px; }
        .field label { font-size: 11px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.03em; }
        .field input { background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 9px; padding: 11px 12px; font-size: 16px; width: 100%; }
        .results { display: flex; flex-direction: column; gap: 4px; margin-top: 4px; max-height: 260px; overflow-y: auto; }
        .result { display: grid; grid-template-columns: auto 1fr auto; gap: 10px; align-items: center; text-align: left; background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 8px; padding: 8px 10px; cursor: pointer; font-size: 12.5px; }
        .result:hover { border-color: rgba(125, 52, 220, 0.4); }
        .rsym { font-weight: 700; }
        .rname { color: var(--text-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .rbel { font-size: 10px; color: var(--text-faint); }
        .picked { display: flex; align-items: center; gap: 10px; font-size: 15px; }
        .change { background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 7px; padding: 4px 10px; font-size: 11px; cursor: pointer; color: var(--text-muted); }
        .existing { font-size: 12.5px; color: var(--text-muted); background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 8px; padding: 9px 11px; }
        .err { color: var(--loss); font-size: 12px; }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
        .submit { background: linear-gradient(145deg, var(--accent), var(--accent-hover)); color: #241404; font-weight: 700; font-size: 13.5px; border: none; border-radius: 10px; padding: 12px; cursor: pointer; }
        .submit:disabled { opacity: 0.55; cursor: default; }
      `}</style>
    </div>
  );
}
