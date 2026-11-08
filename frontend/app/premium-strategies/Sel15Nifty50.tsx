"use client";

// IS-01: the Intraday Stocks tournament's Selected ORB 15-min rule, picking only NIFTY 50 stocks and taking a 1R target.
// Rules and the last-month backtest at 1x and 5x come from ./sel15Nifty50Data.ts, generated from the replay in
// backend/research/sel15_nifty50_2026_11. Research only: no paper account yet.
import { SEL15_N50 as S, type SelRow } from "./sel15Nifty50Data";
import { day, inr, pct, price, tone } from "./format";

const fix = (x: number | null, d: number) => (x == null ? "—" : x.toFixed(d));

function pick(window: string, version: string, leverage: number): SelRow | undefined {
  return S.rows.find((r) => r.window === window && r.version === version && r.leverage === leverage);
}

export default function Sel15Nifty50() {
  const one = pick("Last month", "1:1 target", 1);
  const five = pick("Last month", "1:1 target", 5);
  if (!one || !five) return null;
  return (
    <div className="pd-group">
      <div className="pd-section">
        <h3>Intraday Stocks research</h3>
        <p>
          {"A rule from the app's Intraday Stocks tournament, tested on its own: Selected ORB 15-min with a 1R target, picking only from the NIFTY 50. "}
          {"Backtested on the last month only, after all costs. It does not paper trade yet."}
        </p>
      </div>
      <div className="ps-cards">
        <div className="ps-card is-wide">
          <div className="ps-card-top">
            <span className="ps-fam up">{S.id}</span>
            <span className="ps-pill ps-pill-warn">{S.verdict}</span>
          </div>
          <div className="ps-card-name">{S.name}</div>
          <div className="ps-card-idea">{S.source}</div>
          <div className="ps-stats">
            <div>
              <span className="ps-stat-label">Last month, 1x</span>
              <span className={`ps-stat-val ${tone(one.retPct)}`}>{pct(one.retPct)}</span>
            </div>
            <div>
              <span className="ps-stat-label">Last month, 5x leverage</span>
              <span className={`ps-stat-val ${tone(five.retPct)}`}>{pct(five.retPct)}</span>
            </div>
            <div>
              <span className="ps-stat-label">Trades · win rate</span>
              <span className="ps-stat-val">{one.trades} · {fix(one.winRate, 1)}%</span>
            </div>
          </div>
          <div className="ps-card-note">
            {`${day(one.first)} to ${day(one.last)}, ${one.sessions} sessions: ${inr(one.net)} on a ₹50 lakh book (5 slots of ₹10 lakh). `}
            {`With intraday 5x leverage, 5 slots of ₹50 lakh on the same ₹50 lakh: ${inr(five.net)}. `}
            {`The same rule on its usual top-200 stocks made ${pct(S.compare.orig.retPct)} that month.`}
          </div>
          <div className="pd-paper">
            <span className="ps-stat-label">Paper account</span>
            <span>Not set up yet</span>
          </div>
          <details className="ps-rules" open>
            <summary>Backtest after all costs</summary>
            <div className="is-scroll">
              <table className="ps-table">
                <thead>
                  <tr>
                    <th>Period</th><th>Version</th><th>Leverage</th><th>Trades</th><th>Win %</th><th>Net P&amp;L</th>
                    <th>Return</th><th>PF</th><th>Max DD</th><th>Avg a trade</th>
                  </tr>
                </thead>
                <tbody>
                  {S.rows.map((r) => (
                    <tr key={`${r.window}|${r.version}|${r.leverage}`}>
                      <td className="ps-name">{`${r.window} (${day(r.first)} to ${day(r.last)})`}</td>
                      <td className="is-left">{r.version}</td>
                      <td>{`${r.leverage}x`}</td>
                      <td>{r.trades}</td>
                      <td>{fix(r.winRate, 1)}</td>
                      <td className={tone(r.net)}>{inr(r.net)}</td>
                      <td className={tone(r.retPct)}>{pct(r.retPct)}</td>
                      <td>{fix(r.pf, 2)}</td>
                      <td>{`${fix(r.maxDdPct, 2)}%`}</td>
                      <td className={tone(r.avg)}>{r.avg == null ? "—" : inr(r.avg)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
          <details className="ps-rules">
            <summary>{`Every trade of the last month (${S.trades.length})`}</summary>
            <div className="is-scroll is-tall">
              <table className="ps-table">
                <thead>
                  <tr>
                    <th>Day</th><th>Entry</th><th>Stock</th><th>Side</th><th>Entry price</th><th>Exit price</th><th>Exit</th>
                    <th>Net at 1x</th><th>Net at 5x</th>
                  </tr>
                </thead>
                <tbody>
                  {S.trades.map((t) => (
                    <tr key={`${t.day}|${t.time}|${t.sym}`}>
                      <td className="ps-name">{day(t.day)}</td>
                      <td>{t.time}</td>
                      <td className="is-left">{t.sym}</td>
                      <td>{t.side === "BUY" ? "Long" : "Short"}</td>
                      <td>{price(t.entry)}</td>
                      <td>{price(t.exit)}</td>
                      <td>{t.reason}</td>
                      <td className={tone(t.net1x)}>{inr(t.net1x)}</td>
                      <td className={tone(t.net5x)}>{inr(t.net5x)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
          <details className="ps-rules">
            <summary>Exact rules</summary>
            <dl>
              {S.rules.map((r) => (
                <div key={r.label} className="ps-rule">
                  <dt>{r.label}</dt>
                  <dd>{r.text}</dd>
                </div>
              ))}
            </dl>
          </details>
          <details className="ps-rules">
            <summary>How it was tested</summary>
            <dl>
              {S.method.map((r) => (
                <div key={r.label} className="ps-rule">
                  <dt>{r.label}</dt>
                  <dd>{r.text}</dd>
                </div>
              ))}
            </dl>
          </details>
        </div>
      </div>
      <style jsx>{`
        .is-wide { grid-column: 1 / -1; }
        .is-scroll { overflow-x: auto; margin-top: 8px; }
        .is-tall { max-height: 420px; overflow-y: auto; }
        .is-left { text-align: left !important; }
      `}</style>
    </div>
  );
}
