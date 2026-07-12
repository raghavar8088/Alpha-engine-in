"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import GlassPanel from "../../components/GlassPanel";
import PageHeader from "../../components/PageHeader";
import ErrorBanner from "../../components/ErrorBanner";
import { StrategyInfo, fetchStrategies } from "../../lib/api";

const CATEGORY_LABELS: Record<string, string> = {
  trend: "Trend Following",
  momentum: "Momentum",
  mean_reversion: "Mean Reversion",
  swing: "Swing",
  intraday: "Intraday",
  futures: "Futures",
  options: "Options",
};

const inr = (v: number | null | undefined) =>
  v === null || v === undefined ? "-" : v.toLocaleString("en-IN", { maximumFractionDigits: 0 });

export default function StrategiesPage() {
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    fetchStrategies()
      .then(setStrategies)
      .catch(() => setError("Backend unreachable - is it running on port 8000?"));
  }, []);

  const categories = [...new Set(strategies.map((s) => s.category))];
  const passed = strategies.filter((s) => s.validation?.passed).length;
  const validated = strategies.filter((s) => s.validation).length;
  const realMoney = strategies.filter((s) => s.validation?.real_money_ready).length;

  return (
    <div className="page">
      <PageHeader
        crumb="Strategies"
        title="Strategies"
        subtitle={
          <>
            {strategies.length} registered - {passed}/{validated} pass the backtest gate (PF&gt;1, win
            rate&ge;40%, expectancy&gt;0, max DD&le;25%, &ge;5 trades) and <strong>{realMoney} are
            real-money ready</strong> (gate pass + walk-forward consistency &ge;50% with positive
            out-of-sample net). Gate results come from the latest <span className="mono">validate.py</span> batch.
          </>
        }
      />
      {error && <ErrorBanner message={error} />}

      {categories.map((cat) => (
        <section key={cat}>
          <h2>{CATEGORY_LABELS[cat] ?? cat}</h2>
          <div className="cards">
            {strategies
              .filter((s) => s.category === cat)
              .map((s) => {
                const v = s.validation;
                const badge =
                  v === null
                    ? "unvalidated"
                    : v.real_money_ready
                      ? "realmoney"
                      : v.status === "pass"
                        ? "pass"
                        : v.status === "insufficient_data"
                          ? "nodata"
                          : "fail";
                const badgeLabel = {
                  realmoney: "REAL MONEY READY",
                  pass: "GATE PASS",
                  fail: "GATE FAIL",
                  nodata: "AWAITING DATA",
                  unvalidated: "NOT VALIDATED",
                }[badge];
                const best = v?.best_run;
                const isOpen = expanded === s.strategy_id;
                return (
                  <div key={s.strategy_id} className="card-wrap">
                    <GlassPanel>
                      <button
                        className="card-body"
                        onClick={() => setExpanded(isOpen ? null : s.strategy_id)}
                        aria-expanded={isOpen}
                      >
                        <div className="card-top">
                          <div className="name">{s.name}</div>
                          <span className={`badge ${badge}`}>
                            {badge === "realmoney" && (
                              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round"><path d="M12 2l2.9 6.3L22 9.3l-5 4.9 1.2 6.9L12 17.8 5.8 21l1.2-6.9-5-4.9 7.1-1L12 2z" /></svg>
                            )}
                            {badge === "pass" && (
                              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={3} strokeLinecap="round" strokeLinejoin="round"><path d="M20 6L9 17l-5-5" /></svg>
                            )}
                            {badge === "fail" && (
                              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={3} strokeLinecap="round"><path d="M18 6L6 18M6 6l12 12" /></svg>
                            )}
                            {badgeLabel}
                          </span>
                        </div>
                        <div className="desc">{s.description}</div>
                        <div className="meta-row">
                          <span>{s.timeframes.join(" / ")}</span>
                          <span>{s.suitable_market}</span>
                          {s.risk_reward !== null && <span>RR {s.risk_reward}</span>}
                          {v && <span>{v.passing_runs}/{v.total_runs} runs pass</span>}
                        </div>
                        {v?.real_money && "consistency" in (v.real_money as object) && v.real_money.consistency !== null && (
                          <div className="best-row">
                            <span className="best-label">Walk-forward</span>
                            <span>{v.real_money.symbol} {v.real_money.timeframe}</span>
                            <span>consistency {(v.real_money.consistency * 100).toFixed(0)}%</span>
                            <span className={(v.real_money.oos_net_profit ?? 0) >= 0 ? "gain" : "loss"}>
                              OOS {inr(v.real_money.oos_net_profit)}
                            </span>
                          </div>
                        )}
                        {best && (
                          <div className="best-row">
                            <span className="best-label">Best run</span>
                            <span>{best.symbol} {best.timeframe}</span>
                            <span className={best.metrics.net_profit! >= 0 ? "gain" : "loss"}>
                              {inr(best.metrics.net_profit)}
                            </span>
                            <span>PF {best.metrics.profit_factor ?? "-"}</span>
                            <span>
                              WR {best.metrics.win_rate !== null ? `${((best.metrics.win_rate as number) * 100).toFixed(0)}%` : "-"}
                            </span>
                            <span>DD {best.metrics.max_drawdown_pct}%</span>
                          </div>
                        )}
                      </button>
                      {isOpen && v && (
                        <div className="runs">
                          <table>
                            <thead>
                              <tr><th>Run</th><th>Net</th><th>PF</th><th>WR</th><th>Trades</th><th>Max DD</th><th>Gate</th></tr>
                            </thead>
                            <tbody>
                              {v.runs.map((r) => (
                                <tr key={`${r.symbol}-${r.timeframe}`}>
                                  <td>{r.symbol} {r.timeframe}</td>
                                  <td className={r.metrics.net_profit! >= 0 ? "gain" : "loss"}>{inr(r.metrics.net_profit)}</td>
                                  <td>{r.metrics.profit_factor ?? "-"}</td>
                                  <td>{r.metrics.win_rate !== null ? `${((r.metrics.win_rate as number) * 100).toFixed(0)}%` : "-"}</td>
                                  <td>{r.metrics.total_trades}</td>
                                  <td>{r.metrics.max_drawdown_pct}%</td>
                                  <td>
                                    {r.passed ? (
                                      <span className="gain">pass</span>
                                    ) : (
                                      <span className="fail-reasons" title={r.fail_reasons.join("; ")}>
                                        {r.fail_reasons[0]}{r.fail_reasons.length > 1 ? ` +${r.fail_reasons.length - 1}` : ""}
                                      </span>
                                    )}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                          <div className="actions">
                            <Link href="/backtesting" className="bt-link">Open in Backtesting</Link>
                          </div>
                        </div>
                      )}
                    </GlassPanel>
                  </div>
                );
              })}
          </div>
        </section>
      ))}

      <style jsx>{`
        .page {
          display: flex;
          flex-direction: column;
          gap: 10px;
        }
        h2 {
          font-family: var(--font-display);
          font-size: 14px;
          font-weight: 700;
          letter-spacing: 0.05em;
          text-transform: uppercase;
          color: var(--text-muted);
          margin: 20px 0 10px;
        }
        .sub {
          margin: -4px 0 0;
          color: var(--text-muted);
          font-size: 13px;
          max-width: 760px;
        }
        .mono {
          font-family: var(--font-data);
          font-size: 12px;
        }
        .error {
          padding: 10px 14px;
          border-radius: 9px;
          background: var(--loss-dim);
          border: 1px solid rgba(217, 45, 63, 0.3);
          color: var(--loss);
          font-size: 13px;
        }
        .cards {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
          gap: 14px;
        }
        .card-wrap :global(.panel) {
          height: 100%;
        }
        .card-body {
          display: block;
          width: 100%;
          text-align: left;
          background: none;
          border: none;
          padding: 16px 18px;
          cursor: pointer;
        }
        .card-top {
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 10px;
        }
        .name {
          font-family: var(--font-display);
          font-weight: 700;
          font-size: 14.5px;
        }
        .badge {
          display: inline-flex;
          align-items: center;
          gap: 5px;
          font-size: 10px;
          font-weight: 800;
          letter-spacing: 0.06em;
          padding: 4px 8px;
          border-radius: 999px;
          white-space: nowrap;
        }
        .badge svg { width: 10px; height: 10px; }
        .badge.pass {
          color: var(--gain);
          background: var(--gain-dim);
          border: 1px solid rgba(14, 159, 110, 0.3);
        }
        .badge.fail {
          color: var(--loss);
          background: var(--loss-dim);
          border: 1px solid rgba(217, 45, 63, 0.26);
        }
        .badge.unvalidated,
        .badge.nodata {
          color: var(--text-faint);
          background: var(--canvas-soft);
          border: 1px solid var(--panel-border);
        }
        .badge.realmoney {
          color: var(--accent);
          background: var(--accent-dim);
          border: 1px solid rgba(200, 147, 63, 0.4);
          box-shadow: 0 0 14px rgba(200, 147, 63, 0.22);
        }
        .desc {
          margin-top: 8px;
          font-size: 12.5px;
          color: var(--text-muted);
          line-height: 1.5;
        }
        .meta-row {
          display: flex;
          flex-wrap: wrap;
          gap: 6px 14px;
          margin-top: 10px;
          font-size: 11px;
          color: var(--text-faint);
          font-variant-numeric: tabular-nums;
        }
        .best-row {
          display: flex;
          flex-wrap: wrap;
          gap: 6px 12px;
          margin-top: 10px;
          padding-top: 10px;
          border-top: 1px solid var(--panel-border);
          font-family: var(--font-data);
          font-variant-numeric: tabular-nums;
          font-size: 11.5px;
        }
        .best-label {
          font-size: 9.5px;
          font-weight: 800;
          letter-spacing: 0.06em;
          text-transform: uppercase;
          color: var(--text-faint);
          align-self: center;
        }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
        .runs {
          border-top: 1px solid var(--panel-border);
          padding: 6px 0 0;
        }
        .runs table {
          width: 100%;
          border-collapse: collapse;
          font-size: 11.5px;
          font-variant-numeric: tabular-nums;
        }
        .runs th {
          text-align: left;
          padding: 7px 14px;
          font-size: 9.5px;
          font-weight: 800;
          letter-spacing: 0.06em;
          text-transform: uppercase;
          color: var(--text-faint);
        }
        .runs td {
          padding: 6px 14px;
          border-top: 1px solid var(--panel-border);
        }
        .fail-reasons {
          color: var(--text-muted);
          cursor: help;
        }
        .actions {
          padding: 10px 14px;
        }
        .bt-link {
          font-size: 12px;
          color: var(--accent);
          text-decoration: none;
        }
        .bt-link:hover { text-decoration: underline; }
      `}</style>
    </div>
  );
}
