"use client";

import { useCallback, useEffect, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import DeskHistory from "../../components/DeskHistory";
import PageHeader from "../../components/PageHeader";
import ErrorBanner from "../../components/ErrorBanner";
import LineChart from "../../components/charts/LineChart";
import {
  refreshing,
  IntradayDay,
  IntradayDeskStatus,
  IntradayEquityPoint,
  IntradayPosition,
  IntradayScore,
  IntradayTrade,
  LiveIntradaySummary,
  fetchIntradayDaily,
  fetchIntradayEquity,
  fetchIntradayLeaderboard,
  fetchIntradayStatus,
  fetchIntradayTrades,
  fetchLiveIntradayLeaderboard,
  fetchLiveIntradayPositions,
  fetchLiveIntradaySummary,
  fetchLiveIntradayTrades,
  fetchLiveIntradayDaily,
  fetchIntradayLabDaily,
  type DailyRoi,
} from "../../lib/api";

// The three live books are TABS rather than a dropdown because they are separate
// accounts, not a filter: switching replaces every number on the page.
type IntradayTab = "tournament" | "80k" | "30k" | "10k";
const LIVE_BOOKS: { key: "80k" | "30k" | "10k"; capital: number }[] = [
  { key: "80k", capital: 80000 },
  { key: "30k", capital: 30000 },
  { key: "10k", capital: 10000 },
];

// Signed, because a return of "0.42%" and "-0.42%" must not look alike at a glance.
// Distinct from the file's existing `pct`, which formats an already-scaled percentage.
const roiPct = (v: number | null | undefined, dp = 2) =>
  `${(v ?? 0) >= 0 ? "+" : ""}${(v ?? 0).toFixed(dp)}%`;

/** Realised P&L per session, net of Angel One costs, expressed against desk capital. */
function DailyRoiPanel({ rows, capital }: { rows: DailyRoi[]; capital: number }) {
  return (
    <GlassPanel title={`Daily ROI — on ₹${capital.toLocaleString("en-IN")} desk capital`}>
      {rows.length === 0 ? (
        <div className="empty">No closed sessions yet.</div>
      ) : (
        <div className="table-scroll">
          <table className="data-table">
            <thead><tr><th style={{ textAlign: "left" }}>Date</th><th>Trades</th><th>Win %</th><th>Gross P&amp;L</th><th>Angel fees</th><th>Net P&amp;L</th><th>ROI</th></tr></thead>
            <tbody>
              {rows.map((d) => (
                <tr key={d.date}>
                  <td style={{ textAlign: "left" }}>{d.date}</td>
                  <td>{d.trades}</td>
                  <td>{(d.win_rate * 100).toFixed(1)}%</td>
                  <td className={d.gross_pnl >= 0 ? "gain" : "loss"}>{d.gross_pnl >= 0 ? "+" : ""}₹{inr(d.gross_pnl)}</td>
                  <td className="loss">−₹{inr(d.fees)}</td>
                  <td className={d.realized_pnl >= 0 ? "gain" : "loss"}>{d.realized_pnl >= 0 ? "+" : ""}₹{inr(d.realized_pnl)}</td>
                  <td className={d.roi_pct >= 0 ? "gain" : "loss"}>{roiPct(d.roi_pct, 3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </GlassPanel>
  );
}

const REFRESH_MS = 15000;

const inr = (v: number | null | undefined) =>
  v === null || v === undefined ? "-" : v.toLocaleString("en-IN", { maximumFractionDigits: 0 });
const inr2 = (v: number | null | undefined) =>
  v === null || v === undefined ? "-" : v.toLocaleString("en-IN", { maximumFractionDigits: 2 });
const pct = (v: number | null | undefined, d = 1) =>
  v === null || v === undefined ? "-" : `${v.toFixed(d)}%`;

/** How each price was sourced. Angel is the desk's primary equity feed; a Dhan or
 *  last-bar mark is the honest fallback and is labelled so the page never implies a
 *  live Angel print when the number came from somewhere else. */
function SourcePill({ source }: { source: string | null | undefined }) {
  const label =
    source === "angel_quote" ? "ANGEL" :
    source === "dhan_quote" ? "DHAN" :
    source === "last_bar_close" ? "LAST BAR" : (source ?? "-");
  const cls = source === "angel_quote" ? "src angel" : source === "dhan_quote" ? "src dhan" : "src stale";
  return <span className={cls}>{label}</span>;
}

export default function IntradayStocksPage() {
  const [tab, setTab] = useState<IntradayTab>("tournament");
  const [status, setStatus] = useState<IntradayDeskStatus | null>(null);
  const [scores, setScores] = useState<IntradayScore[]>([]);
  const [trades, setTrades] = useState<IntradayTrade[]>([]);
  const [equity, setEquity] = useState<IntradayEquityPoint[]>([]);
  const [days, setDays] = useState<IntradayDay[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Live Intraday desk (curated ₹80k shortlist)
  const [liveSummary, setLiveSummary] = useState<LiveIntradaySummary | null>(null);
  const [liveScores, setLiveScores] = useState<IntradayScore[]>([]);
  const [livePositions, setLivePositions] = useState<IntradayPosition[]>([]);
  const [liveTrades, setLiveTrades] = useState<IntradayTrade[]>([]);
  const [liveDaily, setLiveDaily] = useState<DailyRoi[]>([]);
  const [labDaily, setLabDaily] = useState<DailyRoi[]>([]);
  const liveBook = tab === "tournament" ? "80k" : tab;
  const isLive = tab !== "tournament";
  const bookCapital = LIVE_BOOKS.find((b) => b.key === liveBook)?.capital ?? 80000;

  const load = useCallback(async () => {
    try {
      const [s, l, t, e, d] = await Promise.all([
        fetchIntradayStatus(),
        fetchIntradayLeaderboard(),
        fetchIntradayTrades(100),
        fetchIntradayEquity(500),
        fetchIntradayDaily(60),
      ]);
      setStatus(s);
      setScores(l);
      setTrades(t);
      setEquity(e);
      setDays(d);
      setLabDaily(await fetchIntradayLabDaily(60));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load the intraday desk");
    }
  }, []);

  const [isRefreshing, setIsRefreshing] = useState(false);
  const handleRefresh = useCallback(async () => {
    setIsRefreshing(true);
    try {
      await refreshing(() => load());
    } finally {
      setIsRefreshing(false);
    }
  }, [load]);

  const loadLive = useCallback(async () => {
    try {
      const [lb, pos, tr, dl] = await Promise.all([
        fetchLiveIntradayLeaderboard(liveBook),
        fetchLiveIntradayPositions(liveBook),
        fetchLiveIntradayTrades(100, liveBook),
        fetchLiveIntradayDaily(liveBook),
      ]);
      setLiveScores(lb);
      setLivePositions(pos.positions);
      setLiveSummary(pos.summary);
      setLiveTrades(tr);
      setLiveDaily(dl);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load the Live Intraday desk");
    }
  }, [liveBook]);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  useEffect(() => {
    if (!isLive) return;
    loadLive();
    const id = setInterval(loadLive, REFRESH_MS);
    return () => clearInterval(id);
  }, [tab, loadLive]);

  const heartbeatAge = status?.heartbeat
    ? (Date.now() - new Date(status.heartbeat).getTime()) / 1000
    : null;
  // The scheduler ticks every ~3 min, so a heartbeat under ~4.5 min old means live.
  const live = Boolean(status?.heartbeat && heartbeatAge !== null && heartbeatAge < 270);
  const todayPnl = days[0]?.net_pnl ?? 0;
  const totalPnl = status?.realized_pnl ?? 0;
  const winners = scores.filter((s) => s.net_pnl > 0).length;
  const feedLabel =
    status?.feed_source === "angel" ? "Angel One (live)" :
    status?.feed_source === "dhan" ? "Dhan (fallback)" : "no live feed";

  return (
    <div className="page">
      <PageHeader
        onRefresh={handleRefresh}
        refreshing={isRefreshing}
        crumb="Intraday Stocks"
        title="Intraday Stocks"
        subtitle="Paper strategy-selection tournament: auto-trades 150 intraday NSE-equity strategies on live Angel One prices. Each strategy runs its own independent ₹10 lakh account (₹15 cr across the desk) and takes a uniform ₹10 lakh per position, so the leaderboard ranks timing edge, not bet size. Long-only cash equities; scalping/momentum/mean-reversion styles square off at 15:15 IST, swing styles may carry a few days."
      />

      <div className="tabs">
        <button className={tab === "tournament" ? "tab active" : "tab"} onClick={() => setTab("tournament")}>
          Tournament · 150 strategies
        </button>
        {LIVE_BOOKS.map((b) => (
          <button
            key={b.key}
            className={tab === b.key ? "tab active" : "tab"}
            onClick={() => setTab(b.key)}
          >
            Live Intraday · ₹{b.key}
          </button>
        ))}
      </div>

      {error && <ErrorBanner message={error} />}

      {tab === "tournament" && (
      <>
      <div className="desk-banner">
        <strong>LONG-ONLY CASH EQUITIES.</strong> Every position is a paper buy sized by its
        strategy&rsquo;s capital slice, with the target and stop taken from the signal itself.
        Prices come from <strong>Angel One</strong> first, Dhan as a per-tick fallback, and the
        last daily-bar close only when neither can price a name — each mark is labelled with its
        source, never faked.
      </div>

      {status?.paused && (
        <div className="breaker">
          <strong>NEW ENTRIES PAUSED.</strong> This catalog lost 16/16 measurable strategies
          to real NSE costs in backtest and is losing live even before costs — the desk is
          paused while it&rsquo;s reworked. Every already-open position is still being marked,
          stopped, targeted and squared off normally; nothing new is being opened.
        </div>
      )}

      {status && status.feed_source !== "angel" && (
        <div className="feed-note">
          <strong>Feed: {feedLabel}.</strong>{" "}
          {status.feed_source === "none"
            ? "Neither Angel One nor Dhan answered the last cycle — only daily-bar swing signals can fire and marks fall back to last-bar-close. Angel One live prices flow only from the whitelisted host."
            : "Running on the Dhan fallback — Angel One live prices flow only from the whitelisted host."}
        </div>
      )}

      <div className="tiles">
        <div className="tile">
          <div className="tile-label">Engine</div>
          <div className={`tile-value ${live ? "gain" : ""}`}>{live ? "RUNNING" : "IDLE"}</div>
          <div className="tile-sub">
            {status?.heartbeat ? `beat ${Math.round(heartbeatAge ?? 0)}s ago` : "no heartbeat"}
          </div>
        </div>
        <div className="tile">
          <div className="tile-label">Equity</div>
          <div className="tile-value">₹{inr(status?.equity)}</div>
          <div className="tile-sub">from ₹{inr(status?.initial_capital)} paper</div>
        </div>
        <div className="tile">
          <div className="tile-label">ROI</div>
          <div className={`tile-value ${(status?.roi_pct ?? 0) >= 0 ? "gain" : "loss"}`}>
            {roiPct(status?.roi_pct, 2)}
          </div>
          <div className="tile-sub">on ₹{inr(status?.initial_capital)} desk capital</div>
        </div>
        <div className="tile">
          <div className="tile-label">Today P&amp;L</div>
          <div className={`tile-value ${todayPnl >= 0 ? "gain" : "loss"}`}>
            {todayPnl >= 0 ? "+" : ""}₹{inr(todayPnl)}
          </div>
          <div className="tile-sub">{roiPct(status?.today_roi_pct, 3)} today · {days[0]?.session ?? "no closes yet"}</div>
        </div>
        <div className="tile">
          <div className="tile-label">Angel fees paid</div>
          <div className="tile-value loss">−₹{inr(status?.total_fees)}</div>
          <div className="tile-sub">gross ₹{inr(status?.gross_realized_pnl)} before costs</div>
        </div>
        <div className="tile">
          <div className="tile-label">Deployed capital</div>
          <div className="tile-value">₹{inr(status?.deployed_capital)}</div>
          <div className="tile-sub">₹{inr(status?.available_cash)} free</div>
        </div>
        <div className="tile">
          <div className="tile-label">Open positions</div>
          <div className="tile-value">{status?.open_positions ?? 0}</div>
          <div className="tile-sub">₹{inr(status?.unrealized_pnl)} unrealised</div>
        </div>
        <div className="tile">
          <div className="tile-label">Strategies</div>
          <div className="tile-value">{status?.strategy_count ?? 0}</div>
          <div className="tile-sub">{winners} in profit · feed {status?.feed_source ?? "-"}</div>
        </div>
        <div className="tile">
          <div className="tile-label">Track record</div>
          <div className={`tile-value ${totalPnl >= 0 ? "gain" : "loss"}`}>
            {totalPnl >= 0 ? "+" : ""}₹{inr(totalPnl)}
          </div>
          <div className="tile-sub">{status?.closed_positions ?? 0} trades closed</div>
        </div>
      </div>

      {equity.length > 1 && (
        <GlassPanel title="Equity">
          <LineChart
            points={equity.map((p) => ({ ts: p.ts, value: p.equity }))}
            height={200}
            formatValue={(v) => `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`}
          />
        </GlassPanel>
      )}

      <GlassPanel title={`Open positions (${status?.open_positions ?? 0})`}>
        {!status?.open_positions_detail?.length ? (
          <div className="empty">No open positions.</div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Symbol</th>
                  <th style={{ textAlign: "left" }}>Strategy</th>
                  <th>Qty</th>
                  <th>Entry</th>
                  <th>LTP</th>
                  <th>Src</th>
                  <th>Target</th>
                  <th>Stop</th>
                  <th>Unrealised</th>
                  <th>Opened</th>
                </tr>
              </thead>
              <tbody>
                {status.open_positions_detail.map((p: IntradayPosition) => (
                  <tr key={p.position_id}>
                    <td style={{ textAlign: "left" }}>{p.display_name || p.symbol}</td>
                    <td style={{ textAlign: "left", fontSize: 11 }}>{p.strategy_name}</td>
                    <td>{p.qty}</td>
                    <td>₹{inr2(p.entry_price)}</td>
                    <td>₹{inr2(p.ltp)}</td>
                    <td><SourcePill source={p.ltp_source} /></td>
                    <td>₹{inr2(p.target)}</td>
                    <td>₹{inr2(p.stoploss)}</td>
                    <td className={(p.unrealized_pnl ?? 0) >= 0 ? "gain" : "loss"}>
                      {(p.unrealized_pnl ?? 0) >= 0 ? "+" : ""}₹{inr(p.unrealized_pnl)}
                    </td>
                    <td style={{ fontSize: 10.5 }}>
                      {p.opened_at ? new Date(p.opened_at).toLocaleString() : "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>

      <GlassPanel title="Strategy leaderboard">
        {!scores.length ? (
          <div className="empty">No strategy stats yet.</div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Strategy</th>
                  <th style={{ textAlign: "left" }}>Category</th>
                  <th>Trades</th>
                  <th>Win %</th>
                  <th>Net P&amp;L</th>
                  <th>Allocated</th>
                </tr>
              </thead>
              <tbody>
                {scores.map((s) => (
                  <tr key={s.strategy_id}>
                    <td style={{ textAlign: "left" }}>{s.name}</td>
                    <td style={{ textAlign: "left" }}>
                      <span className="badge">{s.category}</span>
                    </td>
                    <td>{s.trades}</td>
                    <td>{s.trades ? `${(s.win_rate * 100).toFixed(1)}%` : "-"}</td>
                    <td className={s.net_pnl >= 0 ? "gain" : "loss"}>
                      {s.net_pnl >= 0 ? "+" : ""}₹{inr(s.net_pnl)}
                    </td>
                    <td>₹{inr(s.allocated_capital)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>

      <DailyRoiPanel rows={labDaily} capital={status?.initial_capital ?? 0} />

      <GlassPanel title="Recent paper trades">
        {!trades.length ? (
          <div className="empty">No closed trades yet.</div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Symbol</th>
                  <th style={{ textAlign: "left" }}>Strategy</th>
                  <th>Qty</th>
                  <th>Entry</th>
                  <th>Exit</th>
                  <th>Reason</th>
                  <th>P&amp;L</th>
                  <th>Closed</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((t, i) => (
                  <tr key={`${t.trade_id}-${i}`}>
                    <td style={{ textAlign: "left" }}>{t.symbol}</td>
                    <td style={{ textAlign: "left", fontSize: 11 }}>{t.strategy_name}</td>
                    <td>{t.qty}</td>
                    <td>₹{inr2(t.entry_price)}</td>
                    <td>₹{inr2(t.exit_price)}</td>
                    <td>
                      <span className={`badge ${t.exit_reason === "stoploss" ? "loss" : ""}`}>
                        {t.exit_reason}
                      </span>
                    </td>
                    <td className={t.realized_pnl >= 0 ? "gain" : "loss"}>
                      {t.realized_pnl >= 0 ? "+" : ""}₹{inr(t.realized_pnl)}
                    </td>
                    <td style={{ fontSize: 10.5 }}>
                      {t.closed_at ? new Date(t.closed_at).toLocaleString() : "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>
      </>
      )}

      {isLive && (
      <>
      <div className="desk-banner">
        <strong>LIVE INTRADAY · ₹{bookCapital.toLocaleString("en-IN")} PAPER.</strong> The same 8-strategy
        shortlist runs in three books that differ only in capital — ₹80k, ₹30k and ₹10k — each strategy on
        ₹{inr(liveSummary?.per_strategy_allocation)} here. Six are <strong>ANTI</strong> strategies: this desk places
        the <em>real reverse trade</em> (opposite side, stop/target swapped), not a computed mirror.{" "}
        <strong>P&amp;L is net of real Angel One costs</strong> — brokerage, STT, exchange and SEBI charges, stamp
        duty, GST, and a DP charge on delivery exits. On a book this small a signal must clear roughly
        ₹50 a round trip before it earns anything, which is exactly what the smaller books are here to test.
      </div>

      <div className="tiles">
        <div className="tile"><div className="tile-label">Mode</div><div className="tile-value gain">PAPER</div><div className="tile-sub">{liveSummary?.paused ? "entries paused" : "armed · live Angel feed"}</div></div>
        <div className="tile"><div className="tile-label">Equity</div><div className="tile-value">₹{inr(liveSummary?.equity)}</div><div className="tile-sub">from ₹{inr(liveSummary?.initial_capital)} ({liveSummary?.strategy_count ?? 8} × ₹{inr(liveSummary?.per_strategy_allocation)})</div></div>
        <div className="tile"><div className="tile-label">ROI</div><div className={`tile-value ${(liveSummary?.roi_pct ?? 0) >= 0 ? "gain" : "loss"}`}>{roiPct(liveSummary?.roi_pct, 2)}</div><div className="tile-sub">on ₹{inr(liveSummary?.initial_capital)} desk capital</div></div>
        <div className="tile"><div className="tile-label">Today P&amp;L</div><div className={`tile-value ${(liveSummary?.today_pnl ?? 0) >= 0 ? "gain" : "loss"}`}>{(liveSummary?.today_pnl ?? 0) >= 0 ? "+" : ""}₹{inr(liveSummary?.today_pnl)}</div><div className="tile-sub">{roiPct(liveSummary?.today_roi_pct, 3)} today · breaker at −₹{inr(liveSummary?.daily_loss_limit)}</div></div>
        <div className="tile"><div className="tile-label">Realised P&amp;L</div><div className={`tile-value ${(liveSummary?.realized_pnl ?? 0) >= 0 ? "gain" : "loss"}`}>{(liveSummary?.realized_pnl ?? 0) >= 0 ? "+" : ""}₹{inr(liveSummary?.realized_pnl)}</div><div className="tile-sub">{liveSummary?.closed_positions ?? 0} trades closed</div></div>
        <div className="tile"><div className="tile-label">Angel fees paid</div><div className="tile-value loss">−₹{inr(liveSummary?.total_fees)}</div><div className="tile-sub">gross ₹{inr(liveSummary?.gross_realized_pnl)} before costs</div></div>
        <div className="tile"><div className="tile-label">Open positions</div><div className="tile-value">{liveSummary?.open_positions ?? 0}</div><div className="tile-sub">₹{inr(liveSummary?.unrealized_pnl)} unrealised</div></div>
        <div className="tile"><div className="tile-label">Deployed</div><div className="tile-value">₹{inr(liveSummary?.deployed_capital)}</div><div className="tile-sub">₹{inr(liveSummary?.available_cash)} free</div></div>
        <div className="tile"><div className="tile-label">Strategies</div><div className="tile-value">{liveSummary?.strategy_count ?? 0}</div><div className="tile-sub">₹{inr(liveSummary?.position_notional)} / position</div></div>
      </div>

      <GlassPanel title="Selected strategies">
        {!liveScores.length ? (
          <div className="empty">Loading the shortlist…</div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th style={{ textAlign: "left" }}>Strategy</th><th style={{ textAlign: "left" }}>Category</th><th>Trades</th><th>Win %</th><th>Net P&amp;L</th><th>Account</th></tr></thead>
              <tbody>
                {liveScores.map((s) => (
                  <tr key={s.strategy_id}>
                    <td style={{ textAlign: "left" }}>{s.is_anti && <span className="badge anti">ANTI</span>} {s.name}</td>
                    <td style={{ textAlign: "left" }}><span className="badge">{s.category}</span></td>
                    <td>{s.trades}</td>
                    <td>{s.trades ? `${(s.win_rate * 100).toFixed(1)}%` : "-"}</td>
                    <td className={s.net_pnl >= 0 ? "gain" : "loss"}>{s.net_pnl >= 0 ? "+" : ""}₹{inr(s.net_pnl)}</td>
                    <td>₹{inr(s.allocated_capital)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>

      <DailyRoiPanel rows={liveDaily} capital={bookCapital} />

      <GlassPanel title={`Open positions (${liveSummary?.open_positions ?? 0})`}>
        {!livePositions.filter((p) => p.status === "OPEN").length ? (
          <div className="empty">No open positions yet — the desk trades during market hours (09:15–15:30 IST).</div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th style={{ textAlign: "left" }}>Symbol</th><th style={{ textAlign: "left" }}>Strategy</th><th>Side</th><th>Qty</th><th>Entry</th><th>LTP</th><th>Src</th><th>Target</th><th>Stop</th><th>Unrealised</th></tr></thead>
              <tbody>
                {livePositions.filter((p) => p.status === "OPEN").map((p) => (
                  <tr key={p.position_id}>
                    <td style={{ textAlign: "left" }}>{p.symbol}</td>
                    <td style={{ textAlign: "left", fontSize: 11 }}>{p.strategy_name}</td>
                    <td><span className={p.side === "SELL" ? "badge loss" : "badge"}>{p.side}</span></td>
                    <td>{p.qty}</td>
                    <td>₹{inr2(p.entry_price)}</td>
                    <td>₹{inr2(p.ltp)}</td>
                    <td><SourcePill source={p.ltp_source} /></td>
                    <td>₹{inr2(p.target)}</td>
                    <td>₹{inr2(p.stoploss)}</td>
                    <td className={(p.unrealized_pnl ?? 0) >= 0 ? "gain" : "loss"}>{(p.unrealized_pnl ?? 0) >= 0 ? "+" : ""}₹{inr(p.unrealized_pnl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>

      <GlassPanel title="Recent paper trades">
        {!liveTrades.length ? (
          <div className="empty">No closed trades yet.</div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th style={{ textAlign: "left" }}>Symbol</th><th style={{ textAlign: "left" }}>Strategy</th><th>Side</th><th>Qty</th><th>Entry</th><th>Exit</th><th>Reason</th><th>P&amp;L</th><th>Closed</th></tr></thead>
              <tbody>
                {liveTrades.map((t, i) => (
                  <tr key={`${t.trade_id}-${i}`}>
                    <td style={{ textAlign: "left" }}>{t.symbol}</td>
                    <td style={{ textAlign: "left", fontSize: 11 }}>{t.strategy_name}</td>
                    <td>{t.side}</td>
                    <td>{t.qty}</td>
                    <td>₹{inr2(t.entry_price)}</td>
                    <td>₹{inr2(t.exit_price)}</td>
                    <td><span className={`badge ${t.exit_reason === "stoploss" ? "loss" : ""}`}>{t.exit_reason}</span></td>
                    <td className={t.realized_pnl >= 0 ? "gain" : "loss"}>{t.realized_pnl >= 0 ? "+" : ""}₹{inr(t.realized_pnl)}</td>
                    <td style={{ fontSize: 10.5 }}>{t.closed_at ? new Date(t.closed_at).toLocaleString() : "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>
      </>
      )}

      <DeskHistory deskKey={"intraday-lab"} />

      <style jsx>{`
        .page { display: flex; flex-direction: column; gap: 16px; }
        .tabs { display: flex; gap: 8px; }
        .tab { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); padding: 9px 16px; border-radius: 9px; font-size: 12.5px; font-weight: 600; cursor: pointer; }
        .tab.active { background: var(--purple-dim); border-color: rgba(125, 52, 220, 0.3); color: var(--purple); }
        .badge.anti { background: var(--purple-dim); border-color: rgba(125, 52, 220, 0.3); color: var(--purple); margin-right: 4px; }
        .desk-banner {
          padding: 10px 16px; border-radius: 8px; font-size: 12px; line-height: 1.5;
          background: var(--canvas-soft); border: 1px solid var(--panel-border);
          color: var(--text-secondary);
        }
        .feed-note {
          padding: 10px 16px; border-radius: 8px; font-size: 12px; line-height: 1.5;
          background: var(--loss-dim); border: 1px solid rgba(217, 45, 63, 0.3);
          color: var(--text-secondary);
        }
        .breaker {
          padding: 10px 16px; border-radius: 8px; font-size: 12px; line-height: 1.5;
          background: var(--loss-dim); border: 1px solid rgba(217, 45, 63, 0.55);
        }
        .tiles {
          display: grid; gap: 12px;
          grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
        }
        .tile {
          padding: 12px 14px; border-radius: 10px;
          background: var(--panel); border: 1px solid var(--panel-border);
        }
        .tile-label {
          font-size: 10px; font-weight: 700; letter-spacing: 0.04em;
          text-transform: uppercase; color: var(--text-muted);
        }
        .tile-value {
          margin-top: 5px; font-family: var(--font-data); font-variant-numeric: tabular-nums;
          font-size: 16px; font-weight: 600;
        }
        .tile-sub { margin-top: 3px; font-size: 10.5px; color: var(--text-faint); line-height: 1.4; }
        .empty { padding: 18px 20px; font-size: 12px; color: var(--text-faint); }
        .table-scroll { overflow-x: auto; max-height: 460px; overflow-y: auto; }
        .data-table {
          width: 100%; border-collapse: collapse; font-size: 12px;
          font-variant-numeric: tabular-nums;
        }
        .data-table th {
          text-align: center; padding: 8px 10px; font-size: 10px; font-weight: 700;
          letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted);
          border-bottom: 1px solid var(--panel-border); position: sticky; top: 0;
          background: var(--panel);
        }
        .data-table td {
          padding: 7px 10px; text-align: center; border-bottom: 1px solid var(--canvas-soft);
        }
        .badge {
          display: inline-block; padding: 3px 8px; border-radius: 6px; font-size: 10px;
          font-weight: 700; letter-spacing: 0.05em; background: var(--canvas-soft);
          border: 1px solid var(--panel-border);
        }
        .badge.loss { background: var(--loss-dim); border-color: rgba(217, 45, 63, 0.3); }
        .src {
          display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 9.5px;
          font-weight: 700; letter-spacing: 0.04em; border: 1px solid var(--panel-border);
        }
        .src.angel { background: rgba(34, 170, 96, 0.12); border-color: rgba(34, 170, 96, 0.3); }
        .src.dhan { background: var(--canvas-soft); }
        .src.stale { background: var(--loss-dim); border-color: rgba(217, 45, 63, 0.3); }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
      `}</style>
    </div>
  );
}
