"use client";

import { useState } from "react";
import GlassPanel from "../../../components/GlassPanel";
import { API, ago, num, pct, share, statusClass, useDesk } from "./desk";

const STAGES = [
  ["PRE", "Before 09:15", "Universe, previous closes, F&O list, announcements, results calendar, morning brief"],
  ["0915", "09:15", "Opening prices, gaps, quote coverage"],
  ["0920", "09:20", "First five-minute bar: same-time volume, gap continuation or rejection, early breadth"],
  ["0930", "09:30", "Opening range, sectors vs NIFTY, stocks vs sector, provisional lists"],
  ["0940", "09:40", "Does leadership persist? Rotation, narrowing, failed breakouts"],
  ["0945", "09:45", "Trade plan published (no order is placed by the plan)"],
];

function Inputs({ inputs }: { inputs: any }) {
  const rows = Object.entries(inputs || {});
  if (!rows.length) return <p className="pis-muted">No inputs recorded yet today.</p>;
  return (
    <table className="pis-table">
      <thead><tr><th>Input</th><th>Status</th><th>Detail</th></tr></thead>
      <tbody>
        {rows.map(([k, v]: [string, any]) => {
          const st = String(v?.status ?? "");
          const ok = st.startsWith("ok");
          const detail = Object.entries(v || {}).filter(([kk]) => !["status", "stream"].includes(kk))
            .map(([kk, vv]) => `${kk.replace(/_/g, " ")}: ${typeof vv === "number" && vv > 1e9 ? ago(vv) : typeof vv === "object" ? JSON.stringify(vv)?.slice(0, 80) : String(vv)}`)
            .join(" · ");
          return (
            <tr key={k}>
              <td className="pis-strong">{k.replace(/_/g, " ")}</td>
              <td><span className={ok ? "pis-pill pis-pill-good" : "pis-pill pis-pill-warn"}>{st || "—"}</span></td>
              <td className="pis-wrap pis-small">{detail}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function StageSummary({ id, cp }: { id: string; cp: any }) {
  if (!cp) return <span className="pis-muted">not reached yet</span>;
  if (id === "PRE") {
    return <span>{cp.universe} stocks in the universe ({cp.excluded_count} excluded) · {Object.keys(cp.catalysts || {}).length} with
      {" "}a material announcement since the last close · {cp.results_today?.length ?? 0} on today’s results calendar</span>;
  }
  if (id === "0915") {
    return <span>opening prices for {share(cp.coverage)} of the universe · {cp.gap_up} gapped up, {cp.gap_down} down ·
      {" "}{cp.watchlist?.length ?? 0} on the opening watchlist{cp.set_aside?.length ? ` · ${cp.set_aside.length} set aside (probable corporate action)` : ""}</span>;
  }
  if (id === "0920") {
    return <span>first bar for {cp.with_first_bar} stocks · breadth {cp.breadth?.adv} up / {cp.breadth?.dec} down ·
      {" "}{cp.unusual_volume?.length ?? 0} with 2x+ same-time volume · {cp.gap_rejection?.length ?? 0} gaps rejected</span>;
  }
  if (id === "0930") {
    const strong = (cp.sectors || []).filter((s: any) => s.strong).map((s: any) => s.sector);
    const weak = (cp.sectors || []).filter((s: any) => s.weak).map((s: any) => s.sector);
    return <span>market <b>{cp.market?.condition}</b> · strong: {strong.join(", ") || "none"} · weak: {weak.join(", ") || "none"}</span>;
  }
  if (id === "0940") {
    return <span>market <b>{cp.market?.condition}</b> · {cp.rotation?.length ? cp.rotation.join("; ") : "no rotation in the top two"} ·
      {" "}{cp.narrowing?.length ?? 0} sectors narrowing · {cp.failed_breakouts?.length ?? 0} failed breakouts</span>;
  }
  if (id === "0945") {
    return <span>{cp.setups?.length ?? 0} setups{cp.no_trade?.length ? ` · ${cp.no_trade.join("; ")}` : ""}</span>;
  }
  return null;
}

export default function PlanView() {
  const { data: day, error, reload, loading } = useDesk<any>(`${API}/day`, 30_000);
  const [open, setOpen] = useState<string | null>("0945");
  const cps = day?.checkpoints || {};
  const plan = cps["0945"];
  return (
    <div className="pis-col">
      <GlassPanel title={`Today's trade plan${day?.day ? ` · ${day.day}` : ""}`} onRefresh={reload} refreshing={loading}
        note={day?.progress ? `last bar ${day.progress.done_k >= 0 ? day.progress.done_k : "—"} · ${day.status}` : undefined}>
        {error && <p className="pis-err">{error}</p>}
        {!day?.day && !error && (
          <div className="pis-empty">
            <b>No trading day recorded yet.</b> The desk starts at 08:40 IST on NSE trading days: it builds the universe and
            checks its inputs, then screens at 09:15, 09:20, 09:30 and 09:40 and publishes the plan at 09:45. Nothing
            appears here until its first session.
          </div>
        )}
        {day?.day && (
          <>
            <p className="pis-note">
              The plan never places an order. A setup enters only when its trigger fires on a closed five-minute bar and
              that price is inside its entry range; a price beyond the range is recorded as a missed setup. Only Portfolio
              Eligible strategies may enter the shared portfolio; every other setup is followed in its strategy’s own
              observation book.
            </p>
            {day.restarted_at && (
              <p className="pis-warnline">The desk restarted at {new Date(day.restarted_at * 1000).toLocaleTimeString("en-IN")}:
                nothing was entered for bars before bar {day.restart_resume_k}; exits in the gap were applied and flagged.</p>
            )}
            <div className="pis-timeline">
              {STAGES.map(([id, at, what]) => (
                <button key={id} className={`pis-stage${cps[id] ? " done" : ""}${open === id ? " on" : ""}`}
                  onClick={() => setOpen(open === id ? null : id)}>
                  <span className="pis-stage-at">{at}</span>
                  <span className="pis-stage-what">{what}</span>
                  <span className="pis-stage-sum"><StageSummary id={id} cp={cps[id]} /></span>
                </button>
              ))}
            </div>
            {open === "PRE" && cps.PRE && (
              <div className="pis-detail">
                <h4>Inputs at {cps.PRE.computed_at ? new Date(cps.PRE.computed_at * 1000).toLocaleTimeString("en-IN") : "—"}</h4>
                <Inputs inputs={cps.PRE.inputs} />
                {Object.keys(cps.PRE.catalysts || {}).length > 0 && (
                  <>
                    <h4>Material announcements since the last close</h4>
                    <ul className="pis-list">
                      {Object.entries(cps.PRE.catalysts).slice(0, 30).map(([s, v]: [string, any]) => (
                        <li key={s}><b>{s}</b>: {v.map((x: any) => `${x.desc} (${String(x.at).slice(11, 16)})`).join("; ")}</li>
                      ))}
                    </ul>
                  </>
                )}
              </div>
            )}
            {open === "0915" && cps["0915"] && (
              <div className="pis-detail">
                <p className="pis-small pis-muted">{cps["0915"].spreads}</p>
                <table className="pis-table">
                  <thead><tr><th>Stock</th><th>Sector</th><th className="r">Gap</th><th className="r">Gap / ATR</th><th>Catalyst</th></tr></thead>
                  <tbody>{(cps["0915"].watchlist || []).map((r: any) => (
                    <tr key={r.symbol}><td className="pis-strong">{r.symbol}</td><td>{r.sector}</td>
                      <td className={`r ${r.gap_pct > 0 ? "pis-up" : "pis-down"}`}>{pct(r.gap_pct)}</td><td className="r">{num(r.gap_atr)}</td>
                      <td>{r.catalyst ? "yes" : "—"}</td></tr>))}</tbody>
                </table>
              </div>
            )}
            {open === "0940" && cps["0940"] && (
              <div className="pis-detail">
                <h4>Dropped at the 09:40 check</h4>
                <ul className="pis-list">
                  {Object.entries(cps["0940"].dropped || {}).flatMap(([k, v]: [string, any]) =>
                    v.map((x: any) => <li key={`${k}${x.symbol}`}><b>{k.split("|")[0]}</b> {x.symbol}: {x.why}</li>))}
                </ul>
              </div>
            )}
            {plan && (
              <>
                <h4 className="pis-h4">The plan at 09:45</h4>
                {plan.no_trade?.length > 0 && <div className="pis-empty"><b>No trade for the portfolio:</b> {plan.no_trade.join("; ")}</div>}
                {plan.setups?.length > 0 && (
                  <div className="pis-scroll">
                    <table className="pis-table">
                      <thead><tr><th>Strategy</th><th>Stock</th><th>Side</th><th>Why selected</th><th>Trigger</th>
                        <th>Entry range</th><th>Stop</th><th className="r">Target</th><th>Window · exit</th><th>Status</th></tr></thead>
                      <tbody>{plan.setups.map((s: any, i: number) => (
                        <tr key={i}>
                          <td className="pis-strong">{s.strategy} <span className="pis-muted pis-small">{s.level} {s.variant}</span></td>
                          <td className="pis-strong">{s.symbol}<div className="pis-small pis-muted">{s.sector}</div></td>
                          <td className={s.side === "LONG" ? "pis-up" : "pis-down"}>{s.side}</td>
                          <td className="pis-wrap pis-small">{s.reason}</td>
                          <td className="pis-small">{s.trigger?.type === "vwap_pullback" ? "pullback to VWAP, close back beyond it" :
                            `${s.trigger?.type === "close_above" ? "close above" : "close below"} ${num(s.trigger?.level)}`}</td>
                          <td className="pis-small">{s.entry_range?.[0] != null ? `${num(s.entry_range[0])} – ${num(s.entry_range[1])}` : "within 0.60% of VWAP"}</td>
                          <td className="pis-small">{s.stop_rule?.type === "price" ? num(s.stop_rule.price) : s.stop_rule?.type}
                            {" "}({s.risk_band_pct?.[0]}–{s.risk_band_pct?.[1]}%)</td>
                          <td className="r">{s.target_R}R{s.target_cap ? ` or ${num(s.target_cap)}` : ""}</td>
                          <td className="pis-small">{s.window?.[0]}–{s.window?.[1]} · out {s.time_exit}</td>
                          <td><span className={statusClass(s.status)}>{s.status}</span></td>
                        </tr>))}</tbody>
                    </table>
                  </div>
                )}
              </>
            )}
            <h4 className="pis-h4">Data inputs (latest)</h4>
            <Inputs inputs={day.inputs} />
          </>
        )}
      </GlassPanel>
    </div>
  );
}
