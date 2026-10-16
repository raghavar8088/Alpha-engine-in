"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import PageHeader from "../../../components/PageHeader";
import { fetchFocusSnapshot, type FocusSnapshot } from "../../../lib/intradayFocus";

const rupees = (value: number) => new Intl.NumberFormat("en-IN", {
  style: "currency", currency: "INR", maximumFractionDigits: 2,
}).format(value);
const percent = (value: number) => `${value > 0 ? "+" : ""}${value.toFixed(3)}%`;
const tone = (value: number) => value > 0 ? "gain" : value < 0 ? "loss" : "";
const stamp = (value: string | null) => value ? new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit",
}).format(new Date(value)) : "Not yet recorded";

export default function FocusFivePage() {
  const [data, setData] = useState<FocusSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [strategy, setStrategy] = useState("all");
  const [view, setView] = useState<"open" | "closed" | "daily">("open");
  const [clock, setClock] = useState(Date.now());
  const controller = useRef<AbortController | null>(null);
  const sequence = useRef(0);

  const refresh = useCallback(async () => {
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    const seq = ++sequence.current;
    let timedOut = false;
    const timeout = setTimeout(() => { timedOut = true; request.abort(); }, 25000);
    setLoading(true);
    try {
      const result = await fetchFocusSnapshot(request.signal);
      if (seq === sequence.current) { setData(result); setError(null); }
    } catch (e) {
      if (seq === sequence.current && (!request.signal.aborted || timedOut)) {
        setError(timedOut ? "The server did not respond within 25 seconds. The last loaded record is retained."
          : e instanceof Error ? e.message : "Unable to load the desk.");
      }
    } finally {
      clearTimeout(timeout);
      if (seq === sequence.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const poll = setInterval(() => { if (!document.hidden) void refresh(); }, 30000);
    const clockTimer = setInterval(() => setClock(Date.now()), 10000);
    return () => { ++sequence.current; controller.current?.abort(); clearInterval(poll); clearInterval(clockTimer); };
  }, [refresh]);

  const staleResponse = !!data && clock - new Date(data.updated_at).getTime() > 90000;
  const positions = data?.positions.filter(p => strategy === "all" || p.strategy_id === strategy) ?? [];
  const trades = data?.trades.filter(p => strategy === "all" || p.strategy_id === strategy) ?? [];
  const live = !!data && !error && !staleResponse && data.feed.status === "LIVE";

  return <div className="focus-page">
    <Link className="back" href="/intraday-stocks">← Intraday Stocks</Link>
    <PageHeader crumb="Intraday Stocks / Five-Strategy Desk" title="Five-Strategy Desk"
      subtitle="₹10 lakh per strategy · ₹50 lakh total paper capital. Five independent accounts trading signals from real NSE stock data."
      onRefresh={refresh} refreshing={loading}
      actions={<span className="badge paper">PAPER TRADING · NO BROKER ORDERS</span>} />

    <div className="notice">
      <strong>Real prices. Simulated trades.</strong> These strategies are not validated for real-money use.
      This desk starts a new record when its engine starts—no historical tournament profits are copied.
      Fees and slippage are estimates, not broker executions.
    </div>
    {error && <div className="alert" role="alert">{error} <button onClick={() => void refresh()} disabled={loading}>Retry</button></div>}
    {!data ? <section className="panel placeholder" aria-live="polite">
      <h2>{loading ? "Loading your five strategy accounts…" : "Desk data is unavailable"}</h2>
      <p>Balances and returns will appear after a successful server response. No sample performance is displayed.</p>
    </section> : <>
      <section className="feed" aria-label="Data and engine status">
        <div><span className={`badge ${live ? "live" : "muted"}`}>{error || staleResponse ? "DISPLAY DATA STALE" : data.feed.status.replaceAll("_", " ")}</span>
          <span>{data.feed.source}</span></div>
        <div className="feed-meta">
          <span>Entries: {data.engine.entries_enabled && !staleResponse && !error ? "enabled" : "paused / waiting"}</span>
          <span>Last price: {stamp(data.feed.last_quote_at)} IST</span>
          <span>Engine: {stamp(data.engine.last_tick)} IST</span>
        </div>
        {(data.engine.note || data.feed.reason || staleResponse) && <p>{staleResponse ? "This page has not received a fresh snapshot. Displayed prices and returns may be out of date. " : ""}{data.engine.note} {data.feed.reason}</p>}
      </section>

      <section className="metrics" aria-label="Combined paper account balances">
        <div><span>Allocated capital</span><strong>{rupees(data.initial_capital)}</strong><small>5 × {rupees(data.per_strategy_capital)}</small></div>
        <div><span>Net return</span><strong className={tone(data.return_pct)}>{percent(data.return_pct)}</strong><small>On total starting capital · not annualized</small></div>
        <div><span>Paper equity</span><strong>{rupees(data.equity)}</strong><small>Includes estimated liquidation P&amp;L</small></div>
        <div><span>Available cash</span><strong>{rupees(data.available_cash)}</strong><small>After deployed capital and fee reserve</small></div>
      </section>

      <section className="panel">
        <div className="section-heading"><div><h2>Your five strategy accounts</h2><p>Capital is ring-fenced: no strategy can borrow another strategy’s allocation.</p></div>
          <span className="muted">{data.closed_trades} closed trades · {data.open_positions} open</span></div>
        <div className="table-scroll"><table>
          <caption>Strategy performance since {data.started_at ? `${stamp(data.started_at)} IST` : "engine startup (not started)"}. Each return is on ₹10 lakh.</caption>
          <thead><tr><th>Strategy / timeframe</th><th>Allocation</th><th>Equity</th><th>Available cash</th><th>Net return</th><th>Closed trades</th><th>Win rate</th><th>Open</th></tr></thead>
          <tbody>{data.strategies.map(s => <tr key={s.strategy_id}>
            <td><strong>{s.name}</strong><small>{s.timeframe === "1h" ? "1 hour" : "45 minutes"} · Paper / unvalidated</small></td>
            <td>{rupees(s.initial_capital)}</td><td>{rupees(s.equity)}</td><td>{rupees(s.available_cash)}</td>
            <td className={tone(s.return_pct)}><strong>{percent(s.return_pct)}</strong><small>{rupees(s.total_pnl)}</small></td>
            <td>{s.trades}</td><td>{s.trades ? `${(s.win_rate * 100).toFixed(1)}%` : "—"}</td><td>{s.open_positions} / {data.slots_per_strategy}</td>
          </tr>)}</tbody>
        </table></div>
      </section>

      <section className="rules" aria-label="Trading rules">
        <div><h2>How this desk trades</h2><p>Each ₹10 lakh account has five slots capped at {rupees(data.slot_notional)} including a fee reserve. Whole shares only; no leverage.</p>
          <p>New signals: 09:45–14:30 IST. Automatic stop, target and time exits. Scheduled square-off: 15:05 for closing-auction stocks, 15:12 for others. If prices are unavailable, an exit stays pending—not filled at an invented price.</p>
          <p>A 3% daily loss limit stops new entries for the affected strategy. Existing exits continue. Main Control can pause this desk.</p></div>
        <div className="strategy-rules">{data.strategies.map(s => <details key={s.strategy_id}>
          <summary>{s.name} · {s.timeframe}</summary><p>{s.description}</p>{s.last_skip && <p className="muted">Last entry note: {s.last_skip}</p>}
        </details>)}</div>
      </section>

      <section className="panel">
        <div className="section-heading"><div className="tabs" role="tablist" aria-label="Trading record">
          {([['open', 'Open positions'], ['closed', 'Closed trades'], ['daily', 'Daily returns']] as const).map(([id, label]) =>
            <button key={id} role="tab" aria-selected={view === id} className={view === id ? "active" : ""} onClick={() => setView(id)}>{label}</button>)}
        </div>{view !== "daily" && <label className="filter">Strategy <select aria-label="Strategy" value={strategy} onChange={e => setStrategy(e.target.value)}>
          <option value="all">All five strategies</option>{data.strategies.map(s => <option key={s.strategy_id} value={s.strategy_id}>{s.name} · {s.timeframe}</option>)}
        </select></label>}</div>
        {view === "open" && (positions.length ? <div className="table-scroll"><table>
          <caption>Open paper positions. Return is estimated net liquidation P&amp;L divided by position entry value.</caption>
          <thead><tr><th>Stock / strategy</th><th>Side</th><th>Shares</th><th>Entry</th><th>Last price</th><th>Stop</th><th>Target</th><th>Net return</th></tr></thead>
          <tbody>{positions.map(p => <tr key={p.position_id}><td><strong>{p.symbol}</strong><small>{p.strategy_name}</small></td><td>{p.side === "BUY" ? "LONG" : "SHORT"}</td>
            <td>{p.qty}</td><td>{rupees(p.entry_price)}</td><td>{rupees(p.ltp)}<small>{p.price_status}</small></td><td>{rupees(p.stoploss)}</td><td>{rupees(p.target)}</td>
            <td className={tone(p.return_pct)}>{percent(p.return_pct)}<small>{rupees(p.unrealized_pnl)}</small></td></tr>)}</tbody>
        </table></div> : <div className="empty">No open positions in this view. The engine waits for a qualifying closed-bar signal and fresh real-market quotes.</div>)}
        {view === "closed" && (trades.length ? <div className="table-scroll"><table>
          <caption>Most recent 100 closed paper trades across the desk, filtered by strategy. Trade return is on the position’s entry value.</caption>
          <thead><tr><th>Stock / strategy</th><th>Side</th><th>Shares</th><th>Entry → exit</th><th>Charges</th><th>Net return</th><th>Exit reason</th><th>Closed (IST)</th></tr></thead>
          <tbody>{trades.map(t => <tr key={t.position_id}><td><strong>{t.symbol}</strong><small>{t.strategy_name}</small></td><td>{t.side === "BUY" ? "LONG" : "SHORT"}</td><td>{t.qty}</td>
            <td>{rupees(t.entry_price)} → {rupees(t.exit_price)}</td><td>{rupees(t.fees)}</td><td className={tone(t.return_pct)}>{percent(t.return_pct)}<small>{rupees(t.realized_pnl)}</small></td>
            <td>{t.exit_reason.replaceAll("_", " ")}</td><td>{stamp(t.closed_at)}</td></tr>)}</tbody>
        </table></div> : <div className="empty">No closed trades in this view. Past tournament results are intentionally excluded from these new accounts.</div>)}
        {view === "daily" && (data.daily.length ? <div className="table-scroll"><table>
          <caption>Latest 90 recorded days, all five strategies. Daily realized return is on ₹50 lakh starting desk capital.</caption>
          <thead><tr><th>Date (IST)</th><th>Trades</th><th>Gross P&amp;L</th><th>Charges</th><th>Net P&amp;L</th><th>Daily return</th></tr></thead>
          <tbody>{data.daily.map(d => <tr key={d.date}><td>{d.date}</td><td>{d.trades}</td><td>{rupees(d.gross_pnl)}</td><td>{rupees(d.fees)}</td>
            <td className={tone(d.realized_pnl)}>{rupees(d.realized_pnl)}</td><td className={tone(d.return_pct)}>{percent(d.return_pct)}</td></tr>)}</tbody>
        </table></div> : <div className="empty">Daily returns appear after the first position closes.</div>)}
      </section>
      <footer>{data.cost_note} Snapshot: {stamp(data.updated_at)} IST. Refreshes every 30 seconds while this page is visible.</footer>
    </>}
    <style jsx>{`
      .focus-page { display: flex; flex-direction: column; gap: 20px; padding-bottom: 32px; }
      .focus-page :global(.page-header) { margin-bottom: 0; }
      .back { width: fit-content; color: var(--brand); font-size: 13px; text-decoration: none; }
      .badge { display: inline-block; border-radius: 6px; padding: 6px 10px; font-size: 11px; font-weight: 700; letter-spacing: .3px; background: var(--canvas-soft); border: 1px solid var(--panel-border); }
      .paper { background: var(--brand-dim); color: var(--brand); }
      .live, .gain { color: var(--gain); } .loss { color: var(--loss); } .muted { color: var(--text-muted); }
      .notice { background: var(--canvas-soft); border: 1px solid var(--panel-border); padding: 15px 18px; border-radius: 10px; font-size: 13px; color: var(--text-muted); line-height: 1.7; }
      .notice strong { color: var(--text); margin-right: 5px; }
      .alert { border: 1px solid var(--loss); padding: 16px; color: var(--loss); border-radius: 10px; }
      .alert button { margin-left: 12px; padding: 5px 12px; }
      .feed { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 10px 24px; font-size: 12px; color: var(--text-muted); }
      .feed > div { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
      .feed p { width: 100%; margin: 0; line-height: 1.6; }
      .metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; }
      .metrics > div { padding: 20px; background: var(--panel); border: 1px solid var(--panel-border); border-radius: 12px; display: flex; flex-direction: column; gap: 8px; }
      .metrics span { color: var(--text-muted); font-size: 12px; }
      .metrics strong { font-family: var(--font-data); font-size: 23px; font-variant-numeric: tabular-nums; }
      small { display: block; font-size: 11px; color: var(--text-muted); margin-top: 4px; line-height: 1.5; }
      .panel { border: 1px solid var(--panel-border); background: var(--panel); border-radius: 12px; overflow: hidden; }
      .section-heading { padding: 18px 20px; display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 14px; }
      h2 { font-size: 16px; margin: 0 0 6px; color: var(--text); } p { font-size: 13px; color: var(--text-muted); line-height: 1.65; margin: 0; }
      .section-heading > span { font-size: 12px; }
      .table-scroll { overflow-x: auto; } table { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; }
      caption { text-align: left; padding: 0 20px 13px; color: var(--text-muted); font-size: 11px; }
      th { font-size: 10px; font-weight: 650; text-transform: uppercase; letter-spacing: .35px; color: var(--text-muted); background: var(--canvas-soft); }
      th, td { padding: 13px 16px; text-align: right; white-space: nowrap; border-bottom: 1px solid var(--panel-border); }
      th:first-child, td:first-child { text-align: left; padding-left: 20px; } tr:last-child td { border-bottom: 0; } tbody tr:hover { background: var(--canvas-soft); }
      .rules { display: grid; grid-template-columns: 1fr 1fr; gap: 32px; padding: 8px 4px; } .rules p { margin-top: 10px; }
      details { border-bottom: 1px solid var(--panel-border); padding: 11px 0; } summary { cursor: pointer; font-size: 13px; color: var(--text); font-weight: 600; }
      .tabs { display: flex; gap: 6px; flex-wrap: wrap; } .tabs button, select, .alert button { background: var(--canvas-soft); color: var(--text-muted); border: 1px solid var(--panel-border); border-radius: 7px; font: inherit; cursor: pointer; }
      .tabs button { padding: 8px 12px; font-size: 12px; } .tabs .active { background: var(--brand-dim); color: var(--brand); border-color: var(--brand-border); }
      .filter { font-size: 12px; color: var(--text-muted); } select { padding: 8px; margin-left: 8px; max-width: 260px; }
      .empty, .placeholder { padding: 30px 20px; font-size: 13px; color: var(--text-muted); line-height: 1.7; }
      footer { font-size: 11px; color: var(--text-muted); line-height: 1.7; }
      button:focus-visible, select:focus-visible, summary:focus-visible { outline: 2px solid var(--brand); outline-offset: 3px; }
      @media (max-width: 1100px) { .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
      @media (max-width: 700px) { .rules { grid-template-columns: 1fr; gap: 16px; } .metrics strong { font-size: 19px; } .metrics > div { padding: 14px; } .feed-meta { gap: 8px; } .filter { width: 100%; } }
    `}</style>
  </div>;
}
