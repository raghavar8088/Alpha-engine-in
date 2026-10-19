"use client";

import GlassPanel from "../../components/GlassPanel";
import type { AcAnalytics } from "../../lib/api";
import { BarList, Tile, inr, num, plainPct } from "./ui";

const LABEL: Record<string, string> = {
  brokerage: "Brokerage (₹20 an order)", gst: "GST (18% of brokerage + MCX + SEBI)", exchange: "MCX transaction charge",
  ctt: "CTT (on sells)", stamp: "Stamp duty (on buys)", sebi: "SEBI fee",
};
const KEYS = ["brokerage", "exchange", "ctt", "stamp", "sebi", "gst"];

export default function ChargesTab({ analytics }: { analytics: AcAnalytics | null }) {
  const c = analytics?.charges;
  if (!c) return <GlassPanel title="Charges"><div className="empty">Loading…</div><style jsx>{`.empty { padding: 26px; text-align: center; color: var(--text-faint); }`}</style></GlassPanel>;
  const parts = KEYS.map((k) => [k, c.by_component[k] ?? 0] as [string, number]).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]);
  return (
    <>
      <GlassPanel title="What trading costs you" note="estimated per executed order from Angel's commodity rate card — the contract note is final">
        <div className="tiles">
          <Tile label="Charges so far" value={`−₹${c.total.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`} valueClass="loss" sub={`${c.orders} orders`} />
          <Tile label="Share of gross profit" value={plainPct(c.pct_of_gross_profit_days)} sub="charges ÷ the P&L of the days that made money" />
          <Tile label="Share of turnover" value={plainPct(c.pct_of_turnover, 3)} sub={`on ${inr(c.turnover)} traded`} />
          <Tile label="Per order" value={c.per_order !== null ? `₹${num(c.per_order)}` : "–"} sub="average" />
          <Tile label="Per completed trade" value={c.per_trade !== null ? `₹${num(c.per_trade)}` : "–"} sub="both sides" />
        </div>
        <div className="note">
          On small premiums the fixed ₹20 an order (₹23.60 with GST) dominates: a one-lot round trip pays about ₹47 before any
          percentage charge, so a trade has to make more than that just to break even.
        </div>
      </GlassPanel>

      <GlassPanel title="By component">
        <BarList rows={parts.map(([k, v]) => ({ key: k, label: LABEL[k] ?? k, value: -v }))} format={(v) => `−₹${Math.abs(v).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`} />
      </GlassPanel>

      <GlassPanel title="By day">
        <div className="table-scroll">
          <table className="data-table">
            <thead><tr><th>Date</th><th>Orders</th><th>Turnover</th>{KEYS.map((k) => <th key={k}>{k === "exchange" ? "MCX" : k.toUpperCase()}</th>)}<th>Total</th><th>Share of P&amp;L</th></tr></thead>
            <tbody>{c.days.map((d) => (
              <tr key={d.date}>
                <td>{d.date}</td><td>{d.orders ?? 0}</td><td>{inr(d.turnover)}</td>
                {KEYS.map((k) => <td key={k}>{num(d.breakdown?.[k] ?? 0)}</td>)}
                <td className="loss"><b>{num(d.charges)}</b></td>
                <td>{d.gross && d.gross > 0 ? plainPct(d.charges / d.gross) : "–"}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </GlassPanel>
      <style jsx>{`
        .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; }
        .note { font-size: 11.5px; color: var(--text-muted); padding: 10px 2px 0; line-height: 1.55; }
        .table-scroll { overflow-x: auto; max-height: 480px; overflow-y: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; }
        .data-table th { text-align: center; padding: 8px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); position: sticky; top: 0; background: var(--panel); }
        .data-table td { padding: 7px 8px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .loss { color: var(--loss); }
      `}</style>
    </>
  );
}
