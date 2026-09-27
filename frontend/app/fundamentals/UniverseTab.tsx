"use client";

/** Scan an index or sector, then shop from the result.
 *
 * The scan is a background job on the server, so this polls its progress rather than
 * waiting on a request — five hundred companies is minutes, not seconds.
 *
 * Everything below the scan box reads what is ALREADY stored, so the filters stay usable
 * while a scan runs and the table fills in underneath it.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import {
  GRADE_COLOR,
  GRADE_ORDER,
  GradeKey,
  ScanScopes,
  ScanStatus,
  UniverseStock,
  cancelUniverseScan,
  fetchScanScopes,
  fetchScanStatus,
  fetchUniverseStocks,
  startUniverseScan,
} from "../../lib/api";

const POLL_MS = 2500;

const crore = (v: number | null) => {
  if (v === null || v === undefined) return "—";
  if (v >= 100000) return `${(v / 100000).toFixed(2)}L Cr`;
  return `${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })} Cr`;
};

export default function UniverseTab() {
  const [scopes, setScopes] = useState<ScanScopes | null>(null);
  const [scanType, setScanType] = useState<"index" | "sector">("index");
  const [scanKey, setScanKey] = useState("nifty50");
  const [status, setStatus] = useState<ScanStatus | null>(null);
  const [stocks, setStocks] = useState<UniverseStock[]>([]);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // filters
  const [fIndex, setFIndex] = useState("");
  const [fSector, setFSector] = useState("");
  const [fGrades, setFGrades] = useState<GradeKey[]>([]);
  const [fMinScore, setFMinScore] = useState(0);
  const [fMinResults, setFMinResults] = useState(0);
  const [fMinPnl, setFMinPnl] = useState(0);
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState("score");

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadStocks = useCallback(async () => {
    try {
      const r = await fetchUniverseStocks({
        index: fIndex || undefined,
        sector: fSector || undefined,
        minScore: fMinScore || undefined,
        minResults: fMinResults || undefined,
        minPnl: fMinPnl || undefined,
        grades: fGrades.length ? fGrades : undefined,
        search: search || undefined,
        sort,
      });
      setStocks(r.stocks);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load stocks.");
    }
  }, [fIndex, fSector, fMinScore, fMinResults, fMinPnl, fGrades, search, sort]);

  useEffect(() => {
    fetchScanScopes().then(setScopes).catch(() => {});
    fetchScanStatus().then(setStatus).catch(() => {});
  }, []);

  useEffect(() => {
    loadStocks();
  }, [loadStocks]);

  // Poll only while a scan is actually running, and reload the table as it fills.
  useEffect(() => {
    const running = status?.running || status?.status === "cancelling";
    if (!running) {
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = null;
      return;
    }
    pollRef.current = setInterval(async () => {
      try {
        const s = await fetchScanStatus();
        setStatus(s);
        if (!s.running) {
          loadStocks();
          fetchScanScopes().then(setScopes).catch(() => {});
        } else if (s.done % 20 < 5) {
          loadStocks();
        }
      } catch {
        /* a dropped poll is not worth surfacing; the next one will land */
      }
    }, POLL_MS);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [status?.running, status?.status, loadStocks]);

  const run = async (force: boolean) => {
    setBusy(true);
    setError(null);
    try {
      const r = await startUniverseScan(scanType, scanKey, force);
      if (!r.started) setError(r.reason || "Could not start the scan.");
      setStatus(await fetchScanStatus());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start the scan.");
    } finally {
      setBusy(false);
    }
  };

  const toggle = (sym: string) => {
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(sym)) next.delete(sym);
      else next.add(sym);
      return next;
    });
    setCopied(false);
  };

  const selected = useMemo(
    () => stocks.filter((s) => picked.has(s.symbol)),
    [stocks, picked],
  );

  /** TradingView takes a comma-separated exchange-prefixed list in its watchlist import. */
  const tvList = useMemo(
    () => (selected.length ? selected : stocks).map((s) => `NSE:${s.symbol}`).join(","),
    [selected, stocks],
  );

  const copyTv = async () => {
    try {
      await navigator.clipboard.writeText(tvList);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    } catch {
      setError("Clipboard blocked by the browser — the list is in the box below, select and copy it.");
    }
  };

  const pct = status && status.total ? Math.round((status.done / status.total) * 100) : 0;
  const scopeList = scanType === "index" ? scopes?.indices : scopes?.sectors;

  return (
    <>
      {error && <div className="warn">{error}</div>}

      <GlassPanel title="Scan an index or sector">
        <div className="scanrow">
          <div className="seg">
            <button
              className={scanType === "index" ? "on" : ""}
              onClick={() => {
                setScanType("index");
                setScanKey("nifty50");
              }}
            >
              Index
            </button>
            <button
              className={scanType === "sector" ? "on" : ""}
              onClick={() => {
                setScanType("sector");
                setScanKey(scopes?.sectors?.[0]?.key ?? "");
              }}
            >
              Sector
            </button>
          </div>

          <select value={scanKey} onChange={(e) => setScanKey(e.target.value)}>
            {(scopeList ?? []).map((s) => (
              <option key={s.key} value={s.key}>
                {s.label} ({s.count})
              </option>
            ))}
          </select>

          <button className="primary" onClick={() => run(false)} disabled={busy || status?.running}>
            {status?.running ? "Scanning…" : "Scan and rate"}
          </button>
          {status?.running ? (
            <button className="ghost" onClick={() => cancelUniverseScan().catch(() => {})}>
              Stop
            </button>
          ) : (
            <button className="ghost" onClick={() => run(true)} disabled={busy}>
              Re-fetch all
            </button>
          )}
          <span className="hint">
            {scopes ? `${scopes.rated_stored} stocks rated and stored` : ""}
          </span>
        </div>

        {status && status.total > 0 && (
          <div className="prog">
            <div className="pbar">
              <div className="pfill" style={{ width: `${pct}%` }} />
            </div>
            <div className="pmeta">
              <b>{status.scope?.label}</b> — {status.done} of {status.total} ({pct}%) ·{" "}
              {status.ok} rated · {status.failed} failed
              {status.current && status.running && <> · now {status.current}</>}
              {status.status === "done" && <> · finished</>}
              {status.status === "cancelled" && <> · stopped</>}
            </div>
            {status.failures?.length > 0 && (
              <details className="fails">
                <summary>{status.failures.length} recent failures</summary>
                <ul>
                  {status.failures.map((f) => (
                    <li key={f.symbol}>
                      <b>{f.symbol}</b> — {f.error}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        )}
        {status?.running && (
          <p className="note">
            One screener.in page per stock, paced so the site is not hammered. Anything rated
            in the last day is reused, so a rescan is quick. You can leave this page — the
            scan runs on the server.
          </p>
        )}
      </GlassPanel>

      <GlassPanel title="Filters">
        <div className="filters">
          <label>
            <span>Index</span>
            <select value={fIndex} onChange={(e) => setFIndex(e.target.value)}>
              <option value="">Any</option>
              {(scopes?.indices ?? []).map((i) => (
                <option key={i.key} value={i.key}>
                  {i.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Sector</span>
            <select value={fSector} onChange={(e) => setFSector(e.target.value)}>
              <option value="">Any</option>
              {(scopes?.sectors ?? []).map((s) => (
                <option key={s.key} value={s.key}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Min company score</span>
            <input
              type="number"
              min={0}
              max={10}
              step={0.5}
              value={fMinScore}
              onChange={(e) => setFMinScore(Number(e.target.value))}
            />
          </label>
          <label>
            <span>Min quarter score</span>
            <input
              type="number"
              min={0}
              max={10}
              step={0.5}
              value={fMinResults}
              onChange={(e) => setFMinResults(Number(e.target.value))}
            />
          </label>
          <label>
            <span>Min P&amp;L score</span>
            <input
              type="number"
              min={0}
              max={10}
              step={0.5}
              value={fMinPnl}
              onChange={(e) => setFMinPnl(Number(e.target.value))}
            />
          </label>
          <label>
            <span>Sort by</span>
            <select value={sort} onChange={(e) => setSort(e.target.value)}>
              <option value="score">Company score</option>
              <option value="results">Quarter score</option>
              <option value="pnl">P&amp;L score</option>
              <option value="market_cap">Market cap</option>
              <option value="roce">ROCE</option>
              <option value="pe">P/E (low first)</option>
              <option value="symbol">Symbol</option>
            </select>
          </label>
          <label className="grow">
            <span>Search</span>
            <input
              placeholder="symbol or name"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
        </div>

        <div className="grades">
          {GRADE_ORDER.map((g) => (
            <button
              key={g}
              className={`gchip ${fGrades.includes(g) ? "on" : ""}`}
              style={
                fGrades.includes(g)
                  ? { background: GRADE_COLOR[g], borderColor: GRADE_COLOR[g], color: "#fff" }
                  : { borderColor: GRADE_COLOR[g], color: GRADE_COLOR[g] }
              }
              onClick={() =>
                setFGrades((prev) =>
                  prev.includes(g) ? prev.filter((x) => x !== g) : [...prev, g],
                )
              }
            >
              {g.replace("-", " ")}
            </button>
          ))}
          {fGrades.length > 0 && (
            <button className="clear" onClick={() => setFGrades([])}>
              clear
            </button>
          )}
        </div>
      </GlassPanel>

      <GlassPanel
        title={`${stocks.length} stocks`}
        note={picked.size ? `${picked.size} picked` : "click a row to pick"}
      >
        <div className="tvbar">
          <button className="primary" onClick={copyTv} disabled={!stocks.length}>
            {copied
              ? "Copied"
              : `Copy ${selected.length || stocks.length} for TradingView`}
          </button>
          <button className="ghost" onClick={() => setPicked(new Set())} disabled={!picked.size}>
            Clear picks
          </button>
          <button
            className="ghost"
            onClick={() => setPicked(new Set(stocks.map((s) => s.symbol)))}
            disabled={!stocks.length}
          >
            Select all
          </button>
          <span className="hint">
            Paste into TradingView → Watchlist → Import. Picks none = copies the whole filtered list.
          </span>
        </div>
        {stocks.length > 0 && (
          <textarea className="tvbox" readOnly rows={2} value={tvList} onFocus={(e) => e.target.select()} />
        )}

        <div className="tablewrap">
          <table>
            <thead>
              <tr>
                <th className="pick" />
                <th className="left">Stock</th>
                <th className="left">Sector</th>
                <th>Company</th>
                <th>Quarter</th>
                <th>P&amp;L</th>
                <th>Price</th>
                <th>M-cap</th>
                <th>P/E</th>
                <th>ROCE</th>
              </tr>
            </thead>
            <tbody>
              {stocks.map((s) => (
                <tr
                  key={s.symbol}
                  className={picked.has(s.symbol) ? "on" : ""}
                  onClick={() => toggle(s.symbol)}
                >
                  <td className="pick">
                    <input type="checkbox" readOnly checked={picked.has(s.symbol)} />
                  </td>
                  <td className="left">
                    <b>{s.symbol}</b>
                    <div className="nm">{s.name}</div>
                  </td>
                  <td className="left sec">{s.nse_sector || s.sector || "—"}</td>
                  <td>
                    <GradePill label={s.grade} gkey={s.grade_key} score={s.score} />
                  </td>
                  <td>
                    <GradePill
                      label={s.results_grade}
                      gkey={s.results_grade_key}
                      score={s.results_score}
                    />
                  </td>
                  <td>
                    <GradePill label={s.pnl_grade} gkey={s.pnl_grade_key} score={s.pnl_score} />
                  </td>
                  <td>{s.price?.toLocaleString("en-IN") ?? "—"}</td>
                  <td>{crore(s.market_cap_cr)}</td>
                  <td>{s.pe?.toFixed(1) ?? "—"}</td>
                  <td>{s.roce !== null && s.roce !== undefined ? `${s.roce.toFixed(1)}%` : "—"}</td>
                </tr>
              ))}
              {!stocks.length && (
                <tr>
                  <td colSpan={10} className="empty">
                    Nothing stored for these filters yet — scan an index above, or loosen the
                    filters.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </GlassPanel>

      <style jsx>{`
        .warn {
          margin-bottom: 12px;
          font-size: 12.5px;
          color: #b8690f;
          background: rgba(224, 122, 44, 0.08);
          border: 1px solid rgba(224, 122, 44, 0.3);
          border-radius: 9px;
          padding: 10px 12px;
        }
        .scanrow {
          display: flex;
          gap: 10px;
          align-items: center;
          flex-wrap: wrap;
        }
        .seg {
          display: inline-flex;
          border: 1px solid var(--panel-border);
          border-radius: 9px;
          overflow: hidden;
        }
        .seg button {
          background: none;
          border: none;
          padding: 8px 14px;
          font-size: 12.5px;
          font-weight: 600;
          cursor: pointer;
          color: var(--text-muted);
        }
        .seg button.on {
          background: var(--purple);
          color: #fff;
        }
        select,
        input {
          border: 1px solid var(--panel-border);
          border-radius: 9px;
          padding: 8px 10px;
          font-size: 12.5px;
          background: var(--canvas-soft);
          color: var(--text);
        }
        .primary {
          background: var(--purple);
          color: #fff;
          border: none;
          border-radius: 9px;
          padding: 9px 16px;
          font-weight: 650;
          font-size: 12.5px;
          cursor: pointer;
        }
        .primary:disabled {
          opacity: 0.55;
          cursor: default;
        }
        .ghost {
          background: var(--canvas-soft);
          border: 1px solid var(--panel-border);
          color: var(--text-muted);
          border-radius: 9px;
          padding: 8px 13px;
          font-size: 12.5px;
          font-weight: 600;
          cursor: pointer;
        }
        .ghost:disabled {
          opacity: 0.5;
          cursor: default;
        }
        .hint {
          font-size: 11.5px;
          color: var(--text-faint);
        }
        .prog {
          margin-top: 14px;
        }
        .pbar {
          height: 7px;
          background: var(--panel-border);
          border-radius: 4px;
          overflow: hidden;
        }
        .pfill {
          height: 100%;
          background: var(--purple);
          transition: width 0.4s ease;
        }
        .pmeta {
          font-size: 12px;
          color: var(--text-muted);
          margin-top: 7px;
        }
        .fails {
          margin-top: 8px;
          font-size: 11.5px;
          color: var(--text-faint);
        }
        .fails ul {
          margin: 6px 0 0;
          padding-left: 18px;
        }
        .fails li {
          margin-bottom: 3px;
        }
        .note {
          font-size: 11.5px;
          color: var(--text-faint);
          margin: 10px 0 0;
          line-height: 1.5;
        }
        .filters {
          display: flex;
          gap: 12px;
          flex-wrap: wrap;
        }
        .filters label {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .filters label.grow {
          flex: 1 1 180px;
        }
        .filters span {
          font-size: 10.5px;
          color: var(--text-faint);
          text-transform: uppercase;
          letter-spacing: 0.4px;
        }
        .filters input[type="number"] {
          width: 110px;
        }
        .grades {
          display: flex;
          gap: 6px;
          flex-wrap: wrap;
          margin-top: 14px;
        }
        .gchip {
          border: 1px solid;
          background: none;
          border-radius: 20px;
          padding: 4px 11px;
          font-size: 11px;
          font-weight: 650;
          cursor: pointer;
          text-transform: capitalize;
        }
        .clear {
          border: none;
          background: none;
          color: var(--text-faint);
          font-size: 11px;
          cursor: pointer;
          text-decoration: underline;
        }
        .tvbar {
          display: flex;
          gap: 10px;
          align-items: center;
          flex-wrap: wrap;
          margin-bottom: 10px;
        }
        .tvbox {
          width: 100%;
          border: 1px solid var(--panel-border);
          border-radius: 9px;
          padding: 9px 11px;
          font-family: var(--font-mono, ui-monospace, monospace);
          font-size: 11.5px;
          background: var(--canvas-soft);
          color: var(--text-muted);
          resize: vertical;
          margin-bottom: 12px;
        }
        .tablewrap {
          overflow-x: auto;
        }
        table {
          width: 100%;
          border-collapse: collapse;
          font-size: 12px;
        }
        th,
        td {
          padding: 8px 10px;
          text-align: right;
          border-bottom: 1px solid var(--panel-border);
          white-space: nowrap;
        }
        th {
          font-size: 10.5px;
          text-transform: uppercase;
          letter-spacing: 0.4px;
          color: var(--text-faint);
          font-weight: 600;
        }
        .left {
          text-align: left;
        }
        .pick {
          width: 30px;
          text-align: center;
        }
        tbody tr {
          cursor: pointer;
        }
        tbody tr:hover td {
          background: var(--purple-dim);
        }
        tbody tr.on td {
          background: var(--purple-dim);
        }
        .nm {
          font-size: 10.5px;
          color: var(--text-faint);
          font-weight: 400;
          max-width: 190px;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .sec {
          font-size: 11px;
          color: var(--text-muted);
          max-width: 150px;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .empty {
          text-align: center;
          color: var(--text-faint);
          padding: 26px 10px;
          font-size: 12.5px;
        }
      `}</style>
    </>
  );
}

function GradePill({
  label,
  gkey,
  score,
}: {
  label: string | null;
  gkey: GradeKey | null;
  score: number | null;
}) {
  if (score === null || score === undefined || !gkey) return <span className="dash">—</span>;
  const color = GRADE_COLOR[gkey] ?? GRADE_COLOR.unrated;
  // The tier word alone; the full "Excellent fundamentals" phrase is the tooltip, because
  // three of those in one row would push every number off the screen.
  const tier = (label || "").replace(/ (fundamentals|quarterly results|profit & loss record)$/, "");
  return (
    <span className="pill" style={{ borderColor: color, color }} title={label || ""}>
      <b>{score.toFixed(1)}</b> {tier}
      <style jsx>{`
        .pill {
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
        .pill b {
          font-size: 12px;
        }
      `}</style>
    </span>
  );
}
