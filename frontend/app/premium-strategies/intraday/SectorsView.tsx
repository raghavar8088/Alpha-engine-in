"use client";

import { useState } from "react";
import GlassPanel from "../../../components/GlassPanel";
import { API, num, pct, share, tone, useDesk } from "./desk";

export default function SectorsView() {
  const { data: day, error, reload, loading } = useDesk<any>(`${API}/day`, 30_000);
  const [at, setAt] = useState<"0930" | "0940">("0930");
  const cp = day?.checkpoints?.[at];
  const mk = cp?.market;
  const first = day?.checkpoints?.["0920"];
  return (
    <div className="pis-col">
      <GlassPanel title={`Sector strength and weakness${day?.day ? ` · ${day.day}` : ""}`} onRefresh={reload} refreshing={loading}>
        <div className="pis-chips">
          {(["0930", "0940"] as const).map((x) => (
            <button key={x} className={`pis-chip${at === x ? " on" : ""}`} onClick={() => setAt(x)}>
              {x === "0930" ? "09:30 ranking" : "09:40 persistence"}
            </button>
          ))}
        </div>
        {error && <p className="pis-err">{error}</p>}
        {!cp && !error && (
          <div className="pis-empty">The {at === "0930" ? "09:30" : "09:40"} sector table appears once that checkpoint has run today.</div>
        )}
        {mk && (
          <div className="pis-tiles">
            <div className="pis-tile"><span className="pis-tile-label">Market condition</span>
              <span className="pis-tile-val">{mk.condition.replace("_", " ")}</span><span className="pis-small pis-muted">{mk.why}</span></div>
            <div className="pis-tile"><span className="pis-tile-label">NIFTY since 09:15</span>
              <span className={`pis-tile-val ${tone(mk.nifty_ret_open)}`}>{pct(mk.nifty_ret_open)}</span>
              <span className="pis-small pis-muted">vs previous close {pct(mk.nifty_ret_pc)}</span></div>
            <div className="pis-tile"><span className="pis-tile-label">Advance / decline</span>
              <span className="pis-tile-val">{mk.adv} / {mk.dec}</span>
              <span className="pis-small pis-muted">{share(mk.up_open)} above their open · {share(mk.above_vwap)} above VWAP</span></div>
            <div className="pis-tile"><span className="pis-tile-label">Coverage</span>
              <span className="pis-tile-val">{share(mk.coverage)}</span>
              <span className="pis-small pis-muted">{mk.with_data} of {mk.members} stocks have every bar</span></div>
          </div>
        )}
        {cp?.sectors && (
          <div className="pis-scroll">
            <table className="pis-table">
              <thead><tr><th className="r">Rank</th><th>Sector</th><th className="r">vs NIFTY</th><th>Measured on</th>
                <th className="r">Above open</th><th className="r">A / D</th><th className="r">Above VWAP</th>
                <th className="r">Volume</th><th className="r">Coverage</th><th>Largest contributors</th><th>Read</th></tr></thead>
              <tbody>{cp.sectors.map((s: any) => (
                <tr key={s.sector} className={s.strong ? "pis-row-strong" : s.weak ? "pis-row-weak" : ""}>
                  <td className="r">{s.rank ?? "—"}</td>
                  <td className="pis-strong">{s.sector}{s.strong && <span className="pis-pill pis-pill-good">strong</span>}
                    {s.weak && <span className="pis-pill pis-pill-bad">weak</span>}</td>
                  <td className={`r ${tone(s.rel)}`}>{pct(s.rel)}</td>
                  <td className="pis-small">{s.ret_source === "index" ? s.index : "its members"}</td>
                  <td className="r">{share(s.up_open)}</td>
                  <td className="r">{s.adv} / {s.dec}</td>
                  <td className="r">{share(s.above_vwap)}</td>
                  <td className="r">{s.rvol_med != null ? `${num(s.rvol_med, 1)}x` : "—"}</td>
                  <td className="r">{s.with_data}/{s.members}</td>
                  <td className="pis-small pis-wrap">{(s.top || []).map((t: any) =>
                    `${t.symbol} ${pct(t.ret_open, 1)} (${share(t.weight)} weight)`).join(", ")}
                    {s.top_share != null && <div className="pis-muted">largest share of the move {share(s.top_share)}</div>}</td>
                  <td className="pis-small pis-wrap">
                    {s.narrow && <span className="pis-pill pis-pill-warn">narrow</span>}
                    {s.heavyweight && <span className="pis-pill pis-pill-warn">one stock carries it</span>}
                    <div className="pis-muted">{s.why}</div></td>
                </tr>))}</tbody>
            </table>
          </div>
        )}
        {at === "0940" && cp && (
          <div className="pis-detail">
            <h4>What changed since 09:30</h4>
            <ul className="pis-list">
              <li>Rotation: {cp.rotation?.length ? cp.rotation.join("; ") : "none in the top two"}</li>
              <li>Narrowing participation: {cp.narrowing?.length ? cp.narrowing.map((n: any) => `${n.sector} ${share(n.from)} → ${share(n.to)}`).join("; ") : "none"}</li>
              <li>Failed breakouts (traded beyond the opening range, closed back inside): {cp.failed_breakouts?.length ? cp.failed_breakouts.map((f: any) => f.symbol).join(", ") : "none"}</li>
              <li>Widening spreads: {cp.spreads}</li>
            </ul>
          </div>
        )}
        {first?.diverging_from_sector?.length > 0 && (
          <div className="pis-detail">
            <h4>09:20: stocks moving against their sector</h4>
            <p className="pis-small">{first.diverging_from_sector.map((r: any) =>
              `${r.symbol} ${pct(r.first_bar_pct)} vs ${r.sector} ${pct(r.sector_median_pct)}`).join(" · ")}</p>
          </div>
        )}
        <p className="pis-note">
          A sector is read against its NSE sectoral index (banks against NIFTY BANK) and against its own members, so a move
          made by one heavyweight shows up as narrow: the index moving one way while most members move the other. A narrow
          sector cannot confirm a setup.
        </p>
      </GlassPanel>
    </div>
  );
}
