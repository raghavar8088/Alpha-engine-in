"use client";

// The Premium Strategies paper desk: one Rs 10 lakh account per strategy. The desk runs in its own container
// (premium-paper-service) and this page only reads its records from /api/premium-paper.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import { apiFetch } from "../../lib/api";
import { ago, day, inr, istTime, pct, price, rupees, tone } from "./format";
import { RankNote, RankTd, RankTh, rankOnClient, sortByRank } from "../../components/StrategyRank";
import { ACCOUNT_RANK_NOTE, PREMIUM_RANK_FACTORS, accountRankRow } from "./rank";

export type MarketPnl = { market: string; trades: number; pnl: number };
export type Account = {
  id: string; source: string; name: string; channel: string; markets: string[]; variants: string[]; capital: number; equity: number;
  realised: number; unrealised: number; return_pct: number; closed: number; open: number; wins: number; win_rate: number | null;
  profit_factor: number | null; max_dd_pct: number; today_pnl: number; skipped: Record<string, number>; by_market: MarketPnl[];
  last_trade_t: number | null; updated_at: string;
};
type Position = { sym: string; mkt: string; side: number; qty: number; entry: number; stop: number | null; target: number | null;
  last: number | null; pnl: number; entry_t: number; setup: string };
type Detail = Account & { positions: Position[]; curve: [string, number][] };
type Trade = { id: string; sym: string; mkt: string; side: number; setup: string; date: string; entry_t: number; exit_t: number | null;
  entry: number; exit: number | null; reason: string; open: boolean; last: number | null; qty?: number; pnl?: number; skip?: string | null; sealed: boolean };
type GroupStatus = { at: string; ok: boolean; seconds: number; error: string | null };
export type Summary = { accounts: Account[]; status: { paper_start?: string; btc_start?: string; capital?: number; groups?: Record<string, GroupStatus> }; configured: boolean };

const POLL_MS = 60000;
const REASON: Record<string, string> = { stop: "Stop", stop_gap: "Stop (gap)", be_stop: "Breakeven stop", target: "Target", time: "Session end",
  exit_signal: "Exit signal", vwap_trail: "VWAP trail", open: "Open", trail_stop: "Trailing stop", flip: "Trend flip",
  tp_close: "Take-profit close", next_open: "Next open" };
const GROUP_LABEL: Record<string, string> = { index: "Nifty and Bank Nifty", stocks: "NSE stocks", global: "Bitcoin and gold (Delta), forex, Nasdaq, Apple", daily: "Daily markets" };
export const SOURCE_LABEL: Record<string, string> = { vwap: "VWAP study", booming_bulls: "Booming Bulls", youtube_top20: "YouTube top 20", crypto_playlist: "Crypto playlist", liquidity_sweep: "Liquidity sweep", sniper_headshot: "Sniper headshot" };
SOURCE_LABEL.youtube_channels11 = "11 YouTube channels";
SOURCE_LABEL.youtube_channels20 = "20 YouTube channels";
SOURCE_LABEL.youtube_shortlist = "Channel shortlist";

/** The accounts, kept fresh for the whole page. An empty desk and an unreachable desk must not look the same. */
export function usePaperSummary() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setSummary(await apiFetch("/api/premium-paper/summary"));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not read the paper desk.");
    }
  }, []);
  useEffect(() => {
    load();
    const t = setInterval(load, POLL_MS);
    return () => clearInterval(t);
  }, [load]);
  return { summary, error };
}

function EquityCurve({ curve, capital }: { curve: [string, number][]; capital: number }) {
  const [hover, setHover] = useState<number | null>(null);
  const pts = curve;
  if (pts.length < 2) return <p className="ps-foot">The equity curve appears after trades have closed on at least two days.</p>;
  const W = 640, H = 170, L = 72, R = 12, T = 12, B = 22;
  const vals = pts.map((p) => p[1]);
  const lo = Math.min(capital, ...vals), hi = Math.max(capital, ...vals);
  const span = hi - lo || 1;
  const X = (i: number) => L + (i / (pts.length - 1)) * (W - L - R);
  const Y = (y: number) => T + (1 - (y - lo) / span) * (H - T - B);
  const path = pts.map((p, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(p[1]).toFixed(1)}`).join("");
  const pick = (clientX: number, el: SVGSVGElement) => {
    const r = el.getBoundingClientRect();
    const px = ((clientX - r.left) / r.width) * W;
    setHover(Math.max(0, Math.min(pts.length - 1, Math.round(((px - L) / (W - L - R)) * (pts.length - 1)))));
  };
  const h = hover;
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="ps-curve-svg" role="img"
        aria-label={`Equity from ${rupees(capital)} to ${rupees(vals[vals.length - 1])} between ${day(pts[0][0])} and ${day(pts[pts.length - 1][0])}`}
        onMouseMove={(e) => pick(e.clientX, e.currentTarget)} onMouseLeave={() => setHover(null)}>
        <line x1={L} x2={W - R} y1={Y(capital)} y2={Y(capital)} className="ps-zero" />
        <text x={L - 6} y={Y(hi) + 3} textAnchor="end" className="ps-tick">{rupees(hi)}</text>
        <text x={L - 6} y={Y(lo) + 3} textAnchor="end" className="ps-tick">{rupees(lo)}</text>
        <path d={path} className="ps-line" />
        {h != null && (
          <>
            <line x1={X(h)} x2={X(h)} y1={T} y2={H - B} className="ps-cross" />
            <circle cx={X(h)} cy={Y(pts[h][1])} r={4} className="ps-dot" />
          </>
        )}
        <text x={L} y={H - 6} className="ps-tick">{day(pts[0][0])}</text>
        <text x={W - R} y={H - 6} textAnchor="end" className="ps-tick">{day(pts[pts.length - 1][0])}</text>
      </svg>
      <div className="ps-curve-tip">
        {h != null ? (<><b>{day(pts[h][0])}</b>: {rupees(pts[h][1])}, {pct(100 * (pts[h][1] / capital - 1))} since the start</>) : <span className="ps-faint">Hover the line for any day</span>}
      </div>
    </div>
  );
}

function AccountDetail({ a }: { a: Account }) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [more, setMore] = useState(false);
  const stamp = a.updated_at;
  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const [d, t] = await Promise.all([
          apiFetch(`/api/premium-paper/accounts/${encodeURIComponent(a.id)}`),
          apiFetch(`/api/premium-paper/accounts/${encodeURIComponent(a.id)}/trades?limit=100`),
        ]);
        if (live) {
          setDetail(d);
          setTrades(t.trades);
          setTotal(t.total);
          setError(null);
        }
      } catch (e) {
        if (live) setError(e instanceof Error ? e.message : "Could not read this account.");
      }
    })();
    return () => { live = false; };
  }, [a.id, stamp]);
  const loadMore = async () => {
    setMore(true);
    try {
      const t = await apiFetch(`/api/premium-paper/accounts/${encodeURIComponent(a.id)}/trades?limit=200&offset=${trades.length}`);
      setTrades((x) => [...x, ...t.trades]);
      setTotal(t.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not read more trades.");
    } finally {
      setMore(false);
    }
  };
  if (error) return <p className="ps-foot ps-neg">{error}</p>;
  if (!detail) return <p className="ps-foot">Loading this account…</p>;
  const skipped = Object.entries(a.skipped || {});
  return (
    <div className="pd-detail">
      <div className="pd-detail-grid">
        <div className="pd-detail-curve">
          <h4>Equity, after costs</h4>
          <EquityCurve curve={detail.curve} capital={a.capital} />
        </div>
        <div>
          <h4>P&amp;L by market</h4>
          <table className="ps-table">
            <thead><tr><th>Market</th><th>Trades</th><th>P&amp;L</th></tr></thead>
            <tbody>
              {a.by_market.length === 0 && <tr><td colSpan={3} className="ps-faint">No trades yet on {a.markets.join(", ")}.</td></tr>}
              {a.by_market.map((m) => (
                <tr key={m.market}><td className="ps-name">{m.market}</td><td>{m.trades}</td><td className={tone(m.pnl)}>{inr(m.pnl)}</td></tr>
              ))}
            </tbody>
          </table>
          {skipped.length > 0 && (
            <p className="ps-foot">Signals this account could not size: {skipped.map(([k, n]) => `${n} (${k})`).join(", ")}.</p>
          )}
        </div>
      </div>
      {detail.positions.length > 0 && (
        <>
          <h4>Open positions</h4>
          <div className="ps-scroll">
            <table className="ps-table">
              <thead><tr><th>Instrument</th><th>Market</th><th>Side</th><th>Qty</th><th>Entered</th><th>Entry</th><th>Stop</th><th>Target</th><th>Last</th><th>P&amp;L</th></tr></thead>
              <tbody>
                {detail.positions.map((p) => (
                  <tr key={`${p.sym}-${p.entry_t}`}>
                    <td className="ps-name">{p.sym}</td><td>{p.mkt}</td><td>{p.side > 0 ? "Long" : "Short"}</td><td>{p.qty}</td><td>{istTime(p.entry_t)}</td>
                    <td>{price(p.entry)}</td><td>{price(p.stop)}</td><td>{price(p.target)}</td><td>{price(p.last)}</td><td className={tone(p.pnl)}>{inr(p.pnl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      <h4>Trades ({total})</h4>
      {trades.length === 0 ? <p className="ps-foot">No trades yet.</p> : (
        <div className="ps-scroll ps-tall">
          <table className="ps-table">
            <thead><tr><th>Entered (IST)</th><th>Instrument</th><th>Side</th><th>Qty</th><th>Entry</th><th>Exit</th><th>Left (IST)</th><th>Why</th><th>Net P&amp;L</th></tr></thead>
            <tbody>
              {trades.map((t) => (
                <tr key={t.id} className={t.skip ? "pd-skip" : ""}>
                  <td>{istTime(t.entry_t)}</td><td className="ps-name">{t.sym}</td><td>{t.side > 0 ? "Long" : "Short"}</td>
                  <td>{t.skip ? "—" : t.qty}</td><td>{price(t.entry)}</td><td>{t.open ? price(t.last) : price(t.exit)}</td>
                  <td>{t.open ? "—" : istTime(t.exit_t)}</td>
                  <td>{t.skip ? `Skipped: ${t.skip}` : `${REASON[t.reason] ?? t.reason}${t.sealed || t.open ? "" : " (provisional)"}`}</td>
                  <td className={t.skip ? "" : tone(t.pnl)}>{t.skip ? "—" : inr(t.pnl ?? 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {trades.length < total && (
        <button className="ps-chip pd-more" onClick={loadMore} disabled={more}>{more ? "Loading…" : `Show more (${total - trades.length} left)`}</button>
      )}
    </div>
  );
}

export default function PaperDesk({ summary, error }: { summary: Summary | null; error: string | null }) {
  const [source, setSource] = useState("all");
  const [openId, setOpenId] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30000);
    return () => clearInterval(t);
  }, []);

  const detailRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (openId) detailRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [openId]);

  const accounts = useMemo(() => summary?.accounts ?? [], [summary]);
  const selected = accounts.find((a) => a.id === openId) ?? null;
  const counts = useMemo(() => {
    const c: Record<string, number> = { all: accounts.length };
    accounts.forEach((a) => { c[a.source] = (c[a.source] ?? 0) + 1; });
    return c;
  }, [accounts]);
  const rows = useMemo(() => accounts.filter((a) => source === "all" || a.source === source)
    .sort((a, b) => b.return_pct - a.return_pct || a.id.localeCompare(b.id, "en", { numeric: true })), [accounts, source]);
  // Ranked among the accounts shown (the source chip picks the board), on the desk's account figures (rank.ts).
  const board = useMemo(() => rankOnClient(rows.map(accountRankRow), PREMIUM_RANK_FACTORS,
    { desk: `premium-${source}`, basisNote: ACCOUNT_RANK_NOTE }), [rows, source]);
  const ranked = useMemo(() => sortByRank(rows, board, (a) => a.id), [rows, board]);
  const start = summary?.status?.paper_start;
  const traded = accounts.filter((a) => a.closed + a.open > 0);
  const green = traded.filter((a) => a.equity > a.capital).length;
  const red = traded.filter((a) => a.equity < a.capital).length;
  const closed = accounts.reduce((s, a) => s + a.closed, 0);
  const openPos = accounts.reduce((s, a) => s + a.open, 0);
  const today = new Date(now + 19800000).toISOString().slice(0, 10);
  const groups = summary?.status?.groups ?? {};

  if (error && !summary) {
    return <GlassPanel title="Paper trading"><p className="ps-foot ps-neg">Could not read the paper desk: {error}</p></GlassPanel>;
  }
  if (!summary) return <GlassPanel title="Paper trading"><p className="ps-foot">Loading the accounts…</p></GlassPanel>;
  if (!accounts.length) {
    return (
      <GlassPanel title="Paper trading">
        <p className="ps-foot">The paper desk has not written its accounts yet. It creates all of them, at ₹10,00,000 each, when its service starts.</p>
      </GlassPanel>
    );
  }
  return (
    <>
      {start && today < start && (
        <div className="ps-banner pd-wait" role="status">
          <span className="ps-pill ps-pill-neutral">Starts {day(start)}</span>
          <span>
            Forward paper trading begins on {day(start)} 2026
            {summary?.status?.btc_start ? `; the bitcoin strategies, which trade all week, started on ${istTime(Date.parse(summary.status.btc_start) / 1000)} IST` : ""}.
            {" "}Every other account holds its ₹10,00,000 until then; nothing is back-filled, so each result will come only from days no test has seen.
          </span>
        </div>
      )}
      <div className="pd-tiles">
        <div className="pd-tile"><span className="ps-stat-label">Accounts</span><span className="pd-tile-val">{accounts.length}</span><span className="pd-tile-sub">₹10,00,000 each</span></div>
        <div className="pd-tile"><span className="ps-stat-label">In profit / in loss</span><span className="pd-tile-val">{green} / {red}</span><span className="pd-tile-sub">of {traded.length} that have traded</span></div>
        <div className="pd-tile"><span className="ps-stat-label">Trades closed</span><span className="pd-tile-val">{closed.toLocaleString("en-US")}</span><span className="pd-tile-sub">after all costs</span></div>
        <div className="pd-tile"><span className="ps-stat-label">Open positions</span><span className="pd-tile-val">{openPos}</span><span className="pd-tile-sub">marked to the last bar</span></div>
      </div>

      {selected && (
        <div ref={detailRef} className="pd-selected">
          <GlassPanel title={`${selected.id} ${selected.name}`} note={selected.channel}>
            <button className="ps-chip pd-close" onClick={() => setOpenId(null)}>Close</button>
            <AccountDetail a={selected} />
          </GlassPanel>
        </div>
      )}

      <GlassPanel title="Every strategy's account" note="ranked · click a row for its trades · click a heading to sort">
        <div className="ps-chips">
          {["all", "youtube_shortlist", "vwap", "booming_bulls", "youtube_top20", "crypto_playlist", "sniper_headshot", "youtube_channels11", "youtube_channels20", "liquidity_sweep"].map((k) => (
            <button key={k} className={`ps-chip${source === k ? " on" : ""}`} onClick={() => setSource(k)}>
              {k === "all" ? "All" : SOURCE_LABEL[k]} · {counts[k] ?? 0}
            </button>
          ))}
        </div>
        <RankNote board={board} />
        <div className="ps-scroll">
          <table className="ps-table pd-table">
            <thead>
              <tr><RankTh /><th>Strategy</th><th>Markets</th><th>Equity</th><th>P&amp;L</th><th>Return</th><th>Today</th><th>Trades</th><th>Win rate</th><th>Max drawdown</th><th>Open</th></tr>
            </thead>
            <tbody>
              {ranked.flatMap((a) => {
                const pnl = a.equity - a.capital;
                const isOpen = openId === a.id;
                return [
                  <tr key={a.id} className={`pd-row${isOpen ? " on" : ""}`} onClick={() => setOpenId(isOpen ? null : a.id)}>
                    <RankTd board={board} id={a.id} />
                    <td>
                      <button className="pd-name" aria-expanded={isOpen} onClick={(e) => { e.stopPropagation(); setOpenId(isOpen ? null : a.id); }}>
                        <span className="pd-id">{a.id}</span> {a.name}
                      </button>
                      <div className="pd-sub">{a.channel}</div>
                    </td>
                    <td className="pd-mkts">{a.markets.join(", ")}</td>
                    <td>{rupees(a.equity)}</td>
                    <td className={tone(pnl)}>{inr(pnl)}</td>
                    <td className={`ps-strong ${tone(a.return_pct)}`}>{pct(a.return_pct)}</td>
                    <td className={tone(a.today_pnl)}>{a.today_pnl ? inr(a.today_pnl) : "—"}</td>
                    <td>{a.closed + a.open}</td>
                    <td>{a.win_rate == null ? "—" : `${a.win_rate.toFixed(1)}%`}</td>
                    <td>{a.closed ? `${a.max_dd_pct.toFixed(1)}%` : "—"}</td>
                    <td>{a.open || "—"}</td>
                  </tr>,
                ];
              })}
            </tbody>
          </table>
        </div>
        <p className="ps-foot">
          Today&apos;s figures are provisional until the session&apos;s bars are final; trades are then sealed and never rewritten. Dollar markets are converted to rupees at the entry date&apos;s rate.
        </p>
      </GlassPanel>

      <GlassPanel title="Feed status">
        <div className="pd-feeds">
          {Object.entries(GROUP_LABEL).map(([k, label]) => {
            const g = groups[k];
            return (
              <div key={k} className="pd-feed">
                <span className="pd-feed-name">{label}</span>
                <span className={g && !g.ok ? "ps-neg" : "ps-faint"}>{!g ? "not run yet" : g.ok ? `checked ${ago(g.at, now)}` : `last check failed ${ago(g.at, now)}`}</span>
              </div>
            );
          })}
        </div>
      </GlassPanel>
    </>
  );
}
