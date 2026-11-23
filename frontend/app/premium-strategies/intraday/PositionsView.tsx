"use client";

import GlassPanel from "../../../components/GlassPanel";
import { API, ago, hm, inr, num, tone, useDesk } from "./desk";

export default function PositionsView({ status }: { status: any }) {
  const { data: open, reload, loading } = useDesk<any>(`${API}/positions?status=OPEN`, 30_000);
  const { data: books } = useDesk<any>(`${API}/books`, 60_000);
  const port = (books?.books || []).find((b: any) => b.id === "portfolio");
  const obs = (books?.books || []).filter((b: any) => b.id !== "portfolio");
  const alerts = status?.alerts || [];
  const cap = 1_000_000;
  return (
    <div className="pis-col">
      {alerts.length > 0 && (
        <div className="pis-alert">
          <b>Needs attention</b>
          <ul className="pis-list">{alerts.map((a: any) => (
            <li key={a.id}>{a.type === "failed_exit" ? `UNRESOLVED EXPOSURE: ${a.symbol} ${a.side} ${a.qty} shares in ${a.book} - no price at 15:05/15:10, closed on paper at the last known price ${a.last_price} (${a.at})` : (a.message || a.type)}
              <span className="pis-muted"> · {ago(a.t)}</span></li>))}</ul>
        </div>
      )}
      <GlassPanel title="Shared portfolio (Rs 10 lakh virtual)" note="admits Portfolio Eligible strategies only">
        <div className="pis-tiles">
          <div className="pis-tile"><span className="pis-tile-label">Equity</span><span className="pis-tile-val">{inr(port?.equity ?? cap)}</span>
            <span className={`pis-small ${tone((port?.equity ?? cap) - cap)}`}>{inr((port?.equity ?? cap) - cap)} since the start</span></div>
          <div className="pis-tile"><span className="pis-tile-label">Today</span><span className={`pis-tile-val ${tone(port?.day_realized)}`}>{inr(port?.day_realized ?? 0)}</span>
            <span className="pis-small pis-muted">realised</span></div>
          <div className="pis-tile"><span className="pis-tile-label">Open positions</span><span className="pis-tile-val">{port?.open ?? 0} / 3</span>
            <span className="pis-small pis-muted">stop risk {inr(port?.open_risk ?? 0)} of {inr(cap * 0.0075)}</span></div>
          <div className="pis-tile"><span className="pis-tile-label">Entries</span><span className="pis-tile-val">{port?.blocked ? "blocked" : "allowed"}</span>
            <span className="pis-small pis-muted">{port?.blocked || "no eligible strategy yet: nothing enters"}</span></div>
        </div>
        <p className="pis-note">Limits: 0.25% planned risk a trade, 0.75% total open stop risk, 3 positions, 2 per sector, new entries stop
          after a 1% daily loss and after 14:30; square-off from 15:05, flat by 15:10. Switching the desk OFF stops new scans and
          entries; open paper positions are still managed to their exits.</p>
      </GlassPanel>
      <GlassPanel title="Open paper positions" onRefresh={reload} refreshing={loading}>
        {!open?.rows?.length ? <div className="pis-empty">No open paper position.</div> : (
          <div className="pis-scroll">
            <table className="pis-table">
              <thead><tr><th>Book</th><th>Stock</th><th>Side</th><th className="r">Qty</th><th className="r">Entry</th><th className="r">Stop</th>
                <th className="r">Target</th><th className="r">Notional</th><th className="r">Planned risk</th><th>Entered</th><th>Exit by</th></tr></thead>
              <tbody>{open.rows.map((p: any) => (
                <tr key={p.id}><td className="pis-small">{p.book}</td><td className="pis-strong">{p.symbol}<div className="pis-small pis-muted">{p.sector}</div></td>
                  <td className={p.side > 0 ? "pis-up" : "pis-down"}>{p.side > 0 ? "LONG" : "SHORT"}</td>
                  <td className="r">{p.qty}{p.partial ? <span className="pis-pill pis-pill-warn">partial</span> : null}</td>
                  <td className="r">{num(p.entry)}</td><td className="r">{num(p.stop)}</td><td className="r">{p.target ? num(p.target) : "—"}</td>
                  <td className="r">{inr(p.notional)}</td><td className="r">{inr(p.planned_risk)}</td><td>{hm(p.t_entry)}</td>
                  <td className="pis-small">{String(Math.floor(p.time_exit_min / 60)).padStart(2, "0")}:{String(p.time_exit_min % 60).padStart(2, "0")}</td></tr>))}</tbody>
            </table>
          </div>
        )}
      </GlassPanel>
      <GlassPanel title="Observation books (each strategy's own Rs 10 lakh, same limits)">
        {!obs.length ? <div className="pis-empty">The observation books appear after the desk’s first session.</div> : (
          <div className="pis-scroll">
            <table className="pis-table">
              <thead><tr><th>Book</th><th className="r">Equity</th><th className="r">Since start</th><th className="r">Today</th><th className="r">Open</th><th>Entries</th></tr></thead>
              <tbody>{obs.map((b: any) => (
                <tr key={b.id}><td className="pis-strong">{b.id}</td><td className="r">{inr(b.equity)}</td>
                  <td className={`r ${tone(b.equity - cap)}`}>{inr(b.equity - cap)}</td><td className={`r ${tone(b.day_realized)}`}>{inr(b.day_realized)}</td>
                  <td className="r">{b.open}</td><td className="pis-small">{b.blocked || "allowed"}</td></tr>))}</tbody>
            </table>
          </div>
        )}
      </GlassPanel>
    </div>
  );
}
