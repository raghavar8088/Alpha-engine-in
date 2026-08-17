"use client";

import { useCallback, useEffect, useState } from "react";
import GlassPanel from "./GlassPanel";
import LineChart from "./charts/LineChart";
import { fetchDeskHistory, type DeskHistory as History } from "../lib/api";

/**
 * Since-inception history for any desk: when it started, how long it has run, the equity
 * curve, and per-day P&L with both ROI denominators.
 *
 * One component for every module because the questions are identical everywhere — writing
 * it per page would guarantee each desk eventually defined "ROI" slightly differently.
 */
export default function DeskHistory({
  deskKey,
  scope,
  title = "History",
}: {
  deskKey: string;
  scope?: string | null;
  title?: string;
}) {
  const [h, setH] = useState<History | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    async (fresh = false) => {
      try {
        setH(await fetchDeskHistory(deskKey, scope ?? undefined, fresh));
        setErr(null);
      } catch (e) {
        setErr(e instanceof Error ? e.message : "Could not load history");
      }
    },
    [deskKey, scope],
  );

  useEffect(() => {
    load();
    const id = setInterval(() => load(), 60000);
    return () => clearInterval(id);
  }, [load]);

  async function refresh() {
    setBusy(true);
    try {
      await load(true);
    } finally {
      setBusy(false);
    }
  }

  const inr = (v: number | null | undefined) =>
    v === null || v === undefined ? "—" : `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
  const signed = (v: number | null | undefined) =>
    v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
  const pc = (v: number | null | undefined, dp = 3) =>
    v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(dp)}%`;
  const cls = (v: number | null | undefined) =>
    v === null || v === undefined ? "" : v >= 0 ? "gain" : "loss";

  if (err) return <GlassPanel title={title}><div className="empty">{err}</div></GlassPanel>;
  if (!h) return <GlassPanel title={title}><div className="empty">Loading…</div></GlassPanel>;
  if (!h.started_on)
    return <GlassPanel title={title}><div className="empty">This desk has not closed a trade yet.</div></GlassPanel>;

  return (
    <>
      <GlassPanel title={title} onRefresh={refresh} refreshing={busy}>
        <div className="hstats">
          <div className="hs"><span>Trading since</span><b>{h.started_on}</b><i>{h.days_live} days ago</i></div>
          <div className="hs"><span>Days traded</span><b>{h.days_traded}</b><i>of {h.days_live} calendar days</i></div>
          <div className="hs"><span>Avg / trading day</span><b className={cls(h.avg_per_trading_day)}>{signed(h.avg_per_trading_day)}</b><i>{pc(h.avg_roi_per_trading_day_pct, 4)} of capital</i></div>
          <div className="hs"><span>Avg / calendar day</span><b className={cls(h.avg_per_calendar_day)}>{signed(h.avg_per_calendar_day)}</b><i>incl. days it did not trade</i></div>
          <div className="hs"><span>Total ROI</span><b className={cls(h.roi_pct)}>{pc(h.roi_pct)}</b><i>on {inr(h.capital)}</i></div>
          <div className="hs">
            <span>ROI on deployed</span>
            <b className={cls(h.deployed_roi_pct)}>{pc(h.deployed_roi_pct, 2)}</b>
            <i>{h.deployed_known ? "of capital at risk" : "not reconstructable"}</i>
          </div>
          <div className="hs"><span>Trades</span><b>{h.trades.toLocaleString("en-IN")}</b><i>{(h.win_rate * 100).toFixed(1)}% win</i></div>
          <div className="hs"><span>Open now</span><b>{h.open_positions}</b><i>{inr(h.deployed_now)} at risk</i></div>
        </div>
        {h.deployed_note && <p className="hnote">{h.deployed_note}.</p>}
      </GlassPanel>

      <GlassPanel title="Equity" note={h.curve_is_derived ? "derived from closed trades — steps on each close" : undefined}>
        {h.curve.length < 2 ? (
          <div className="empty">Not enough points to draw a curve yet.</div>
        ) : (
          <LineChart
            points={h.curve.map((p) => ({ ts: p.ts, value: p.value }))}
            height={210}
            formatValue={(v) => `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`}
          />
        )}
      </GlassPanel>

      <GlassPanel title="Daily P&L and ROI">
        {!h.daily.length ? (
          <div className="empty">No closed sessions yet.</div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Date</th><th>Trades</th><th>Win %</th>
                  <th>Deployed</th><th>Fees</th><th>Net P&amp;L</th>
                  <th>ROI (capital)</th><th>ROI (deployed)</th>
                </tr>
              </thead>
              <tbody>
                {h.daily.map((d) => (
                  <tr key={d.date}>
                    <td style={{ textAlign: "left" }}>{d.date}</td>
                    <td>{d.trades}</td>
                    <td>{(d.win_rate * 100).toFixed(0)}%</td>
                    <td>{d.deployed ? inr(d.deployed) : "—"}</td>
                    <td className={d.fees ? "loss" : ""}>{d.fees ? `−${inr(d.fees)}` : "—"}</td>
                    <td className={cls(d.realized_pnl)}>{signed(d.realized_pnl)}</td>
                    <td className={cls(d.roi_pct)}>{pc(d.roi_pct, 4)}</td>
                    <td className={cls(d.deployed_roi_pct)}>{pc(d.deployed_roi_pct, 2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>

      <style jsx>{`
        .hstats { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); padding: 14px 16px; }
        .hs { display: flex; flex-direction: column; gap: 2px; }
        .hs span { font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); }
        .hs b { font-family: var(--font-data); font-variant-numeric: tabular-nums; font-size: 17px; font-weight: 700; }
        .hs i { font-size: 10.5px; color: var(--text-faint); font-style: normal; }
        .hnote { margin: 0; padding: 0 16px 14px; font-size: 11px; line-height: 1.6; color: var(--text-faint); }
        .empty { padding: 18px 20px; font-size: 12px; color: var(--text-faint); text-align: center; }
        .table-scroll { overflow-x: auto; max-height: 460px; overflow-y: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; }
        .data-table th { text-align: center; padding: 8px 10px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); position: sticky; top: 0; background: var(--panel); }
        .data-table td { padding: 7px 10px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
      `}</style>
    </>
  );
}
