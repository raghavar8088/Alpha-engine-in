"use client";

/**
 * Paste a symbol list in any shape, get it back in TradingView's watchlist format.
 *
 * Converts as you type rather than behind a button, because the whole value of this is
 * seeing that the output is right before you paste it somewhere that will silently drop
 * what it cannot resolve.
 *
 * WHAT IT DELIBERATELY DOES NOT DO: silently remove anything. Indices get flagged, not
 * dropped — NIFTYMETAL and CNXPHARMA are real tickers that TradingView will resolve as
 * indices rather than equities, and whether that is wanted depends on what the list is
 * for. Duplicates are the one exception: a repeated symbol is never meaningful in a
 * watchlist, and the count says how many went.
 */

import { useMemo, useState } from "react";
import GlassPanel from "./GlassPanel";

type Fmt = "tv" | "plain" | "lines";

const FORMATS: { key: Fmt; label: string; hint: string }[] = [
  { key: "tv", label: "TradingView", hint: "NSE:AAA,NSE:BBB — paste into a watchlist" },
  { key: "plain", label: "Plain", hint: "AAA, BBB — bare tickers" },
  { key: "lines", label: "One per line", hint: "for a CSV or a config file" },
];

// Symbols may contain & (M&MFIN), - (NAM-INDIA), digits and underscores. Anything else is
// a separator: commas, tabs, newlines, spaces, quotes, brackets.
const TOKEN = /[A-Za-z0-9&_.-]+/g;

// Cash-series suffixes NSE appends. TradingView wants the base symbol.
const SERIES = /-(EQ|BE|BZ|SM|ST|IV|RR|SZ)$/i;

// Index families. Flagged, never removed — see the module comment.
const INDEXY = /^(NIFTY|CNX|BANKNIFTY|FINNIFTY|MIDCPNIFTY|SENSEX|INDIAVIX)/i;

function parse(raw: string) {
  const seen = new Set<string>();
  const out: string[] = [];
  let dupes = 0;
  let stripped = 0;

  for (const m of raw.match(TOKEN) ?? []) {
    let t = m.toUpperCase();
    // A pasted list often already carries an exchange prefix from wherever it came
    // from. Strip it here so the chosen format decides the prefix, rather than ending
    // up with NSE:NSE:FOO.
    if (t === "NSE" || t === "BSE") continue;
    t = t.replace(/^(NSE|BSE):/, "");
    if (SERIES.test(t)) { t = t.replace(SERIES, ""); stripped++; }
    if (!t || t.length > 25) continue;
    if (seen.has(t)) { dupes++; continue; }
    seen.add(t);
    out.push(t);
  }
  return { symbols: out, dupes, stripped };
}

export default function SymbolConverter({
  title = "Convert a symbol list",
  initial = "",
}: { title?: string; initial?: string }) {
  const [raw, setRaw] = useState(initial);
  const [fmt, setFmt] = useState<Fmt>("tv");
  const [dropIdx, setDropIdx] = useState(false);
  const [copied, setCopied] = useState(false);

  const { symbols, dupes, stripped } = useMemo(() => parse(raw), [raw]);
  const indices = useMemo(() => symbols.filter((s) => INDEXY.test(s)), [symbols]);
  const kept = dropIdx ? symbols.filter((s) => !INDEXY.test(s)) : symbols;

  const output = useMemo(() => {
    if (!kept.length) return "";
    if (fmt === "tv") return kept.map((s) => `NSE:${s}`).join(",");
    if (fmt === "plain") return kept.join(", ");
    return kept.join("\n");
  }, [kept, fmt]);

  const copy = () => {
    if (!output) return;
    const done = () => { setCopied(true); setTimeout(() => setCopied(false), 2000); };
    // The clipboard API is unavailable on insecure origins and can be refused outright,
    // so a failure falls back to a prompt rather than leaving the button looking broken.
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(output).then(done)
        .catch(() => window.prompt("Copy the list below (Ctrl/⌘ + C):", output));
    } else {
      window.prompt("Copy the list below (Ctrl/⌘ + C):", output);
    }
  };

  return (
    <GlassPanel title={title}
      note={symbols.length ? `${kept.length} symbol${kept.length === 1 ? "" : "s"}` : undefined}>
      <div className="sc">
        <textarea
          className="in"
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          rows={5}
          spellCheck={false}
          placeholder={"Paste symbols in any shape — commas, spaces, tabs or one per line.\n\nPRECWIRE, SHAHALLOYS, KALYANIFRG, M&MFIN\nNSE:TITAN\nRELIANCE-EQ"}
        />

        <div className="ctl">
          <div className="fmts">
            {FORMATS.map((f) => (
              <button key={f.key} className={fmt === f.key ? "on" : ""}
                title={f.hint} onClick={() => setFmt(f.key)}>
                {f.label}
              </button>
            ))}
          </div>
          {raw.trim() && (
            <button className="clear" onClick={() => setRaw("")}>clear</button>
          )}
        </div>

        {symbols.length > 0 && (
          <>
            <div className="stats">
              <span><b>{kept.length}</b> out</span>
              {dupes > 0 && <span>{dupes} duplicate{dupes === 1 ? "" : "s"} collapsed</span>}
              {stripped > 0 && <span>{stripped} series suffix{stripped === 1 ? "" : "es"} stripped</span>}
              {indices.length > 0 && (
                <span className="idx">
                  {indices.length} look{indices.length === 1 ? "s" : ""} like an index
                  {" ("}{indices.slice(0, 4).join(", ")}{indices.length > 4 ? "…" : ""}{")"}
                  <button onClick={() => setDropIdx(!dropIdx)}>
                    {dropIdx ? "put back" : "remove"}
                  </button>
                </span>
              )}
            </div>

            <textarea className="out" value={output} readOnly rows={5} spellCheck={false}
              onFocus={(e) => e.currentTarget.select()} />

            <div className="acts">
              <button className="copy" onClick={copy} disabled={!output}>
                {copied ? `copied ${kept.length} ✓` : "Copy"}
              </button>
              <span className="hint">
                {fmt === "tv"
                  ? "Paste into a TradingView watchlist — this also works as the paste input for the All Time High watchlist, whose parser strips the NSE: prefix."
                  : fmt === "plain" ? "Bare tickers, comma separated."
                  : "One per line."}
              </span>
            </div>
          </>
        )}
      </div>

      <style jsx>{`
        .sc { display: flex; flex-direction: column; gap: 10px; }
        textarea {
          width: 100%; padding: 10px 12px; border-radius: 9px; resize: vertical;
          border: 1px solid var(--border); background: var(--canvas-soft);
          color: var(--text-primary); font-size: 12.5px; line-height: 1.6;
          font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        }
        textarea:focus { outline: none; border-color: var(--accent); }
        .out { background: var(--canvas); color: var(--text-secondary); }
        .ctl { display: flex; align-items: center; gap: 8px; }
        .fmts { display: flex; gap: 6px; }
        .fmts button, .clear {
          padding: 5px 13px; border-radius: 999px; font-size: 12px;
          border: 1px solid var(--border); background: var(--canvas-soft);
          color: var(--text-secondary); cursor: pointer;
        }
        .fmts button.on { background: var(--accent); border-color: var(--accent); color: #fff; }
        .clear { margin-left: auto; }
        .stats {
          display: flex; flex-wrap: wrap; gap: 14px; align-items: center;
          font-size: 11.5px; color: var(--text-muted);
        }
        .stats b { color: var(--text-primary); font-size: 12.5px; }
        .idx { color: #b45309; display: inline-flex; align-items: center; gap: 7px; }
        .idx button {
          padding: 2px 9px; border-radius: 6px; font-size: 11px; cursor: pointer;
          border: 1px solid rgba(217, 119, 6, 0.4); background: transparent; color: #b45309;
        }
        .acts { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
        .copy {
          padding: 7px 20px; border-radius: 8px; font-size: 13px; font-weight: 600;
          border: 1px solid var(--accent); background: var(--accent); color: #fff;
          cursor: pointer; white-space: nowrap;
        }
        .copy:disabled { opacity: 0.45; cursor: default; }
        .hint {
          font-size: 11.5px; color: var(--text-muted); line-height: 1.5; flex: 1 1 260px;
        }
      `}</style>
    </GlassPanel>
  );
}
