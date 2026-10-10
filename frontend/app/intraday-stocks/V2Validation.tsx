"use client";

import { useCallback, useEffect, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import ErrorBanner from "../../components/ErrorBanner";
import H1Panel from "./H1Panel";
import {
  fetchV2Backtest,
  fetchV2Registry,
  type V2BacktestResult,
  type V2BacktestRun,
  type V2RegistryEntry,
} from "../../lib/api";

const CHECK_LABEL: Record<string, string> = {
  trades: "too few trades",
  dsr: "deflated Sharpe < 0.95",
  profit_factor: "profit factor < 1.1",
  drawdown: "drawdown > 25%",
  months: "< 55% positive months",
  holdout: "lost in the holdout",
  pbo: "desk overfitting > 0.5",
  selection_positive: "lost in selection",
};

const inr = (v: number | null | undefined) =>
  v == null ? "-" : Math.round(v).toLocaleString("en-IN");

/** The proof a strategy must show before it is worth real money — and what it showed.
 *
 * Every v2 strategy is replayed on two years of real 15-minute bars with the live
 * engine's own rules and fill model, then judged against a gate that accounts for how
 * many strategies were tried at once. Passing only earns a place in INCUBATION, where the
 * forward paper record is tested against the expectation frozen at registration. */
export default function V2Validation() {
  const [run, setRun] = useState<V2BacktestRun | null>(null);
  const [rows, setRows] = useState<V2BacktestResult[]>([]);
  const [reg, setReg] = useState<V2RegistryEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [showAll, setShowAll] = useState(false);

  const load = useCallback(async () => {
    try {
      const [bt, rg] = await Promise.all([fetchV2Backtest(), fetchV2Registry()]);
      setRun(bt.run);
      setRows(bt.results ?? []);
      setReg(rg.strategies ?? []);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load the validation results");
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const regBy = Object.fromEntries(reg.map((r) => [r.strategy_id, r]));
  const passed = rows.filter((r) => r.passed);
  const shown = showAll ? rows : rows.slice(0, 12);

  return (
    <GlassPanel title="Validation — walk-forward backtest and incubation" onRefresh={load}>
      {error && <ErrorBanner message={`Couldn't load the validation results. ${error}`} onRetry={load} />}
      {!loaded ? (
        <div className="empty">Loading…</div>
      ) : !run ? (
        <div className="empty">
          No backtest has been run yet. It replays every strategy on the stored 15-minute history
          once that history is complete.
        </div>
      ) : (
        <>
          <div className="summary">
            <div>
              <div className="k">Run</div>
              <div className="v">{run.run_id}</div>
              <div className="s">{run.first_day} → holdout from {run.holdout_from}</div>
            </div>
            <div>
              <div className="k">Sessions</div>
              <div className="v">{run.sessions}</div>
              <div className="s">{run.selection_sessions} selection · {run.holdout_sessions} holdout</div>
            </div>
            <div>
              <div className="k">Universe</div>
              <div className="v">{run.symbols} names</div>
              <div className="s">point-in-time top 200 · median {run.coverage_median}/day</div>
            </div>
            <div>
              <div className="k">Overfitting (PBO)</div>
              <div className={`v ${run.pbo?.pbo != null && run.pbo.pbo > 0.5 ? "loss" : ""}`}>
                {run.pbo?.pbo != null ? `${(run.pbo.pbo * 100).toFixed(0)}%` : "-"}
              </div>
              <div className="s">over {run.pbo?.combinations?.toLocaleString("en-IN")} splits; 50% = a coin flip</div>
            </div>
            <div>
              <div className="k">Passed the gate</div>
              <div className={`v ${passed.length ? "gain" : ""}`}>
                {passed.length} of {rows.length}
              </div>
              <div className="s">{reg.length} in incubation</div>
            </div>
          </div>

          <div className="note">
            Same rules and fill model as live (stops first when a bar crosses both, slippage by
            liquidity, Angel One costs). A strategy must clear <strong>every</strong> check: a
            deflated Sharpe of 0.95 after accounting for {run.n_trials} strategies tried at once,
            profit factor 1.1, drawdown under 25%, most months positive, profitable in the holdout
            it was never selected on, and a desk-wide probability of overfitting under 50%.
            {!passed.length && (
              <>
                {" "}<strong>None passed.</strong> On this history these rules do not beat their
                costs; the tournament keeps trading them on paper so the backtest&rsquo;s fill model
                can be checked against what really happens, but nothing here is a candidate for
                real money.
              </>
            )}
          </div>

          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Strategy</th>
                  <th>Trades</th>
                  <th>Gross ₹</th>
                  <th>Net ₹</th>
                  <th>PF</th>
                  <th>Win</th>
                  <th>DSR</th>
                  <th>Holdout ₹</th>
                  <th style={{ textAlign: "left" }}>Verdict</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((r) => {
                  const s = r.selection;
                  const failed = Object.entries(r.checks).filter(([, ok]) => !ok).map(([k]) => CHECK_LABEL[k] ?? k);
                  const rg = regBy[r.strategy_id];
                  return (
                    <tr key={r.strategy_id}>
                      <td style={{ textAlign: "left" }}>
                        {r.name}
                        {r.optimistic_bound && (
                          <div className="sub">
                            optimistic reading of ambiguous trigger bars: ₹{inr(r.optimistic_bound.selection_net)}
                            {r.optimistic_bound.ambiguous ? " — undecided on 15m bars" : ""}
                          </div>
                        )}
                      </td>
                      <td>{s.trades.toLocaleString("en-IN")}</td>
                      <td className={s.gross_pnl >= 0 ? "gain" : "loss"}>{inr(s.gross_pnl)}</td>
                      <td className={s.net_pnl >= 0 ? "gain" : "loss"}>{inr(s.net_pnl)}</td>
                      <td>{s.profit_factor ?? "-"}</td>
                      <td>{(s.win_rate * 100).toFixed(0)}%</td>
                      <td>{r.dsr != null ? r.dsr.toFixed(2) : "-"}</td>
                      <td className={r.holdout.net_pnl >= 0 ? "gain" : "loss"}>{inr(r.holdout.net_pnl)}</td>
                      <td style={{ textAlign: "left", fontSize: 11 }}>
                        {r.passed ? (
                          <span className="pill pass">PASSED{rg ? ` · ${rg.status}` : ""}</span>
                        ) : (
                          <span className="fails">{failed.slice(0, 3).join(" · ")}{failed.length > 3 ? ` +${failed.length - 3}` : ""}</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {rows.length > 12 && (
            <button className="more" onClick={() => setShowAll((v) => !v)}>
              {showAll ? "Show the top 12" : `Show all ${rows.length}`}
            </button>
          )}

          {reg.length > 0 && (
            <>
              <div className="h">Incubation — forward record vs the expectation frozen at registration</div>
              <div className="table-scroll">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th style={{ textAlign: "left" }}>Strategy</th>
                      <th>Status</th>
                      <th>Since</th>
                      <th>Forward trades</th>
                      <th>Forward ₹/trade</th>
                      <th>Expected ₹/trade</th>
                      <th>z vs expected</th>
                    </tr>
                  </thead>
                  <tbody>
                    {reg.map((g) => (
                      <tr key={g.strategy_id}>
                        <td style={{ textAlign: "left" }}>{g.name}</td>
                        <td><span className={`pill ${g.status.toLowerCase()}`}>{g.status}</span></td>
                        <td>{g.registered_at ? new Date(g.registered_at).toLocaleDateString("en-IN") : "-"}</td>
                        <td>{g.forward?.trades ?? 0} / {g.thresholds?.min_trades}</td>
                        <td>{g.forward?.mean != null ? inr(g.forward.mean) : "-"}</td>
                        <td>{inr(g.expected?.per_trade_net_mean)}</td>
                        <td>{g.forward?.z_vs_expected != null ? g.forward.z_vs_expected.toFixed(2) : "-"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}
      <H1Panel />
      <style jsx>{`
        .empty { padding: 18px 20px; font-size: 12px; color: var(--text-faint); }
        .summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; padding: 4px 4px 12px; }
        .k { font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); }
        .v { font-size: 17px; font-weight: 700; margin-top: 2px; }
        .s { font-size: 11px; color: var(--text-muted); margin-top: 2px; }
        .note { font-size: 12px; line-height: 1.55; color: var(--text-muted); padding: 10px 12px; margin-bottom: 10px;
                background: var(--canvas-soft); border-radius: 10px; }
        .h { font-size: 12px; font-weight: 700; margin: 16px 2px 6px; }
        .sub { font-size: 10.5px; color: var(--text-muted); margin-top: 2px; }
        .fails { color: var(--loss); }
        .pill { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 10.5px; font-weight: 700;
                background: var(--canvas-soft); border: 1px solid var(--panel-border); }
        .pill.pass, .pill.confirmed { color: var(--gain); border-color: rgba(34, 170, 96, 0.35); }
        .pill.failed { color: var(--loss); border-color: rgba(217, 45, 63, 0.35); }
        .more { margin-top: 8px; background: var(--panel); border: 1px solid var(--panel-border); border-radius: 8px;
                padding: 6px 12px; font-size: 12px; cursor: pointer; }
        .table-scroll { overflow-x: auto; max-height: 520px; overflow-y: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; }
        .data-table th { text-align: center; padding: 8px 10px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em;
                         text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border);
                         position: sticky; top: 0; background: var(--panel); }
        .data-table td { padding: 7px 10px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .data-table tbody tr:hover td { background: var(--canvas-soft); }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
        @media (max-width: 640px) { .summary { grid-template-columns: repeat(2, 1fr); } }
      `}</style>
    </GlassPanel>
  );
}
