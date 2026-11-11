"use client";

// A Grade Strategies (2026-11-11): seven tournament strategies the owner picked off the paper books' boards and the
// Five-Strategy Desk, each
// trading its OWN Rs 10 lakh paper account (live_intraday_engine.A_GRADE). One strategy's money is never used by
// another, and each account's realised profit is reinvested in that strategy alone: every position is sized on the
// account's realised equity / 5 at the moment of entry. The books copy the tournament's own fills (same entry and exit
// prices), so a difference from the tournament is size and cost, never a different signal. Paper only.
import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch } from "../../lib/api";

type Book = { book: string; strategy: string; name: string; board: string; rank: number; score: number; trades: number; net: number };
// Where each was picked (the owner's screenshots of 11 Nov 2026) - the record it earns here is the test.
const BOOKS: Book[] = [
  { book: "ag_gap_go", strategy: "iv2_gap_go", name: "Gap and Go", board: "Live Intraday ₹10 lakh", rank: 1, score: 63.6, trades: 25, net: 19346 },
  { book: "ag_orb_sel15", strategy: "iv2_orb_sel15", name: "Selected ORB 15-min (top-5 expected move)", board: "Live Intraday ₹10 lakh", rank: 2, score: 58.9, trades: 23, net: 34975 },
  { book: "ag_rsi_momentum_15m", strategy: "iv2_rsi_momentum_15m", name: "RSI Momentum 60/40 · 15 min", board: "Live Intraday ₹10 lakh", rank: 3, score: 58.0, trades: 7, net: 6643 },
  { book: "ag_donchian_1h", strategy: "iv2_donchian_1h", name: "Donchian 20 Breakout · 1 hour", board: "Live Intraday ₹10 lakh", rank: 4, score: 57.6, trades: 5, net: 12087 },
  { book: "ag_pdh_pdl_15m", strategy: "iv2_pdh_pdl_15m", name: "Prior-Day High/Low Break · 15 min", board: "Live Intraday ₹10 lakh", rank: 5, score: 54.1, trades: 3, net: 11228 },
  { book: "ag_supertrend_45m", strategy: "iv2_supertrend_45m", name: "Supertrend Flip · 45 min", board: "Top 10 ₹10 lakh", rank: 1, score: 64.9, trades: 25, net: 8883 },
  { book: "ag_supertrend_1h", strategy: "iv2_supertrend_1h", name: "Supertrend Flip · 1 hour", board: "Five-Strategy Desk", rank: 1, score: 100.0, trades: 123, net: 53746.91 },
];
const POLL_MS = 60000;

type Summary = {
  book: string; initial_capital: number; equity: number; realized_pnl: number; unrealized_pnl: number; total_fees: number;
  roi_pct: number; open_positions: number; closed_positions: number; position_cap?: number; max_open_positions?: number;
  available_cash: number; deployed_capital: number; today_pnl: number; breaker_tripped: boolean; daily_loss_limit: number;
  paused: boolean; copying_since?: string | null; compounding?: boolean; last_run_at?: string | null;
  skipped?: Record<string, number>;
};
type Score = { strategy_id: string; trades: number; win_rate: number; net_pnl: number; fees?: number; skipped_total?: number };
type Position = { position_id: string; symbol: string; side: string; entry_price: number; qty: number; capital_deployed: number;
  stoploss: number | null; target: number | null; ltp: number; unrealized_pnl: number; realized_pnl: number | null;
  exit_price: number | null; exit_reason: string | null; status: string; opened_at: string | null; closed_at: string | null };
type Trade = { trade_id: string; symbol: string; side: string; entry_price: number; exit_price: number; qty: number;
  realized_pnl: number; exit_reason: string | null; opened_at: string | null; closed_at: string | null };
type Day = { date: string; trades: number; wins: number; realized_pnl: number; fees: number; roi_pct: number };
type Data = { summary?: Summary; score?: Score; open: Position[]; trades: Trade[]; daily: Day[]; error?: string };

function inr(n: number | null | undefined, signed = false): string {
  if (n == null || !Number.isFinite(n)) return "—";
  const s = `₹${Math.round(Math.abs(n)).toLocaleString("en-IN")}`;
  if (n < 0) return `−${s}`;
  return signed && n > 0 ? `+${s}` : s;
}
const pct = (n: number | null | undefined, d = 2) =>
  n == null || !Number.isFinite(n) ? "—" : `${n > 0 ? "+" : n < 0 ? "−" : ""}${Math.abs(n).toFixed(d)}%`;
const tone = (n: number | null | undefined) => (n == null || n === 0 ? "" : n > 0 ? "pos" : "neg");
const ist = (iso: string | null | undefined) => {
  if (!iso) return "—";
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`);
  return d.toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });
};
const REASON: Record<string, string> = { stoploss: "Stop", stop: "Stop", target: "Target", eod: "Session close", time: "Time stop",
  eod_last_known_price: "Session close (last known price)" };

async function loadBook(b: Book): Promise<Data> {
  try {
    const [summary, board, pos, tr, daily] = await Promise.all([
      apiFetch(`/api/live-intraday/summary?book=${b.book}`),
      apiFetch(`/api/live-intraday/leaderboard?book=${b.book}`),
      apiFetch(`/api/live-intraday/positions?book=${b.book}&status=OPEN&limit=50`),
      apiFetch(`/api/live-intraday/trades?book=${b.book}&limit=100`),
      apiFetch(`/api/live-intraday/daily?book=${b.book}&limit=60`),
    ]);
    const score = ((board?.leaderboard ?? []) as Score[]).find((r) => r.strategy_id === b.strategy);
    return { summary, score, open: pos?.positions ?? [], trades: tr?.trades ?? [], daily: daily?.daily ?? [] };
  } catch (e) {
    return { open: [], trades: [], daily: [], error: e instanceof Error ? e.message : "could not load" };
  }
}

export default function AGradeStrategies() {
  const [data, setData] = useState<Record<string, Data>>({});
  const [sel, setSel] = useState<string>(BOOKS[0].book);
  const [loadedAt, setLoadedAt] = useState<Date | null>(null);
  const load = useCallback(async () => {
    const rows = await Promise.all(BOOKS.map((b) => loadBook(b)));
    setData(Object.fromEntries(BOOKS.map((b, i) => [b.book, rows[i]])));
    setLoadedAt(new Date());
  }, []);
  useEffect(() => {
    load();
    const t = setInterval(load, POLL_MS);
    return () => clearInterval(t);
  }, [load]);

  const total = useMemo(() => {
    const ss = BOOKS.map((b) => data[b.book]?.summary).filter(Boolean) as Summary[];
    const cap = ss.reduce((a, s) => a + s.initial_capital, 0);
    const eq = ss.reduce((a, s) => a + s.equity, 0);
    return { n: ss.length, cap, eq, roi: cap ? ((eq - cap) / cap) * 100 : 0, closed: ss.reduce((a, s) => a + s.closed_positions, 0),
      open: ss.reduce((a, s) => a + s.open_positions, 0) };
  }, [data]);
  const cur = BOOKS.find((b) => b.book === sel)!;
  const d = data[sel];
  const started = BOOKS.map((b) => data[b.book]?.summary?.copying_since).filter(Boolean).sort()[0];

  return (
    <div className="ag">
      <div className="ag-banner">
        <strong>A GRADE STRATEGIES · 7 ACCOUNTS · ₹10 LAKH EACH · PAPER ONLY.</strong>{" "}
        Each strategy trades <strong>its own ₹10 lakh account</strong> — one strategy&apos;s money is never used by
        another — and <strong>its profit is reinvested in that strategy alone</strong>: every new position is sized on
        the account&apos;s realised equity ÷ 5 at the moment of entry, so ₹50,000 of profit makes each later position
        a tenth bigger (a loss shrinks it the same way). The accounts copy the tournament&apos;s own trades for their
        strategy — the same entry and exit prices, sized to the account, charged Angel One&apos;s intraday costs on{" "}
        <em>its</em> quantity: at most 5 positions at a time, whole shares, never two in one stock, no leverage, a 3%
        daily-loss breaker. They started when they were added{started ? ` (${ist(started)} IST)` : ""}; nothing earlier is
        back-filled. Simulated fills, not broker orders.
        <div className="ag-note">
          Picked on 11 Nov 2026: six from the paper books&apos; boards on 3 to 25 trades each, and Supertrend Flip ·
          1 hour from the Five-Strategy Desk on 123 trades (that desk fills the same rule at its own live quotes; this
          account copies the tournament&apos;s fills, like the other six). A few weeks at the top of a board is where
          luck collects; the record these accounts earn from here is the real test.
        </div>
      </div>

      <div className="ag-panel">
        <div className="ag-head">
          <span>Accounts</span>
          <span className="ag-dim">
            {total.n ? <>Together {inr(total.eq)} on {inr(total.cap)} · <b className={tone(total.roi)}>{pct(total.roi)}</b> · {total.closed} closed · {total.open} open</> : "loading…"}
            {loadedAt ? ` · updated ${loadedAt.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}` : ""}
          </span>
        </div>
        <div className="ag-scroll">
          <table className="ag-t">
            <thead>
              <tr>
                <th>Strategy</th><th>Picked from</th><th>Equity</th><th>Return</th><th>Realised</th><th>Open P&amp;L</th>
                <th>Trades</th><th>Win %</th><th>Open</th><th>Next position up to</th><th>Today</th><th>Status</th>
              </tr>
            </thead>
            <tbody>
              {BOOKS.map((b) => {
                const x = data[b.book];
                const s = x?.summary;
                const status = x?.error ? "Not loaded" : !s ? "…" : s.paused ? "Paused" : s.breaker_tripped ? "Breaker: no new entries today" : "Trading";
                return (
                  <tr key={b.book} className={sel === b.book ? "pick on" : "pick"} onClick={() => setSel(b.book)}>
                    <td className="ag-name">{b.name}</td>
                    <td className="ag-dim">#{b.rank} · {b.score} on {b.board} · {b.trades} trades, {inr(b.net, true)}</td>
                    <td>{inr(s?.equity)}</td>
                    <td className={tone(s?.roi_pct)}>{pct(s?.roi_pct)}</td>
                    <td className={tone(s?.realized_pnl)}>{inr(s?.realized_pnl, true)}</td>
                    <td className={tone(s?.unrealized_pnl)}>{inr(s?.unrealized_pnl, true)}</td>
                    <td>{s?.closed_positions ?? "—"}</td>
                    <td>{x?.score && x.score.trades ? `${(100 * x.score.win_rate).toFixed(1)}%` : "—"}</td>
                    <td>{s?.open_positions ?? "—"}</td>
                    <td>{inr(s?.position_cap)}</td>
                    <td className={tone(s?.today_pnl)}>{inr(s?.today_pnl, true)}</td>
                    <td className={x?.error || s?.breaker_tripped || s?.paused ? "neg" : ""}>{status}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div className="ag-chips">
        {BOOKS.map((b) => (
          <button key={b.book} className={`ag-chip${sel === b.book ? " on" : ""}`} onClick={() => setSel(b.book)}>{b.name}</button>
        ))}
      </div>

      <div className="ag-panel">
        <div className="ag-head">
          <span>{cur.name} · ₹10 lakh account</span>
          <span className="ag-dim">
            {d?.summary ? <>cash {inr(d.summary.available_cash)} · deployed {inr(d.summary.deployed_capital)} · fees {inr(d.summary.total_fees)} · daily loss limit {inr(d.summary.daily_loss_limit)}{d.score?.skipped_total ? ` · ${d.score.skipped_total} signals it could not take` : ""}</> : d?.error ? `could not load: ${d.error}` : "loading…"}
          </span>
        </div>
        <h4>Open positions ({d?.open.length ?? 0})</h4>
        {d?.open.length ? (
          <div className="ag-scroll">
            <table className="ag-t">
              <thead><tr><th>Stock</th><th>Side</th><th>Qty</th><th>Entry</th><th>Stop</th><th>Target</th><th>Last</th><th>Open P&amp;L</th><th>Since</th></tr></thead>
              <tbody>
                {d.open.map((p) => (
                  <tr key={p.position_id}>
                    <td className="ag-name">{p.symbol}</td><td>{p.side}</td><td>{p.qty}</td><td>{p.entry_price}</td>
                    <td>{p.stoploss ?? "—"}</td><td>{p.target ?? "—"}</td><td>{p.ltp}</td>
                    <td className={tone(p.unrealized_pnl)}>{inr(p.unrealized_pnl, true)}</td><td>{ist(p.opened_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <p className="ag-dim">None open. Entries come from the tournament&apos;s own signals for this strategy, in NSE hours.</p>}

        <h4>Closed trades ({d?.trades.length ?? 0}{d && d.trades.length >= 100 ? ", latest 100" : ""})</h4>
        {d?.trades.length ? (
          <div className="ag-scroll">
            <table className="ag-t">
              <thead><tr><th>Closed</th><th>Stock</th><th>Side</th><th>Qty</th><th>Entry</th><th>Exit</th><th>Why</th><th>Net P&amp;L</th></tr></thead>
              <tbody>
                {d.trades.map((t) => (
                  <tr key={t.trade_id}>
                    <td>{ist(t.closed_at)}</td><td className="ag-name">{t.symbol}</td><td>{t.side}</td><td>{t.qty}</td>
                    <td>{t.entry_price}</td><td>{t.exit_price}</td><td>{REASON[t.exit_reason ?? ""] ?? t.exit_reason ?? "—"}</td>
                    <td className={tone(t.realized_pnl)}>{inr(t.realized_pnl, true)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <p className="ag-dim">No closed trades yet.</p>}

        <h4>Day by day</h4>
        {d?.daily.length ? (
          <div className="ag-scroll">
            <table className="ag-t">
              <thead><tr><th>Day</th><th>Trades</th><th>Won</th><th>Fees</th><th>Net P&amp;L</th><th>On ₹10 lakh</th></tr></thead>
              <tbody>
                {d.daily.map((x) => (
                  <tr key={x.date}>
                    <td>{x.date}</td><td>{x.trades}</td><td>{x.wins}</td><td>{inr(x.fees)}</td>
                    <td className={tone(x.realized_pnl)}>{inr(x.realized_pnl, true)}</td><td className={tone(x.roi_pct)}>{pct(x.roi_pct, 3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <p className="ag-dim">No closed days yet.</p>}
      </div>

      <style jsx>{`
        .ag { display: flex; flex-direction: column; gap: 14px; }
        .ag-banner { padding: 10px 16px; border-radius: 8px; font-size: 12px; line-height: 1.55; background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-secondary); }
        .ag-note { margin-top: 6px; color: var(--text-muted); }
        .ag-panel { border: 1px solid var(--panel-border); border-radius: 10px; padding: 12px 14px; background: var(--panel-bg, transparent); }
        .ag-head { display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; font-weight: 600; font-size: 13px; margin-bottom: 8px; }
        .ag-dim { color: var(--text-muted); font-weight: 400; font-size: 12px; }
        .ag-scroll { overflow-x: auto; }
        .ag-t { width: 100%; border-collapse: collapse; font-size: 12.5px; }
        .ag-t th { text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: 0.03em; color: var(--text-muted); padding: 6px 8px; border-bottom: 1px solid var(--panel-border); white-space: nowrap; }
        .ag-t td { padding: 7px 8px; border-bottom: 1px solid var(--panel-border); white-space: nowrap; }
        .ag-t tbody tr.pick { cursor: pointer; }
        .ag-t tbody tr.on { background: var(--purple-dim); }
        .ag-name { font-weight: 600; color: var(--text-primary, inherit); }
        .ag-chips { display: flex; gap: 8px; flex-wrap: wrap; }
        .ag-chip { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); padding: 7px 12px; border-radius: 8px; font-size: 12px; font-weight: 600; cursor: pointer; }
        .ag-chip.on { background: var(--purple-dim); border-color: rgba(var(--brand-rgb), 0.3); color: var(--purple); }
        h4 { margin: 12px 0 6px; font-size: 12.5px; }
        .pos { color: var(--profit, #16a34a); }
        .neg { color: var(--loss, #dc2626); }
      `}</style>
    </div>
  );
}
