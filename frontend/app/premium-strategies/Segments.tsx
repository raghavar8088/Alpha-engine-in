"use client";

// The paper desk by market: Indian Market (Options & F&O, Equity intraday, Equity daily), Crypto, Gold, and Forex & US.
// premium-paper-service/segments.py writes, after every desk cycle, each feed's source, last real bar and state, each
// book's state with the reason, and each segment's totals, latest trades and open positions; this view only reads them
// from /api/premium-paper/summary. Paper only: live prices feed simulated trades and nothing here can place an order.
import { useEffect, useMemo, useRef, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import { apiFetch } from "../../lib/api";
import { ago, day, inr, istTime, pct, price, rupees, tone } from "./format";
import { SOURCE_LABEL, type Account, type Summary } from "./PaperDesk";
import { RankNote, RankTd, RankTh, rankOnClient, sortByRank } from "../../components/StrategyRank";
import { BOOK_RANK_NOTE, PREMIUM_RANK_FACTORS, bookRankRow } from "./rank";
import { DAYS_NOTE, dailyFigures, startOf, tradingDays, type StartStatus } from "./tradingDays";

type Feed = {
  source?: string; instrument?: string; last_t?: number | null; last_price?: number | null; last_session?: string;
  state: string; reason: string; checked_at?: string; fetch_error?: string | null;
};
type BookRow = {
  mkt: string; market: string; segment: string; feed: string; state: string; reason: string; trades: number; closed: number;
  wins: number; pnl: number; open: number; unrealised: number; skipped: number; open_since: number | null;
};
type SegTrade = {
  acct: string; mkt: string; market: string; sym: string; side: number; setup: string; entry_t: number; exit_t: number | null;
  entry: number | null; exit: number | null; last: number | null; stop: number | null; target: number | null; qty: number;
  pnl: number; reason: string; sealed?: boolean;
};
type SegTotals = {
  books: number; trades: number; closed: number; wins: number; pnl: number; open: number; unrealised: number;
  states: Record<string, number>; recent: SegTrade[]; positions: SegTrade[];
};
type Recorder = { connected: boolean; since?: number | null; last_msg_t?: number | null; written_to?: number | null; error?: string | null; at?: number };
type SegStatus = Summary["status"] & {
  feeds?: Record<string, Feed>; recorder?: Recorder; books?: Record<string, BookRow[]>; segments?: Record<string, SegTotals>;
  segments_at?: string; sh_start?: string;
};
type AcctTrade = {
  id: string; sym: string; mkt: string; side: number; setup: string; entry_t: number; exit_t: number | null; entry: number;
  exit: number | null; reason: string; open: boolean; last: number | null; qty?: number; pnl?: number; skip?: string | null; sealed: boolean;
};

export type MarketTab = "indian" | "crypto" | "gold" | "global";
export type SegId = "in_options" | "in_equity" | "in_equity_daily" | "crypto" | "gold" | "global";
/** Where each segment sits on the page (Indian Market has three sub-tabs), for the links from the 20-channel tab. */
export const SEG_PLACE: Record<SegId, { tab: MarketTab; label: string }> = {
  in_options: { tab: "indian", label: "Indian Market › Options & F&O" },
  in_equity: { tab: "indian", label: "Indian Market › Equity intraday" },
  in_equity_daily: { tab: "indian", label: "Indian Market › Equity daily" },
  crypto: { tab: "crypto", label: "Crypto" },
  gold: { tab: "gold", label: "Gold" },
  global: { tab: "global", label: "Forex & US" },
};
/** Opens a market tab on one sub-tab with one study's strategies shown, and optionally one book's trades
 *  (`acct|mkt`). `at` makes every click a fresh open. */
export type SegFocus = { seg: SegId; study: string; book?: string; at: number };
/** The study chips' order: the 20-channel study (its own tab) first; a study not listed here follows, by name. */
const STUDY_ORDER = ["youtube_shortlist", "youtube_channels20", "youtube_channels11", "youtube_top20", "booming_bulls", "crypto_playlist", "sniper_headshot",
  "vwap", "liquidity_sweep"];
const studyLabel = (s: string) => (s === "youtube_shortlist" ? "Channel shortlist (new)" : s === "youtube_channels20" ? "20 channels" : SOURCE_LABEL[s] ?? s);

const SEG: Record<SegId, { label: string; feeds: string[]; note: string }> = {
  in_options: {
    label: "Options & F&O",
    feeds: ["NIFTY", "BANKNIFTY", "NIFTY_D"],
    note: "Nifty and Bank Nifty strategies on 1-minute index bars, priced as one index-futures lot (Nifty 65, Bank Nifty 30) with Angel One's futures charges. None of them buys or sells option premiums yet.",
  },
  in_equity: {
    label: "Equity intraday",
    feeds: ["NSE"],
    note: "NSE stocks on 5- and 15-minute bars with NSE intraday charges and slippage. Every position closes by the end of the session.",
  },
  in_equity_daily: {
    label: "Equity daily",
    feeds: ["NSED"],
    note: "NSE stocks on daily bars from NSE's bhavcopy, held for days, with delivery charges.",
  },
  crypto: {
    label: "Crypto",
    feeds: ["BTCUSD", "ETHUSD"],
    note: "Bitcoin from Delta Exchange India: the BTCUSD perpetual's 1-minute candles, read every 2 minutes, with Delta's taker fee (0.05% plus 18% GST a side), half a $1 spread and 2 bp of slippage. The order-flow strategies (CP-14, CP-15) also need Delta's live trade feed, recorded minute by minute. Ether (Delta ETHUSD, 0.01 contracts) is NJ-33's comparison market and DR-04's own market.",
  },
  gold: {
    label: "Gold",
    feeds: ["XAUUSD", "XAGUSD"],
    note: "Gold from Delta Exchange India: the XAUTUSD perpetual (Tether Gold, one token per troy ounce), read every 2 minutes, with Delta's fee (0.01% plus 18% GST a side), a $0.02 half spread and $0.10 of slippage. XAUTUSD trades every day, but these strategies follow the gold market's week, as they were tested: nothing trades from Friday 17:00 to Sunday 17:00 New York. Silver (Yahoo) is only CP-24's comparison market.",
  },
  global: {
    label: "Forex & US",
    feeds: ["EURUSD", "GBPUSD", "NAS100", "AAPL", "SPX500_D", "NAS100_D"],
    note: "EUR/USD, GBP/USD, the Nasdaq 100 and Apple on 1-minute bars from Yahoo Finance (read every 9 minutes), and the S&P 500 and Nasdaq 100 on daily bars.",
  },
};
const MARKET_SEGS: Record<MarketTab, SegId[]> = { indian: ["in_options", "in_equity", "in_equity_daily"], crypto: ["crypto"], gold: ["gold"], global: ["global"] };
const FEED_NAME: Record<string, string> = {
  NIFTY: "Nifty 50", BANKNIFTY: "Nifty Bank", NIFTY_D: "Nifty 50 daily", NSE: "NSE stocks", NSED: "NSE stocks daily", BTCUSD: "Bitcoin", ETHUSD: "Ether",
  XAUUSD: "Gold", XAGUSD: "Silver", EURUSD: "EUR/USD", GBPUSD: "GBP/USD", NAS100: "Nasdaq 100", AAPL: "Apple",
  SPX500_D: "S&P 500 daily", NAS100_D: "Nasdaq 100 daily",
};
const STATE: Record<string, { label: string; cls: string; rank: number }> = {
  "in trade": { label: "In a trade", cls: "trade", rank: 0 },
  live: { label: "Live", cls: "live", rank: 1 },
  running: { label: "Running", cls: "live", rank: 1 },
  armed: { label: "Armed", cls: "idle", rank: 2 },
  waiting: { label: "Waiting", cls: "idle", rank: 2 },
  closed: { label: "Market closed", cls: "idle", rank: 3 },
  stale: { label: "Stale data", cls: "bad", rank: 4 },
  "no data": { label: "No data", cls: "bad", rank: 5 },
  error: { label: "Error", cls: "bad", rank: 6 },
};
const REASON: Record<string, string> = { stop: "Stop", stop_gap: "Stop (gap)", be_stop: "Breakeven stop", target: "Target", time: "Session end",
  exit_signal: "Exit signal", vwap_trail: "VWAP trail", open: "Open" };
const STALE_DESK_MIN = 15;
const ACTIVE = ["live", "running", "in trade"];

function Pill({ state }: { state: string }) {
  const s = STATE[state] ?? { label: state, cls: "idle" };
  return <span className={`sg-pill ${s.cls}`}>{s.label}</span>;
}

function age(t: number | null | undefined, now: number): string {
  if (!t) return "";
  const m = Math.max(0, Math.round((now / 1000 - t) / 60));
  if (m < 1) return "under a minute ago";
  if (m < 90) return `${m} min ago`;
  const h = Math.round(m / 60);
  return h < 48 ? `${h} h ago` : `${Math.round(h / 24)} days ago`;
}

function FeedCard({ id, f, now }: { id: string; f: Feed | undefined; now: number }) {
  if (!f) {
    return (
      <div className="sg-feed">
        <div className="sg-feed-top"><span className="sg-feed-name">{FEED_NAME[id] ?? id}</span><Pill state="no data" /></div>
        <p className="sg-feed-why">The desk has not reported this feed yet; it does after the feed&apos;s next cycle.</p>
      </div>
    );
  }
  const daily = !!f.last_session || id.endsWith("_D") || id === "NSED";
  return (
    <div className="sg-feed">
      <div className="sg-feed-top"><span className="sg-feed-name">{FEED_NAME[id] ?? id}</span><Pill state={f.state} /></div>
      <div className="sg-feed-src">{f.source}{f.instrument ? ` · ${f.instrument}` : ""}</div>
      <div className="sg-feed-nums">
        {f.last_price != null && <span><b>{price(f.last_price)}</b></span>}
        {daily ? (
          <span>{f.last_session ? `last daily bar ${day(f.last_session)}` : "no daily bar yet"}</span>
        ) : (
          <span>{f.last_t ? <>last bar {istTime(f.last_t)} IST · <b>{age(f.last_t, now)}</b></> : "no bar received"}</span>
        )}
      </div>
      {!(f.state === "live" && f.reason.startsWith("Last bar")) && <p className="sg-feed-why">{f.reason}</p>}
      {f.checked_at && <div className="sg-feed-chk">checked {ago(f.checked_at, now)}</div>}
    </div>
  );
}

function RecorderCard({ r, now }: { r: Recorder | undefined; now: number }) {
  const up = !!r?.connected && !!r.at && now / 1000 - r.at < 120;
  return (
    <div className="sg-feed">
      <div className="sg-feed-top"><span className="sg-feed-name">Delta trade feed</span><span className={`sg-pill ${up ? "live" : "bad"}`}>{up ? "Connected" : "Not connected"}</span></div>
      <div className="sg-feed-src">wss://socket.india.delta.exchange · all_trades BTCUSD (who was the taker in each trade)</div>
      <div className="sg-feed-nums">
        <span>{r?.since ? `recording whole minutes since ${istTime(r.since)} IST` : "not recording"}</span>
        {r?.last_msg_t ? <span>last message {age(r.last_msg_t, now)}</span> : null}
      </div>
      <p className="sg-feed-why">
        {up ? "CP-14 and CP-15 read each minute's taker buying and selling from here. Minutes it did not see whole are left unknown, never guessed."
          : `CP-14 and CP-15 cannot trade minutes this feed did not record.${r?.error ? ` Last error: ${r.error}` : ""}`}
      </p>
    </div>
  );
}

function BookTrades({ acct, mkt, positions }: { acct: string; mkt: string; positions: SegTrade[] }) {
  const [rows, setRows] = useState<AcctTrade[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    apiFetch(`/api/premium-paper/accounts/${encodeURIComponent(acct)}/trades?limit=500`)
      .then((t) => { if (live) { setRows((t.trades as AcctTrade[]).filter((x) => x.mkt === mkt)); setErr(null); } })
      .catch((e) => { if (live) setErr(e instanceof Error ? e.message : "Could not read the trades."); });
    return () => { live = false; };
  }, [acct, mkt]);
  const open = positions.filter((p) => p.acct === acct && p.mkt === mkt);
  if (err) return <p className="ps-foot ps-neg">{err}</p>;
  if (!rows) return <p className="ps-foot">Loading this book&apos;s trades…</p>;
  return (
    <div className="sg-book-detail">
      {open.length > 0 && <TradeTable rows={open} open />}
      {rows.length === 0 ? <p className="ps-foot">No trades on this market yet.</p> : (
        <div className="ps-scroll ps-tall">
          <table className="ps-table">
            <thead><tr><th>Entered (IST)</th><th>Instrument</th><th>Side</th><th>Qty</th><th>Entry</th><th>Exit</th><th>Left (IST)</th><th>Why</th><th>Net P&amp;L</th></tr></thead>
            <tbody>
              {rows.map((t) => (
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
    </div>
  );
}

function TradeTable({ rows, open }: { rows: SegTrade[]; open?: boolean }) {
  return (
    <div className="ps-scroll">
      <table className="ps-table">
        <thead>
          <tr>
            <th>Strategy</th><th>Instrument</th><th>Side</th><th>Qty</th><th>Entered (IST)</th><th>Entry</th>
            {open ? <><th>Stop</th><th>Target</th><th>Last</th></> : <><th>Exit</th><th>Left (IST)</th><th>Why</th></>}
            <th>{open ? "Open P&L" : "Net P&L"}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((t) => (
            <tr key={`${t.acct}-${t.mkt}-${t.sym}-${t.entry_t}-${t.side}`}>
              <td className="ps-name">{t.acct}</td><td>{t.sym === t.mkt ? t.market : t.sym}</td><td>{t.side > 0 ? "Long" : "Short"}</td><td>{t.qty}</td>
              <td>{istTime(t.entry_t)}</td><td>{price(t.entry)}</td>
              {open ? <><td>{price(t.stop)}</td><td>{price(t.target)}</td><td>{price(t.last)}</td></>
                : <><td>{price(t.exit)}</td><td>{istTime(t.exit_t)}</td><td>{`${REASON[t.reason] ?? t.reason}${t.sealed ? "" : " (provisional)"}`}</td></>}
              <td className={tone(t.pnl)}>{inr(t.pnl ?? 0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** One study's share of a segment, in the shape the desk writes for the whole segment. */
function totalsOf(rows: { b: BookRow }[], positions: SegTrade[], recent: SegTrade[]): SegTotals {
  const t: SegTotals = { books: rows.length, trades: 0, closed: 0, wins: 0, pnl: 0, open: 0, unrealised: 0, states: {}, recent, positions };
  rows.forEach(({ b }) => {
    t.trades += b.trades;
    t.closed += b.closed;
    t.wins += b.wins;
    t.pnl += b.pnl;
    t.open += b.open;
    t.unrealised += b.unrealised;
    t.states[b.state] = (t.states[b.state] ?? 0) + 1;
  });
  return t;
}

function SegmentView({ seg, summary, now, study, setStudy, initialOpen }: {
  seg: SegId; summary: Summary; now: number; study: string; setStudy: (s: string) => void; initialOpen?: string | null;
}) {
  const status = summary.status as SegStatus;
  const def = SEG[seg];
  const segTot = status.segments?.[seg];
  const [filter, setFilter] = useState<"all" | "active" | "idle">("all");
  const [openKey, setOpenKey] = useState<string | null>(initialOpen ?? null);
  // The book's trades open in a panel above the table, never as an extra table row: the app's SortableTables
  // reorders every row of a tbody, which would carry a detail row away from its strategy.
  const detailRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (openKey) detailRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [openKey]);
  const byId = useMemo(() => {
    const m: Record<string, Account> = {};
    summary.accounts.forEach((a) => { m[a.id] = a; });
    return m;
  }, [summary]);
  const rows = useMemo(() => {
    const out: { acct: Account | undefined; id: string; b: BookRow }[] = [];
    Object.entries(status.books ?? {}).forEach(([id, bs]) => bs.forEach((b) => { if (b.segment === seg) out.push({ acct: byId[id], id, b }); }));
    return out.sort((x, y) => (STATE[x.b.state]?.rank ?? 9) - (STATE[y.b.state]?.rank ?? 9) || y.b.pnl - x.b.pnl
      || x.id.localeCompare(y.id, "en", { numeric: true }));
  }, [status.books, seg, byId]);
  // The tab's own board: every strategy's book in this segment, ranked on its trades here (rank.ts).
  const board = useMemo(() => rankOnClient(
    rows.map(({ acct, id, b }) => bookRankRow(`${id}|${b.mkt}`, b, acct, (status.books?.[id]?.length ?? 0) === 1)),
    PREMIUM_RANK_FACTORS, { desk: `premium-${seg}`, basisNote: BOOK_RANK_NOTE }), [rows, status.books, seg]);
  // The study filter: which study (its own tab, or a section of the Strategies tab) each strategy comes from. The board
  // above stays the whole market's, so a filtered row keeps its Rank among every strategy here.
  const studies = useMemo(() => {
    const n: Record<string, number> = {};
    rows.forEach((r) => { const s = r.acct?.source ?? "other"; n[s] = (n[s] ?? 0) + 1; });
    return n;
  }, [rows]);
  const studyKeys = ["all", ...STUDY_ORDER.filter((s) => studies[s] || s === study),
    ...Object.keys(studies).filter((s) => !STUDY_ORDER.includes(s)).sort(),
    ...(study !== "all" && !STUDY_ORDER.includes(study) && !studies[study] ? [study] : [])];
  const inStudy = useMemo(() => (study === "all" ? rows : rows.filter((r) => (r.acct?.source ?? "other") === study)), [rows, study]);
  const tot = useMemo(() => {
    if (study === "all" || !segTot) return segTot;
    const mine = (t: SegTrade) => byId[t.acct]?.source === study;
    return totalsOf(inStudy, (segTot.positions ?? []).filter(mine), (segTot.recent ?? []).filter(mine));
  }, [study, segTot, inStudy, byId]);
  const shown = sortByRank(inStudy.filter((r) => filter === "all" || (filter === "active" ? ACTIVE.includes(r.b.state) : !ACTIVE.includes(r.b.state))),
    board, (r) => `${r.id}|${r.b.mkt}`);
  const active = inStudy.filter((r) => ACTIVE.includes(r.b.state)).length;
  const btcStart = status.btc_start ? Date.parse(status.btc_start) / 1000 : null;
  const shStart = status.sh_start ? Date.parse(status.sh_start) / 1000 : null;
  const paperStart = status.paper_start;
  const today = new Date(now + 19800000).toISOString().slice(0, 10);
  const pnl = (tot?.pnl ?? 0);
  const winRate = tot && tot.closed ? (100 * tot.wins) / tot.closed : null;
  const states = Object.entries(tot?.states ?? {}).sort((a, b) => (STATE[a[0]]?.rank ?? 9) - (STATE[b[0]]?.rank ?? 9));
  const opened = rows.find((r) => `${r.id}|${r.b.mkt}` === openKey) ?? null;

  return (
    <div className="sg-seg">
      <p className="sg-note">{def.note}</p>
      {seg === "crypto" && btcStart ? (
        <div className="ps-banner pd-wait" role="status">
          <span className="ps-pill ps-pill-neutral">Since {istTime(btcStart)} IST</span>
          <span>{`The bitcoin strategies trade forward from ${istTime(btcStart)} IST on Delta Exchange's live candles; nothing before that is back-filled. The daily Fear & Greed book (CP-29) starts with the others${paperStart ? ` on ${day(paperStart)}` : ""}.${shStart ? ` The Sniper-headshot books (SH-00 to SH-04) start at ${istTime(shStart)} IST, also flat and with nothing back-filled.` : ""}`}</span>
        </div>
      ) : paperStart && today < paperStart ? (
        <div className="ps-banner pd-wait" role="status">
          <span className="ps-pill ps-pill-neutral">Starts {day(paperStart)}</span>
          <span>These strategies start paper trading on {day(paperStart)}; until then each holds its ₹10,00,000 and nothing is back-filled.</span>
        </div>
      ) : null}

      <GlassPanel title="Market data" note="where each price comes from, and how fresh it is">
        <div className="sg-feeds">
          {def.feeds.map((f) => <FeedCard key={f} id={f} f={status.feeds?.[f]} now={now} />)}
          {seg === "crypto" && <RecorderCard r={status.recorder} now={now} />}
        </div>
        <p className="ps-foot">
          A feed is <b>stale</b> when no new bar has arrived for a while; its strategies then stop instead of trading on old prices, and nothing is ever substituted for a missing price.
          Paper only: these prices drive simulated trades, and no order is ever sent to a broker or an exchange.
        </p>
      </GlassPanel>

      <div className="ps-chips sg-studies" role="group" aria-label="Study">
        <span className="sg-chiplabel">Study</span>
        {studyKeys.map((k) => (
          <button key={k} className={`ps-chip${study === k ? " on" : ""}`} aria-pressed={study === k} onClick={() => setStudy(k)}>
            {k === "all" ? `All studies · ${rows.length}` : `${studyLabel(k)} · ${studies[k] ?? 0}`}
          </button>
        ))}
      </div>

      <div className="pd-tiles">
        <div className="pd-tile"><span className="ps-stat-label">Strategies</span><span className="pd-tile-val">{tot?.books ?? inStudy.length}</span><span className="pd-tile-sub">{active} live or in a trade now</span></div>
        <div className="pd-tile"><span className="ps-stat-label">P&amp;L, after costs</span><span className={`pd-tile-val ${tone(pnl)}`}>{inr(pnl)}</span><span className="pd-tile-sub">closed {inr((tot?.pnl ?? 0) - (tot?.unrealised ?? 0))} · open {inr(tot?.unrealised ?? 0)}</span></div>
        <div className="pd-tile"><span className="ps-stat-label">Trades closed</span><span className="pd-tile-val">{(tot?.closed ?? 0).toLocaleString("en-US")}</span><span className="pd-tile-sub">{winRate == null ? "no closed trade yet" : `${winRate.toFixed(1)}% won`}</span></div>
        <div className="pd-tile"><span className="ps-stat-label">Open positions</span><span className="pd-tile-val">{tot?.open ?? 0}</span><span className="pd-tile-sub">marked to the last bar</span></div>
      </div>

      {opened && (
        <div ref={detailRef} className="pd-selected">
          <GlassPanel title={`${opened.id} ${opened.acct?.name ?? ""} · ${opened.b.market}`} note={opened.acct?.channel ?? ""}>
            <button className="ps-chip pd-close" onClick={() => setOpenKey(null)}>Close</button>
            <div className="sg-open-state"><Pill state={opened.b.state} /><span>{opened.b.reason}</span></div>
            <BookTrades acct={opened.id} mkt={opened.b.mkt} positions={segTot?.positions ?? []} />
          </GlassPanel>
        </div>
      )}

      <GlassPanel title="Strategies" note="ranked · click a row for its trades">
        <div className="ps-chips">
          {(["all", "active", "idle"] as const).map((k) => (
            <button key={k} className={`ps-chip${filter === k ? " on" : ""}`} onClick={() => setFilter(k)}>
              {k === "all" ? `All · ${inStudy.length}` : k === "active" ? `Live or in a trade · ${active}` : `Not trading now · ${inStudy.length - active}`}
            </button>
          ))}
          <span className="sg-states">{states.map(([s, n]) => `${n} ${(STATE[s]?.label ?? s).toLowerCase()}`).join(" · ")}</span>
        </div>
        {inStudy.length === 0 ? (
          <p className="ps-foot">{study === "all" ? "No strategy trades this market." : `No strategy from ${studyLabel(study)} trades this market.`}</p>
        ) : (<>
          <RankNote board={board} />
          {study !== "all" && (
            <p className="ps-foot">{`Showing ${inStudy.length === 1 ? "the one strategy" : `the ${inStudy.length} strategies`} from ${studyLabel(study)}; each Rank is its place among all ${rows.length} strategies of this market.`}</p>
          )}
          <div className="ps-scroll">
            <table className="ps-table sg-table">
              <thead><tr><RankTh /><th>Strategy</th><th>Market</th><th>Status</th><th>Trades</th><th>Win rate</th><th>P&amp;L</th><th title="The strategy's own paper account">Capital</th><th title="Net P&L after all costs, closed and open, as a share of the capital">Total return</th><th title="Market trading days since the strategy started, today included, whether or not it traded">Trading days</th><th title="Total return divided by the trading days (arithmetic, not compounded)">Avg daily return</th><th title="Net P&L divided by the trading days">Avg daily profit</th><th>Open</th></tr></thead>
              <tbody>
                {shown.map(({ acct, id, b }) => {
                  const key = `${id}|${b.mkt}`;
                  const isOpen = openKey === key;
                  return (
                    <tr key={key} className={`pd-row${isOpen ? " on" : ""}`} onClick={() => setOpenKey(isOpen ? null : key)}>
                      <RankTd board={board} id={key} />
                      <td>
                        <button className="pd-name" aria-expanded={isOpen} onClick={(e) => { e.stopPropagation(); setOpenKey(isOpen ? null : key); }}>
                          <span className="pd-id">{id}</span> {acct?.name ?? ""}
                        </button>
                        <div className="pd-sub">{[acct?.channel, acct ? studyLabel(acct.source) : null].filter(Boolean).join(" · ")}</div>
                      </td>
                      <td className="pd-mkts">{b.market}</td>
                      <td className="sg-status"><Pill state={b.state} /><div className="sg-why">{b.reason}</div></td>
                      <td>{b.closed + b.open}{b.skipped ? <div className="pd-sub">{b.skipped} not sized</div> : null}</td>
                      <td>{b.closed ? `${((100 * b.wins) / b.closed).toFixed(1)}%` : "—"}</td>
                      <td className={tone(b.pnl)}>{b.trades ? inr(b.pnl) : "—"}</td>
                      {(() => {
                        // this book alone: its market's calendar from its own start; capital is the account's
                        const cap = acct?.capital || null;
                        const days = acct ? tradingDays([{ start: startOf(acct.source, id, b.market, status as StartStatus), market: b.market }], now) : null;
                        const f = dailyFigures(b.pnl, cap, days);
                        return (<>
                          <td>{cap ? rupees(cap) : "N/A"}</td>
                          <td className={tone(f.ret)}>{f.ret == null ? "N/A" : pct(f.ret, 3)}</td>
                          <td>{days ?? "N/A"}</td>
                          <td className={tone(f.avgPct)}>{f.avgPct == null ? "N/A" : pct(f.avgPct, 3)}</td>
                          <td className={tone(f.avgRs)}>{f.avgRs == null ? "N/A" : inr(f.avgRs)}</td>
                        </>);
                      })()}
                      <td>{b.open || "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="ps-foot">{DAYS_NOTE} A strategy that trades several markets shows each market's share of its account here; its whole account is on the All accounts tab.</p>
        </>)}
      </GlassPanel>

      <GlassPanel title={`Open positions (${tot?.positions.length ?? 0})`}>
        {tot && tot.positions.length ? <TradeTable rows={tot.positions} open /> : <p className="ps-foot">No open position.</p>}
      </GlassPanel>

      <GlassPanel title="Latest closed trades" note={study === "all" ? "the newest 40" : `${studyLabel(study)}, among the market's newest 40`}>
        {tot && tot.recent.length ? <TradeTable rows={tot.recent} /> : (
          <p className="ps-foot">{study === "all" ? "No closed trade yet." : "None of the market's newest 40 closed trades is from this study."}</p>
        )}
        <p className="ps-foot">Today&apos;s trades are provisional until the session&apos;s bars are final; they are then sealed and never rewritten. Dollar markets are converted to rupees at the entry date&apos;s rate.</p>
      </GlassPanel>
    </div>
  );
}

export default function Segments({ market, summary, error, focus }: {
  market: MarketTab; summary: Summary | null; error: string | null; focus?: SegFocus | null;
}) {
  const segs = MARKET_SEGS[market];
  const [sub, setSub] = useState<SegId>(focus && segs.includes(focus.seg) ? focus.seg : segs[0]);
  // The study filter holds across Indian Market's sub-tabs, so a study opened from its own tab stays shown.
  const [study, setStudy] = useState<string>(focus?.study ?? "all");
  // A book opened from a link shows its trades once, on its own sub-tab; switching sub-tabs drops it.
  const [pendingBook, setPendingBook] = useState<string | null>(focus?.book ?? null);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30000);
    return () => clearInterval(t);
  }, []);
  const seg = segs.includes(sub) ? sub : segs[0];

  if (error && !summary) return <GlassPanel title="Paper trading"><p className="ps-foot ps-neg">Could not read the paper desk: {error}</p></GlassPanel>;
  if (!summary) return <GlassPanel title="Paper trading"><p className="ps-foot">Loading the desk…</p></GlassPanel>;
  const status = summary.status as SegStatus;
  const at = status.segments_at;
  const srcOf: Record<string, string> = {};
  summary.accounts.forEach((a) => { srcOf[a.id] = a.source; });
  // A sub-tab's count follows the study filter, so it says how many rows that sub-tab will show.
  const countIn = (s: SegId) => (study === "all" ? status.segments?.[s]?.books ?? 0
    : Object.entries(status.books ?? {}).reduce((n, [id, bs]) => n + (srcOf[id] === study ? bs.filter((b) => b.segment === s).length : 0), 0));
  const deskMin = at ? Math.round((now - Date.parse(at)) / 60000) : null;
  return (
    <>
      {segs.length > 1 && (
        <div className="sg-subtabs" role="tablist">
          {segs.map((s) => (
            <button key={s} role="tab" aria-selected={seg === s} className={`sg-subtab${seg === s ? " on" : ""}`}
              onClick={() => { setSub(s); setPendingBook(null); }}>
              {SEG[s].label}<span className="sg-count">{countIn(s)}</span>
            </button>
          ))}
        </div>
      )}
      {!at ? (
        <GlassPanel title={SEG[seg].label}>
          <p className="ps-foot">The desk has not written its market status yet. It does at the end of its next cycle (every 2 minutes for crypto and gold).</p>
        </GlassPanel>
      ) : (
        <>
          {deskMin != null && deskMin > STALE_DESK_MIN && (
            <div className="ps-banner" role="alert">
              <span className="ps-pill ps-pill-warn">Desk not updating</span>
              <span>The desk last wrote its status {ago(at, now)}. The figures below are from then; trading resumes when the desk runs again.</span>
            </div>
          )}
          {error && <p className="ps-foot ps-neg">The last refresh failed ({error}); showing the previous figures.</p>}
          <SegmentView key={seg} seg={seg} summary={summary} now={now} study={study} setStudy={setStudy} initialOpen={pendingBook} />
        </>
      )}
      <style jsx global>{`
        .sg-seg { display: flex; flex-direction: column; gap: 16px; }
        .sg-note { margin: 0; font-size: 13px; line-height: 1.6; color: var(--text-muted); max-width: 980px; }
        .sg-subtabs { display: flex; flex-wrap: wrap; gap: 8px; }
        .sg-subtab { display: inline-flex; align-items: center; gap: 8px; background: var(--canvas-soft); border: 1px solid var(--panel-border);
                     color: var(--text-muted); padding: 7px 14px; border-radius: 999px; font-size: 12.5px; font-weight: 700; cursor: pointer; }
        .sg-subtab:hover { color: var(--text); }
        .sg-subtab.on { color: var(--purple); border-color: var(--purple); background: var(--purple-dim); }
        .sg-count { font-size: 11px; font-weight: 800; padding: 1px 7px; border-radius: 999px; background: var(--panel); color: var(--text-muted);
                    border: 1px solid var(--panel-border); font-variant-numeric: tabular-nums; }
        .sg-feeds { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; }
        .sg-feed { display: flex; flex-direction: column; gap: 5px; padding: 12px 14px; border-radius: 12px; background: var(--canvas-soft);
                   border: 1px solid var(--panel-border); min-width: 0; }
        .sg-feed-top { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
        .sg-feed-name { font-size: 14px; font-weight: 800; color: var(--text); }
        .sg-feed-src { font-size: 11.5px; color: var(--text-faint); line-height: 1.45; overflow-wrap: anywhere; }
        .sg-feed-nums { display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: 12.5px; color: var(--text-muted); font-variant-numeric: tabular-nums; }
        .sg-feed-nums b { color: var(--text); }
        .sg-feed-why { margin: 0; font-size: 12px; line-height: 1.5; color: var(--text-muted); }
        .sg-feed-chk { font-size: 11px; color: var(--text-faint); }
        .sg-pill { display: inline-block; padding: 3px 9px; border-radius: 999px; font-size: 11px; font-weight: 800; white-space: nowrap; }
        .sg-pill.live { background: var(--gain-dim); color: var(--gain); }
        .sg-pill.trade { background: var(--purple-dim); color: var(--purple); }
        .sg-pill.idle { background: var(--panel); color: var(--text-muted); border: 1px solid var(--panel-border); }
        .sg-pill.bad { background: var(--loss-dim); color: var(--loss); }
        .sg-states { align-self: center; font-size: 12px; color: var(--text-faint); }
        .sg-studies { align-items: center; }
        .sg-chiplabel { font-size: 11px; font-weight: 800; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-faint); margin-right: 2px; }
        .sg-table td { vertical-align: top; }
        .sg-table th:nth-child(2), .sg-table th:nth-child(3) { text-align: left; }
        .sg-status { text-align: left !important; white-space: normal !important; min-width: 240px; max-width: 420px; }
        .sg-why { margin-top: 4px; font-size: 11.5px; line-height: 1.45; color: var(--text-muted); }
        .sg-open-state { display: flex; align-items: flex-start; gap: 10px; font-size: 12.5px; line-height: 1.5; color: var(--text-muted); margin-bottom: 10px; }
        .sg-book-detail { display: flex; flex-direction: column; gap: 10px; padding: 4px 0; }
        @media (max-width: 640px) {
          .sg-status { min-width: 200px; }
        }
      `}</style>
    </>
  );
}
