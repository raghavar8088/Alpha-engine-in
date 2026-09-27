"use client";

import { useCallback, useEffect, useState } from "react";
import PageHeader from "../../components/PageHeader";
import GlassPanel from "../../components/GlassPanel";
import ErrorBanner from "../../components/ErrorBanner";
import UniverseTab from "./UniverseTab";
import {
  GRADE_COLOR,
  GradeKey,
  FundamentalRating,
  RatingBand,
  RatingMethodology,
  RateResponse,
  fetchRatingMethodology,
  fetchRecentRatings,
  rateFundamentals,
} from "../../lib/api";

const BAND_COLOR: Record<RatingBand, string> = {
  strong: "#1a9c5b",
  good: "#4a9c1a",
  mixed: "#c98a10",
  weak: "#e07a2c",
  poor: "#d4443c",
  unknown: "#8a8a99",
};

const inr = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;

const crore = (v: number | null | undefined) => {
  if (v === null || v === undefined) return "—";
  if (v >= 100000) return `₹${(v / 100000).toFixed(2)} L Cr`;
  return `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })} Cr`;
};

export default function FundamentalsPage() {
  const [input, setInput] = useState("");
  const [result, setResult] = useState<RateResponse | null>(null);
  const [recent, setRecent] = useState<FundamentalRating[]>([]);
  const [method, setMethod] = useState<RatingMethodology | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showMethod, setShowMethod] = useState(false);
  const [tab, setTab] = useState<"rate" | "universe">("rate");
  const [copiedSym, setCopiedSym] = useState<string | null>(null);

  const loadSide = useCallback(async () => {
    try {
      const [r, m] = await Promise.all([fetchRecentRatings(40), fetchRatingMethodology()]);
      setRecent(r.ratings);
      setMethod(m);
    } catch {
      /* the side panels are a convenience; a failure here must not block rating */
    }
  }, []);

  useEffect(() => {
    loadSide();
  }, [loadSide]);

  const run = useCallback(
    async (force: boolean) => {
      if (!input.trim()) {
        setError("Paste at least one stock symbol.");
        return;
      }
      setBusy(true);
      setError(null);
      try {
        const res = await rateFundamentals(input, force);
        setResult(res);
        if (res.ratings.length === 1) setExpanded(res.ratings[0].symbol);
        loadSide();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Rating failed.");
      } finally {
        setBusy(false);
      }
    },
    [input, loadSide],
  );

  const ratings = result?.ratings ?? [];

  const copyBrief = useCallback(async (r: FundamentalRating) => {
    const text = r.copy_text || r.brief || "";
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopiedSym(r.symbol);
      setTimeout(() => setCopiedSym((s) => (s === r.symbol ? null : s)), 2500);
    } catch {
      setError("The browser blocked the clipboard — expand the card and copy the text by hand.");
    }
  }, []);

  return (
    <div className="page">
      <PageHeader
        crumb="Fundamental Rating"
        title="Fundamental Rating"
        subtitle={
          <>
            Paste one stock or a whole list. Each name is looked up on screener.in, its
            filings are read, and it is scored out of 10 on return on capital, growth,
            margins, balance sheet, cash conversion, valuation and promoter holding — with
            the reason for every pillar written out. Research aid over public filings, not
            investment advice.
          </>
        }
        actions={
          <button className="ghost" onClick={() => setShowMethod((v) => !v)}>
            {showMethod ? "Hide" : "How it scores"}
          </button>
        }
      />

      <div className="tabs">
        <button className={tab === "rate" ? "on" : ""} onClick={() => setTab("rate")}>
          Rate stocks
        </button>
        <button className={tab === "universe" ? "on" : ""} onClick={() => setTab("universe")}>
          Universe &amp; picker
        </button>
      </div>

      {tab === "universe" && <UniverseTab />}

      {tab === "rate" && (
      <>
      {error && <ErrorBanner message={error} onRetry={() => run(false)} />}

      {showMethod && method && (
        <GlassPanel title="How the score is built" tint="lavender">
          <div className="weights">
            {method.pillars.map((p) => (
              <div key={p.pillar} className="w">
                <b>{Math.round(p.weight * 100)}%</b>
                <span>{p.label}</span>
              </div>
            ))}
          </div>
          <div className="bands">
            {method.bands.map((b) => (
              <div key={b.band} className="bd">
                <span className="dot" style={{ background: BAND_COLOR[b.band] }} />
                <b>
                  {b.from}–{b.to}
                </b>
                <span>{b.verdict}</span>
              </div>
            ))}
          </div>
          <ul className="notes">
            {method.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </GlassPanel>
      )}

      <GlassPanel title="Stocks to rate">
        <textarea
          className="paste"
          rows={3}
          placeholder="RELIANCE, TCS, INFY&#10;or one per line — NSE symbols, commas, spaces or newlines all work"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) run(false);
          }}
        />
        <div className="controls">
          <button className="primary" onClick={() => run(false)} disabled={busy}>
            {busy ? "Reading screener.in…" : "Rate these stocks"}
          </button>
          <button className="ghost" onClick={() => run(true)} disabled={busy}>
            Force refresh
          </button>
          <span className="hint">
            {method
              ? `Up to ${method.max_symbols} at a time · cached ${method.cache_hours}h · ⌘/Ctrl+Enter to run`
              : "⌘/Ctrl+Enter to run"}
          </span>
        </div>
        {busy && (
          <div className="progress">
            Fetching one page per stock, paced so screener.in is not hammered — a long list
            takes a moment the first time, then comes back instantly for a day.
          </div>
        )}
      </GlassPanel>

      {result && (
        <>
          {result.note && <div className="warn">{result.note}</div>}
          {result.failures.length > 0 && (
            <div className="warn">
              Could not rate:{" "}
              {result.failures.map((f) => `${f.symbol} (${f.error})`).join(" · ")}
            </div>
          )}

          <GlassPanel
            title={`Ratings — ${result.rated} of ${result.requested}`}
            note="Best first"
          >
            <div className="cards">
              {ratings.map((r) => (
                <div key={r.symbol} className="card">
                  <button
                    className="card-head"
                    onClick={() => setExpanded(expanded === r.symbol ? null : r.symbol)}
                  >
                    <div
                      className="score"
                      style={{
                        background: GRADE_COLOR[r.grade_key] ?? BAND_COLOR[r.band],
                        boxShadow: `0 4px 14px ${(GRADE_COLOR[r.grade_key] ?? BAND_COLOR[r.band])}44`,
                      }}
                    >
                      {r.score === null ? "—" : r.score.toFixed(1)}
                    </div>
                    <div className="who">
                      <div className="nm">
                        {r.name || r.symbol} <span className="sym">{r.symbol}</span>
                      </div>
                      <div
                        className="vd"
                        style={{ color: GRADE_COLOR[r.grade_key] ?? BAND_COLOR[r.band] }}
                      >
                        {r.grade ?? r.verdict}
                      </div>
                      <div className="trio">
                        <MiniGrade label="Quarter" g={r.results?.grade_key} s={r.results?.score ?? null} />
                        <MiniGrade label="P&L" g={r.pnl?.grade_key} s={r.pnl?.score ?? null} />
                      </div>
                      <div className="meta">
                        {r.industry || r.sector || "—"}
                        {r.is_lender && <span className="tag">lender scoring</span>}
                        {r.basis && <span className="tag">{r.basis}</span>}
                        {r.from_cache && <span className="tag">cached</span>}
                        {r.coverage < 0.75 && (
                          <span className="tag warnTag">
                            {Math.round(r.coverage * 100)}% data coverage
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="nums">
                      <div>
                        <span>Price</span>
                        <b>{inr(r.price)}</b>
                      </div>
                      <div>
                        <span>M-cap</span>
                        <b>{crore(r.market_cap_cr)}</b>
                      </div>
                      <div>
                        <span>P/E</span>
                        <b>{r.pe?.toFixed(1) ?? "—"}</b>
                      </div>
                      <div>
                        <span>ROCE</span>
                        <b>{r.roce !== null && r.roce !== undefined ? `${r.roce.toFixed(1)}%` : "—"}</b>
                      </div>
                    </div>
                    <span className="chev">{expanded === r.symbol ? "▲" : "▼"}</span>
                  </button>

                  {r.brief && (
                    <div className="briefrow">
                      <p className="brieftext">{r.brief}</p>
                      <button
                        className="copybtn"
                        onClick={(e) => {
                          e.stopPropagation();
                          copyBrief(r);
                        }}
                        title="Copy this write-up, the three grades and the key numbers"
                      >
                        {copiedSym === r.symbol ? "Copied" : "Copy"}
                      </button>
                    </div>
                  )}

                  {expanded === r.symbol && (
                    <div className="detail">
                      <p className="summary">{r.summary}</p>

                      {r.results && (
                        <div className="results">
                          <div className="rhead">
                            <span
                              className="rscore"
                              style={{
                                background: GRADE_COLOR[r.results.grade_key] ?? BAND_COLOR[r.results.band],
                              }}
                            >
                              {r.results.score === null ? "—" : r.results.score.toFixed(1)}
                            </span>
                            <div>
                              <div
                                className="rverdict"
                                style={{ color: GRADE_COLOR[r.results.grade_key] ?? BAND_COLOR[r.results.band] }}
                              >
                                {r.results.grade ?? r.results.verdict}
                              </div>
                              <div className="rsub">
                                Latest quarter{" "}
                                {r.results.latest_quarter && (
                                  <b>{r.results.latest_quarter}</b>
                                )}{" "}
                                vs {r.results.comparison_quarter ?? "a year earlier"} — judged
                                separately from the {r.score}/10 business score above
                              </div>
                            </div>
                          </div>
                          <p className="rhead-line">{r.results.headline}</p>
                          {r.results.signals.length > 0 && (
                            <div className="sig">
                              {r.results.signals.map((s) => (
                                <div key={s.label} className={`sg ${s.tone}`} title={s.detail}>
                                  <span className="sl">{s.label}</span>
                                  <b className="sv">{s.value}</b>
                                </div>
                              ))}
                            </div>
                          )}
                          {r.results.one_off_flag && r.results.one_off_note && (
                            <div className="oneoff">⚠ {r.results.one_off_note}</div>
                          )}
                        </div>
                      )}

                      {r.pnl && r.pnl.rated && (
                        <div className="results">
                          <div className="rhead">
                            <span
                              className="rscore"
                              style={{ background: GRADE_COLOR[r.pnl.grade_key] }}
                            >
                              {r.pnl.score === null ? "—" : r.pnl.score.toFixed(1)}
                            </span>
                            <div>
                              <div
                                className="rverdict"
                                style={{ color: GRADE_COLOR[r.pnl.grade_key] }}
                              >
                                {r.pnl.grade}
                              </div>
                              <div className="rsub">
                                {r.pnl.years} years of accounts
                                {r.pnl.first_year && r.pnl.last_year && (
                                  <>
                                    {" "}
                                    ({r.pnl.first_year} → {r.pnl.last_year})
                                  </>
                                )}{" "}
                                — the P&amp;L record on its own, apart from the balance sheet
                              </div>
                            </div>
                          </div>
                          <p className="rhead-line">{r.pnl.headline}</p>
                          {r.pnl.signals.length > 0 && (
                            <div className="sig">
                              {r.pnl.signals.map((sg) => (
                                <div key={sg.label} className={`sg ${sg.tone}`} title={sg.detail}>
                                  <span className="sl">{sg.label}</span>
                                  <b className="sv">{sg.value}</b>
                                </div>
                              ))}
                            </div>
                          )}
                          {r.pnl.one_off_flag && r.pnl.one_off_note && (
                            <div className="oneoff">⚠ {r.pnl.one_off_note}</div>
                          )}
                        </div>
                      )}

                      {r.statements && (
                        <>
                          <StatementTable
                            title="Quarterly Results"
                            subtitle={`${r.basis === "standalone" ? "Standalone" : "Consolidated"} figures in Rs. Crores`}
                            periods={r.statements.quarters_periods}
                            rows={r.statements.quarters}
                            bold={["Operating Profit", "Profit before tax", "Net Profit", "Financing Profit"]}
                            percentRows={["OPM %", "Tax %", "Financing Margin %"]}
                          />
                          <StatementTable
                            title="Profit & Loss"
                            subtitle={`${r.basis === "standalone" ? "Standalone" : "Consolidated"} figures in Rs. Crores`}
                            periods={r.statements.profit_loss_periods}
                            rows={r.statements.profit_loss}
                            bold={["Operating Profit", "Profit before tax", "Net Profit", "Financing Profit"]}
                            percentRows={["OPM %", "Tax %", "Dividend Payout %", "Financing Margin %"]}
                          />
                          {Object.keys(r.statements.ranges).length > 0 && (
                            <div className="ranges">
                              {Object.entries(r.statements.ranges).map(([title, vals]) => (
                                <div key={title} className="rg">
                                  <div className="rgt">{title}</div>
                                  {Object.entries(vals).map(([k, v]) => (
                                    <div key={k} className="rgr">
                                      <span>{k}</span>
                                      <b>{v === null || v === undefined ? "—" : `${v}%`}</b>
                                    </div>
                                  ))}
                                </div>
                              ))}
                            </div>
                          )}
                        </>
                      )}

                      {r.pillars.map((p) => (
                        <div key={p.pillar} className="pillar">
                          <div className="prow">
                            <span className="plabel">{p.label}</span>
                            <span className="pweight">
                              {Math.round((p.effective_weight ?? p.weight) * 100)}% of score
                            </span>
                            <span className="pscore" style={{ color: BAND_COLOR[scoreBand(p.score)] }}>
                              {p.score.toFixed(1)}/10
                            </span>
                          </div>
                          <div className="bar">
                            <div
                              className="fill"
                              style={{
                                width: `${p.score * 10}%`,
                                background: BAND_COLOR[scoreBand(p.score)],
                              }}
                            />
                          </div>
                          <div className="preason">{p.reason}</div>
                        </div>
                      ))}

                      {r.skipped.length > 0 && (
                        <div className="skipped">
                          <b>Not scored:</b>{" "}
                          {r.skipped.map((s) => `${s.label} — ${s.why}`).join(" · ")}
                        </div>
                      )}

                      {(r.screener_pros?.length || r.screener_cons?.length) && (
                        <div className="proscons">
                          <div>
                            <b>screener.in pros</b>
                            <ul>
                              {(r.screener_pros ?? []).map((p) => (
                                <li key={p}>{p}</li>
                              ))}
                              {!r.screener_pros?.length && <li className="none">none listed</li>}
                            </ul>
                          </div>
                          <div>
                            <b>screener.in cons</b>
                            <ul>
                              {(r.screener_cons ?? []).map((c) => (
                                <li key={c}>{c}</li>
                              ))}
                              {!r.screener_cons?.length && <li className="none">none listed</li>}
                            </ul>
                          </div>
                          <p className="src">
                            These two lists are screener.in&rsquo;s own machine-generated notes,
                            not part of the score above.{" "}
                            {r.source_url && (
                              <a href={r.source_url} target="_blank" rel="noreferrer">
                                Open on screener.in ↗
                              </a>
                            )}
                          </p>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </GlassPanel>
        </>
      )}

      {!result && recent.length > 0 && (
        <GlassPanel title="Rated earlier" note="Click to re-run">
          <div className="chips">
            {recent.map((r) => (
              <button
                key={r.symbol}
                className="chip"
                onClick={() => setInput(r.symbol)}
                title={r.verdict}
              >
                <span className="cs" style={{ background: BAND_COLOR[r.band] }}>
                  {r.score?.toFixed(1) ?? "—"}
                </span>
                {r.symbol}
              </button>
            ))}
          </div>
        </GlassPanel>
      )}

      </>
      )}

      <style jsx>{`
        .tabs {
          display: flex;
          gap: 6px;
          margin-bottom: 18px;
          border-bottom: 1px solid var(--panel-border);
        }
        .tabs button {
          background: none;
          border: none;
          border-bottom: 2px solid transparent;
          padding: 9px 14px;
          font-size: 13px;
          font-weight: 600;
          color: var(--text-muted);
          cursor: pointer;
          margin-bottom: -1px;
        }
        .tabs button.on {
          color: var(--purple);
          border-bottom-color: var(--purple);
        }
        .page {
          padding: 28px 32px 64px;
          max-width: 1180px;
          margin: 0 auto;
        }
        .paste {
          width: 100%;
          border: 1px solid var(--panel-border);
          border-radius: 10px;
          padding: 12px 14px;
          font-size: 14px;
          font-family: var(--font-mono, ui-monospace, monospace);
          background: var(--canvas-soft);
          color: var(--text);
          resize: vertical;
        }
        .paste:focus {
          outline: none;
          border-color: rgba(125, 52, 220, 0.45);
        }
        .controls {
          display: flex;
          align-items: center;
          gap: 10px;
          margin-top: 12px;
          flex-wrap: wrap;
        }
        .hint {
          font-size: 12px;
          color: var(--text-faint);
        }
        .primary {
          background: var(--purple);
          color: #fff;
          border: none;
          border-radius: 9px;
          padding: 9px 18px;
          font-weight: 650;
          font-size: 13px;
          cursor: pointer;
        }
        .primary:disabled {
          opacity: 0.6;
          cursor: default;
        }
        .ghost {
          background: var(--canvas-soft);
          border: 1px solid var(--panel-border);
          color: var(--text-muted);
          border-radius: 9px;
          padding: 8px 14px;
          font-size: 12.5px;
          font-weight: 600;
          cursor: pointer;
        }
        .progress,
        .warn {
          margin-top: 12px;
          font-size: 12.5px;
          color: var(--text-muted);
          background: var(--canvas-soft);
          border: 1px solid var(--panel-border);
          border-radius: 9px;
          padding: 10px 12px;
        }
        .warn {
          margin: 12px 0;
          border-color: rgba(224, 122, 44, 0.35);
        }
        .cards {
          display: flex;
          flex-direction: column;
          gap: 10px;
        }
        .card {
          border: 1px solid var(--panel-border);
          border-radius: 12px;
          overflow: hidden;
          background: var(--canvas-soft);
        }
        .card-head {
          display: flex;
          align-items: center;
          gap: 16px;
          width: 100%;
          padding: 14px 16px;
          background: none;
          border: none;
          cursor: pointer;
          text-align: left;
          color: inherit;
        }
        .score {
          flex: 0 0 auto;
          width: 54px;
          height: 54px;
          border-radius: 12px;
          color: #fff;
          font-weight: 800;
          font-size: 19px;
          display: flex;
          align-items: center;
          justify-content: center;
          font-family: var(--font-display);
        }
        .who {
          flex: 1 1 auto;
          min-width: 0;
        }
        .nm {
          font-weight: 700;
          font-size: 14.5px;
        }
        .sym {
          color: var(--text-faint);
          font-weight: 500;
          font-size: 12px;
          margin-left: 6px;
        }
        .vd {
          font-size: 12.5px;
          font-weight: 650;
          margin-top: 1px;
        }
        .trio {
          display: flex;
          gap: 5px;
          margin-top: 4px;
        }
        .meta {
          font-size: 11.5px;
          color: var(--text-faint);
          margin-top: 3px;
          display: flex;
          gap: 6px;
          align-items: center;
          flex-wrap: wrap;
        }
        .tag {
          border: 1px solid var(--panel-border);
          border-radius: 20px;
          padding: 1px 8px;
        }
        .warnTag {
          border-color: rgba(224, 122, 44, 0.4);
          color: #e07a2c;
        }
        .nums {
          display: flex;
          gap: 18px;
          flex: 0 0 auto;
        }
        .nums div {
          display: flex;
          flex-direction: column;
          gap: 1px;
        }
        .nums span {
          font-size: 10.5px;
          color: var(--text-faint);
          text-transform: uppercase;
          letter-spacing: 0.4px;
        }
        .nums b {
          font-size: 13px;
        }
        .chev {
          color: var(--text-faint);
          font-size: 10px;
        }
        .briefrow {
          display: flex;
          align-items: flex-start;
          gap: 12px;
          padding: 0 16px 14px;
        }
        .brieftext {
          flex: 1 1 auto;
          margin: 0;
          font-size: 12.5px;
          line-height: 1.6;
          color: var(--text-muted);
        }
        .copybtn {
          flex: 0 0 auto;
          background: var(--canvas-soft);
          border: 1px solid var(--panel-border);
          color: var(--text-muted);
          border-radius: 8px;
          padding: 5px 12px;
          font-size: 11.5px;
          font-weight: 650;
          cursor: pointer;
        }
        .copybtn:hover {
          color: var(--purple);
          border-color: rgba(125, 52, 220, 0.35);
          background: var(--purple-dim);
        }
        .detail {
          padding: 4px 16px 16px;
          border-top: 1px solid var(--panel-border);
        }
        .summary {
          font-size: 13px;
          color: var(--text-muted);
          margin: 12px 0 16px;
          line-height: 1.55;
        }
        .pillar {
          margin-bottom: 14px;
        }
        .prow {
          display: flex;
          align-items: baseline;
          gap: 10px;
        }
        .plabel {
          font-weight: 650;
          font-size: 13px;
        }
        .pweight {
          font-size: 11px;
          color: var(--text-faint);
          flex: 1 1 auto;
        }
        .pscore {
          font-weight: 750;
          font-size: 13px;
        }
        .bar {
          height: 5px;
          border-radius: 3px;
          background: var(--panel-border);
          margin: 6px 0 5px;
          overflow: hidden;
        }
        .fill {
          height: 100%;
          border-radius: 3px;
        }
        .preason {
          font-size: 12.5px;
          color: var(--text-muted);
          line-height: 1.5;
        }
        .results {
          border: 1px solid var(--panel-border);
          border-radius: 10px;
          padding: 12px 14px;
          margin-bottom: 16px;
          background: var(--canvas);
        }
        .rhead {
          display: flex;
          align-items: center;
          gap: 12px;
        }
        .rscore {
          width: 40px;
          height: 40px;
          border-radius: 10px;
          color: #fff;
          font-weight: 800;
          font-size: 15px;
          display: flex;
          align-items: center;
          justify-content: center;
          flex: 0 0 auto;
          font-family: var(--font-display);
        }
        .rverdict {
          font-weight: 700;
          font-size: 13.5px;
        }
        .rsub {
          font-size: 11.5px;
          color: var(--text-faint);
          margin-top: 1px;
        }
        .rhead-line {
          font-size: 12.5px;
          color: var(--text-muted);
          line-height: 1.55;
          margin: 10px 0 0;
        }
        .sig {
          display: flex;
          gap: 8px;
          flex-wrap: wrap;
          margin-top: 10px;
        }
        .sg {
          border: 1px solid var(--panel-border);
          border-radius: 9px;
          padding: 6px 11px;
          display: flex;
          flex-direction: column;
          gap: 1px;
          cursor: help;
        }
        .sg.good {
          border-color: rgba(26, 156, 91, 0.4);
        }
        .sg.bad {
          border-color: rgba(212, 68, 60, 0.4);
        }
        .sl {
          font-size: 10.5px;
          color: var(--text-faint);
        }
        .sv {
          font-size: 13px;
        }
        .sg.good .sv {
          color: #1a9c5b;
        }
        .sg.bad .sv {
          color: #d4443c;
        }
        .oneoff {
          margin-top: 10px;
          font-size: 11.5px;
          color: #b8690f;
          background: rgba(224, 122, 44, 0.08);
          border: 1px solid rgba(224, 122, 44, 0.3);
          border-radius: 8px;
          padding: 8px 10px;
          line-height: 1.5;
        }
        .ranges {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
          gap: 10px;
          margin: 4px 0 16px;
        }
        .rg {
          border: 1px solid var(--panel-border);
          border-radius: 9px;
          padding: 10px 12px;
        }
        .rgt {
          font-size: 11.5px;
          font-weight: 700;
          margin-bottom: 6px;
        }
        .rgr {
          display: flex;
          justify-content: space-between;
          font-size: 12px;
          color: var(--text-muted);
          padding: 1px 0;
        }
        .skipped {
          font-size: 12px;
          color: var(--text-faint);
          border-top: 1px dashed var(--panel-border);
          padding-top: 10px;
          margin-top: 6px;
        }
        .proscons {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 18px;
          margin-top: 14px;
          border-top: 1px dashed var(--panel-border);
          padding-top: 12px;
        }
        .proscons b {
          font-size: 12px;
        }
        .proscons ul {
          margin: 6px 0 0;
          padding-left: 16px;
        }
        .proscons li {
          font-size: 12px;
          color: var(--text-muted);
          margin-bottom: 4px;
          line-height: 1.45;
        }
        .none {
          color: var(--text-faint);
          font-style: italic;
        }
        .src {
          grid-column: 1 / -1;
          font-size: 11.5px;
          color: var(--text-faint);
          margin: 4px 0 0;
        }
        .src a {
          color: var(--purple);
        }
        .weights {
          display: flex;
          gap: 8px;
          flex-wrap: wrap;
          margin-bottom: 14px;
        }
        .w {
          border: 1px solid var(--panel-border);
          border-radius: 9px;
          padding: 8px 12px;
          display: flex;
          flex-direction: column;
          gap: 2px;
        }
        .w b {
          font-size: 15px;
          font-family: var(--font-display);
        }
        .w span {
          font-size: 11px;
          color: var(--text-faint);
        }
        .bands {
          display: flex;
          gap: 16px;
          flex-wrap: wrap;
          margin-bottom: 12px;
        }
        .bd {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 12px;
          color: var(--text-muted);
        }
        .dot {
          width: 9px;
          height: 9px;
          border-radius: 50%;
        }
        .notes {
          margin: 0;
          padding-left: 18px;
        }
        .notes li {
          font-size: 12px;
          color: var(--text-muted);
          margin-bottom: 5px;
          line-height: 1.5;
        }
        .chips {
          display: flex;
          gap: 7px;
          flex-wrap: wrap;
        }
        .chip {
          display: inline-flex;
          align-items: center;
          gap: 7px;
          border: 1px solid var(--panel-border);
          background: var(--canvas-soft);
          border-radius: 20px;
          padding: 5px 12px 5px 5px;
          font-size: 12px;
          font-weight: 600;
          cursor: pointer;
          color: inherit;
        }
        .cs {
          color: #fff;
          border-radius: 50%;
          width: 22px;
          height: 22px;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          font-size: 10.5px;
          font-weight: 800;
        }
        @media (max-width: 860px) {
          .page {
            padding: 20px 16px 48px;
          }
          .nums {
            display: none;
          }
          .proscons {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
    </div>
  );
}

/** A screener.in statement rendered as-is: periods across, line items down.
 *
 * Horizontally scrollable rather than wrapped or truncated — a P&L with twelve years and a
 * TTM column cannot be made narrow without losing the comparison that makes it worth
 * reading, and the first column is pinned so the line item stays visible while scrolling.
 */
function StatementTable({
  title,
  subtitle,
  periods,
  rows,
  bold = [],
  percentRows = [],
}: {
  title: string;
  subtitle: string;
  periods: string[];
  rows: Record<string, (number | null)[]>;
  bold?: string[];
  percentRows?: string[];
}) {
  const names = Object.keys(rows);
  if (!names.length || !periods.length) return null;

  const fmt = (v: number | null | undefined, pct: boolean) => {
    if (v === null || v === undefined) return "—";
    if (pct) return `${v.toFixed(0)}%`;
    return v.toLocaleString("en-IN", { maximumFractionDigits: 2 });
  };

  return (
    <div className="stmt">
      <div className="stmt-head">
        <b>{title}</b>
        <span>{subtitle}</span>
      </div>
      <div className="stmt-scroll">
        <table>
          <thead>
            <tr>
              <th className="lead" />
              {periods.map((p) => (
                <th key={p}>{p}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {names.map((name) => {
              const pct = percentRows.includes(name);
              return (
                <tr key={name} className={bold.includes(name) ? "strong" : ""}>
                  <td className="lead">{name}</td>
                  {periods.map((p, i) => (
                    <td key={p} className={(rows[name]?.[i] ?? 0) < 0 ? "neg" : ""}>
                      {fmt(rows[name]?.[i], pct)}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <style jsx>{`
        .stmt {
          margin: 16px 0;
          border: 1px solid var(--panel-border);
          border-radius: 10px;
          overflow: hidden;
          background: var(--canvas);
        }
        .stmt-head {
          padding: 10px 12px;
          border-bottom: 1px solid var(--panel-border);
          display: flex;
          align-items: baseline;
          gap: 10px;
          flex-wrap: wrap;
        }
        .stmt-head b {
          font-size: 13px;
        }
        .stmt-head span {
          font-size: 11.5px;
          color: var(--text-faint);
        }
        .stmt-scroll {
          overflow-x: auto;
        }
        table {
          border-collapse: collapse;
          width: 100%;
          font-size: 12px;
          white-space: nowrap;
        }
        th,
        td {
          padding: 7px 10px;
          text-align: right;
          border-bottom: 1px solid var(--panel-border);
        }
        th {
          font-size: 11px;
          font-weight: 600;
          color: var(--text-faint);
          background: var(--canvas-soft);
          position: sticky;
          top: 0;
        }
        .lead {
          text-align: left;
          position: sticky;
          left: 0;
          background: var(--canvas);
          z-index: 1;
          font-weight: 500;
          min-width: 150px;
        }
        th.lead {
          background: var(--canvas-soft);
          z-index: 2;
        }
        tr.strong td {
          font-weight: 700;
        }
        tr.strong .lead {
          font-weight: 700;
        }
        tbody tr:hover td {
          background: var(--purple-dim);
        }
        tbody tr:hover .lead {
          background: var(--purple-dim);
        }
        .neg {
          color: #d4443c;
        }
      `}</style>
    </div>
  );
}

/** The other two grades, shown small on the collapsed card so all three read at a glance. */
function MiniGrade({ label, g, s }: { label: string; g?: GradeKey | null; s: number | null }) {
  if (s === null || s === undefined || !g) return null;
  return (
    <span className="mg" style={{ borderColor: GRADE_COLOR[g], color: GRADE_COLOR[g] }}>
      {label} <b>{s.toFixed(1)}</b>
      <style jsx>{`
        .mg {
          border: 1px solid;
          border-radius: 20px;
          padding: 1px 8px;
          font-size: 10px;
          font-weight: 600;
        }
      `}</style>
    </span>
  );
}

function scoreBand(score: number): RatingBand {
  if (score >= 8.5) return "strong";
  if (score >= 7) return "good";
  if (score >= 5.5) return "mixed";
  if (score >= 4) return "weak";
  return "poor";
}
