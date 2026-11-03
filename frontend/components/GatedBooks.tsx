"use client";

/* Gated paper accounts — Phase 4 of INTRADAY_STOCKS_AI_UPGRADE_PLAN.md.
   Two Rs 10 lakh books copy the tournament's positions through risk-based sizing, exposure
   and loss limits; every refusal is recorded with its reason. Self-contained styles: the
   page's tile classes are scoped to the page component. */

import { useEffect, useState } from "react";
import { apiFetch } from "../lib/api";

type OpenCopy = { strategy_id: string; symbol: string; side: string; qty: number; entry_price: number; sector?: string };
type GatedBook = {
  book: string; label: string; capital: number; equity: number; realized: number; return_pct: number;
  drawdown_pct: number; today_pnl: number; trades: number; win_rate: number | null; open: OpenCopy[];
  today_decisions: Record<string, number>; rules: string[] | "all";
};
type GatedSummary = {
  enabled: boolean; why_off?: string; config_version: string; config: Record<string, number>; books: GatedBook[];
};

const inr = (v?: number | null) =>
  v === null || v === undefined ? "-" : v.toLocaleString("en-IN", { maximumFractionDigits: 0 });
const sign = (v: number) => (v > 0 ? "gb-gain" : v < 0 ? "gb-loss" : "");

export default function GatedBooks() {
  const [data, setData] = useState<GatedSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const r = (await apiFetch("/api/intraday-lab/v2/gated")) as GatedSummary;
        if (alive) {
          setData(r);
          setError(null);
        }
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : "could not load");
      }
    };
    load();
    const id = setInterval(load, 60000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  // A 404 means the backend serving the page predates the gated books: show nothing yet.
  if (error && !data) return /404|not found/i.test(error) ? null : <div className="gb-note">Gated paper accounts: {error}</div>;
  if (!data) return null;
  if (!data.enabled) return <div className="gb-note">Gated paper accounts are off: {data.why_off}</div>;

  return (
    <section className="gb">
      <div className="gb-head">
        <strong>Gated paper accounts</strong>{" "}
        <span className="gb-muted">
          (Phase 4) · the tournament&rsquo;s trades copied through risk-based size ({data.config.risk_per_trade_pct}% of
          equity a trade), reward ≥ {data.config.min_reward_to_risk}× risk after costs, ≤ {data.config.max_open} open,
          ≤ {data.config.max_open_risk_pct}% at risk, one per stock, ≤ {data.config.max_per_sector} per industry, a{" "}
          {data.config.daily_loss_stop_pct}% daily stop and a {data.config.drawdown_pause_pct}% drawdown pause ·
          gates v{data.config_version}
        </span>
      </div>
      <div className="gb-books">
        {data.books.map((b) => (
          <div className="gb-book" key={b.book}>
            <div className="gb-title">{b.label} · ₹{inr(b.capital)}</div>
            <div className="gb-row">
              <div><div className="gb-k">Equity</div><div className="gb-v">₹{inr(b.equity)}</div></div>
              <div><div className="gb-k">Return</div><div className={`gb-v ${sign(b.return_pct)}`}>{b.return_pct.toFixed(2)}%</div></div>
              <div><div className="gb-k">Today</div><div className={`gb-v ${sign(b.today_pnl)}`}>₹{inr(b.today_pnl)}</div></div>
              <div><div className="gb-k">Trades</div><div className="gb-v">{b.trades}</div></div>
              <div><div className="gb-k">Win rate</div><div className="gb-v">{b.win_rate === null ? "-" : `${(b.win_rate * 100).toFixed(0)}%`}</div></div>
              <div><div className="gb-k">Drawdown</div><div className="gb-v">{b.drawdown_pct.toFixed(2)}%</div></div>
            </div>
            <div className="gb-k">Open ({b.open.length})</div>
            <div className="gb-list">
              {b.open.length === 0
                ? "none"
                : b.open.map((o) => `${o.symbol} ${o.side} ${o.qty} @ ${o.entry_price.toFixed(2)} (${o.strategy_id.replace("iv2_", "")})`).join(" · ")}
            </div>
            <div className="gb-k">Today&rsquo;s decisions</div>
            <div className="gb-list">
              {Object.keys(b.today_decisions).length === 0
                ? "none yet"
                : Object.entries(b.today_decisions).sort((x, y) => y[1] - x[1]).map(([k, n]) => `${k}: ${n}`).join(" · ")}
            </div>
          </div>
        ))}
      </div>
      <style jsx>{`
        .gb { margin: 12px 0; border: 1px solid var(--border, #2a2f3a); border-radius: 8px; padding: 10px 12px; }
        .gb-head { font-size: 13px; margin-bottom: 8px; }
        .gb-muted, .gb-note { color: var(--muted, #8b93a7); font-size: 12px; }
        .gb-books { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 10px; }
        .gb-book { border: 1px solid var(--border, #2a2f3a); border-radius: 6px; padding: 8px 10px; }
        .gb-title { font-weight: 600; font-size: 13px; margin-bottom: 6px; }
        .gb-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px 10px; margin-bottom: 8px; }
        .gb-k { color: var(--muted, #8b93a7); font-size: 11px; text-transform: uppercase; letter-spacing: 0.03em; }
        .gb-v { font-size: 15px; font-weight: 600; }
        .gb-gain { color: var(--gain, #16a34a); }
        .gb-loss { color: var(--loss, #dc2626); }
        .gb-list { font-size: 12px; margin-bottom: 6px; word-break: break-word; }
      `}</style>
    </section>
  );
}
