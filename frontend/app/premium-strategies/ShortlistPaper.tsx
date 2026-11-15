"use client";

// One channel-shortlist strategy's paper account, for the Shortlist tab: the capital allocated to it, its equity, net
// profit or loss after the engine's estimated fees, spread and slippage, return, win rate, maximum drawdown, open and
// closed trades, each market book's state with the desk's reason (trading, waiting for a signal, armed for the next
// session, or paused for missing or stale data), and the trade history on demand. Strategies that are not on the desk
// (rules incomplete, or a repeat of a library strategy) say so instead. Paper only: nothing here can place an order.
import { useEffect, useState } from "react";
import { apiFetch } from "../../lib/api";
import { inr, istTime, pct, price, rupees } from "./format";
import type { Account } from "./PaperDesk";

export type ShortlistBook = {
  mkt: string; market: string; state: string; reason: string; trades: number; closed: number; wins: number; pnl: number;
  open: number; unrealised: number;
};
type Trade = {
  id: string; sym: string; mkt: string; side: number; setup: string; entry_t: number; exit_t: number | null; entry: number;
  exit: number | null; reason: string; open: boolean; last: number | null; qty?: number; pnl?: number; skip?: string | null;
};

const CAPITAL = 1_000_000;
/** The desk's book states (premium-paper-service/segments.py) in the owner's words. */
const STATE: Record<string, { label: string; cls: string }> = {
  "in trade": { label: "Trading", cls: "ok" },
  running: { label: "Waiting for a signal", cls: "idle" },
  live: { label: "Waiting for a signal", cls: "idle" },
  armed: { label: "Armed for the next session", cls: "idle" },
  waiting: { label: "Starts later", cls: "idle" },
  closed: { label: "Market closed", cls: "idle" },
  stale: { label: "Paused: stale data", cls: "bad" },
  "no data": { label: "Paused: no data", cls: "bad" },
  error: { label: "Paused: error", cls: "bad" },
};
const REASON: Record<string, string> = {
  stop: "Stop", stop_gap: "Stop (gap)", be_stop: "Breakeven stop", target: "Target", time: "Session end", exit_signal: "Exit signal",
  trail_stop: "Trailing stop", open: "Open",
};
const MKT: Record<string, string> = { BTCUSD: "Bitcoin", ETHUSD: "Ether", XAUTUSD: "Gold", XAUUSD: "Gold", NAS100: "Nasdaq 100",
  AAPL: "Apple", EURUSD: "EUR/USD", GBPUSD: "GBP/USD", NIFTY: "Nifty", BANKNIFTY: "Bank Nifty", NSE5: "NSE stocks",
  NSE15: "NSE stocks", NSED: "NSE stocks", NIFTY_OPT: "Nifty options" };

const istIso = (iso: string) =>
  new Date(iso).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", dateStyle: "medium", timeStyle: "short" });

function History({ acct }: { acct: string }) {
  const [rows, setRows] = useState<Trade[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    apiFetch(`/api/premium-paper/accounts/${encodeURIComponent(acct)}/trades?limit=200`)
      .then((t) => { if (live) { setRows(t.trades as Trade[]); setErr(null); } })
      .catch((e) => { if (live) setErr(e instanceof Error ? e.message : "Could not read the trades."); });
    return () => { live = false; };
  }, [acct]);
  if (err) return <p className="slp-dim slp-neg">{err}</p>;
  if (!rows) return <p className="slp-dim">Loading the trades…</p>;
  if (!rows.length) return <p className="slp-dim">No trades yet.</p>;
  return (
    <div className="slp-scroll">
      <table className="slp-table">
        <thead>
          <tr><th>Entered (IST)</th><th>Market</th><th>Side</th><th>Qty</th><th>Entry</th><th>Exit / last</th><th>Left (IST)</th><th>Why</th><th>Net P&amp;L</th></tr>
        </thead>
        <tbody>
          {rows.map((t) => (
            <tr key={t.id} className={t.skip ? "slp-skip" : ""}>
              <td>{istTime(t.entry_t)}</td>
              <td>{MKT[t.mkt] ?? t.mkt}</td>
              <td>{t.side > 0 ? "Long" : "Short"}</td>
              <td>{t.qty != null ? t.qty.toLocaleString("en-US", { maximumFractionDigits: 4 }) : "—"}</td>
              <td>{price(t.entry)}</td>
              <td>{t.open ? <>{price(t.last)} <span className="slp-dim">open</span></> : price(t.exit)}</td>
              <td>{t.open ? "—" : istTime(t.exit_t)}</td>
              <td>{t.skip ? `Not sized: ${t.skip}` : (REASON[t.reason] ?? t.reason)}</td>
              <td className={(t.pnl ?? 0) >= 0 ? "slp-pos" : "slp-neg"}>{t.pnl != null ? inr(t.pnl) : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function ShortlistPaper({ status, account, books, start, blockedReason, dataBlocked, duplicateOf, duplicateWhy }: {
  status: "coded" | "blocked" | "duplicate"; account?: Account; books?: ShortlistBook[]; start: string;
  blockedReason?: string | null; dataBlocked?: boolean; duplicateOf?: string | null; duplicateWhy?: string | null;
}) {
  const [showTrades, setShowTrades] = useState(false);
  if (status === "duplicate") {
    return (
      <span className="slp-inline">
        <span className="slp-pill idle">Not traded separately</span> it repeats {duplicateOf}, already in the app{duplicateWhy ? `: ${duplicateWhy}` : "."}
        <Styles />
      </span>
    );
  }
  if (status === "blocked") {
    return (
      <span className="slp-inline">
        <span className="slp-pill bad">{dataBlocked ? "Paused: missing data" : "Paused: rules incomplete"}</span> no paper account
        {blockedReason ? `: ${blockedReason}` : "."}
        <Styles />
      </span>
    );
  }
  if (!account) {
    return (
      <div className="slp-box">
        <span><span className="slp-pill idle">Not on the desk yet</span> its ₹10 lakh account appears after the next deploy.</span>
        <Styles />
      </div>
    );
  }
  const started = Date.now() >= new Date(start).getTime();
  const capital = account.capital || CAPITAL;
  const net = account.equity - capital;
  return (
    <div className="slp-box">
      <div className="slp-stats">
        <span><b>Allocated</b> {rupees(capital)}</span>
        <span><b>Equity</b> {rupees(account.equity)}</span>
        <span><b>Net P&amp;L</b> <i className={net >= 0 ? "slp-pos" : "slp-neg"}>{inr(net)}</i></span>
        <span><b>Return</b> <i className={account.return_pct >= 0 ? "slp-pos" : "slp-neg"}>{pct(account.return_pct)}</i></span>
        <span><b>Win rate</b> {account.win_rate == null ? "—" : `${account.win_rate.toFixed(1)}%`}</span>
        <span><b>Max drawdown</b> {account.closed ? `${(account.max_dd_pct || 0).toFixed(1)}%` : "—"}</span>
        <span><b>Trades</b> {account.closed} closed · {account.open} open</span>
      </div>
      {!started && <div className="slp-dim">Armed: trading starts {istIso(start)} IST, flat; nothing before that is back-filled.</div>}
      {(books ?? []).length > 0 && (
        <ul className="slp-books">
          {(books ?? []).map((b) => {
            const s = STATE[b.state] ?? { label: b.state, cls: "idle" };
            return (
              <li key={b.mkt}>
                <span className={`slp-pill ${s.cls}`}>{s.label}</span> <b>{MKT[b.mkt] ?? b.market ?? b.mkt}</b>{" "}
                <span className="slp-dim">{b.reason}</span>
              </li>
            );
          })}
        </ul>
      )}
      <div className="slp-dim">Net of the engine&apos;s estimated fees, spread and slippage; simulated orders on real Delta Exchange and desk prices.</div>
      <details className="slp-sec" onToggle={(e) => setShowTrades((e.target as HTMLDetailsElement).open)}>
        <summary>Trade history ({account.closed + account.open})</summary>
        {showTrades && <History acct={account.id} />}
      </details>
      <Styles />
    </div>
  );
}

function Styles() {
  return (
    <style jsx global>{`
        .slp-inline { font-size: 12.5px; }
        .slp-box { font-size: 12.5px; padding: 8px 10px; border-radius: 8px; background: var(--canvas-soft); display: grid; gap: 6px; }
        .slp-stats { display: flex; flex-wrap: wrap; gap: 6px 14px; }
        .slp-stats b { font-weight: 700; color: var(--text-muted); margin-right: 3px; }
        .slp-stats i { font-style: normal; font-weight: 700; }
        .slp-pos { color: var(--gain); }
        .slp-neg { color: var(--loss); }
        .slp-dim { color: var(--text-muted); font-size: 11.5px; }
        .slp-books { list-style: none; margin: 0; padding: 0; display: grid; gap: 4px; }
        .slp-pill { display: inline-block; font-size: 11px; font-weight: 700; padding: 1px 8px; border-radius: 999px; border: 1px solid var(--panel-border);
          color: var(--text-muted); margin-right: 4px; }
        .slp-pill.ok { border-color: var(--gain); color: var(--gain); }
        .slp-pill.bad { border-color: var(--loss); color: var(--loss); }
        .slp-sec summary { cursor: pointer; font-weight: 700; color: var(--purple); font-size: 12px; }
        .slp-scroll { max-height: 320px; overflow: auto; margin-top: 6px; }
        .slp-table { border-collapse: collapse; width: 100%; font-size: 11.5px; }
        .slp-table th, .slp-table td { text-align: left; padding: 3px 6px; border-bottom: 1px solid var(--panel-border); white-space: nowrap; }
        .slp-skip td { color: var(--text-muted); }
      `}</style>
  );
}
