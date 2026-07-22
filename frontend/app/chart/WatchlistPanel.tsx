"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ChartSymbol,
  Watchlist,
  WatchlistQuote,
  fetchWatchlistQuotes,
  fetchWatchlists,
} from "../../lib/api";

/** Quotes come off the live broker feed, so this polls no faster than the rest of
 * the app and only while it can actually be seen — a background tab or a collapsed
 * panel spends the account's rate limit for nothing. */
const REFRESH_MS = 15_000;

const num = (v: number | null | undefined, digits = 2) =>
  v === null || v === undefined
    ? "—"
    : v.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });

const signed = (v: number | null | undefined, digits = 2) =>
  v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}${num(v, digits)}`;

function toneOf(v: number | null | undefined): string {
  if (v === null || v === undefined || v === 0) return "flat";
  return v > 0 ? "up" : "down";
}

/** A watchlist row carries everything the chart needs to address the contract.
 * `name`/`asset_class`/`tick_size` are placeholders: selectSymbol() immediately
 * resolves the authoritative ChartSymbolInfo from the backend, and `selected` is
 * only ever read for security_id, exchange_segment and symbol. */
function toChartSymbol(q: WatchlistQuote): ChartSymbol {
  return {
    symbol: q.symbol,
    name: q.symbol,
    security_id: q.security_id,
    exchange_segment: q.exchange_segment,
    asset_class: "",
    tick_size: 0,
  };
}

export default function WatchlistPanel({
  activeSecurityId,
  onSelect,
}: {
  activeSecurityId?: string | null;
  onSelect: (s: ChartSymbol) => void;
}) {
  const [lists, setLists] = useState<Watchlist[]>([]);
  const [listId, setListId] = useState<string>("");
  const [quotes, setQuotes] = useState<WatchlistQuote[]>([]);
  const [collapsed, setCollapsed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  // Previous prices drive the brief flash on change, the way a live blotter does.
  const prevRef = useRef<Record<string, number>>({});
  const [flashes, setFlashes] = useState<Record<string, "up" | "down">>({});

  useEffect(() => {
    let alive = true;
    fetchWatchlists()
      .then(({ watchlists }) => {
        if (!alive) return;
        setLists(watchlists);
        setListId((cur) => cur || watchlists[0]?.watchlist_id || "");
        if (!watchlists.length) setLoading(false);
      })
      .catch((e) => {
        if (!alive) return;
        setError(e instanceof Error ? e.message : "Could not load watchlists");
        setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  const refresh = useCallback(async () => {
    if (!listId) return;
    try {
      const { quotes: next } = await fetchWatchlistQuotes(listId);
      setQuotes(next);
      setError(null);
      setUpdatedAt(new Date());

      const flash: Record<string, "up" | "down"> = {};
      for (const q of next) {
        const prev = prevRef.current[q.security_id];
        if (q.ltp !== null && prev !== undefined && q.ltp !== prev) {
          flash[q.security_id] = q.ltp > prev ? "up" : "down";
        }
        if (q.ltp !== null) prevRef.current[q.security_id] = q.ltp;
      }
      if (Object.keys(flash).length) {
        setFlashes(flash);
        setTimeout(() => setFlashes({}), 600);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Quotes unavailable");
    } finally {
      setLoading(false);
    }
  }, [listId]);

  useEffect(() => {
    if (!listId || collapsed) return;
    setLoading(true);
    refresh();
    const tick = () => {
      if (typeof document !== "undefined" && document.hidden) return;
      refresh();
    };
    const timer = setInterval(tick, REFRESH_MS);
    return () => clearInterval(timer);
  }, [listId, collapsed, refresh]);

  const activeList = useMemo(
    () => lists.find((l) => l.watchlist_id === listId) || null,
    [lists, listId],
  );

  if (collapsed) {
    return (
      <aside className="wl collapsed">
        <button className="expand" onClick={() => setCollapsed(false)} title="Show watchlist">
          <span className="vert">Watchlist</span>
        </button>
        <style jsx>{`
          .wl.collapsed { width: 34px; flex: 0 0 34px; border-left: 1px solid var(--panel-border); align-self: stretch; min-height: 520px; }
          .expand { width: 100%; height: 100%; background: none; border: none; cursor: pointer; color: var(--text-muted); padding: 10px 0; }
          .vert { writing-mode: vertical-rl; font-size: 11.5px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; }
          .expand:hover { color: var(--purple); }
        `}</style>
      </aside>
    );
  }

  return (
    <aside className="wl">
      <div className="head">
        {lists.length > 1 ? (
          <select value={listId} onChange={(e) => setListId(e.target.value)} aria-label="Watchlist">
            {lists.map((l) => (
              <option key={l.watchlist_id} value={l.watchlist_id}>{l.name}</option>
            ))}
          </select>
        ) : (
          <div className="title">{activeList?.name || "Watchlist"}</div>
        )}
        <button className="collapse" onClick={() => setCollapsed(true)} title="Hide watchlist">×</button>
      </div>

      <div className="cols">
        <span>Symbol</span>
        <span className="r">Last</span>
        <span className="r">Chg</span>
        <span className="r">Chg%</span>
      </div>

      <div className="rows">
        {loading && !quotes.length ? (
          <div className="msg">Loading…</div>
        ) : !lists.length ? (
          <div className="msg">
            No watchlists yet — create one on the <a href="/watchlist">Watchlist</a> page.
          </div>
        ) : !quotes.length ? (
          <div className="msg">
            This list is empty. Add symbols on the <a href="/watchlist">Watchlist</a> page.
          </div>
        ) : (
          quotes.map((q) => {
            const active = !!activeSecurityId && q.security_id === activeSecurityId;
            return (
              <button
                key={`${q.exchange_segment}-${q.security_id}`}
                className={`row${active ? " active" : ""}${flashes[q.security_id] ? ` flash-${flashes[q.security_id]}` : ""}`}
                onClick={() => onSelect(toChartSymbol(q))}
                title={`Chart ${q.symbol}`}
              >
                <span className="sym">{q.symbol}</span>
                <span className="r last">{num(q.ltp)}</span>
                <span className={`r ${toneOf(q.change)}`}>{signed(q.change)}</span>
                <span className={`r ${toneOf(q.pct_change)}`}>
                  {q.pct_change === null || q.pct_change === undefined ? "—" : `${signed(q.pct_change)}%`}
                </span>
              </button>
            );
          })
        )}
      </div>

      {error ? (
        <div className="foot err">{error}</div>
      ) : updatedAt ? (
        <div className="foot">Updated {updatedAt.toLocaleTimeString("en-IN", { hour12: false })}</div>
      ) : null}

      <style jsx>{`
        .wl {
          width: 268px; flex: 0 0 268px; display: flex; flex-direction: column;
          border-left: 1px solid var(--panel-border); background: var(--canvas-soft);
          /* The row is flex-start aligned, so stretch to the chart's height and let
             the symbol list scroll inside rather than growing the page. */
          align-self: stretch; min-height: 520px; max-height: 720px; overflow: hidden;
        }
        .head { display: flex; align-items: center; gap: 8px; padding: 10px 10px 8px; border-bottom: 1px solid var(--panel-border); }
        .title { font-size: 12.5px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.03em; color: var(--text-muted); flex: 1; }
        select { flex: 1; background: var(--canvas); color: inherit; border: 1px solid var(--panel-border); border-radius: 7px; padding: 5px 7px; font-size: 12px; }
        .collapse { background: none; border: none; color: var(--text-faint); font-size: 17px; line-height: 1; cursor: pointer; padding: 0 2px; }
        .collapse:hover { color: var(--loss); }

        .cols, .row { display: grid; grid-template-columns: 1fr 72px 62px 62px; gap: 6px; align-items: center; }
        .cols { padding: 7px 10px; font-size: 10.5px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.03em; color: var(--text-faint); border-bottom: 1px solid var(--panel-border); }
        .r { text-align: right; }

        .rows { overflow-y: auto; flex: 1; }
        .row {
          width: 100%; padding: 8px 10px; background: none; border: none; border-bottom: 1px solid var(--panel-border);
          cursor: pointer; font-size: 12.5px; color: inherit; font-family: inherit; text-align: left;
          transition: background 120ms ease;
        }
        .row:hover { background: var(--panel-border); }
        .row.active { background: var(--purple-dim); box-shadow: inset 2px 0 0 var(--purple); }
        .sym { font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .last { font-variant-numeric: tabular-nums; font-weight: 700; }
        .up { color: var(--gain); font-variant-numeric: tabular-nums; }
        .down { color: var(--loss); font-variant-numeric: tabular-nums; }
        .flat { color: var(--text-faint); font-variant-numeric: tabular-nums; }
        .row.flash-up { background: var(--gain-dim); }
        .row.flash-down { background: var(--loss-dim); }

        .msg { padding: 16px 12px; font-size: 12px; color: var(--text-faint); line-height: 1.6; }
        .msg a { color: var(--purple); }
        .foot { padding: 7px 10px; font-size: 10.5px; color: var(--text-faint); border-top: 1px solid var(--panel-border); }
        .foot.err { color: var(--loss); }

        @media (max-width: 1100px) {
          .wl { width: 100%; flex: 1 1 auto; border-left: none; border-top: 1px solid var(--panel-border); max-height: 320px; }
        }
      `}</style>
    </aside>
  );
}
