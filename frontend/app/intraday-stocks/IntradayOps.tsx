"use client";

import { useCallback, useEffect, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import { fetchEdgeReport, fetchIntradayAlarms, type EdgeReport, type OpsAlarm } from "../../lib/api";

const LABEL: Record<string, string> = {
  stream_down: "Live stream down",
  v2_engine_stalled: "v2 engine stalled",
  universe_incomplete: "Universe not fully scanned",
  memory_high: "Backend memory high",
  angel_throttled: "Angel One throttling candle calls",
  stream_bars_inaccurate: "Live bars drifting from Angel's candles",
  history_incomplete: "Bar history incomplete",
  calendar_expiring: "NSE holiday list expiring",
  squareoff_missed: "Square-off missed",
  market_closed_unlisted: "Market closed (not on the holiday list)",
};

const inr = (v: number | null | undefined) =>
  v == null ? "-" : `${v < 0 ? "-" : ""}₹${Math.abs(Math.round(v)).toLocaleString("en-IN")}`;

function detailText(a: OpsAlarm): string {
  const d = a.detail || {};
  return Object.entries(d)
    .filter(([, v]) => v !== null && v !== undefined && typeof v !== "object")
    .slice(0, 4)
    .map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`)
    .join(" · ");
}

/** Active alarms as a banner — shown only when something is wrong now. */
export function AlarmBanner() {
  const [active, setActive] = useState<OpsAlarm[]>([]);
  const load = useCallback(async () => {
    try {
      setActive((await fetchIntradayAlarms(2)).active ?? []);
    } catch {
      /* the banner is advisory; the page has its own load errors */
    }
  }, []);
  useEffect(() => {
    load();
    const id = setInterval(load, 60000);
    return () => clearInterval(id);
  }, [load]);
  if (!active.length) return null;
  return (
    <div className="alarms">
      {active.map((a) => (
        <div key={a.id} className="alarm">
          <strong>{LABEL[a.kind] ?? a.kind}</strong>
          <span>{detailText(a)}</span>
        </div>
      ))}
      <style jsx>{`
        .alarms { display: flex; flex-direction: column; gap: 6px; }
        .alarm { display: flex; gap: 10px; flex-wrap: wrap; align-items: baseline; padding: 9px 12px;
                 border-radius: 10px; background: var(--loss-dim); border: 1px solid rgba(217, 45, 63, 0.3);
                 color: var(--loss); font-size: 12.5px; }
        .alarm span { color: var(--text-muted); font-size: 11.5px; }
      `}</style>
    </div>
  );
}

/** The latest daily edge report: where the desk's money went, and whether the forward
 *  record is living up to the backtest. */
export function EdgeReportPanel() {
  const [rep, setRep] = useState<EdgeReport | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      const r = await fetchEdgeReport();
      setRep("date" in r && r.date ? (r as EdgeReport) : null);
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "failed");
    } finally {
      setLoaded(true);
    }
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  const rows = rep?.strategies ?? [];
  const best = rows.slice(0, 5);
  const worst = rows.length > 5 ? rows.slice(-5).reverse() : [];
  const cal = rep?.calibration;

  return (
    <GlassPanel title={`Edge report${rep ? ` — ${rep.date}` : ""}`} onRefresh={load}>
      {!loaded ? (
        <div className="empty">Loading…</div>
      ) : err ? (
        <div className="empty">Couldn&rsquo;t load the edge report: {err}</div>
      ) : !rep ? (
        <div className="empty">The first report is written after the first v2 session closes (5 Oct 2026, ~15:50 IST).</div>
      ) : (
        <>
          <div className="tiles">
            <div><div className="k">Trades</div><div className="v">{rep.desk.trades}</div></div>
            <div><div className="k">Gross</div><div className={`v ${rep.desk.gross_pnl >= 0 ? "gain" : "loss"}`}>{inr(rep.desk.gross_pnl)}</div>
              <div className="s">after slippage, before fees</div></div>
            <div><div className="k">Slippage (est.)</div><div className="v loss">{inr(-rep.desk.slippage_est)}</div></div>
            <div><div className="k">Fees</div><div className="v loss">{inr(-rep.desk.fees)}</div></div>
            <div><div className="k">Net</div><div className={`v ${rep.desk.net_pnl >= 0 ? "gain" : "loss"}`}>{inr(rep.desk.net_pnl)}</div></div>
            <div><div className="k">Forward vs backtest</div>
              <div className={`v ${(cal?.median_gap_per_trade ?? 0) < 0 ? "loss" : "gain"}`}>
                {cal?.median_gap_per_trade != null ? `${inr(cal.median_gap_per_trade)}/trade` : "-"}
              </div>
              <div className="s">median gap over {cal?.strategies_compared ?? 0} strategies</div></div>
          </div>
          {rep.stream_quality?.close_bp && (
            <div className="note">
              Live bars vs Angel&rsquo;s candles: closes off by a median {rep.stream_quality.close_bp.median ?? "-"} bp
              (95th percentile {rep.stream_quality.close_bp.p95 ?? "-"} bp) over {rep.stream_quality.bars_compared} bars.
            </div>
          )}
          <div className="cols">
            {[["Best today", best], ["Worst today", worst]].map(([title, list]) => (
              <div key={title as string}>
                <div className="h">{title as string}</div>
                {(list as typeof rows).map((r) => (
                  <div key={r.strategy_id} className="row">
                    <span className="nm">{r.name}</span>
                    <span className="n">{r.trades} tr</span>
                    <span className={r.net_pnl >= 0 ? "gain" : "loss"}>{inr(r.net_pnl)}</span>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </>
      )}
      <style jsx>{`
        .empty { padding: 18px 20px; font-size: 12px; color: var(--text-faint); }
        .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px; padding: 4px 4px 10px; }
        .k { font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); }
        .v { font-size: 16px; font-weight: 700; margin-top: 2px; font-variant-numeric: tabular-nums; }
        .s { font-size: 10.5px; color: var(--text-muted); }
        .note { font-size: 12px; color: var(--text-muted); padding: 8px 12px; background: var(--canvas-soft); border-radius: 10px; margin-bottom: 8px; }
        .cols { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
        .h { font-size: 11px; font-weight: 700; margin: 6px 0; text-transform: uppercase; color: var(--text-muted); }
        .row { display: flex; gap: 8px; font-size: 12px; padding: 4px 0; border-bottom: 1px solid var(--canvas-soft); }
        .nm { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .n { color: var(--text-muted); }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
        @media (max-width: 640px) { .cols { grid-template-columns: 1fr; } }
      `}</style>
    </GlassPanel>
  );
}
