"use client";

/**
 * ⌘K instrument console — app-wide search, navigation, and natural-language screening.
 *
 * Replaces a bare textarea where you typed tickers blind. Three modes, chosen by what you
 * type rather than by a mode switch:
 *
 *   (nothing)   today's strongest movers, from the screener's own daily snapshot — so an
 *               empty box answers "what should I even name?" instead of sitting there
 *   text        ranked instrument search: exact ticker first, typo-tolerant, enriched
 *   ? sentence  natural language -> a filter that is SHOWN to you -> deterministic results
 *
 * Every result says whether the desk would actually trade it. That is the point: 2,457
 * symbols are searchable but only ~500 clear the liquidity floor, and before this you
 * found out by watching a name produce silence for a week.
 *
 * Keyboard-first per the usual palette conventions: ⌘K/Ctrl-K to open, ↑↓ to move, ⏎ to
 * act, ⇧⏎ for the secondary action, Esc to close — and a visible ⌘K affordance elsewhere
 * in the UI so the shortcut is not folklore.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  SearchResponse,
  SearchResult,
  naturalSearch,
  searchInstruments,
  trendingInstruments,
} from "../lib/api";

const DEBOUNCE_MS = 140;

const PAGES: { label: string; href: string; hint: string }[] = [
  { label: "Trending Stocks", href: "/trending-stocks", hint: "long-only desk on your basket" },
  { label: "Market Data", href: "/dashboard", hint: "live NSE indices" },
  { label: "Momentum Trading", href: "/momentum-trading", hint: "intraday cash momentum" },
  { label: "Stock Screener", href: "/stock-screener", hint: "momentum, sectors, patterns" },
  { label: "Strategy Factory", href: "/strategy-factory", hint: "546 composed strategies" },
  { label: "Live Trading", href: "/live-trading", hint: "real-money desk" },
  { label: "Chart", href: "/chart", hint: "candles and drawings" },
  { label: "Portfolio", href: "/portfolio", hint: "holdings and P&L" },
];

const inr = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
const pct = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
const crore = (v: number | null | undefined) =>
  v === null || v === undefined ? null : `₹${(v / 1e7).toLocaleString("en-IN", { maximumFractionDigits: 0 })}cr`;

export default function CommandPalette({
  onPick,
  pickLabel = "add to basket",
}: {
  /** When present, ⏎ on an instrument calls this instead of navigating. */
  onPick?: (symbol: string, result: SearchResult) => void | Promise<void>;
  pickLabel?: string;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [data, setData] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cursor, setCursor] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const isNatural = q.trim().startsWith("?");
  const naturalQuery = q.trim().replace(/^\?\s*/, "");

  // ---- open / close ----------------------------------------------------------
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      } else if (e.key === "Escape") {
        setOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    const openEvent = () => setOpen(true);
    window.addEventListener("open-command-palette", openEvent);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("open-command-palette", openEvent);
    };
  }, []);

  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 20);
    else {
      setQ("");
      setCursor(0);
      setError(null);
    }
  }, [open]);

  // ---- fetch -----------------------------------------------------------------
  const run = useCallback(async (query: string) => {
    setLoading(true);
    try {
      const trimmed = query.trim();
      let res: SearchResponse;
      if (!trimmed) res = await trendingInstruments(10, "1d");
      else if (trimmed.startsWith("?")) {
        const nq = trimmed.replace(/^\?\s*/, "");
        if (nq.length < 3) {
          setLoading(false);
          return;
        }
        res = await naturalSearch(nq, 20);
      } else res = await searchInstruments(trimmed, { limit: 12 });
      setData(res);
      setCursor(0);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Search failed");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    // Natural-language queries hit a model, so they wait for you to stop typing rather
    // than firing on every keystroke.
    const delay = q.trim().startsWith("?") ? 650 : DEBOUNCE_MS;
    const t = setTimeout(() => run(q), delay);
    return () => clearTimeout(t);
  }, [q, open, run]);

  // ---- rows ------------------------------------------------------------------
  const pageMatches = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s || s.startsWith("?")) return [];
    return PAGES.filter((p) => p.label.toLowerCase().includes(s)).slice(0, 3);
  }, [q]);

  const results = data?.results ?? [];
  const totalRows = results.length + pageMatches.length;

  const act = useCallback(
    async (index: number, secondary = false) => {
      if (index < results.length) {
        const r = results[index];
        if (onPick) {
          setBusy(r.symbol);
          try {
            await onPick(r.symbol, r);
            if (!secondary) setOpen(false);
          } finally {
            setBusy(null);
          }
        } else if (typeof window !== "undefined" && window.location.pathname === "/trending-stocks") {
          // Already on the desk: hand the symbol to the page rather than navigating to
          // the page we are on. One palette instance serves the whole app; the page
          // listens for this instead of mounting a second one that would also grab ⌘K.
          window.dispatchEvent(new CustomEvent("palette-add-symbol", { detail: { symbol: r.symbol } }));
          if (!secondary) setOpen(false);
        } else {
          router.push(`/trending-stocks?add=${encodeURIComponent(r.symbol)}`);
          setOpen(false);
        }
        return;
      }
      const page = pageMatches[index - results.length];
      if (page) {
        router.push(page.href);
        setOpen(false);
      }
    },
    [results, pageMatches, onPick, router],
  );

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setCursor((c) => Math.min(c + 1, Math.max(0, totalRows - 1)));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setCursor((c) => Math.max(0, c - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      act(cursor, e.shiftKey);
    }
  };

  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>(`[data-i="${cursor}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [cursor]);

  if (!open) return null;

  return (
    <div className="cp-scrim" onMouseDown={() => setOpen(false)}>
      <div className="cp" onMouseDown={(e) => e.stopPropagation()}>
        <div className="cp-input">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round">
            <circle cx="11" cy="11" r="7" /><path d="M21 21l-4.3-4.3" />
          </svg>
          <input
            ref={inputRef}
            value={q}
            placeholder="Search a stock, or start with ? to describe what you want…"
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={onKeyDown}
            spellCheck={false}
            autoComplete="off"
          />
          {loading && <span className="cp-spin" />}
          <kbd>Esc</kbd>
        </div>

        {isNatural && data?.mode === "natural-language" && data.filter_english && (
          <div className="cp-filter">
            <b>Filter run:</b> {data.filter_english}
            <div className="cp-dim">
              The model only translated your words — this filter was executed by ordinary
              code over the {data.as_of ?? "latest"} screener snapshot.
            </div>
          </div>
        )}
        {isNatural && data?.nl_available === false && (
          <div className="cp-filter warn">{data.nl_note}</div>
        )}
        {error && <div className="cp-filter warn">{error}</div>}

        <div className="cp-list" ref={listRef}>
          {!q.trim() && (
            <div className="cp-head">
              Trending now{data?.as_of ? ` · ${data.as_of}` : ""}
            </div>
          )}
          {q.trim() && !isNatural && results.length > 0 && <div className="cp-head">Instruments</div>}

          {results.map((r, i) => (
            <Row
              key={r.symbol}
              r={r}
              i={i}
              active={i === cursor}
              busy={busy === r.symbol}
              pickLabel={pickLabel}
              onHover={() => setCursor(i)}
              onClick={() => act(i)}
            />
          ))}

          {pageMatches.length > 0 && <div className="cp-head">Go to</div>}
          {pageMatches.map((p, k) => {
            const i = results.length + k;
            return (
              <div
                key={p.href}
                data-i={i}
                className={`cp-row nav${i === cursor ? " on" : ""}`}
                onMouseEnter={() => setCursor(i)}
                onClick={() => act(i)}
              >
                <div className="cp-sym">{p.label}</div>
                <div className="cp-dim">{p.hint}</div>
              </div>
            );
          })}

          {!loading && totalRows === 0 && (
            <div className="cp-empty">
              {isNatural
                ? "Nothing matched that description."
                : q.trim()
                ? `No instrument matches “${q.trim()}”.`
                : "No screener snapshot yet — run the Stock Screener to populate today's movers."}
            </div>
          )}
        </div>

        <div className="cp-foot">
          <span><kbd>↑</kbd><kbd>↓</kbd> move</span>
          <span><kbd>⏎</kbd> {onPick ? pickLabel : "open"}</span>
          {onPick && <span><kbd>⇧⏎</kbd> {pickLabel}, keep searching</span>}
          <span><kbd>?</kbd> natural language</span>
          <span className="cp-right">{data?.universe ? `${data.universe.toLocaleString("en-IN")} instruments` : ""}</span>
        </div>
      </div>

      <style jsx>{`
        .cp-scrim { position: fixed; inset: 0; z-index: 200; background: rgba(10,12,20,.45);
                    backdrop-filter: blur(3px); display: flex; justify-content: center;
                    align-items: flex-start; padding: 10vh 16px 16px; }
        .cp { width: min(760px, 100%); background: var(--panel); border: 1px solid var(--panel-border);
              border-radius: 16px; box-shadow: 0 24px 70px rgba(0,0,0,.28); overflow: hidden;
              display: flex; flex-direction: column; max-height: 74vh; }
        .cp-input { display: flex; align-items: center; gap: 10px; padding: 14px 16px;
                    border-bottom: 1px solid var(--panel-border); }
        .cp-input svg { width: 17px; height: 17px; color: var(--text-muted); flex: none; }
        .cp-input input { flex: 1; border: 0; outline: 0; background: transparent; font-size: 15px;
                          color: var(--text); font-family: var(--font-ui); }
        .cp-spin { width: 13px; height: 13px; border: 2px solid var(--panel-border);
                   border-top-color: var(--purple); border-radius: 50%; animation: sp .7s linear infinite; }
        @keyframes sp { to { transform: rotate(360deg); } }
        .cp-filter { padding: 10px 16px; font-size: 12px; background: var(--purple-dim);
                     border-bottom: 1px solid var(--panel-border); }
        .cp-filter.warn { background: rgba(180,83,9,.10); }
        .cp-list { overflow-y: auto; padding: 6px 0 8px; }
        .cp-head { font-size: 9.5px; font-weight: 800; letter-spacing: .07em; text-transform: uppercase;
                   color: var(--text-muted); padding: 10px 16px 5px; }
        .cp-row.nav { padding: 9px 16px; cursor: pointer; display: flex; gap: 10px; align-items: baseline; }
        .cp-row.nav.on { background: var(--canvas-soft); }
        .cp-sym { font-weight: 700; font-size: 13px; }
        .cp-dim { color: var(--text-muted); font-size: 11.5px; }
        .cp-empty { padding: 26px 16px; text-align: center; color: var(--text-muted); font-size: 12.5px; }
        .cp-foot { display: flex; gap: 14px; align-items: center; padding: 9px 16px;
                   border-top: 1px solid var(--panel-border); font-size: 10.5px; color: var(--text-muted); }
        .cp-right { margin-left: auto; }
        kbd { font-family: var(--font-data); font-size: 9.5px; border: 1px solid var(--panel-border);
              border-radius: 4px; padding: 1px 5px; margin-right: 3px; background: var(--canvas-soft); }
      `}</style>
    </div>
  );
}

function Row({
  r, i, active, busy, pickLabel, onHover, onClick,
}: {
  r: SearchResult; i: number; active: boolean; busy: boolean; pickLabel: string;
  onHover: () => void; onClick: () => void;
}) {
  const blocked = !r.tradability.ok;
  const ret1d = r.returns?.["1d"];
  const ret1m = r.returns?.["1m"];
  return (
    <div
      data-i={i}
      className={`row${active ? " on" : ""}${blocked ? " blocked" : ""}`}
      onMouseEnter={onHover}
      onClick={onClick}
    >
      <div className="line1">
        <span className="sym">{r.symbol}</span>
        <span className="nm">{r.name}</span>
        {r.index_label && <span className="tag">{r.index_label}</span>}
        {r.sector && <span className="tag soft">{r.sector}</span>}
        {busy && <span className="tag">adding…</span>}
        {active && !busy && <span className="cta">⏎ {pickLabel}</span>}
      </div>

      <div className="line2">
        {r.ltp !== null && <span className="px">{inr(r.ltp)}</span>}
        {ret1d !== null && ret1d !== undefined && (
          <span className={ret1d >= 0 ? "up" : "dn"}>{pct(ret1d)} 1d</span>
        )}
        {ret1m !== null && ret1m !== undefined && (
          <span className={ret1m >= 0 ? "up" : "dn"}>{pct(ret1m)} 1M</span>
        )}
        {r.pct_from_ath !== null && r.pct_from_ath !== undefined && (
          <span className="dim">{Math.abs(r.pct_from_ath).toFixed(1)}% below ATH</span>
        )}
        {crore(r.turnover) && <span className="dim">{crore(r.turnover)} turnover</span>}
        {r.volume_x !== null && r.volume_x !== undefined && r.volume_x >= 1.5 && (
          <span className="hot">{r.volume_x.toFixed(1)}× volume</span>
        )}
        {r.up_streak !== null && r.up_streak !== undefined && r.up_streak >= 3 && (
          <span className="hot">{r.up_streak} up days</span>
        )}
      </div>

      {blocked ? (
        <div className="warn">⚠ {r.tradability.blockers[0]}</div>
      ) : r.tradability.warnings.length > 0 ? (
        <div className="soft-warn">{r.tradability.warnings[0]}</div>
      ) : (
        <div className="ok">✓ tradable · {r.coverage_note}</div>
      )}

      {r.why && r.why.length > 0 && r.matched_on === undefined && (
        <div className="why">{r.why.slice(0, 2).join(" ")}</div>
      )}

      <style jsx>{`
        .row { padding: 9px 16px; cursor: pointer; border-left: 2px solid transparent; }
        .row.on { background: var(--canvas-soft); border-left-color: var(--purple); }
        .row.blocked { opacity: .72; }
        .line1 { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
        .sym { font-family: var(--font-data); font-weight: 700; font-size: 13.5px; }
        .nm { font-size: 12.5px; color: var(--text); }
        .tag { font-size: 9.5px; font-weight: 700; padding: 1px 6px; border-radius: 5px;
               background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); }
        .tag.soft { font-weight: 500; }
        .cta { margin-left: auto; font-size: 10px; color: var(--purple); font-weight: 700; }
        .line2 { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 3px; font-size: 11.5px;
                 font-variant-numeric: tabular-nums; }
        .px { font-family: var(--font-data); font-weight: 600; }
        .up { color: var(--gain); } .dn { color: var(--loss); }
        .dim { color: var(--text-muted); }
        .hot { color: var(--purple); font-weight: 600; }
        .warn { margin-top: 4px; font-size: 11px; color: var(--loss); }
        .soft-warn { margin-top: 4px; font-size: 11px; color: #b45309; }
        .ok { margin-top: 4px; font-size: 11px; color: var(--text-faint); }
        .why { margin-top: 3px; font-size: 11px; color: var(--text-muted); }
      `}</style>
    </div>
  );
}
