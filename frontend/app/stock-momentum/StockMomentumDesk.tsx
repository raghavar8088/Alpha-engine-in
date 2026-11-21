"use client";

// The Stock Momentum Trading desk (21 Nov 2026: its own module, rebuilt from the Stock Screener tab
// MorningMomentum.tsx). Everything it shows and does goes through /api/screener/morning/{index}:
//   GET   the universe's book: scanner/paper switches, approved rules, the 09:30 board, open and closed paper
//         positions, missed square-offs and rejected entries, the rules, the replay report, limits and label
//   POST  {scan} | {paper} | {strategy, approve}
// The replay report is the module's own (backend/app/data/morning_replay.json, morning_replay.py): every rule
// loses after costs there, and the page says so beside the approve buttons.
// Styles are global but scoped under .smt: the tables and empty states are drawn by small components, which a
// <style jsx> block would not reach (the old tab's tables rendered unstyled for that reason).
import { useCallback, useEffect, useMemo, useState } from "react";
import PageHeader from "../../components/PageHeader";
import StatusPill from "../../components/StatusPill";
import EmptyState from "../../components/EmptyState";
import ErrorBanner from "../../components/ErrorBanner";
import { apiFetch, fetchScreenerConfig } from "../../lib/api";

type Candidate = { symbol: string; sector: string; side: number; rank: number; score: number; change: number;
  market: number; relative: number; vwap: number; volume: number; turnover?: number; gap?: number };
type Board = { day?: string; asof?: string; processed?: string; total: number; usable: number; rows: Candidate[];
  excluded: Record<string, string> };
type Position = { id?: string; symbol: string; rule: string; side: number; entry: number; qty: number; stop: number;
  target: number; opened?: string; deadline?: number; net?: number; exit?: number; why?: string; basis?: string;
  closed?: string };
type Result = { rule: string; mode: string; period: string; side: string; trades: number; win_pct: number | null;
  profit_factor: number | null; drawdown_rs: number; mean_net_pct: number | null; net_rs: number; failed_exits: number };
type Limits = { book_rs: number; risk_rs: number; notional_rs: number; max_positions: number; entry_until: string;
  square_off: string; entry_quote_s: number; exit_quote_s?: number; late_quote_s?: number };
type Desk = { scan: boolean; paper: boolean; approved: string[]; board?: Board; rules: Record<string, string>;
  policy: string; report: { split: string; rows: Result[]; coverage: [string, number, number][] };
  positions?: Position[]; recent?: Position[]; failed?: string[]; rejected?: string[][]; label?: string;
  limits?: Limits };

const INDICES = [{ key: "nifty50", label: "Nifty 50" }, { key: "nifty100", label: "Nifty 100" },
  { key: "nifty250", label: "Nifty 250" }, { key: "nifty500", label: "Nifty 500" }];
const LIMITS: Limits = { book_rs: 100000, risk_rs: 100, notional_rs: 10000, max_positions: 5, entry_until: "14:30",
  square_off: "15:10", entry_quote_s: 5 };
const RULE_NAMES: Record<string, string> = { orb15: "15-min opening range", orb30: "30-min opening range",
  vwap: "VWAP trend", relative: "Relative strength", pullback: "Pullback", gap_go: "Gap and go", gap_fade: "Gap fade",
  volume: "Volume breakout" };
const WHY: Record<string, string> = { stop: "Stop", target: "Target", "square-off": "Square-off" };
const POLL_MS = 20_000;
const STORE_KEY = "stockMomentumIndex";

const minus = (v: number) => (v < 0 ? "−" : "");
const inr = (v: number | null | undefined, signed = false) => {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const sign = signed ? (v > 0 ? "+" : minus(v)) : minus(v);
  const a = Math.abs(v);
  return `${sign}₹${a.toLocaleString("en-IN", { maximumFractionDigits: a < 1000 ? 2 : 0, minimumFractionDigits: a < 1000 && a % 1 ? 2 : 0 })}`;
};
const spct = (v: number | null | undefined, d = 2) =>
  v === null || v === undefined || Number.isNaN(v) ? "—" : `${v > 0 ? "+" : minus(v)}${Math.abs(v).toFixed(d)}%`;
const num = (v: number | null | undefined, d = 2) =>
  v === null || v === undefined || Number.isNaN(v) ? "—" : v.toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
const tone = (v: number | null | undefined) => (!v ? "" : v > 0 ? "gain" : "loss");
const istToday = () => new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
const istTime = (iso?: string) => (!iso ? "—" : new Date(iso).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata",
  hour: "2-digit", minute: "2-digit", hour12: false }));
const dayText = (iso?: string) => (!iso ? "—" : new Date(`${iso.slice(0, 10)}T12:00:00+05:30`).toLocaleDateString("en-IN",
  { timeZone: "Asia/Kolkata", day: "2-digit", month: "short" }));
const ruleName = (r: string) => RULE_NAMES[r] ?? r;
const sideText = (s: number) => (s === 1 ? "Long" : "Short");

function Scroll({ children }: { children: React.ReactNode }) {
  return <div className="smt-scroll">{children}</div>;
}

function Candidates({ title, side, board, today }: { title: string; side: number; board?: Board; today: string }) {
  const rows = (board?.rows ?? []).filter((c) => c.side === side).sort((a, b) => a.rank - b.rank);
  const fresh = board?.day === today;
  return (
    <section className="smt-card">
      <div className="smt-card-head">
        <b>{title}</b>
        <span>{rows.length ? `${rows.length} ranked${fresh ? "" : ` · ${dayText(board?.day)}`}` : "none"}</span>
      </div>
      {rows.length ? (
        <Scroll>
          <table className="smt-table">
            <thead>
              <tr><th>#</th><th className="l">Stock</th><th>Strength</th><th>Open move</th><th>vs Nifty</th>
                <th>vs sector</th><th>vs VWAP</th><th>Volume</th><th>Turnover</th></tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.symbol}>
                  <td>{c.rank}</td>
                  <td className="l"><b>{c.symbol}</b><div className="smt-sub">{c.sector}</div></td>
                  <td className="smt-num">{num(c.score)}</td>
                  <td className={`smt-num ${tone(c.change)}`}>{spct(c.change)}</td>
                  <td className={tone(c.market)}>{spct(c.market)}</td>
                  <td className={tone(c.relative)}>{spct(c.relative)}</td>
                  <td className={tone(c.vwap)}>{spct(c.vwap)}</td>
                  <td>{`${num(c.volume, 1)}×`}</td>
                  <td>{c.turnover ? `₹${num(c.turnover / 1e7, 1)} cr` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Scroll>
      ) : (
        <EmptyState title={board ? "No stock qualified" : "Waiting for the 09:30 scan"}
          note={board ? `A ${side === 1 ? "long" : "short"} candidate must lead on every measure: its open move, Nifty, its sector and VWAP, with ₹1 crore of opening turnover and above-normal volume.`
            : "The scan ranks the first 15 minutes of the session; the strongest ten each side appear here."} />
      )}
    </section>
  );
}

export default function StockMomentumDesk() {
  const [indices, setIndices] = useState(INDICES);
  const [index, setIndex] = useState("");
  const [desk, setDesk] = useState<Desk | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [period, setPeriod] = useState<"test" | "train">("test");
  const [side, setSide] = useState<"both" | "long" | "short">("both");
  const [mode, setMode] = useState<"ranked" | "all">("ranked");
  const today = istToday();

  // the universe: ?index= in the link, else the last one picked here, else the screener's default
  useEffect(() => {
    let pick = "";
    try {
      pick = new URLSearchParams(window.location.search).get("index") || window.localStorage.getItem(STORE_KEY) || "";
    } catch { /* storage blocked */ }
    fetchScreenerConfig()
      .then((c) => {
        if (c.indices?.length) setIndices(c.indices);
        setIndex((cur) => cur || (c.indices.some((x) => x.key === pick) ? pick : c.default_index));
      })
      .catch(() => setIndex((cur) => cur || (INDICES.some((x) => x.key === pick) ? pick : "nifty500")));
  }, []);
  const choose = (k: string) => {
    setIndex(k);
    setDesk(null);
    try {
      window.localStorage.setItem(STORE_KEY, k);
      const u = new URL(window.location.href);
      u.searchParams.set("index", k);
      window.history.replaceState(null, "", u.toString());
    } catch { /* no storage or URL */ }
  };

  const url = index ? `/api/screener/morning/${encodeURIComponent(index)}` : "";
  const load = useCallback(async () => {
    if (!url) return;
    try {
      const d = (await apiFetch(`${url}?fresh=true`)) as Desk;
      setDesk(d);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The desk could not be read.");
    }
  }, [url]);
  useEffect(() => {
    load();
    const t = setInterval(load, POLL_MS);
    return () => clearInterval(t);
  }, [load]);
  const refresh = async () => { setRefreshing(true); await load(); setRefreshing(false); };
  const send = async (what: string, body: Record<string, boolean | string>) => {
    setBusy(what);
    try {
      await apiFetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "The change was not saved.");
    } finally {
      setBusy(null);
    }
  };

  const L = desk?.limits ?? LIMITS;
  const board = desk?.board;
  const label = desk?.label ?? indices.find((x) => x.key === index)?.label ?? index;
  const open = desk?.positions ?? [];
  const closed = useMemo(() => [...(desk?.recent ?? [])].reverse(), [desk?.recent]);
  const closedToday = closed.filter((p) => (p.closed ?? "").slice(0, 10) === today);
  const net = closed.reduce((a, p) => a + (p.net ?? 0), 0);
  const netToday = closedToday.reduce((a, p) => a + (p.net ?? 0), 0);
  const wins = closed.filter((p) => (p.net ?? 0) > 0).length;
  const used = open.reduce((a, p) => a + p.qty * p.entry, 0);
  const atRisk = open.reduce((a, p) => a + Math.abs(p.entry - p.stop) * p.qty, 0);
  const longs = (board?.rows ?? []).filter((c) => c.side === 1).length;
  const shorts = (board?.rows ?? []).filter((c) => c.side === -1).length;
  const ranked = board?.day === today;
  const scanText = !desk ? "…" : !desk.scan ? "Paused" : ranked ? `Ranked at ${istTime(board?.processed)}` : "Waiting for 09:30";

  // what the module's own replay says, counted from the report (so it stays true if the report is re-run)
  const report = desk?.report;
  const verdict = useMemo(() => {
    if (!report) return null;
    const rows = report.rows.filter((r) => r.mode === "ranked" && r.side === "both");
    const rules = Array.from(new Set(rows.map((r) => r.rule)));
    const lost = rules.filter((k) => rows.filter((r) => r.rule === k).every((r) => r.trades > 0 && r.net_rs < 0));
    const test = rows.filter((r) => r.period === "test" && r.trades > 0);
    const pfs = test.map((r) => r.profit_factor ?? 0);
    const n = test.reduce((a, r) => a + r.trades, 0);
    const avg = n ? test.reduce((a, r) => a + (r.mean_net_pct ?? 0) * r.trades, 0) / n : null;
    const cov = report.coverage;
    if (!rules.length || !pfs.length) return null;
    // the rules that did not lose in both samples, with how many trades that rests on
    const rest = rules.filter((k) => !lost.includes(k)).map((k) => ({ rule: k,
      trades: rows.filter((r) => r.rule === k).reduce((a, r) => a + r.trades, 0),
      lostOne: rows.some((r) => r.rule === k && r.trades > 0 && r.net_rs < 0) }));
    return { rules: rules.length, lost: lost.length, lostSet: new Set(lost), rest, pfMin: Math.min(...pfs), pfMax: Math.max(...pfs), avg,
      sessions: cov.length, first: cov[0]?.[0], last: cov[cov.length - 1]?.[0], split: report.split };
  }, [report]);
  const review = (desk ? Object.keys(desk.rules) : []).map((k) => ({
    rule: k, text: desk!.rules[k], row: report?.rows.find((r) => r.rule === k && r.mode === mode && r.period === period && r.side === side),
  }));
  const approve = (k: string) => {
    if (!desk) return;
    const on = desk.approved.includes(k);
    if (!on) {
      const r = report?.rows.find((x) => x.rule === k && x.mode === "ranked" && x.period === "test" && x.side === "both");
      const lose = verdict?.lostSet.has(k);
      if (lose && !window.confirm(`${ruleName(k)} loses in its own replay${r ? ` (out of sample: ${r.trades} trades, ${inr(r.net_rs, true)}, profit factor ${num(r.profit_factor)})` : ""}.\n\nApprove it for the ${label} paper book anyway? Paper only: no real order is placed.`)) return;
    }
    send(`rule:${k}`, { strategy: k, approve: !on });
  };
  const audit = (desk?.failed?.length ?? 0) + (desk?.rejected?.length ?? 0);
  const excluded = Object.entries(board?.excluded ?? {});

  return (
    <div className="smt">
      <PageHeader
        crumb="Stock Momentum Trading"
        title="Stock Momentum Trading"
        subtitle="NSE stocks ranked at 09:30 on the session's first 15 minutes: opening move, strength against Nifty and the sector, VWAP, turnover and volume. A paper book trades the rules you approve on those candidates, until the 15:10 square-off, after Angel One costs."
        onRefresh={refresh}
        refreshing={refreshing}
      />

      <div className="smt-controls">
        <div className="smt-seg" role="tablist" aria-label="Universe">
          {indices.map((x) => (
            <button key={x.key} type="button" role="tab" aria-selected={index === x.key}
              className={`smt-seg-b${index === x.key ? " on" : ""}`} onClick={() => choose(x.key)}>{x.label}</button>
          ))}
        </div>
        {desk && (
          <div className="smt-pills">
            <StatusPill label={desk.scan ? "Scanner on" : "Scanner paused"} tone={desk.scan ? "gain" : "warn"} pulse={desk.scan && ranked} />
            <StatusPill label={desk.paper ? `Paper entries on · ${desk.approved.length} rule${desk.approved.length === 1 ? "" : "s"}` : "Paper entries off"}
              tone={desk.paper ? "accent" : "muted"} />
          </div>
        )}
      </div>

      {error && <ErrorBanner message={error} onRetry={load} />}

      {verdict && verdict.rules > 0 && (
        <div className="smt-warn" role="note">
          <b>{verdict.lost === verdict.rules ? "Every rule loses after costs in its own replay." : `${verdict.lost} of ${verdict.rules} rules lose after costs in their own replay.`}</b>{" "}
          {`Over ${verdict.sessions} sessions (${dayText(verdict.first)} to ${dayText(verdict.last)}), traded on the morning ranking, the out-of-sample part (from ${dayText(verdict.split)}) made a profit factor of ${num(verdict.pfMin)} to ${num(verdict.pfMax)} and ${spct(verdict.avg, 2)} a trade after Angel One costs.`}
          {verdict.rest.length ? ` ${verdict.rest.map((x) => `${ruleName(x.rule)} ${x.lostOne ? "lost in one sample" : "made money"} on ${x.trades} trade${x.trades === 1 ? "" : "s"} in all${x.trades < 30 ? ", too few to judge" : ""}.`).join(" ")}` : ""}
          {" Approving a rule runs it on paper only; it is not evidence that it works."}
        </div>
      )}

      {!desk ? (
        <div className="smt-card"><EmptyState title={error ? "The desk could not be read" : "Loading the desk…"} note={label ? `${label} book` : undefined} /></div>
      ) : (
        <>
          <section className="smt-card smt-ctl" aria-label="Desk controls">
            <div className="smt-ctl-row">
              <button type="button" role="switch" aria-checked={desk.scan} aria-label="Scanner"
                className={`smt-switch${desk.scan ? " on" : ""}`} disabled={!!busy} onClick={() => send("scan", { scan: !desk.scan })}>
                <span className="smt-knob" />
              </button>
              <div className="smt-ctl-text">
                <b>{busy === "scan" ? "Saving…" : desk.scan ? "Scanner: ON" : "Scanner: OFF"}</b>
                <span>{desk.scan ? `Ranks ${label} at 09:30 on every trading day (scanned again until 09:45 while stocks still lack their opening bars).` : "No 09:30 ranking; the last board stays on the page."}</span>
              </div>
            </div>
            <div className="smt-ctl-row">
              <button type="button" role="switch" aria-checked={desk.paper} aria-label="Paper entries"
                className={`smt-switch${desk.paper ? " on" : ""}`} disabled={!!busy} onClick={() => send("paper", { paper: !desk.paper })}>
                <span className="smt-knob" />
              </button>
              <div className="smt-ctl-text">
                <b>{busy === "paper" ? "Saving…" : desk.paper ? "Paper entries: ON" : "Paper entries: OFF"}</b>
                <span>{desk.paper
                  ? desk.approved.length ? `The approved rules (${desk.approved.map(ruleName).join(", ")}) open paper trades on the ranked candidates until ${L.entry_until} IST. OFF stops new entries; open positions still close at their stop, target or ${L.square_off}.`
                    : "On, but no rule is approved: approve one in the review below or nothing will trade."
                  : `Switch on to let the approved rules trade the ${label} paper book (${inr(L.book_rs)}).`}</span>
              </div>
            </div>
            <div className="smt-facts">
              <span>Book <b>{inr(L.book_rs)}</b></span>
              <span>Risk a trade <b>{inr(L.risk_rs)}</b></span>
              <span>At most <b>{inr(L.notional_rs)}</b> a trade, <b>{L.max_positions}</b> open</span>
              <span>Entries <b>09:30–{L.entry_until}</b> · square-off <b>{L.square_off} IST</b></span>
              <span>Paper only: <b>no real orders</b></span>
            </div>
          </section>

          <div className="smt-tiles">
            <div className="smt-tile"><span className="smt-k">Scan</span><span className="smt-v smt-v-sm">{scanText}</span>
              <span className="smt-s">{board?.day ? `last board ${dayText(board.day)}` : "first scan at 09:30 IST"}</span></div>
            <div className="smt-tile"><span className="smt-k">Usable data</span><span className="smt-v">{board ? `${board.usable} / ${board.total}` : "—"}</span>
              <span className="smt-s">{board ? `${excluded.length} without complete opening data` : "stocks with complete opening bars"}</span></div>
            <div className="smt-tile"><span className="smt-k">Candidates</span><span className="smt-v">{board ? `${longs} / ${shorts}` : "—"}</span>
              <span className="smt-s">long / short, ten at most a side</span></div>
            <div className="smt-tile"><span className="smt-k">Open positions</span><span className="smt-v">{`${open.length} / ${L.max_positions}`}</span>
              <span className="smt-s">{open.length ? `${inr(used)} in use · ${inr(atRisk)} at risk` : "none open"}</span></div>
            <div className="smt-tile"><span className="smt-k">Today, closed</span><span className={`smt-v ${tone(netToday)}`}>{closedToday.length ? inr(netToday, true) : "—"}</span>
              <span className="smt-s">{`${closedToday.length} trade${closedToday.length === 1 ? "" : "s"} today`}</span></div>
            <div className="smt-tile"><span className="smt-k">Paper P&amp;L</span><span className={`smt-v ${tone(net)}`}>{closed.length ? inr(net, true) : "—"}</span>
              <span className="smt-s">{closed.length ? `${closed.length} closed · ${Math.round((100 * wins) / closed.length)}% won · ${spct((100 * net) / L.book_rs)} of the book` : "no closed trade yet"}</span></div>
          </div>

          <div className="smt-grid2">
            <Candidates title="Long candidates" side={1} board={board} today={today} />
            <Candidates title="Short candidates" side={-1} board={board} today={today} />
          </div>

          <section className="smt-card">
            <div className="smt-card-head"><b>Paper positions</b><span>{open.length ? `${open.length} open` : "none open"}</span></div>
            {open.length ? (
              <Scroll>
                <table className="smt-table">
                  <thead><tr><th className="l">Stock</th><th className="l">Rule</th><th className="l">Side</th><th>Qty</th><th>Entry</th>
                    <th>Stop</th><th>Target</th><th>At risk</th><th>Opened</th></tr></thead>
                  <tbody>
                    {open.map((p) => (
                      <tr key={p.id ?? `${p.symbol}${p.rule}`}>
                        <td className="l"><b>{p.symbol}</b></td><td className="l">{ruleName(p.rule)}</td>
                        <td className="l"><span className={`smt-side ${p.side === 1 ? "long" : "short"}`}>{sideText(p.side)}</span></td>
                        <td>{p.qty}</td><td>{num(p.entry)}</td><td>{num(p.stop)}</td><td>{num(p.target)}</td>
                        <td>{inr(Math.abs(p.entry - p.stop) * p.qty)}</td><td>{istTime(p.opened)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Scroll>
            ) : (
              <EmptyState title="No open paper position"
                note={desk.paper ? (desk.approved.length ? "An approved rule opens one when a ranked candidate triggers it." : "Approve a rule below to let the book trade.") : "Paper entries are off."} />
            )}
          </section>

          {closed.length > 0 && (
            <section className="smt-card">
              <div className="smt-card-head"><b>Closed paper trades</b><span>{`latest ${Math.min(closed.length, 100)} · net ${inr(net, true)}`}</span></div>
              <Scroll>
                <table className="smt-table">
                  <thead><tr><th className="l">Day</th><th className="l">Stock</th><th className="l">Rule</th><th className="l">Side</th>
                    <th>Qty</th><th>Entry</th><th>Exit</th><th className="l">Closed by</th><th>Net</th></tr></thead>
                  <tbody>
                    {closed.map((p, i) => (
                      <tr key={`${p.id ?? p.symbol}-${i}`}>
                        <td className="l">{`${dayText(p.closed)} ${istTime(p.closed)}`}</td><td className="l"><b>{p.symbol}</b></td>
                        <td className="l">{ruleName(p.rule)}</td>
                        <td className="l"><span className={`smt-side ${p.side === 1 ? "long" : "short"}`}>{sideText(p.side)}</span></td>
                        <td>{p.qty}</td><td>{num(p.entry)}</td><td>{p.exit !== undefined ? num(p.exit) : "—"}</td>
                        <td className="l">{p.why ? WHY[p.why] ?? p.why : "—"}{p.basis && p.basis !== "quote" ? <div className="smt-sub">{p.basis}</div> : null}</td>
                        <td className={`smt-num ${tone(p.net)}`}>{inr(p.net, true)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Scroll>
            </section>
          )}

          <section className="smt-card">
            <div className="smt-card-head smt-card-head-wrap">
              <div><b>Strategy review</b><span className="smt-head-note">{`The module's replay: ${verdict?.sessions ?? 0} sessions, out of sample from ${dayText(report?.split)}. Approve the rules the paper book may trade.`}</span></div>
              <div className="smt-filters">
                <div className="smt-seg smt-seg-sm" role="radiogroup" aria-label="Sample">
                  {([["test", "Out of sample"], ["train", "In sample"]] as const).map(([k, t]) => (
                    <button key={k} type="button" role="radio" aria-checked={period === k} className={`smt-seg-b${period === k ? " on" : ""}`} onClick={() => setPeriod(k)}>{t}</button>
                  ))}
                </div>
                <div className="smt-seg smt-seg-sm" role="radiogroup" aria-label="Selection">
                  {([["ranked", "Morning ranked"], ["all", "Every signal"]] as const).map(([k, t]) => (
                    <button key={k} type="button" role="radio" aria-checked={mode === k} className={`smt-seg-b${mode === k ? " on" : ""}`} onClick={() => setMode(k)}>{t}</button>
                  ))}
                </div>
                <div className="smt-seg smt-seg-sm" role="radiogroup" aria-label="Direction">
                  {([["both", "Both"], ["long", "Long"], ["short", "Short"]] as const).map(([k, t]) => (
                    <button key={k} type="button" role="radio" aria-checked={side === k} className={`smt-seg-b${side === k ? " on" : ""}`} onClick={() => setSide(k)}>{t}</button>
                  ))}
                </div>
              </div>
            </div>
            <Scroll>
              <table className="smt-table smt-review">
                <thead><tr><th className="l">Rule</th><th>Trades</th><th>Win %</th><th>PF</th><th>Avg net</th><th>Net</th>
                  <th>Max drawdown</th><th>Failed exits</th><th className="l">Verdict</th><th className="l">Paper book</th></tr></thead>
                <tbody>
                  {review.map(({ rule, text, row }) => {
                    const on = desk.approved.includes(rule);
                    return (
                      <tr key={rule} className={on ? "smt-row-on" : ""}>
                        <td className="l smt-rule"><b>{ruleName(rule)}</b><div className="smt-sub">{text}</div></td>
                        <td>{row ? row.trades : "—"}</td>
                        <td>{row?.win_pct !== null && row?.win_pct !== undefined ? `${num(row.win_pct, 1)}%` : "—"}</td>
                        <td>{row?.profit_factor !== null && row?.profit_factor !== undefined ? num(row.profit_factor) : "—"}</td>
                        <td className={tone(row?.mean_net_pct)}>{row ? spct(row.mean_net_pct, 3) : "—"}</td>
                        <td className={`smt-num ${tone(row?.net_rs)}`}>{row ? inr(row.net_rs, true) : "—"}</td>
                        <td>{row ? inr(row.drawdown_rs) : "—"}</td>
                        <td>{row ? row.failed_exits : "—"}</td>
                        <td className="l">{!row || !row.trades ? <span className="smt-badge muted">no trades</span>
                          : row.net_rs < 0 ? <span className="smt-badge loss">loses</span>
                            : <span className="smt-badge warn">{row.trades < 30 ? "too few trades" : "earns here"}</span>}</td>
                        <td className="l">
                          <button type="button" className={`smt-btn${on ? " on" : ""}`} aria-pressed={on} disabled={!!busy} onClick={() => approve(rule)}>
                            {busy === `rule:${rule}` ? "Saving…" : on ? "Approved ✓" : "Approve"}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </Scroll>
            <p className="smt-foot">{desk.policy}</p>
          </section>

          <details className="smt-card smt-details">
            <summary>Execution gates <span>checked before every paper entry</span></summary>
            <ul className="smt-gates">
              <li><b>Data and trigger.</b> Completed five-minute bars of the session, a confirmed closing trigger, and a quote no older than {L.entry_quote_s} seconds.</li>
              <li><b>Liquidity and instrument.</b>{" "}₹1 crore of opening turnover, volume above the same interval of earlier sessions, and F&amp;O eligibility for a short.</li>
              <li><b>Risk and limits.</b> {inr(L.risk_rs)} at the stop, {inr(L.notional_rs)} at most a trade, {L.max_positions} positions at most, the margin left in the {inr(L.book_rs)} book, one entry a stock and rule a day.</li>
              <li><b>Exits.</b> Entry checks never block an exit: a stop or target is judged on a quote up to {L.exit_quote_s ?? 60} seconds old, the {L.square_off} square-off on any quote from the last {Math.round((L.late_quote_s ?? 900) / 60)} minutes, and failing that on the last stored five-minute close.</li>
            </ul>
          </details>

          {excluded.length > 0 && (
            <details className="smt-card smt-details">
              <summary>Data exclusions <span>{`${excluded.length} stock${excluded.length === 1 ? "" : "s"} not ranked ${dayText(board?.day)}`}</span></summary>
              <Scroll>
                <table className="smt-table">
                  <thead><tr><th className="l">Stock</th><th className="l">Reason</th></tr></thead>
                  <tbody>{excluded.map(([s, why]) => <tr key={s}><td className="l"><b>{s}</b></td><td className="l">{why}</td></tr>)}</tbody>
                </table>
              </Scroll>
            </details>
          )}

          {audit > 0 && (
            <details className="smt-card smt-details">
              <summary>Order audit <span>{`${audit} event${audit === 1 ? "" : "s"}`}</span></summary>
              {desk.failed?.length ? <p className="smt-audit">{`Missed the square-off on time: ${desk.failed.join(", ")}`}</p> : null}
              {desk.rejected?.length ? (
                <Scroll>
                  <table className="smt-table">
                    <thead><tr><th className="l">Stock</th><th className="l">Rule</th><th className="l">Why it was not entered</th></tr></thead>
                    <tbody>{desk.rejected.map((r, i) => <tr key={i}><td className="l"><b>{r[0]}</b></td><td className="l">{ruleName(r[1])}</td><td className="l">{(r[2] ?? "").replace(/_/g, " ")}</td></tr>)}</tbody>
                  </table>
                </Scroll>
              ) : null}
            </details>
          )}
        </>
      )}

      <style jsx global>{`
        .smt { display: flex; flex-direction: column; gap: 16px; padding-bottom: 40px; }
        .smt .gain { color: var(--gain); }
        .smt .loss { color: var(--loss); }
        .smt-controls { display: flex; justify-content: space-between; align-items: center; gap: 10px 12px; flex-wrap: wrap; }
        .smt-pills { display: flex; gap: 8px; flex-wrap: wrap; }
        .smt-seg { display: inline-flex; gap: 4px; background: var(--canvas-soft); padding: 4px; border-radius: 10px;
          border: 1px solid var(--panel-border); flex-wrap: wrap; }
        .smt-seg-b { border: 0; background: transparent; padding: 7px 14px; border-radius: 7px; font: inherit; font-size: 13px;
          font-weight: 600; color: var(--text-muted); cursor: pointer; white-space: nowrap; }
        .smt-seg-b.on { background: var(--panel); color: var(--text); box-shadow: var(--shadow-sm); }
        .smt-seg-b:focus-visible, .smt-btn:focus-visible, .smt-switch:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
        .smt-seg-sm .smt-seg-b { padding: 5px 10px; font-size: 12px; }
        .smt-warn { padding: 12px 16px; border-radius: 14px; font-size: 13px; line-height: 1.6; color: var(--text-secondary);
          background: var(--loss-dim); border: 1px solid rgba(var(--loss-rgb), 0.3); }
        .smt-warn b { color: var(--loss); }
        .smt-card { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 14px; box-shadow: var(--shadow-sm);
          min-width: 0; }
        .smt-card-head { display: flex; justify-content: space-between; align-items: baseline; gap: 6px 14px; padding: 14px 16px 10px;
          border-bottom: 1px solid var(--panel-border); flex-wrap: wrap; }
        .smt-card-head b { font-size: 14px; font-weight: 800; color: var(--text); }
        .smt-card-head > span, .smt-head-note { font-size: 12px; color: var(--text-muted); }
        .smt-card-head-wrap { align-items: center; }
        .smt-head-note { display: block; margin-top: 3px; max-width: 520px; line-height: 1.45; }
        .smt-filters { display: flex; gap: 8px; flex-wrap: wrap; }
        .smt-ctl { padding: 16px; display: flex; flex-direction: column; gap: 14px; }
        .smt-ctl-row { display: flex; align-items: center; gap: 14px; }
        .smt-ctl-text { display: flex; flex-direction: column; gap: 2px; font-size: 13px; line-height: 1.45; color: var(--text-muted); }
        .smt-ctl-text b { font-size: 14.5px; color: var(--text); }
        .smt-switch { position: relative; flex: 0 0 auto; width: 58px; height: 32px; border-radius: 999px; padding: 0; border: 0;
          background: var(--text-faint); cursor: pointer; transition: background 0.15s; }
        .smt-switch.on { background: var(--gain-solid); }
        .smt-switch:disabled { opacity: 0.55; cursor: default; }
        .smt-knob { position: absolute; top: 4px; left: 4px; width: 24px; height: 24px; border-radius: 50%; background: var(--on-accent);
          box-shadow: var(--shadow-sm); transition: left 0.15s; }
        .smt-switch.on .smt-knob { left: 30px; }
        .smt-facts { display: flex; flex-wrap: wrap; gap: 6px 18px; padding-top: 12px; border-top: 1px solid var(--panel-border);
          font-size: 12.5px; color: var(--text-muted); }
        .smt-facts b { color: var(--text); font-variant-numeric: tabular-nums; }
        .smt-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; }
        .smt-tile { display: flex; flex-direction: column; gap: 4px; padding: 14px 16px; border-radius: 14px; background: var(--panel);
          border: 1px solid var(--panel-border); min-width: 0; }
        .smt-k { font-size: 10.5px; font-weight: 800; letter-spacing: 0.06em; text-transform: uppercase; color: var(--text-faint); }
        .smt-v { font-family: var(--font-data); font-size: 22px; font-weight: 700; color: var(--text); font-variant-numeric: tabular-nums; }
        .smt-v-sm { font-size: 17px; }
        .smt-v.gain { color: var(--gain); }
        .smt-v.loss { color: var(--loss); }
        .smt-s { font-size: 12px; color: var(--text-muted); }
        /* side by side only when both nine-column tables fit whole (about 1,600 px wide screens) */
        .smt-grid2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 680px), 1fr)); gap: 14px; }
        .smt-scroll { overflow-x: auto; }
        .smt-table { width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums; }
        .smt-table th { font-size: 10.5px; font-weight: 800; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-faint);
          text-align: right; padding: 10px 12px; border-bottom: 1px solid var(--panel-border); white-space: nowrap; background: var(--panel); }
        .smt-table td { text-align: right; padding: 9px 12px; border-bottom: 1px solid var(--border-soft, var(--panel-border));
          white-space: nowrap; vertical-align: top; color: var(--text); }
        .smt-table tbody tr:last-child td { border-bottom: 0; }
        .smt-table tbody tr:hover td { background: var(--panel-tint, var(--canvas-soft)); }
        .smt-table .l { text-align: left; }
        .smt-table td.gain { color: var(--gain); }
        .smt-table td.loss { color: var(--loss); }
        .smt-num { font-family: var(--font-data); font-weight: 700; }
        .smt-sub { font-size: 11.5px; font-weight: 400; color: var(--text-muted); line-height: 1.45; margin-top: 2px; white-space: normal; }
        .smt-review td.smt-rule { min-width: 220px; max-width: 360px; white-space: normal; }
        .smt-row-on td { background: var(--brand-dim); }
        .smt-row-on td:first-child { box-shadow: inset 3px 0 0 var(--brand); }
        .smt-side { display: inline-block; font-size: 11px; font-weight: 800; padding: 2px 8px; border-radius: 6px; }
        .smt-side.long { background: var(--gain-dim); color: var(--gain); }
        .smt-side.short { background: var(--loss-dim); color: var(--loss); }
        .smt-badge { display: inline-block; font-size: 11px; font-weight: 800; padding: 2px 9px; border-radius: 999px; white-space: nowrap; }
        .smt-badge.loss { background: var(--loss-dim); color: var(--loss); }
        .smt-badge.warn { background: var(--warn-dim); color: var(--warn); }
        .smt-badge.muted { background: var(--canvas-soft); color: var(--text-muted); border: 1px solid var(--panel-border); }
        .smt-btn { font: inherit; font-size: 12px; font-weight: 700; padding: 6px 12px; border-radius: 8px; cursor: pointer; white-space: nowrap;
          border: 1px solid var(--panel-border); background: var(--panel); color: var(--text); }
        .smt-btn:hover:not(:disabled) { border-color: var(--brand); color: var(--brand); }
        .smt-btn.on { background: var(--brand); border-color: var(--brand); color: var(--on-brand); }
        .smt-btn:disabled { opacity: 0.55; cursor: default; }
        .smt-foot { margin: 0; padding: 10px 16px 14px; font-size: 12px; line-height: 1.55; color: var(--text-muted);
          border-top: 1px solid var(--panel-border); }
        .smt-details > summary { cursor: pointer; padding: 13px 16px; font-size: 13px; font-weight: 800; color: var(--text);
          display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
        .smt-details > summary span { font-weight: 500; color: var(--text-faint); font-size: 12px; }
        .smt-details[open] > summary { border-bottom: 1px solid var(--panel-border); }
        .smt-gates { margin: 0; padding: 12px 16px 14px 32px; display: flex; flex-direction: column; gap: 6px; font-size: 12.5px;
          line-height: 1.55; color: var(--text-secondary); }
        .smt-gates b { color: var(--text); }
        .smt-audit { margin: 12px 16px; padding: 8px 12px; border-radius: 8px; font-size: 12.5px; color: var(--loss); background: var(--loss-dim); }
        @media (max-width: 640px) {
          .smt-tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; } .smt-tile { padding: 12px; }
          .smt-v { font-size: 19px; } .smt-v-sm { font-size: 15px; } .smt-ctl { padding: 14px; }
          .smt-seg-b { padding: 6px 10px; }
        }
      `}</style>
    </div>
  );
}
