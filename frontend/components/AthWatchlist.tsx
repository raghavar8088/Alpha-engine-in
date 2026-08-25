"use client";

/**
 * Hand-built watchlist for the All Time High desk.
 *
 * Paste → map → curate → submit, in that order, because a pasted list is always partly
 * wrong. Somebody's list will contain a renamed scrip, a BSE-only name or a typo, and the
 * mapping step is what surfaces that BEFORE the list is committed rather than as a silent
 * absence at scan time.
 *
 * Rows that cannot be traded are shown, not filtered away, with the specific reason. "Not
 * found" and "no all-time high yet" look identical in a list that just omits them, and they
 * call for opposite responses: one is a typo to fix, the other fixes itself once the seeder
 * reaches that symbol.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import GlassPanel from "./GlassPanel";
import EmptyState from "./EmptyState";
import {
  mapAthSymbols, fetchAthWatchlist, saveAthWatchlist,
  AthMappedSymbol, AthWatchlist as AthWatchlistDoc,
} from "../lib/api";

type Row = AthMappedSymbol & { selected: boolean };

const STATUS_LABEL: Record<string, string> = {
  ok: "tradable",
  not_found: "not found",
  not_quotable: "no live quote",
  no_high: "no all-time high yet",
  too_new: "too newly listed",
  no_market_cap: "no market cap",
  below_cap: "below the floor",
};
const STATUS_TONE: Record<string, string> = {
  ok: "ok", not_found: "bad", not_quotable: "bad",
  no_high: "warn", too_new: "warn", no_market_cap: "warn", below_cap: "warn",
};

const MODES: { key: string; label: string; hint: string }[] = [
  { key: "auto", label: "Screen only", hint: "Every NSE stock above the market-cap floor. Your list is ignored." },
  { key: "manual", label: "My list only", hint: "Trade only the symbols below. The screen is switched off." },
  { key: "both", label: "Screen + my list", hint: "The screen, plus anything you have added by hand." },
];

const cr = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `₹${v.toLocaleString("en-IN")}cr`;

export default function AthWatchlist({ onSaved }: { onSaved?: () => void }) {
  const [rows, setRows] = useState<Row[]>([]);
  const [paste, setPaste] = useState("");
  const [mode, setMode] = useState("auto");
  const [enforceCap, setEnforceCap] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const applyDoc = useCallback((d: AthWatchlistDoc) => {
    setMode(d.mode ?? "auto");
    setEnforceCap(d.enforce_market_cap ?? true);
    // Everything already saved comes back selected — it IS the committed list.
    setRows((d.rows ?? []).map((r) => ({ ...r, selected: true })));
  }, []);

  useEffect(() => {
    fetchAthWatchlist()
      .then(applyDoc)
      .catch((e) => setError(e.message))
      .finally(() => setLoaded(true));
  }, [applyDoc]);

  const addPasted = async () => {
    if (!paste.trim()) return;
    setBusy(true); setError(null); setSaved(null);
    try {
      const res = await mapAthSymbols(paste);
      setRows((prev) => {
        const have = new Set(prev.map((r) => r.symbol));
        // New rows arrive selected when tradable and unselected when not — the common case
        // is "add these and keep the good ones", and pre-ticking a row that cannot trade
        // would put it in the committed list by default.
        const added = res.rows
          .filter((r) => !have.has(r.symbol))
          .map((r) => ({ ...r, selected: r.tradable }));
        return [...prev, ...added];
      });
      setPaste("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  };

  const toggle = (sym: string) =>
    setRows((rs) => rs.map((r) => (r.symbol === sym ? { ...r, selected: !r.selected } : r)));
  const remove = (sym: string) => setRows((rs) => rs.filter((r) => r.symbol !== sym));

  const selected = useMemo(() => rows.filter((r) => r.selected), [rows]);
  const tradableSelected = useMemo(() => selected.filter((r) => r.tradable).length, [selected]);

  const submit = async () => {
    setBusy(true); setError(null); setSaved(null);
    try {
      const res = await saveAthWatchlist(selected.map((r) => r.symbol), mode, enforceCap);
      applyDoc(res);
      setSaved(
        `Saved ${res.count} symbol${res.count === 1 ? "" : "s"} — ${res.tradable} tradable now.` +
        (mode === "auto" ? " Mode is still Screen only, so the desk will not use this list yet."
                         : ""));
      onSaved?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  };

  return (
    <div className="wl">
      <GlassPanel title="Add stocks by hand">
        <div className="pastebox">
          <textarea
            value={paste}
            onChange={(e) => setPaste(e.target.value)}
            placeholder={"Paste NSE symbols — commas, spaces or one per line.\n\nRELIANCE, TCS, INFY\nNSE:HDFCBANK\nSIEMENS"}
            rows={5}
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key === "Enter") addPasted();
            }}
          />
          <div className="pasteside">
            <button className="map" disabled={busy || !paste.trim()} onClick={addPasted}>
              {busy ? "Mapping…" : "Map symbols"}
            </button>
            <div className="hint">
              TradingView&rsquo;s <code>NSE:</code> prefix, a trailing <code>-EQ</code>,
              quotes and mixed case are all handled. Duplicates collapse.
              <br />⌘/Ctrl + ⏎ to map.
            </div>
          </div>
        </div>
      </GlassPanel>

      <GlassPanel title="Your list"
        note={rows.length ? `${selected.length} selected · ${tradableSelected} tradable` : undefined}>
        {error && <div className="err">{error}</div>}
        {saved && <div className="ok">{saved}</div>}

        {!loaded ? <EmptyState title="Loading…" /> :
         rows.length === 0 ? (
          <EmptyState title="Nothing added yet"
            note="Paste some NSE symbols above and map them. Anything that cannot be traded will say why." />
        ) : (
          <>
            <div className="bulk">
              <button onClick={() => setRows((rs) => rs.map((r) => ({ ...r, selected: r.tradable })))}>
                Select all tradable
              </button>
              <button onClick={() => setRows((rs) => rs.map((r) => ({ ...r, selected: false })))}>
                Deselect all
              </button>
              <button onClick={() => setRows((rs) => rs.filter((r) => r.tradable))}>
                Remove untradable
              </button>
            </div>

            <div className="tw">
              <table>
                <thead><tr>
                  <th className="c"></th><th className="l">Symbol</th><th className="l">Name</th>
                  <th>Market cap</th><th>All-time high</th><th>Status</th>
                  <th className="l">Why</th><th></th>
                </tr></thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.symbol} className={r.selected ? "on" : "off"}>
                      <td className="c">
                        <input type="checkbox" checked={r.selected}
                          onChange={() => toggle(r.symbol)}
                          aria-label={`Include ${r.symbol}`} />
                      </td>
                      <td className="l"><b>{r.symbol}</b></td>
                      <td className="l dim">{r.name}</td>
                      <td className="dim">{cr(r.market_cap_cr)}</td>
                      <td className="dim">
                        {r.all_time_high
                          ? r.all_time_high.toLocaleString("en-IN", { maximumFractionDigits: 2 })
                          : "—"}
                      </td>
                      <td>
                        <span className={`st ${STATUS_TONE[r.status] ?? "warn"}`}>
                          {STATUS_LABEL[r.status] ?? r.status}
                        </span>
                      </td>
                      <td className="l sub wide">{r.note}</td>
                      <td>
                        <button className="rm" onClick={() => remove(r.symbol)}
                          title="Remove from the list">✕</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </GlassPanel>

      <GlassPanel title="How the desk should use this">
        <div className="modes">
          {MODES.map((m) => (
            <button key={m.key} className={mode === m.key ? "md on" : "md"}
              onClick={() => setMode(m.key)}>
              <span className="mlabel">{m.label}</span>
              <span className="mhint">{m.hint}</span>
            </button>
          ))}
        </div>

        <label className="capline">
          <input type="checkbox" checked={enforceCap}
            onChange={(e) => setEnforceCap(e.target.checked)} />
          <span>
            <b>Apply the ₹1,000 crore floor to my hand-picked names too</b>
            <small>
              On by default, because the size floor is part of the rule this desk was asked
              for. Turn it off and your picks trade regardless of size — but then the equity
              curve mixes two different strategies, so it is worth doing deliberately.
            </small>
          </span>
        </label>

        <button className="submit" disabled={busy} onClick={submit}>
          {busy ? "Saving…" : `Submit final list (${selected.length})`}
        </button>
      </GlassPanel>

      <style jsx>{`
        .wl { display: flex; flex-direction: column; gap: 14px; }
        .pastebox { display: grid; grid-template-columns: minmax(0, 1fr) 220px; gap: 12px; }
        @media (max-width: 800px) { .pastebox { grid-template-columns: 1fr; } }
        textarea { width: 100%; padding: 10px 12px; border-radius: 10px; border: 1px solid var(--panel-border); background: var(--panel); color: var(--text); font-size: 13px; font-family: var(--font-data), monospace; resize: vertical; line-height: 1.6; }
        .pasteside { display: flex; flex-direction: column; gap: 8px; }
        .map { padding: 10px; border: 0; border-radius: 9px; background: var(--purple); color: #fff; font-weight: 700; font-size: 13px; cursor: pointer; }
        .map:disabled { opacity: .5; cursor: default; }
        .hint { font-size: 10.5px; color: var(--text-faint); line-height: 1.5; }
        code { background: var(--canvas-soft); padding: 1px 4px; border-radius: 3px; font-size: 10px; }

        .err { font-size: 12px; color: var(--loss); background: var(--loss-dim); border: 1px solid var(--loss); border-radius: 8px; padding: 8px 11px; margin-bottom: 10px; }
        .ok { font-size: 12px; color: var(--gain); background: var(--gain-dim); border: 1px solid var(--gain); border-radius: 8px; padding: 8px 11px; margin-bottom: 10px; }

        .bulk { display: flex; gap: 6px; margin-bottom: 10px; flex-wrap: wrap; }
        .bulk button { border: 1px solid var(--panel-border); background: var(--panel); border-radius: 7px; padding: 5px 11px; font-size: 11.5px; color: var(--text-muted); cursor: pointer; }
        .bulk button:hover { border-color: var(--purple); color: var(--purple); }

        .tw { overflow-x: auto; max-height: 460px; overflow-y: auto; }
        table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
        th, td { padding: 7px 9px; text-align: right; white-space: nowrap; border-bottom: 1px solid var(--panel-border); font-variant-numeric: tabular-nums; }
        th { font-size: 10px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: .04em; position: sticky; top: 0; background: var(--panel); }
        th.l, td.l { text-align: left; }
        th.c, td.c { text-align: center; width: 34px; }
        td.dim { color: var(--text-muted); }
        .sub { font-size: 10.5px; color: var(--text-faint); white-space: normal; }
        td.wide { max-width: 320px; white-space: normal; }
        tr.off td { opacity: .45; }
        .st { font-size: 9.5px; font-weight: 700; padding: 2px 7px; border-radius: 4px; white-space: nowrap; }
        .st.ok { background: var(--gain-dim); color: var(--gain); }
        .st.warn { background: var(--warn-dim); color: var(--warn); }
        .st.bad { background: var(--loss-dim); color: var(--loss); }
        .rm { border: 0; background: transparent; color: var(--text-faint); cursor: pointer; font-size: 12px; }
        .rm:hover { color: var(--loss); }

        .modes { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 8px; }
        .md { display: flex; flex-direction: column; gap: 3px; align-items: flex-start; text-align: left; border: 1px solid var(--panel-border); background: var(--panel); border-radius: 10px; padding: 10px 12px; cursor: pointer; }
        .md.on { border-color: var(--purple); background: var(--purple-dim); }
        .mlabel { font-size: 13px; font-weight: 700; color: var(--text); }
        .mhint { font-size: 10.5px; color: var(--text-muted); line-height: 1.45; }

        .capline { display: flex; gap: 9px; align-items: flex-start; margin: 14px 0; cursor: pointer; }
        .capline b { font-size: 12.5px; display: block; }
        .capline small { font-size: 10.5px; color: var(--text-muted); line-height: 1.5; display: block; margin-top: 3px; }

        .submit { width: 100%; padding: 12px; border: 0; border-radius: 10px; background: var(--purple); color: #fff; font-weight: 700; font-size: 13.5px; cursor: pointer; }
        .submit:disabled { opacity: .5; cursor: default; }
      `}</style>
    </div>
  );
}
