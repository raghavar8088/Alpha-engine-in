"use client";

import { useState } from "react";
import GlassPanel from "../../../components/GlassPanel";
import { RESEARCH } from "./researchData";
import { R, bp, inr, num, pct, share, statusClass, tone } from "./desk";

function SelDetail({ x, onClose }: { x: any; onClose: () => void }) {
  return (
    <div className="pis-selbox">
      <div className="pis-selbox-head"><b>#{x.rank} {x.name}</b><button className="pis-btn" onClick={onClose}>Close</button></div>
                    <div className="pis-detail-grid">
                      <div>
                        <h4>Rule (as the module defines it)</h4><p className="pis-small">{x.rule}</p>
                        <h4>Why it is not eligible</h4><p className="pis-small">{x.reason}</p>
                        <h4>Version and evidence</h4><p className="pis-small">{x.version} · {x.evidence_date}</p>
                      </div>
                      <div>
                        <h4>Rank factors (percentiles)</h4>
                        <p className="pis-small">expectancy {num(x.factors.expectancy)} · drawdown {num(x.factors.drawdown)} · consistency {num(x.factors.consistency)}
                          {" "}· sample {num(x.factors.sample)} · contribution {num(x.factors.contribution)} (1 - corr {num(x.contribution_1_minus_corr)})</p>
                        <h4>Book: long / short</h4>
                        <p className="pis-small">long {x.book_view.long?.trades ?? 0} trades {R(x.book_view.long?.mean_R)} · short {x.book_view.short?.trades ?? 0} trades {R(x.book_view.short?.mean_R)}
                          {" "}· {x.book_view.days_traded} trading days · win rate {num(x.book_view.win_pct, 1)}%</p>
                        {x.variants?.length > 0 && (<><h4>Variants (same rule, other timeframes)</h4>
                          <p className="pis-small">{x.variants.map((v: any) => v.name).join(", ")}</p></>)}
                        {x.overlaps?.length > 0 && (<><h4>Trades the same stocks at the same times as</h4>
                          <p className="pis-small">{x.overlaps.map((o: any) => `${o.with} (${share(o.overlap)} of entries shared)`).join(", ")}</p></>)}
                      </div>
                    </div>
                  
    </div>
  );
}

export default function ImportedView() {
  const I = RESEARCH.imported;
  const [open, setOpen] = useState<string | null>(null);
  const sel = I.top25.find((x: any) => x.id === open);
  const qualified = I.top25.filter((x: any) => !String(x.status).startsWith("Rejected")).length;
  return (
    <div className="pis-col">
      <div className="pis-banner">
        <span className="pis-pill pis-pill-bad">{qualified} of {I.top25.length} qualify</span>
        <span>
          Membership in this list does not authorise trading. All 62 existing strategies (54 from Intraday Stocks, 8 from
          Stock Momentum Trading) were run on one harness: the same {I.sessions} sessions ({I.window[0]} to {I.window[1]}),
          this desk’s universe, Rs 10 lakh books, its costs and fills. Every one of the 25 below loses after costs.
        </span>
      </div>
      <GlassPanel title="How the 25 were chosen">
        <ul className="pis-list">
          <li><b>Ranked</b> on five factors fixed before the run: net expectancy {share(I.weights.expectancy)}, drawdown {share(I.weights.drawdown)},
            consistency (months up) {share(I.weights.consistency)}, sample size {share(I.weights.sample)} and contribution to a portfolio
            of the others (1 - correlation) {share(I.weights.contribution)}.</li>
          <li><b>Equivalent rules</b> (one tournament family on 15-minute, 45-minute and 1-hour bars) count once: the best timeframe
            represents the family and the others are listed as its variants.</li>
          <li><b>Same trades:</b> pairs sharing at least half of their (stock, day, half-hour, side) entries are duplicates; the lower
            ranked is dropped. {Object.keys(I.dropped).length ? `Dropped: ${Object.entries(I.dropped).map(([k, v]: [string, any]) => `${k} (same entries as ${v.duplicate_of})`).join("; ")}.` : ""}</li>
          <li><b>Not replayable here:</b> {I.not_replayable.map((x: any) => `${x.name}: ${x.why}`).join(" ")}</li>
          <li><b>Read first:</b> INTRADAY_STOCKS_54_STRATEGY_AUDIT.md (no look-ahead; every rule loses after ~10.5 bp a round trip) and
            Stock Momentum’s own replay (backend/app/data/morning_replay.json: 7 of 8 rules lose in and out of sample, -0.47% to
            -0.79% a trade at Rs 10,000 positions).</li>
        </ul>
      </GlassPanel>
      <GlassPanel title="Imported Top 25" note="every-signal = each signal as its own 0.25%-risk trade; book = Rs 10 lakh with the desk's limits">
        <div className="pis-scroll">
          <table className="pis-table">
            <thead><tr><th className="r">#</th><th>Strategy</th><th className="r">Score</th>
              <th className="r">Signals</th><th className="r">Mean net R</th><th className="r">Net / trade</th>
              <th className="r">Book return</th><th className="r">Max DD</th><th className="r">PF</th><th className="r">Months up</th>
              <th className="r">Avg day</th><th className="r">Costs</th><th className="r">At 2x slip</th><th>Status</th></tr></thead>
            <tbody>{I.top25.map((x: any) => (
                <tr key={x.id} className={`pis-click${open === x.id ? " pis-sel" : ""}`} onClick={() => setOpen(open === x.id ? null : x.id)}>
                  <td className="r">{x.rank}</td>
                  <td className="pis-strong pis-wrap">{x.name}<div className="pis-small pis-muted">{x.source} · {x.id}</div></td>
                  <td className="r">{num(x.score, 3)}</td>
                  <td className="r">{x.rule_view.trades?.toLocaleString("en-IN")}</td>
                  <td className={`r ${tone(x.rule_view.mean_R)}`}>{R(x.rule_view.mean_R)}</td>
                  <td className={`r ${tone(x.rule_view.mean_net_bp)}`}>{bp(x.rule_view.mean_net_bp)}</td>
                  <td className={`r ${tone(x.book_view.return_pct)}`}>{pct(x.book_view.return_pct)}</td>
                  <td className="r">{num(x.book_view.max_dd_pct, 1)}%</td>
                  <td className="r">{num(x.book_view.profit_factor)}</td>
                  <td className="r">{x.book_view.months_up}/{x.book_view.months}</td>
                  <td className={`r ${tone(x.book_view.avg_daily_net_sessions)}`}>{inr(x.book_view.avg_daily_net_sessions)}</td>
                  <td className="r">{inr(x.book_view.costs)}</td>
                  <td className={`r ${tone(x.book_R_2x)}`}>{R(x.book_R_2x)}</td>
                  <td><span className={statusClass(x.status)}>{String(x.status).split(" (")[0]}</span></td>
                </tr>
            ))}</tbody>
          </table>
        </div>
        {sel && <SelDetail x={sel} onClose={() => setOpen(null)} />}
      </GlassPanel>
    </div>
  );
}
