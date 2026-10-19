"use client";

import GlassPanel from "../../components/GlassPanel";
import type { AcAnalytics, AcSummary } from "../../lib/api";
import { Tile, num } from "./ui";

export default function OrdersTab({ data, analytics }: { data: AcSummary; analytics: AcAnalytics | null }) {
  const o = analytics?.orders;
  const today = data.today.orders;
  const st = o?.by_status ?? {};
  const slip = o?.limit_fill_vs_limit_price;
  return (
    <>
      <GlassPanel title="Orders" note="every MCX order the page has seen since it began recording">
        {o && o.orders ? (
          <>
            <div className="tiles">
              <Tile label="Orders" value={String(o.orders)} sub={Object.entries(o.by_type).map(([k, v]) => `${v} ${k}`).join(" · ")} />
              <Tile label="Completed" value={String(st.complete ?? 0)} valueClass="gain" />
              <Tile label="Rejected" value={String(st.rejected ?? 0)} valueClass={(st.rejected ?? 0) ? "loss" : ""} />
              <Tile label="Cancelled" value={String(st.cancelled ?? 0)} />
              <Tile label="Limit fills vs limit price" value={slip === null || slip === undefined ? "–" : `${slip <= 0 ? "" : "+"}${num(slip, 2)}`}
                valueClass={slip !== null && slip !== undefined ? (slip <= 0 ? "gain" : "loss") : ""}
                sub={`average over ${o.limit_fills} filled limit orders; negative = filled better than the limit`} />
            </div>
            {o.rejections.length > 0 && (
              <div className="rej">
                <div className="sub-title">Why orders were rejected</div>
                {o.rejections.map((r) => <div key={r.reason} className="rej-row"><b>{r.count}×</b> {r.reason}</div>)}
              </div>
            )}
          </>
        ) : <div className="empty">No orders recorded yet.</div>}
      </GlassPanel>

      <GlassPanel title={`Today's orders · ${data.today.date}`}>
        {today.length ? (
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th>Time</th><th className="l">Contract</th><th>Side</th><th>Type</th><th>Product</th><th>Qty</th><th>Filled</th><th>Limit</th><th>Avg fill</th><th>Status</th><th className="l">Note</th></tr></thead>
              <tbody>{today.map((x) => (
                <tr key={x.orderid}>
                  <td className="small">{x.time}</td><td className="l">{x.tradingsymbol}</td>
                  <td className={x.side === "BUY" ? "gain" : "loss"}>{x.side}</td><td>{x.ordertype}</td><td className="small">{x.product}</td>
                  <td>{x.qty}</td><td>{x.filled}</td><td>{x.price ? num(x.price) : "–"}</td><td>{x.avg_price ? num(x.avg_price) : "–"}</td>
                  <td className={x.status === "rejected" ? "loss" : x.status === "complete" ? "gain" : ""}>{x.status}</td>
                  <td className="l small muted">{x.text}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : <div className="empty">No MCX orders today.</div>}
      </GlassPanel>
      <style jsx>{`
        .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; }
        .sub-title { font-size: 11.5px; color: var(--text-muted); margin: 12px 0 4px; font-weight: 600; }
        .rej-row { font-size: 12px; padding: 4px 0; border-bottom: 1px solid var(--canvas-soft); }
        .table-scroll { overflow-x: auto; max-height: 520px; overflow-y: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; }
        .data-table th { text-align: center; padding: 8px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); position: sticky; top: 0; background: var(--panel); }
        .data-table td { padding: 7px 8px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .data-table .l { text-align: left; }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
        .small { font-size: 11px; }
        .muted { color: var(--text-muted); }
        .empty { padding: 22px; text-align: center; color: var(--text-faint); font-size: 12.5px; }
      `}</style>
    </>
  );
}
