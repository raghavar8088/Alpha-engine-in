"use client";

/**
 * All Time High Trading.
 *
 * The page leads with the rule and the coverage, in that order, because both are needed to
 * read anything below them. "No positions today" means one thing if 1,100 stocks were
 * scanned and another if 400 were — and only the coverage panel can tell you which.
 */

import { useCallback, useEffect, useState } from "react";
import PageHeader from "../../components/PageHeader";
import GlassPanel from "../../components/GlassPanel";
import ErrorBanner from "../../components/ErrorBanner";
import EmptyState from "../../components/EmptyState";
import StatusPill from "../../components/StatusPill";
import Skeleton from "../../components/Skeleton";
import {
  refreshing, fetchAthSummary, fetchAthCoverage, fetchAthPositions, fetchAthTrades,
  fetchAthSignals, fetchAthNearHighs, fetchAthUniverse, runAthCycle, seedAthHighs,
  AthSummary, AthCoverage, AthPosition, AthTrade, AthSignal, AthNearHigh, AthUniverseRow,
} from "../../lib/api";

type Tab = "positions" | "near" | "signals" | "trades" | "universe";
const TABS: { key: Tab; label: string }[] = [
  { key: "positions", label: "Positions" },
  { key: "near", label: "Approaching highs" },
  { key: "signals", label: "Signals" },
  { key: "trades", label: "Closed" },
  { key: "universe", label: "Universe" },
];

const inr = (v: number | null | undefined, dp = 0) =>
  v === null || v === undefined ? "—" :
    `₹${v.toLocaleString("en-IN", { minimumFractionDigits: dp, maximumFractionDigits: dp })}`;
const num = (v: number | null | undefined, dp = 2) =>
  v === null || v === undefined ? "—" : v.toLocaleString("en-IN", { maximumFractionDigits: dp });
const pct = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
const cls = (v: number | null | undefined) =>
  v === null || v === undefined ? "" : v > 0 ? "gain" : v < 0 ? "loss" : "";
const cr = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}cr`;

export default function AllTimeHighTradingPage() {
  const [summary, setSummary] = useState<AthSummary | null>(null);
  const [coverage, setCoverage] = useState<AthCoverage | null>(null);
  const [positions, setPositions] = useState<AthPosition[]>([]);
  const [trades, setTrades] = useState<AthTrade[]>([]);
  const [signals, setSignals] = useState<AthSignal[]>([]);
  const [near, setNear] = useState<AthNearHigh[]>([]);
  const [uni, setUni] = useState<AthUniverseRow[]>([]);
  const [tab, setTab] = useState<Tab>("positions");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const jobs: Promise<unknown>[] = [
        fetchAthSummary().then(setSummary),
        fetchAthCoverage().then(setCoverage),
      ];
      if (tab === "positions") jobs.push(fetchAthPositions().then((r) => setPositions(r.rows)));
      if (tab === "trades") jobs.push(fetchAthTrades().then((r) => setTrades(r.rows)));
      if (tab === "signals") jobs.push(fetchAthSignals().then((r) => setSignals(r.rows)));
      if (tab === "near") jobs.push(fetchAthNearHighs(60).then((r) => setNear(r.rows)));
      if (tab === "universe") jobs.push(fetchAthUniverse(400).then((r) => setUni(r.rows)));
      await Promise.all(jobs);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [tab]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, [load]);

  const act = async (fn: () => Promise<Record<string, unknown>>, label: string) => {
    setBusy(true); setNotice(null);
    try {
      const r = await fn();
      setNotice(`${label}: ${JSON.stringify(r)}`);
      await refreshing(load);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  };

  return (
    <div className="page">
      <PageHeader
        crumb="All Time High Trading"
        title="All Time High Trading"
        subtitle="Buys ₹1,00,000 of any NSE stock above ₹1,000 crore market cap on the day it prints a new all-time high, then holds it to +20% or −20% and nothing else — no time limit, no square-off. Paper, on live Angel One prices, with real Angel delivery costs charged on exit."
        onRefresh={() => refreshing(load)}
        actions={
          <div className="acts">
            {summary && <StatusPill label={summary.market_open ? "Market Open" : "Market Closed"}
              tone={summary.market_open ? "gain" : "muted"} pulse={summary.market_open} />}
            <StatusPill label="PAPER" tone="accent" />
          </div>
        }
      />

      {error && <ErrorBanner message={error} onRetry={load} />}
      {notice && <div className="notice">{notice}<button onClick={() => setNotice(null)}>✕</button></div>}

      {/* ── the rule, stated before any number ─────────────────────────── */}
      {summary && (
        <div className="rule">
          <b>The rule.</b> Market cap above {cr(summary.market_cap_floor_cr)} · buy{" "}
          {inr(summary.per_position)} at a new all-time high · exit at{" "}
          <b className="gain">+{summary.target_pct}%</b> or{" "}
          <b className="loss">−{summary.stop_pct}%</b>. {summary.exit_note}
        </div>
      )}

      {/* ── stats ──────────────────────────────────────────────────────── */}
      <div className="stats">
        {summary ? (
          <>
            <Cell label="Equity" value={inr(summary.equity)} strong />
            <Cell label="Deployed" value={inr(summary.deployed)}
              note={`${summary.open_positions} of ${summary.max_positions} slots`} />
            <Cell label="Available" value={inr(summary.available)} />
            <Cell label="Realised" value={inr(summary.realised_pnl)}
              tone={summary.realised_pnl >= 0 ? "gain" : "loss"}
              note={`after ${inr(summary.fees_paid)} costs`} />
            <Cell label="Unrealised" value={inr(summary.unrealised_pnl)}
              tone={summary.unrealised_pnl >= 0 ? "gain" : "loss"} />
            <Cell label="ROI" value={pct(summary.roi_pct)}
              tone={summary.roi_pct >= 0 ? "gain" : "loss"} />
            <Cell label="Target / Stop hits"
              value={`${summary.target_hits} / ${summary.stop_hits}`}
              note={summary.win_rate !== null ? `${summary.win_rate}% win rate` : "no trades yet"} />
            <Cell label="Scanned" value={String(summary.last_scanned ?? "—")}
              note={summary.last_cycle ? new Date(summary.last_cycle).toLocaleTimeString() : "not run yet"} />
          </>
        ) : Array.from({ length: 8 }).map((_, i) => (
          <div className="cell" key={i}><Skeleton height={34} /></div>
        ))}
      </div>

      {/* ── coverage: why the numbers above are what they are ──────────── */}
      {coverage && (
        <GlassPanel title="What the desk can actually see"
          note={`${coverage.tradable} tradable`}>
          <div className="cov">
            <Step n={coverage.above_market_cap} label={`above ${cr(coverage.market_cap_floor_cr)}`} />
            <Arrow />
            <Step n={coverage.angel_quotable} label="Angel-quotable on NSE" />
            <Arrow />
            <Step n={coverage.with_all_time_high} label="with a stored all-time high" />
            <Arrow />
            <Step n={coverage.tradable} label={`and ≥ ${coverage.min_sessions} sessions`} strong />
          </div>
          <div className="note">{coverage.note}</div>
          <div className="note warn">{coverage.exchange_note}</div>
          {coverage.missing_highs > 0 && (
            <button className="seed" disabled={busy}
              onClick={() => act(() => seedAthHighs(120), "Seeded highs")}>
              {busy ? "Working…" : `Seed all-time highs for ${coverage.missing_highs} more stocks`}
            </button>
          )}
        </GlassPanel>
      )}

      <div className="tabbar">
        {TABS.map((t) => (
          <button key={t.key} className={tab === t.key ? "tb active" : "tb"}
            onClick={() => setTab(t.key)}>{t.label}</button>
        ))}
        <button className="run" disabled={busy}
          onClick={() => act(runAthCycle, "Cycle")}>Run a cycle now</button>
      </div>

      <GlassPanel>
        {tab === "positions" && (
          positions.length === 0 ? (
            <EmptyState title="No open positions"
              note="The desk buys only when a qualifying stock prints a NEW all-time high. On most days that is nobody." />
          ) : (
            <div className="tw"><table>
              <thead><tr>
                <th className="l">Stock</th><th>Mkt cap</th><th>Entry</th><th>Qty</th><th>LTP</th>
                <th>Return</th><th>P&amp;L</th><th>Stop</th><th>Target</th>
                <th>To target</th><th>To stop</th><th>Held</th>
              </tr></thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={p.position_id}>
                    <td className="l"><b>{p.symbol}</b><div className="sub">{p.name}</div></td>
                    <td className="dim">{cr(p.market_cap_cr)}</td>
                    <td>{num(p.entry)}</td>
                    <td className="dim">{p.quantity}</td>
                    <td>{num(p.ltp)}</td>
                    <td className={cls(p.return_pct)}>{pct(p.return_pct)}</td>
                    <td className={cls(p.unrealised_pnl)}><b>{inr(p.unrealised_pnl)}</b></td>
                    <td className="loss">{num(p.stop)}</td>
                    <td className="gain">{num(p.target)}</td>
                    <td className="dim">{pct(p.to_target_pct)}</td>
                    <td className="dim">{pct(p.to_stop_pct)}</td>
                    <td className="dim">{p.days_held}d</td>
                  </tr>
                ))}
              </tbody>
            </table></div>
          )
        )}

        {tab === "near" && (
          near.length === 0 ? <EmptyState title="Nothing close to an all-time high" /> : (
            <>
              <div className="note">
                Stocks approaching their all-time high without having broken it. The desk acts
                only on the break — this is what it is watching.
              </div>
              <div className="tw"><table>
                <thead><tr>
                  <th className="l">Stock</th><th>Mkt cap</th><th>LTP</th>
                  <th>All-time high</th><th>Set on</th><th>Gap</th><th>History</th>
                </tr></thead>
                <tbody>
                  {near.map((r) => (
                    <tr key={r.symbol}>
                      <td className="l"><b>{r.symbol}</b><div className="sub">{r.name}</div></td>
                      <td className="dim">{cr(r.market_cap_cr)}</td>
                      <td>{num(r.ltp)}</td>
                      <td>{num(r.all_time_high)}</td>
                      <td className="dim">{r.ath_date}</td>
                      <td className={r.pct_from_ath > -2 ? "warn" : "dim"}>
                        <b>{pct(r.pct_from_ath)}</b></td>
                      <td className="dim">{r.sessions} sessions</td>
                    </tr>
                  ))}
                </tbody>
              </table></div>
            </>
          )
        )}

        {tab === "signals" && (
          signals.length === 0 ? (
            <EmptyState title="No signals yet"
              note="Every all-time-high break is recorded here — including the ones the desk could not take, and why." />
          ) : (
            <div className="tw"><table>
              <thead><tr>
                <th className="l">Stock</th><th>Price</th><th>Broke</th><th>Mkt cap</th>
                <th>Taken</th><th className="l">Reason</th><th>When</th>
              </tr></thead>
              <tbody>
                {signals.map((s) => (
                  <tr key={s.signal_id}>
                    <td className="l"><b>{s.symbol}</b></td>
                    <td>{num(s.ltp)}</td>
                    <td className="dim">{num(s.all_time_high)}</td>
                    <td className="dim">{cr(s.market_cap_cr)}</td>
                    <td><span className={s.taken ? "yes" : "no"}>{s.taken ? "BOUGHT" : "skipped"}</span></td>
                    <td className="l sub wide">{s.why}</td>
                    <td className="dim">{new Date(s.ts).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table></div>
          )
        )}

        {tab === "trades" && (
          trades.length === 0 ? (
            <EmptyState title="No closed trades"
              note="A position closes only at +20% or −20%, so the first results take as long as the market takes." />
          ) : (
            <div className="tw"><table>
              <thead><tr>
                <th className="l">Stock</th><th>Entry</th><th>Exit</th><th>Qty</th>
                <th>Reason</th><th>Return</th><th>Gross</th><th>Costs</th><th>Net</th><th>Held</th>
              </tr></thead>
              <tbody>
                {trades.map((t) => (
                  <tr key={t.position_id}>
                    <td className="l"><b>{t.symbol}</b></td>
                    <td>{num(t.entry)}</td>
                    <td>{num(t.exit)}</td>
                    <td className="dim">{t.quantity}</td>
                    <td><span className={t.exit_reason === "TARGET" ? "yes" : "no"}>{t.exit_reason}</span></td>
                    <td className={cls(t.return_pct)}>{pct(t.return_pct)}</td>
                    <td className={cls(t.gross_pnl)}>{inr(t.gross_pnl)}</td>
                    <td className="dim">{inr(t.fees)}</td>
                    <td className={cls(t.net_pnl)}><b>{inr(t.net_pnl)}</b></td>
                    <td className="dim">{t.days_held}d</td>
                  </tr>
                ))}
              </tbody>
            </table></div>
          )
        )}

        {tab === "universe" && (
          uni.length === 0 ? <EmptyState title="Universe empty" /> : (
            <div className="tw"><table>
              <thead><tr>
                <th className="l">Stock</th><th>Market cap</th><th>All-time high</th>
                <th>Set on</th><th>History</th>
              </tr></thead>
              <tbody>
                {uni.map((r) => (
                  <tr key={r.symbol}>
                    <td className="l"><b>{r.symbol}</b><div className="sub">{r.name}</div></td>
                    <td>{cr(r.market_cap_cr)}</td>
                    <td>{num(r.all_time_high)}</td>
                    <td className="dim">{r.ath_date}</td>
                    <td className="dim">{r.sessions}</td>
                  </tr>
                ))}
              </tbody>
            </table></div>
          )
        )}
      </GlassPanel>

      <style jsx>{`
        .page { display: flex; flex-direction: column; gap: 14px; }
        .acts { display: flex; gap: 8px; align-items: center; }
        .notice { display: flex; justify-content: space-between; gap: 12px; padding: 9px 13px; border-radius: 9px; background: var(--gain-dim); color: var(--gain); border: 1px solid var(--gain); font-size: 12px; }
        .notice button { border: 0; background: transparent; color: inherit; cursor: pointer; }
        .rule { font-size: 12.5px; line-height: 1.6; color: var(--text-muted); background: var(--purple-dim); border: 1px solid var(--purple); border-radius: 10px; padding: 11px 15px; }
        .rule b { color: var(--text); }
        .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 8px; }

        .cov { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; margin-bottom: 10px; }
        .note { font-size: 11.5px; color: var(--text-muted); line-height: 1.55; background: var(--canvas-soft); border-radius: 8px; padding: 9px 12px; margin-top: 8px; }
        .note.warn { color: var(--warn); background: var(--warn-dim); border: 1px solid var(--warn); }
        .seed { margin-top: 10px; border: 1px solid var(--purple); background: var(--purple-dim); color: var(--purple); border-radius: 8px; padding: 7px 13px; font-size: 12px; font-weight: 600; cursor: pointer; }
        .seed:disabled { opacity: .5; cursor: default; }

        .tabbar { display: flex; gap: 2px; align-items: center; border-bottom: 1px solid var(--panel-border); }
        .tb { border: 0; background: transparent; padding: 9px 15px; font-size: 13px; font-weight: 600; color: var(--text-muted); cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -1px; }
        .tb.active { color: var(--purple); border-bottom-color: var(--purple); }
        .run { margin-left: auto; border: 1px solid var(--panel-border); background: var(--panel); border-radius: 8px; padding: 5px 11px; font-size: 11.5px; color: var(--text-muted); cursor: pointer; }

        .tw { overflow-x: auto; }
        table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
        th, td { padding: 8px 10px; text-align: right; white-space: nowrap; border-bottom: 1px solid var(--panel-border); font-variant-numeric: tabular-nums; }
        th { font-size: 10.5px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: .04em; }
        th.l, td.l { text-align: left; }
        td.dim { color: var(--text-muted); }
        .sub { font-size: 10px; color: var(--text-faint); white-space: normal; }
        td.wide { max-width: 340px; white-space: normal; }
        .gain { color: var(--gain); } .loss { color: var(--loss); } .warn { color: var(--warn); }
        .yes { font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 4px; background: var(--gain-dim); color: var(--gain); }
        .no { font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 4px; background: var(--canvas-soft); color: var(--text-muted); }
      `}</style>
    </div>
  );
}

function Cell({ label, value, note, tone, strong }: {
  label: string; value: string; note?: string; tone?: "gain" | "loss"; strong?: boolean;
}) {
  return (
    <div className="cell">
      <div className="cl">{label}</div>
      <div className={`cv ${tone ?? ""}${strong ? " strong" : ""}`}>{value}</div>
      {note && <div className="cn">{note}</div>}
      <style jsx>{`
        .cell { border: 1px solid var(--panel-border); border-radius: 10px; padding: 9px 12px; background: var(--panel); }
        .cl { font-size: 10px; text-transform: uppercase; letter-spacing: .05em; color: var(--text-muted); }
        .cv { font-size: 16px; font-weight: 600; margin-top: 2px; font-variant-numeric: tabular-nums; }
        .cv.strong { font-weight: 700; }
        .cv.gain { color: var(--gain); } .cv.loss { color: var(--loss); }
        .cn { font-size: 10px; color: var(--text-faint); margin-top: 1px; }
      `}</style>
    </div>
  );
}

function Step({ n, label, strong }: { n: number; label: string; strong?: boolean }) {
  return (
    <div className={strong ? "st on" : "st"}>
      <div className="n">{n.toLocaleString("en-IN")}</div>
      <div className="l">{label}</div>
      <style jsx>{`
        .st { border: 1px solid var(--panel-border); border-radius: 9px; padding: 7px 12px; background: var(--panel); }
        .st.on { border-color: var(--purple); background: var(--purple-dim); }
        .n { font-size: 17px; font-weight: 700; font-variant-numeric: tabular-nums; }
        .l { font-size: 10px; color: var(--text-muted); }
      `}</style>
    </div>
  );
}

function Arrow() {
  return (
    <span className="ar">→<style jsx>{`.ar { color: var(--text-faint); font-size: 14px; }`}</style></span>
  );
}
