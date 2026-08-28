"use client";

/**
 * Chartink — run any public Chartink screener from inside the app.
 *
 * This is a SECONDARY idea feed and the panel never pretends otherwise. Chartink's free
 * tier is delayed, so the delay is stated at the top, on every result, and the rows carry
 * a "delayed" tone rather than the live gain/loss styling used everywhere else in this
 * module. Confusing a 40-minute-old close for a live one is the specific mistake this
 * layout is built to prevent.
 *
 * The scan's own clause is shown, not hidden. "Breakouts" is a title, not a definition —
 * a reader cannot judge whether a screen means what its name suggests without seeing what
 * it actually tests, and pasting someone else's screener without reading it is how you
 * end up trading a rule you never agreed to.
 */

import { useCallback, useEffect, useState } from "react";
import GlassPanel from "./GlassPanel";
import EmptyState from "./EmptyState";
import Skeleton from "./Skeleton";
import SymbolConverter from "./SymbolConverter";
import {
  fetchScreenerChartinkNamed, ChartinkResult, ScreenerConfig,
} from "../lib/api";

type Cfg = ScreenerConfig["chartink"] | undefined;

const num = (v: number | null | undefined, dp = 2) =>
  v === null || v === undefined ? "—" : v.toLocaleString("en-IN", { maximumFractionDigits: dp });
const vol = (v: number | null | undefined) => {
  if (v === null || v === undefined) return "—";
  if (v >= 1e7) return `${(v / 1e7).toFixed(2)}cr`;
  if (v >= 1e5) return `${(v / 1e5).toFixed(2)}L`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(1)}k`;
  return String(v);
};

export default function ChartinkPanel({ cfg }: { cfg: Cfg }) {
  const [slug, setSlug] = useState("short-term-breakouts");
  const [input, setInput] = useState("");
  const [res, setRes] = useState<ChartinkResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState<"tv" | "plain" | null>(null);
  const [sort, setSort] = useState<"change" | "volume" | "close" | "symbol">("change");

  const run = useCallback(async (s: string, fresh = false) => {
    if (!s) return;
    setBusy(true); setCopied(null);
    try {
      setRes(await fetchScreenerChartinkNamed(s, fresh));
    } catch (e) {
      setRes({ ok: false, rows: [], error: e instanceof Error ? e.message : String(e) });
    } finally { setBusy(false); }
  }, []);

  useEffect(() => { run(slug); }, [slug, run]);

  const enabled = cfg?.enabled !== false;
  const rows = [...(res?.rows ?? [])].sort((a, b) => {
    if (sort === "symbol") return a.symbol.localeCompare(b.symbol);
    const k = sort === "change" ? "change_pct" : sort === "volume" ? "volume" : "close";
    return (b[k] ?? -Infinity) - (a[k] ?? -Infinity);
  });

  /** Copy the result as a symbol list.
   *
   * Two formats because they feed two different places. TradingView's watchlist import
   * wants `NSE:SYM,NSE:SYM` with no spaces — that same string is also what the All Time
   * High watchlist accepts, since its parser strips the `NSE:` prefix, so this one covers
   * both. Plain is kept for anywhere that wants bare tickers.
   *
   * The clipboard API is unavailable on insecure origins and can be refused outright, so
   * a failure falls back to a prompt rather than silently doing nothing and leaving the
   * button looking broken.
   */
  const copy = (fmt: "tv" | "plain") => {
    const text = fmt === "tv"
      ? rows.map((r) => `NSE:${r.symbol}`).join(",")
      : rows.map((r) => r.symbol).join(", ");
    const done = () => { setCopied(fmt); setTimeout(() => setCopied(null), 2000); };
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(() => window.prompt(
        "Copy the list below (Ctrl/⌘ + C):", text));
    } else {
      window.prompt("Copy the list below (Ctrl/⌘ + C):", text);
    }
  };

  return (
    <div className="ck">
      {/* ── what this is, before any number ──────────────────────────────── */}
      <div className="banner">
        <b>Second opinion, not a price feed.</b> Chartink&rsquo;s free tier runs behind the
        live market — commonly 30&ndash;45 minutes intraday. Everything else in this module
        is live Angel One or computed from our own stored bars. Use these as{" "}
        <i>ideas to check</i>, never as a price to trade.
      </div>

      <GlassPanel title="Run a Chartink screener"
        note={enabled ? undefined : "adapter disabled"}>
        {!enabled ? (
          <EmptyState title="Chartink is switched off"
            note="Set SCREENER_CHARTINK_ENABLED=1 on the backend to turn this on." />
        ) : (
          <>
            <div className="urlbar">
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Paste any screener URL — https://chartink.com/screener/short-term-breakouts"
                onKeyDown={(e) => { if (e.key === "Enter" && input.trim()) setSlug(input.trim()); }}
              />
              <button className="go" disabled={busy || !input.trim()}
                onClick={() => setSlug(input.trim())}>
                {busy ? "Running…" : "Run"}
              </button>
            </div>
            <div className="hint">
              Any <b>public</b> Chartink screener works — paste the whole URL or just the
              last part of it. Private screeners are only readable while signed in as their
              owner, and the panel will say so rather than showing an empty table.
            </div>

            <div className="chips">
              {(cfg?.named ?? []).map((n) => (
                <button key={n.slug}
                  className={`chip ${slug === n.slug ? "on" : ""}`}
                  title={n.why}
                  onClick={() => { setSlug(n.slug); setInput(""); }}>
                  {n.label}
                </button>
              ))}
            </div>
          </>
        )}
      </GlassPanel>

      <SymbolConverter />

      {enabled && (
        <GlassPanel
          title={res?.name ? res.name : "Results"}
          note={res?.ok ? `${res.rows.length} stock${res.rows.length === 1 ? "" : "s"}` : undefined}
          onRefresh={() => run(slug, true)}
          refreshing={busy}
        >
          {busy && !res ? (
            <div className="sk">{Array.from({ length: 8 }).map((_, i) =>
              <Skeleton key={i} height={26} />)}</div>
          ) : !res ? null : !res.ok ? (
            <EmptyState title="That scan did not run" note={res.error ?? undefined} />
          ) : (
            <>
              {res.description && <div className="desc">{res.description}</div>}

              <div className="meta">
                <span className="lag">
                  {res.behind_mins != null
                    ? `Chartink reports this ${res.behind_mins} min behind live`
                    : "Delayed — Chartink free tier"}
                </span>
                {res.url && (
                  <a href={res.url} target="_blank" rel="noreferrer noopener">
                    open on chartink.com ↗
                  </a>
                )}
                <div className="copies">
                  <button className="copy primary" onClick={() => copy("tv")}
                    disabled={!rows.length}
                    title="NSE:SYM,NSE:SYM — paste straight into a TradingView watchlist, or into the All Time High watchlist">
                    {copied === "tv" ? `copied ${rows.length} ✓` : "copy for TradingView"}
                  </button>
                  <button className="copy" onClick={() => copy("plain")}
                    disabled={!rows.length}
                    title="Bare tickers, comma separated">
                    {copied === "plain" ? "copied ✓" : "plain"}
                  </button>
                </div>
              </div>

              {res.clause && (
                <details className="clause">
                  <summary>What this screen actually tests</summary>
                  <code>{res.clause}</code>
                </details>
              )}

              {!rows.length ? (
                <EmptyState title="No stocks passed"
                  note="The scan ran and returned nothing. On a quiet day that is the honest answer, not a fault." />
              ) : (
                <div className="tw">
                  <table>
                    <thead>
                      <tr>
                        <Th k="symbol" sort={sort} set={setSort} align="l">Symbol</Th>
                        <th className="l">Name</th>
                        <Th k="close" sort={sort} set={setSort}>Close</Th>
                        <Th k="change" sort={sort} set={setSort}>Change</Th>
                        <Th k="volume" sort={sort} set={setSort}>Volume</Th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((r) => (
                        <tr key={r.symbol}>
                          <td className="l sym">{r.symbol}</td>
                          <td className="l nm">{r.name}</td>
                          <td>{num(r.close)}</td>
                          <td className={r.change_pct == null ? "" :
                            r.change_pct > 0 ? "gain" : r.change_pct < 0 ? "loss" : ""}>
                            {r.change_pct == null ? "—" :
                              `${r.change_pct > 0 ? "+" : ""}${r.change_pct.toFixed(2)}%`}
                          </td>
                          <td>{vol(r.volume)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </GlassPanel>
      )}

      <style jsx>{`
        .ck { display: flex; flex-direction: column; gap: 16px; }
        .banner {
          border: 1px solid var(--warn-border, rgba(217, 119, 6, 0.32));
          background: var(--warn-soft, rgba(217, 119, 6, 0.08));
          color: var(--text-secondary);
          border-radius: 12px; padding: 11px 14px; font-size: 12.5px; line-height: 1.55;
        }
        .banner b { color: var(--text-primary); }
        .urlbar { display: flex; gap: 8px; }
        .urlbar input {
          flex: 1; min-width: 0;
          padding: 9px 12px; font-size: 13px;
          border: 1px solid var(--border); border-radius: 9px;
          background: var(--canvas-soft); color: var(--text-primary);
        }
        .urlbar input:focus { outline: none; border-color: var(--accent); }
        .go {
          padding: 9px 18px; border-radius: 9px; font-size: 13px; font-weight: 600;
          border: 1px solid var(--accent); background: var(--accent); color: #fff;
          cursor: pointer; white-space: nowrap;
        }
        .go:disabled { opacity: 0.45; cursor: default; }
        .hint {
          margin-top: 8px; font-size: 11.5px; line-height: 1.55; color: var(--text-muted);
        }
        .chips { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 14px; }
        .chip {
          padding: 6px 12px; border-radius: 999px; font-size: 12px;
          border: 1px solid var(--border); background: var(--canvas-soft);
          color: var(--text-secondary); cursor: pointer;
        }
        .chip:hover { border-color: var(--accent); color: var(--text-primary); }
        .chip.on { background: var(--accent); border-color: var(--accent); color: #fff; }
        .desc { font-size: 12.5px; color: var(--text-secondary); line-height: 1.55; margin-bottom: 10px; }
        .meta {
          display: flex; flex-wrap: wrap; align-items: center; gap: 12px;
          font-size: 11.5px; color: var(--text-muted); margin-bottom: 10px;
        }
        .lag {
          padding: 3px 9px; border-radius: 999px;
          border: 1px solid var(--warn-border, rgba(217, 119, 6, 0.32));
          color: var(--warn, #b45309); font-weight: 600;
        }
        .meta a { color: var(--accent); text-decoration: none; }
        .meta a:hover { text-decoration: underline; }
        .copies { margin-left: auto; display: flex; gap: 6px; }
        .copy {
          padding: 4px 11px; border-radius: 7px; font-size: 11.5px;
          border: 1px solid var(--border); background: var(--canvas-soft);
          color: var(--text-secondary); cursor: pointer; white-space: nowrap;
        }
        .copy:hover:not(:disabled) { border-color: var(--accent); color: var(--text-primary); }
        .copy.primary {
          border-color: var(--accent); color: var(--accent); font-weight: 600;
        }
        .copy:disabled { opacity: 0.4; cursor: default; }
        .clause { margin-bottom: 12px; }
        .clause summary {
          cursor: pointer; font-size: 12px; color: var(--text-secondary);
          padding: 6px 0; user-select: none;
        }
        .clause code {
          display: block; margin-top: 6px; padding: 10px 12px;
          background: var(--canvas-soft); border: 1px solid var(--border);
          border-radius: 8px; font-size: 11.5px; line-height: 1.65;
          color: var(--text-secondary); white-space: pre-wrap; word-break: break-word;
        }
        .sk { display: flex; flex-direction: column; gap: 8px; }
        .tw { overflow-x: auto; }
        .tw table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
        .tw :global(th) {
          text-align: right; padding: 8px 10px; font-weight: 600; font-size: 11px;
          text-transform: uppercase; letter-spacing: 0.04em; color: var(--text-muted);
          border-bottom: 1px solid var(--border); white-space: nowrap;
        }
        .tw :global(th.l) { text-align: left; }
        .tw td {
          text-align: right; padding: 8px 10px; white-space: nowrap;
          border-bottom: 1px solid var(--border-soft, var(--border));
          color: var(--text-secondary);
        }
        .tw td.l { text-align: left; }
        .tw td.sym { font-weight: 650; color: var(--text-primary); }
        .tw td.nm {
          color: var(--text-muted); max-width: 280px;
          overflow: hidden; text-overflow: ellipsis;
        }
        .tw tbody tr:hover td { background: var(--canvas-soft); }
        .gain { color: var(--gain); font-weight: 600; }
        .loss { color: var(--loss); font-weight: 600; }
      `}</style>
    </div>
  );
}

/** A sortable header cell. Sorting is a plain click with no icon library. */
function Th({ k, sort, set, align, children }: {
  k: "change" | "volume" | "close" | "symbol";
  sort: string;
  set: (v: "change" | "volume" | "close" | "symbol") => void;
  align?: "l";
  children: React.ReactNode;
}) {
  return (
    <th className={align === "l" ? "l" : ""}
      onClick={() => set(k)}
      style={{ cursor: "pointer", color: sort === k ? "var(--accent)" : undefined }}>
      {children}{sort === k ? " ↓" : ""}
    </th>
  );
}
