"use client";

import GlassPanel from "../../components/GlassPanel";
import type { AcRisk } from "../../lib/api";
import { BarList, Kv, Tile, inr, num, plainPct, signed, tone } from "./ui";

export default function RiskTab({ risk, loading, error, onRefresh }: {
  risk: AcRisk | null; loading: boolean; error: string | null; onRefresh: () => void;
}) {
  if (!risk) {
    return (
      <GlassPanel title="Open positions — Greeks, margin and what-ifs">
        <div className="empty">{error ? `Could not build the risk view: ${error}` : "Re-quoting your open positions and asking Angel's margin calculator… (up to ~20 seconds)"}</div>
        <style jsx>{`.empty { padding: 26px; text-align: center; color: var(--text-faint); font-size: 12.5px; }`}</style>
      </GlassPanel>
    );
  }
  const rows = risk.positions;
  const tot = (k: "delta_rupees_1pct" | "theta_day" | "vega_point") => rows.reduce((s, r) => s + (r[k] ?? 0), 0);
  const sumMargin = rows.reduce((s, r) => s + (r.margin ?? 0), 0);
  const scen = risk.scenarios ?? [];
  return (
    <>
      <GlassPanel title="Open positions — Greeks, margin and what-ifs" note={risk.as_of ? `re-quoted ${new Date(risk.as_of).toLocaleTimeString()}` : undefined}>
        {rows.length ? (
          <>
            <div className="tiles">
              <Tile label="Net delta" value={signed(tot("delta_rupees_1pct"))} valueClass={tone(tot("delta_rupees_1pct"))}
                sub="₹ the book makes if every underlying rises 1%" />
              <Tile label="Theta" value={`${signed(tot("theta_day"))} / day`} valueClass={tone(tot("theta_day"))}
                sub="time decay over one calendar day, nothing else moving" />
              <Tile label="Vega" value={`${signed(tot("vega_point"))} / vol pt`} valueClass={tone(tot("vega_point"))}
                sub="if implied volatility rises one point" />
              <Tile label="Margin (Angel)" value={inr(risk.basket_margin)}
                sub={`whole basket · ${risk.basket_margin_source ?? ""} · Angel reports ${inr(risk.angel_in_use)} in use`} />
              <Tile label="One day, no move" value={signed(risk.one_day_no_move)} valueClass={tone(risk.one_day_no_move)} sub="re-priced one day closer to expiry" />
              <Tile label="Volatility −20% / +20%" value={<><span className={tone(risk.iv_minus_20pct)}>{signed(risk.iv_minus_20pct)}</span> / <span className={tone(risk.iv_plus_20pct)}>{signed(risk.iv_plus_20pct)}</span></>}
                sub="every option's implied volatility scaled, the future held" />
            </div>
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr><th className="l">Contract</th><th>Qty (lots)</th><th>Avg</th><th>LTP</th><th>Future</th><th>IV</th><th>Delta</th>
                    <th>₹ per 1%</th><th>Theta ₹/day</th><th>Vega ₹/pt</th><th>DTE</th><th>Moneyness</th><th>Breakeven</th>
                    <th>Intrinsic / time</th><th>Margin</th></tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.tradingsymbol}>
                      <td className="l"><b>{r.tradingsymbol}</b><div className="small muted">{r.product}</div></td>
                      <td className={r.qty > 0 ? "gain" : "loss"}>{r.qty.toLocaleString("en-IN")} ({r.lots})</td>
                      <td>{num(r.avg)}</td>
                      <td>{num(r.ltp)}</td>
                      <td>{r.future_price ? num(r.future_price, 1) : "–"}</td>
                      <td>{r.iv ? `${(r.iv * 100).toFixed(1)}%` : r.kind === "FUT" ? "–" : "n/a"}{r.iv_assumed ? <span className="small muted"> (assumed)</span> : null}</td>
                      <td>{r.delta !== undefined ? num(r.delta, 3) : "–"}</td>
                      <td className={tone(r.delta_rupees_1pct)}>{signed(r.delta_rupees_1pct)}</td>
                      <td className={tone(r.theta_day)}>{signed(r.theta_day)}</td>
                      <td className={tone(r.vega_point)}>{signed(r.vega_point)}</td>
                      <td>{r.dte ?? "–"}</td>
                      <td>{r.moneyness ?? "–"}{r.moneyness_pct !== undefined ? <div className="small muted">{plainPct(r.moneyness_pct, 2)}</div> : null}</td>
                      <td>{r.breakeven ? num(r.breakeven, 2) : "–"}</td>
                      <td>{r.intrinsic !== undefined ? `${num(r.intrinsic)} / ${num(r.time_value)}` : "–"}</td>
                      <td>{inr(r.margin)}<div className="small muted">{r.margin_source}</div></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="small muted">
              Per-position margins add up to {inr(sumMargin)}; the basket figure above is Angel&apos;s answer for all of them together.
              A bought option&apos;s capital is its premium (margin ₹0).
            </div>
          </>
        ) : <div className="empty">{risk.note ?? "No open positions."}</div>}
        <button type="button" className="btn" onClick={onRefresh} disabled={loading}>{loading ? "Re-quoting…" : "Re-quote now"}</button>
      </GlassPanel>

      {rows.length > 0 && (
        <div className="grid-2">
          <GlassPanel title="If the underlying moves" note="every option re-priced at the moved future, volatility held">
            <BarList rows={scen.map((s) => ({ key: String(s.move_pct), label: `${s.move_pct > 0 ? "+" : ""}${s.move_pct}%`, value: s.pnl }))} />
          </GlassPanel>
          <GlassPanel title="By commodity">
            {(risk.by_underlying ?? []).map((u) => (
              <div key={u.underlying} className="u">
                <div className="u-head"><b>{u.underlying}</b><span className="small muted">{u.positions} position(s) · marked value {signed(u.value)}</span></div>
                <Kv k="₹ per 1% rise" v={signed(u.delta_rupees_1pct)} vClass={tone(u.delta_rupees_1pct)} />
                <Kv k="Theta a day" v={signed(u.theta_day)} vClass={tone(u.theta_day)} />
                <Kv k="Vega per vol point" v={signed(u.vega_point)} vClass={tone(u.vega_point)} />
                <Kv k="Convexity on a 1% move" v={signed(u.gamma_rupees_1pct)} vClass={tone(u.gamma_rupees_1pct)} />
              </div>
            ))}
            <div className="note">{risk.note}</div>
          </GlassPanel>
        </div>
      )}

      <style jsx>{`
        .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin-bottom: 12px; }
        .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
        @media (max-width: 1000px) { .grid-2 { grid-template-columns: 1fr; } }
        .table-scroll { overflow-x: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; }
        .data-table th { text-align: center; padding: 8px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); white-space: nowrap; }
        .data-table td { padding: 7px 8px; text-align: center; border-bottom: 1px solid var(--canvas-soft); white-space: nowrap; }
        .data-table .l { text-align: left; }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
        .small { font-size: 11px; }
        .muted { color: var(--text-muted); }
        .note { font-size: 11.5px; color: var(--text-muted); padding: 8px 2px 0; line-height: 1.55; }
        .empty { padding: 22px; text-align: center; color: var(--text-faint); font-size: 12.5px; }
        .u { margin-bottom: 12px; }
        .u-head { display: flex; justify-content: space-between; gap: 8px; font-size: 12.5px; }
        .btn { margin-top: 10px; font-size: 12px; font-weight: 600; padding: 6px 12px; border-radius: 8px; border: 1px solid var(--panel-border); background: var(--panel); color: var(--text); cursor: pointer; }
        .btn:disabled { opacity: 0.5; cursor: not-allowed; }
      `}</style>
    </>
  );
}
