"use client";

import { useCallback, useEffect, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import PageHeader from "../../components/PageHeader";
import ErrorBanner from "../../components/ErrorBanner";
import {
  ManualInstrument,
  Watchlist,
  WatchlistQuote,
  addWatchlistSymbol,
  createWatchlist,
  deleteWatchlist,
  fetchWatchlistQuotes,
  fetchWatchlists,
  removeWatchlistSymbol,
  searchWatchlistInstruments,
} from "../../lib/api";

type FilterId = "all" | "gainers" | "losers" | "near_high" | "near_low";

const FILTERS: { id: FilterId; label: string }[] = [
  { id: "all", label: "All" },
  { id: "gainers", label: "Gainers" },
  { id: "losers", label: "Losers" },
  { id: "near_high", label: "Near Day High" },
  { id: "near_low", label: "Near Day Low" },
];

const NEAR_THRESHOLD_PCT = 0.5; // within 0.5% of the day's high/low counts as "near"

const inr = (v: number | null | undefined) =>
  v === null || v === undefined ? "-" : v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export default function WatchlistPage() {
  const [watchlists, setWatchlists] = useState<Watchlist[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [quotes, setQuotes] = useState<WatchlistQuote[]>([]);
  const [filter, setFilter] = useState<FilterId>("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [addListOpen, setAddListOpen] = useState(false);
  const [addStockOpen, setAddStockOpen] = useState(false);

  const loadWatchlists = useCallback(async () => {
    try {
      const data = await fetchWatchlists();
      setWatchlists(data.watchlists);
      setActiveId((cur) => cur ?? data.watchlists[0]?.watchlist_id ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load watchlists");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadWatchlists();
  }, [loadWatchlists]);

  const active = watchlists.find((w) => w.watchlist_id === activeId) ?? null;

  const loadQuotes = useCallback(async () => {
    if (!activeId) {
      setQuotes([]);
      return;
    }
    try {
      const data = await fetchWatchlistQuotes(activeId);
      setQuotes(data.quotes);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load quotes");
    }
  }, [activeId]);

  useEffect(() => {
    loadQuotes();
    const timer = setInterval(loadQuotes, 15_000);
    return () => clearInterval(timer);
  }, [loadQuotes]);

  const addList = useCallback(
    async (name: string) => {
      const wl = await createWatchlist(name);
      setWatchlists((prev) => [...prev, wl]);
      setActiveId(wl.watchlist_id);
      setAddListOpen(false);
    },
    [],
  );

  const removeList = useCallback(
    async (wl: Watchlist) => {
      if (!window.confirm(`Delete watchlist "${wl.name}"? This removes all ${wl.symbols.length} symbol(s) in it.`)) return;
      await deleteWatchlist(wl.watchlist_id);
      setWatchlists((prev) => prev.filter((w) => w.watchlist_id !== wl.watchlist_id));
      setActiveId((cur) => (cur === wl.watchlist_id ? null : cur));
    },
    [],
  );

  const addStock = useCallback(
    async (inst: ManualInstrument) => {
      if (!activeId) return;
      const entry = await addWatchlistSymbol(activeId, inst);
      setWatchlists((prev) =>
        prev.map((w) => (w.watchlist_id === activeId ? { ...w, symbols: [...w.symbols, entry] } : w)),
      );
      setAddStockOpen(false);
      loadQuotes();
    },
    [activeId, loadQuotes],
  );

  const removeStock = useCallback(
    async (symbol: string) => {
      if (!activeId) return;
      await removeWatchlistSymbol(activeId, symbol);
      setWatchlists((prev) =>
        prev.map((w) => (w.watchlist_id === activeId ? { ...w, symbols: w.symbols.filter((s) => s.symbol !== symbol) } : w)),
      );
      setQuotes((prev) => prev.filter((q) => q.symbol !== symbol));
    },
    [activeId],
  );

  const filteredQuotes = quotes.filter((q) => {
    if (filter === "gainers") return (q.pct_change ?? 0) > 0;
    if (filter === "losers") return (q.pct_change ?? 0) < 0;
    if (filter === "near_high") {
      if (q.high == null || q.ltp == null || q.high === 0) return false;
      return ((q.high - q.ltp) / q.high) * 100 <= NEAR_THRESHOLD_PCT;
    }
    if (filter === "near_low") {
      if (q.low == null || q.ltp == null || q.low === 0) return false;
      return ((q.ltp - q.low) / q.low) * 100 <= NEAR_THRESHOLD_PCT;
    }
    return true;
  });

  return (
    <div className="page">
      <PageHeader
        crumb="Watchlist"
        title="Watchlist"
        subtitle="Create named watchlists and track live prices for the symbols in each — real Dhan quotes."
        actions={
          <button className="add-cta" onClick={() => setAddListOpen(true)}>
            + Add Watchlist
          </button>
        }
      />

      {error && <ErrorBanner message={error} />}

      {loading ? (
        <GlassPanel title="Watchlists">
          <div className="empty">Loading…</div>
        </GlassPanel>
      ) : watchlists.length === 0 ? (
        <GlassPanel title="Watchlists">
          <div className="empty">
            No watchlists yet — hit <b>+ Add Watchlist</b> to create your first one.
          </div>
        </GlassPanel>
      ) : (
        <>
          <div className="tabs-row">
            <div className="tabs">
              {watchlists.map((w) => (
                <button
                  key={w.watchlist_id}
                  className={w.watchlist_id === activeId ? "tab active" : "tab"}
                  onClick={() => setActiveId(w.watchlist_id)}
                >
                  {w.name}
                  <span className="count">{w.symbols.length}</span>
                </button>
              ))}
            </div>
            {active && (
              <button className="delete-list-btn" onClick={() => removeList(active)}>
                Delete "{active.name}"
              </button>
            )}
          </div>

          {active && (
            <>
              <div className="filter-row">
                <div className="filters">
                  {FILTERS.map((f) => (
                    <button
                      key={f.id}
                      className={filter === f.id ? "filter-chip active" : "filter-chip"}
                      onClick={() => setFilter(f.id)}
                    >
                      {f.label}
                    </button>
                  ))}
                </div>
                <button className="add-stock-btn" onClick={() => setAddStockOpen(true)}>
                  + Add Stock
                </button>
              </div>

              <GlassPanel title={active.name} note={`${filteredQuotes.length} of ${active.symbols.length} symbol(s)`}>
                {active.symbols.length === 0 ? (
                  <div className="empty">
                    No stocks in this watchlist yet — hit <b>+ Add Stock</b> to search and add one.
                  </div>
                ) : filteredQuotes.length === 0 ? (
                  <div className="empty">No symbols match this filter right now.</div>
                ) : (
                  <div className="table-scroll">
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th style={{ textAlign: "left" }}>Symbol</th>
                          <th>LTP</th>
                          <th>Change</th>
                          <th>% Change</th>
                          <th>Open</th>
                          <th>High</th>
                          <th>Low</th>
                          <th>Prev Close</th>
                          <th></th>
                        </tr>
                      </thead>
                      <tbody>
                        {filteredQuotes.map((q) => (
                          <tr key={q.symbol}>
                            <td style={{ textAlign: "left" }}>
                              <div className="name-cell">
                                <span className="name">{q.symbol}</span>
                                <span className="chip">{q.exchange_segment === "BSE_EQ" ? "BSE" : "NSE"}</span>
                              </div>
                            </td>
                            <td className="num">{inr(q.ltp)}</td>
                            <td className={`num ${(q.change ?? 0) >= 0 ? "gain" : "loss"}`}>
                              {q.change === null ? "-" : `${q.change >= 0 ? "+" : ""}${inr(q.change)}`}
                            </td>
                            <td className={`num ${(q.pct_change ?? 0) >= 0 ? "gain" : "loss"}`}>
                              {q.pct_change === null ? "-" : `${q.pct_change >= 0 ? "+" : ""}${q.pct_change.toFixed(2)}%`}
                            </td>
                            <td className="num">{inr(q.open)}</td>
                            <td className="num">{inr(q.high)}</td>
                            <td className="num">{inr(q.low)}</td>
                            <td className="num">{inr(q.prev_close)}</td>
                            <td>
                              <button className="remove-btn" onClick={() => removeStock(q.symbol)}>
                                Remove
                              </button>
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
        </>
      )}

      {addListOpen && <AddWatchlistModal onClose={() => setAddListOpen(false)} onCreate={addList} />}
      {addStockOpen && active && <AddStockModal onClose={() => setAddStockOpen(false)} onAdd={addStock} existing={active.symbols.map((s) => s.symbol)} />}

      <style jsx>{`
        .page { display: flex; flex-direction: column; gap: 18px; }
        .add-cta { background: linear-gradient(145deg, var(--accent), var(--accent-hover)); color: #241404; font-weight: 700; font-size: 13px; border: none; border-radius: 10px; padding: 10px 20px; cursor: pointer; }
        .empty { padding: 28px 20px; font-size: 13px; color: var(--text-muted); }
        .tabs-row { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
        .tabs { display: flex; gap: 8px; flex-wrap: wrap; }
        .tab {
          display: flex; align-items: center; gap: 7px;
          background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted);
          padding: 9px 16px; border-radius: 9px; font-size: 12.5px; font-weight: 600; cursor: pointer;
        }
        .tab.active { background: var(--purple-dim); border-color: rgba(125, 52, 220, 0.3); color: var(--purple); }
        .count { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 20px; padding: 1px 8px; font-size: 10.5px; }
        .tab.active .count { background: var(--purple); color: #fff; border-color: transparent; }
        .delete-list-btn { background: var(--loss-dim); color: var(--loss); border: 1px solid rgba(217, 45, 63, 0.26); border-radius: 8px; padding: 7px 12px; font-size: 11.5px; font-weight: 600; cursor: pointer; }
        .filter-row { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
        .filters { display: flex; gap: 6px; flex-wrap: wrap; }
        .filter-chip { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); border-radius: 20px; padding: 6px 13px; font-size: 11.5px; font-weight: 600; cursor: pointer; }
        .filter-chip.active { background: var(--accent-dim); border-color: var(--accent); color: var(--accent); }
        .add-stock-btn { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text); font-weight: 700; font-size: 12.5px; border-radius: 9px; padding: 8px 16px; cursor: pointer; }
        .table-scroll { overflow-x: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums; }
        .data-table th { text-align: center; padding: 9px 12px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); background: var(--panel); position: sticky; top: 0; }
        .data-table td { padding: 12px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .name-cell { display: flex; align-items: center; gap: 6px; }
        .name { font-weight: 700; font-size: 13px; }
        .chip { background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 6px; padding: 2px 7px; font-size: 10px; font-weight: 700; color: var(--text-muted); }
        .num { font-variant-numeric: tabular-nums; }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
        .remove-btn { background: var(--loss-dim); color: var(--loss); border: 1px solid rgba(217, 45, 63, 0.26); border-radius: 8px; padding: 6px 12px; font-size: 11px; font-weight: 700; cursor: pointer; }
      `}</style>
    </div>
  );
}

function AddWatchlistModal({ onClose, onCreate }: { onClose: () => void; onCreate: (name: string) => Promise<void> }) {
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = useCallback(async () => {
    const trimmed = name.trim();
    if (!trimmed) {
      setErr("Enter a name for the watchlist");
      return;
    }
    setSubmitting(true);
    setErr(null);
    try {
      await onCreate(trimmed);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to create watchlist");
    } finally {
      setSubmitting(false);
    }
  }, [name, onCreate]);

  return (
    <div className="modal-scrim" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div className="modal-title">New watchlist</div>
          <button className="modal-close" onClick={onClose}>
            &times;
          </button>
        </div>
        <div className="field">
          <label>Name</label>
          <input
            placeholder="e.g. Nifty Bank stocks"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            autoFocus
          />
        </div>
        {err && <div className="err">{err}</div>}
        <button className="submit-btn" onClick={submit} disabled={submitting}>
          {submitting ? "Creating…" : "Create watchlist"}
        </button>
      </div>
      <style jsx>{`
        .modal-scrim { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.5); display: flex; align-items: flex-start; justify-content: center; z-index: 50; padding: 5vh 16px 16px; overflow-y: auto; }
        .modal { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 16px; padding: 20px; width: 100%; max-width: 400px; display: flex; flex-direction: column; gap: 14px; }
        .modal-head { display: flex; justify-content: space-between; align-items: center; }
        .modal-title { font-family: var(--font-display); font-weight: 800; font-size: 17px; }
        .modal-close { background: none; border: none; font-size: 26px; line-height: 1; color: var(--text-muted); cursor: pointer; padding: 0 4px; }
        .field { display: flex; flex-direction: column; gap: 6px; }
        .field label { font-size: 11px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.03em; }
        .field input { background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 9px; padding: 11px 12px; font-size: 16px; width: 100%; }
        .err { color: var(--loss); font-size: 12px; }
        .submit-btn { background: linear-gradient(145deg, var(--accent), var(--accent-hover)); color: #241404; font-weight: 700; font-size: 13.5px; border: none; border-radius: 10px; padding: 12px; cursor: pointer; }
        .submit-btn:disabled { opacity: 0.55; cursor: default; }
      `}</style>
    </div>
  );
}

function AddStockModal({
  onClose,
  onAdd,
  existing,
}: {
  onClose: () => void;
  onAdd: (inst: ManualInstrument) => Promise<void>;
  existing: string[];
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<ManualInstrument[]>([]);
  const [searching, setSearching] = useState(false);
  const [adding, setAdding] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const q = query.trim();
    if (q.length < 1) {
      setResults([]);
      setSearching(false);
      return;
    }
    setSearching(true);
    const t = setTimeout(async () => {
      try {
        setResults(await searchWatchlistInstruments(q));
      } catch {
        setResults([]);
      } finally {
        setSearching(false);
      }
    }, 250);
    return () => clearTimeout(t);
  }, [query]);

  const add = useCallback(
    async (inst: ManualInstrument) => {
      setAdding(inst.symbol);
      setErr(null);
      try {
        await onAdd(inst);
      } catch (e) {
        setErr(e instanceof Error ? e.message : "Failed to add symbol");
      } finally {
        setAdding(null);
      }
    },
    [onAdd],
  );

  return (
    <div className="modal-scrim" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div className="modal-title">Add stock</div>
          <button className="modal-close" onClick={onClose}>
            &times;
          </button>
        </div>
        <div className="field">
          <label>Search NSE / BSE</label>
          <input
            placeholder="Search stock name or symbol"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            autoFocus
          />
        </div>
        {err && <div className="err">{err}</div>}
        <div className="dropdown">
          {query.trim().length >= 1 && results.length === 0 && (
            <div className="dropdown-empty">{searching ? "Searching…" : "No matching stocks"}</div>
          )}
          {results.map((r) => {
            const already = existing.includes(r.symbol);
            return (
              <button
                key={`${r.exchange_segment}-${r.security_id}`}
                type="button"
                className="dropdown-item"
                disabled={already || adding === r.symbol}
                onClick={() => add(r)}
              >
                <span className="dsym">{r.symbol}</span>
                <span className="dname">{r.name}</span>
                <span className={`dseg ${r.exchange_segment === "BSE_EQ" ? "bse" : "nse"}`}>
                  {r.exchange_segment === "BSE_EQ" ? "BSE" : "NSE"}
                </span>
                {already && <span className="already">Added</span>}
              </button>
            );
          })}
        </div>
      </div>
      <style jsx>{`
        .modal-scrim { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.5); display: flex; align-items: flex-start; justify-content: center; z-index: 50; padding: 5vh 16px 16px; overflow-y: auto; }
        .modal { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 16px; padding: 20px; width: 100%; max-width: 440px; display: flex; flex-direction: column; gap: 14px; }
        .modal-head { display: flex; justify-content: space-between; align-items: center; }
        .modal-title { font-family: var(--font-display); font-weight: 800; font-size: 17px; }
        .modal-close { background: none; border: none; font-size: 26px; line-height: 1; color: var(--text-muted); cursor: pointer; padding: 0 4px; }
        .field { display: flex; flex-direction: column; gap: 6px; }
        .field label { font-size: 11px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.03em; }
        .field input { background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 9px; padding: 11px 12px; font-size: 16px; width: 100%; }
        .err { color: var(--loss); font-size: 12px; }
        .dropdown { background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 10px; max-height: 320px; overflow-y: auto; -webkit-overflow-scrolling: touch; }
        .dropdown-item { display: flex; align-items: center; gap: 10px; width: 100%; text-align: left; padding: 12px; background: none; border: none; border-bottom: 1px solid var(--panel-border); cursor: pointer; font-size: 13.5px; }
        .dropdown-item:last-child { border-bottom: none; }
        .dropdown-item:hover:not(:disabled), .dropdown-item:active:not(:disabled) { background: var(--panel); }
        .dropdown-item:disabled { opacity: 0.55; cursor: default; }
        .dsym { font-weight: 700; min-width: 74px; flex-shrink: 0; }
        .dname { flex: 1; color: var(--text-muted); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .dseg { font-size: 10px; font-weight: 800; flex-shrink: 0; padding: 2px 6px; border-radius: 5px; letter-spacing: 0.03em; }
        .dseg.nse { color: #1d4f91; background: rgba(29, 79, 145, 0.12); }
        .dseg.bse { color: #b45309; background: rgba(180, 83, 9, 0.12); }
        .already { font-size: 10px; font-weight: 700; color: var(--gain); flex-shrink: 0; }
        .dropdown-empty { padding: 14px 12px; font-size: 13px; color: var(--text-faint); text-align: center; }
      `}</style>
    </div>
  );
}
