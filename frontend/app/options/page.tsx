"use client";

import { useCallback, useEffect, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import PageHeader from "../../components/PageHeader";
import ErrorBanner from "../../components/ErrorBanner";
import Histogram from "../../components/charts/Histogram";
import LineChart from "../../components/charts/LineChart";
import PayoffChart from "../../components/charts/PayoffChart";
import {
  refreshing,
  OptionChain,
  OptionStrikeRow,
  OptionsSellingSweep,
  OptionsSweep,
  PayoffLegRequest,
  fetchExpiries,
  fetchOptionChain,
  fetchPayoff,
  fetchQualifiedSellingStrategies,
  fetchQualifiedStrategies,
  runOptionsBacktest,
  runOptionsSellingSweep,
  runOptionsSweep,
} from "../../lib/api";

const INDICES = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"];
const OPTIONS_STRATEGIES = ["long_call", "long_put", "covered_call", "bull_put_spread", "iron_condor"];

const inr = (v: number | null | undefined) =>
  v === null || v === undefined ? "-" : v.toLocaleString("en-IN", { maximumFractionDigits: 2 });
const num = (v: number | null | undefined, d = 2) => (v === null || v === undefined ? "-" : v.toFixed(d));

function buildupTone(label: string | null): string {
  if (label === "Long Build-up" || label === "Short Covering") return "gain";
  if (label === "Short Build-up" || label === "Long Unwinding") return "loss";
  return "";
}

function classifyBuildup(leg: OptionStrikeRow["ce"]): string | null {
  const ltp = leg.last_price, prev = leg.previous_close_price;
  const oi = leg.oi, prevOi = leg.previous_oi;
  if (!ltp || !prev) return null;
  const priceUp = ltp > prev, oiUp = oi > prevOi;
  if (priceUp && oiUp) return "Long Build-up";
  if (!priceUp && oiUp) return "Short Build-up";
  if (!priceUp && !oiUp) return "Long Unwinding";
  return "Short Covering";
}

export default function OptionsPage() {
  const [tab, setTab] = useState<"chain" | "payoff" | "backtest" | "lab" | "selling">("chain");

  // Chain tab
  const [symbol, setSymbol] = useState("NIFTY");
  const [expiries, setExpiries] = useState<string[]>([]);
  const [expiry, setExpiry] = useState("");
  const [chain, setChain] = useState<OptionChain | null>(null);
  const [chainLoading, setChainLoading] = useState(false);
  const [chainError, setChainError] = useState<string | null>(null);

  useEffect(() => {
    fetchExpiries(symbol)
      .then((d) => {
        setExpiries(d.expiries);
        setExpiry(d.expiries[0] ?? "");
      })
      .catch(() => setExpiries([]));
  }, [symbol]);

  const loadChain = useCallback(async () => {
    if (!expiry) return;
    setChainLoading(true);
    setChainError(null);
    try {
      setChain(await fetchOptionChain(symbol, expiry));
    } catch (e) {
      setChainError(e instanceof Error ? e.message : "Failed to load chain");
    } finally {
      setChainLoading(false);
    }
  }, [symbol, expiry]);

  const [isRefreshing, setIsRefreshing] = useState(false);
  const handleRefresh = useCallback(async () => {
    setIsRefreshing(true);
    try {
      await refreshing(() => loadChain());
    } finally {
      setIsRefreshing(false);
    }
  }, [loadChain]);

  // Payoff tab
  const [legs, setLegs] = useState<PayoffLegRequest[]>([
    { option_type: "PE", strike: 25000, premium: 150, quantity: 75, direction: "SELL" },
    { option_type: "PE", strike: 24800, premium: 80, quantity: 75, direction: "BUY" },
  ]);
  const [payoffResult, setPayoffResult] = useState<any>(null);
  const [payoffError, setPayoffError] = useState<string | null>(null);

  const computePayoff = useCallback(async () => {
    setPayoffError(null);
    try {
      setPayoffResult(await fetchPayoff(legs, chain?.spot));
    } catch (e) {
      setPayoffError(e instanceof Error ? e.message : "Failed to compute payoff");
    }
  }, [legs, chain]);

  useEffect(() => {
    computePayoff();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Backtest tab
  const [btForm, setBtForm] = useState({ strategy_id: "bull_put_spread", symbol: "NIFTY", years: 5, dte_days: 30, otm_pct: 3 });
  const [btResult, setBtResult] = useState<any>(null);
  const [btRunning, setBtRunning] = useState(false);
  const [btError, setBtError] = useState<string | null>(null);

  const runBacktest = useCallback(async () => {
    setBtRunning(true);
    setBtError(null);
    try {
      const result = await runOptionsBacktest({
        strategy_id: btForm.strategy_id, symbol: btForm.symbol, years: btForm.years,
        dte_days: btForm.dte_days, otm_pct: btForm.otm_pct / 100,
      });
      setBtResult(result);
    } catch (e) {
      setBtError(e instanceof Error ? e.message : "Backtest failed");
    } finally {
      setBtRunning(false);
    }
  }, [btForm]);

  // Buying Lab tab (50-strategy sweep + qualification leaderboard)
  const [labForm, setLabForm] = useState({ symbol: "NIFTY", years: 10, min_win_rate: 40, min_expectancy: 150, adx_regime: 0 });
  const [sweep, setSweep] = useState<OptionsSweep | null>(null);
  const [labRunning, setLabRunning] = useState(false);
  const [labError, setLabError] = useState<string | null>(null);
  const [labFilter, setLabFilter] = useState<"all" | "qualified">("qualified");

  useEffect(() => {
    fetchQualifiedStrategies()
      .then((d) => { if (d.sweep_id) setSweep(d); })
      .catch(() => {});
  }, []);

  const runSweep = useCallback(async () => {
    setLabRunning(true);
    setLabError(null);
    try {
      setSweep(await runOptionsSweep({
        symbol: labForm.symbol, years: labForm.years, min_win_rate: labForm.min_win_rate / 100,
        min_expectancy: labForm.min_expectancy, adx_regime: labForm.adx_regime > 0 ? labForm.adx_regime : null,
      }));
    } catch (e) {
      setLabError(e instanceof Error ? e.message : "Sweep failed");
    } finally {
      setLabRunning(false);
    }
  }, [labForm]);

  // Selling Lab tab (option-SELLING sweep + tail-risk qualification gate)
  const [sellForm, setSellForm] = useState({
    symbol: "NIFTY", years: 10, min_profit_factor: 1.3, min_trades: 20,
    max_worst_trade_pct_capital: 1.5, max_drawdown_pct: 10,
  });
  const [sellSweep, setSellSweep] = useState<OptionsSellingSweep | null>(null);
  const [sellRunning, setSellRunning] = useState(false);
  const [sellError, setSellError] = useState<string | null>(null);
  const [sellFilter, setSellFilter] = useState<"all" | "qualified">("all");

  useEffect(() => {
    fetchQualifiedSellingStrategies()
      .then((d) => { if (d.sweep_id) setSellSweep(d); })
      .catch(() => {});
  }, []);

  const runSellingSweep = useCallback(async () => {
    setSellRunning(true);
    setSellError(null);
    try {
      setSellSweep(await runOptionsSellingSweep(sellForm));
    } catch (e) {
      setSellError(e instanceof Error ? e.message : "Selling sweep failed");
    } finally {
      setSellRunning(false);
    }
  }, [sellForm]);

  return (
    <div className="page">
      <PageHeader
        onRefresh={handleRefresh}
        refreshing={isRefreshing}
        crumb="Options"
        title="Options"
        subtitle="Live Dhan option chain with Greeks/OI analytics, a multi-leg payoff builder, and a Black-Scholes synthetic-premium backtester for the 5 options strategies (#46-50) — see the note in the backtest tab for why premiums are modeled rather than historical-quoted."
      />

      <div className="tabs">
        {(["chain", "payoff", "backtest", "lab", "selling"] as const).map((t) => (
          <button key={t} className={tab === t ? "tab active" : "tab"} onClick={() => setTab(t)}>
            {t === "chain" ? "Option Chain" : t === "payoff" ? "Payoff Builder" : t === "backtest" ? "Strategy Backtest" : t === "lab" ? "Buying Lab (50)" : "Selling Lab (24)"}
          </button>
        ))}
      </div>

      {tab === "chain" && (
        <GlassPanel title="Option Chain">
          <div className="form">
            <label>
              Underlying
              <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
                {INDICES.map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </label>
            <label>
              Expiry
              <select value={expiry} onChange={(e) => setExpiry(e.target.value)}>
                {expiries.map((e) => (
                  <option key={e}>{e}</option>
                ))}
              </select>
            </label>
            <button onClick={loadChain} disabled={chainLoading || !expiry}>
              {chainLoading ? "Loading..." : "Load chain"}
            </button>
          </div>
          {chainError && <ErrorBanner message={chainError} />}
          {chain && (
            <>
              <div className="tiles">
                <div className="tile"><div className="tile-label">Spot</div><div className="tile-value">{inr(chain.spot)}</div></div>
                <div className="tile"><div className="tile-label">Days to Expiry</div><div className="tile-value">{chain.days_to_expiry}</div></div>
                <div className="tile"><div className="tile-label">PCR (OI)</div><div className="tile-value">{chain.pcr_oi ?? "-"}</div></div>
                <div className="tile"><div className="tile-label">Max Pain</div><div className="tile-value">{inr(chain.max_pain)}</div></div>
              </div>
              <div className="table-scroll">
                <table className="data-table chain-table">
                  <thead>
                    <tr>
                      <th colSpan={5} className="side-header call">CALLS</th>
                      <th className="strike-header">Strike</th>
                      <th colSpan={5} className="side-header put">PUTS</th>
                    </tr>
                    <tr>
                      <th>OI</th><th>Vol</th><th>IV</th><th>LTP</th><th>Buildup</th>
                      <th className="strike-header"></th>
                      <th>Buildup</th><th>LTP</th><th>IV</th><th>Vol</th><th>OI</th>
                    </tr>
                  </thead>
                  <tbody>
                    {chain.strikes
                      .filter((s) => Math.abs(s.strike - chain.spot) / chain.spot < 0.1)
                      .map((s) => {
                        const isAtm = Math.abs(s.strike - chain.spot) < (chain.strikes[1]?.strike - chain.strikes[0]?.strike || 50) / 2;
                        const ceBuildup = classifyBuildup(s.ce);
                        const peBuildup = classifyBuildup(s.pe);
                        return (
                          <tr key={s.strike} className={isAtm ? "atm-row" : ""}>
                            <td>{s.ce.oi?.toLocaleString("en-IN")}</td>
                            <td>{s.ce.volume?.toLocaleString("en-IN")}</td>
                            <td>{num(s.ce.implied_volatility, 1)}{s.ce.implied_volatility_source === "computed" ? "*" : ""}</td>
                            <td>{num(s.ce.last_price)}</td>
                            <td className={buildupTone(ceBuildup)}>{ceBuildup ?? "-"}</td>
                            <td className="strike-cell">{s.strike}</td>
                            <td className={buildupTone(peBuildup)}>{peBuildup ?? "-"}</td>
                            <td>{num(s.pe.last_price)}</td>
                            <td>{num(s.pe.implied_volatility, 1)}{s.pe.implied_volatility_source === "computed" ? "*" : ""}</td>
                            <td>{s.pe.volume?.toLocaleString("en-IN")}</td>
                            <td>{s.pe.oi?.toLocaleString("en-IN")}</td>
                          </tr>
                        );
                      })}
                  </tbody>
                </table>
              </div>
              <div className="footnote">* IV/Greeks computed via Black-Scholes (illiquid strike, no broker quote) rather than broker-reported.</div>
            </>
          )}
        </GlassPanel>
      )}

      {tab === "payoff" && (
        <GlassPanel title="Multi-leg Payoff Builder">
          <div className="legs-editor">
            {legs.map((leg, i) => (
              <div className="leg-row" key={i}>
                <select value={leg.direction} onChange={(e) => setLegs(legs.map((l, j) => (j === i ? { ...l, direction: e.target.value } : l)))}>
                  <option>BUY</option>
                  <option>SELL</option>
                </select>
                <select value={leg.option_type} onChange={(e) => setLegs(legs.map((l, j) => (j === i ? { ...l, option_type: e.target.value } : l)))}>
                  <option>CE</option>
                  <option>PE</option>
                </select>
                <input type="number" value={leg.strike} placeholder="Strike" onChange={(e) => setLegs(legs.map((l, j) => (j === i ? { ...l, strike: Number(e.target.value) } : l)))} />
                <input type="number" value={leg.premium} placeholder="Premium" onChange={(e) => setLegs(legs.map((l, j) => (j === i ? { ...l, premium: Number(e.target.value) } : l)))} />
                <input type="number" value={leg.quantity} placeholder="Qty" onChange={(e) => setLegs(legs.map((l, j) => (j === i ? { ...l, quantity: Number(e.target.value) } : l)))} />
                <button className="remove-btn" onClick={() => setLegs(legs.filter((_, j) => j !== i))}>×</button>
              </div>
            ))}
            <div className="leg-actions">
              <button className="add-btn" onClick={() => setLegs([...legs, { option_type: "CE", strike: 25000, premium: 100, quantity: 75, direction: "BUY" }])}>
                + Add leg
              </button>
              <button onClick={computePayoff}>Recompute</button>
            </div>
          </div>
          {payoffError && <ErrorBanner message={payoffError} />}
          {payoffResult && (
            <>
              <div className="tiles">
                <div className="tile"><div className="tile-label">Max Profit</div><div className="tile-value gain">{payoffResult.profit_unbounded ? "Unbounded" : inr(payoffResult.max_profit)}</div></div>
                <div className="tile"><div className="tile-label">Max Loss</div><div className="tile-value loss">{payoffResult.loss_unbounded ? "Unbounded" : inr(payoffResult.max_loss)}</div></div>
                {payoffResult.net_greeks && (
                  <>
                    <div className="tile"><div className="tile-label">Net Delta</div><div className="tile-value">{payoffResult.net_greeks.delta}</div></div>
                    <div className="tile"><div className="tile-label">Net Theta</div><div className="tile-value">{payoffResult.net_greeks.theta}</div></div>
                    <div className="tile"><div className="tile-label">Net Vega</div><div className="tile-value">{payoffResult.net_greeks.vega}</div></div>
                  </>
                )}
              </div>
              <PayoffChart points={payoffResult.diagram} breakevens={payoffResult.breakevens} />
            </>
          )}
        </GlassPanel>
      )}

      {tab === "backtest" && (
        <>
          <GlassPanel title="Options Strategy Backtest">
            <div className="form">
              <label>
                Strategy
                <select value={btForm.strategy_id} onChange={(e) => setBtForm({ ...btForm, strategy_id: e.target.value })}>
                  {OPTIONS_STRATEGIES.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </label>
              <label>
                Underlying
                <select value={btForm.symbol} onChange={(e) => setBtForm({ ...btForm, symbol: e.target.value })}>
                  {INDICES.map((s) => (
                    <option key={s}>{s}</option>
                  ))}
                </select>
              </label>
              <label>
                Years
                <input type="number" min={0.5} step={0.5} value={btForm.years} onChange={(e) => setBtForm({ ...btForm, years: Number(e.target.value) })} />
              </label>
              <label>
                DTE (days)
                <input type="number" min={5} value={btForm.dte_days} onChange={(e) => setBtForm({ ...btForm, dte_days: Number(e.target.value) })} />
              </label>
              <label>
                OTM %
                <input type="number" min={0} step={0.5} value={btForm.otm_pct} onChange={(e) => setBtForm({ ...btForm, otm_pct: Number(e.target.value) })} />
              </label>
              <button onClick={runBacktest} disabled={btRunning}>{btRunning ? "Running..." : "Run backtest"}</button>
            </div>
            <div className="footnote">
              Premiums are Black-Scholes-modeled from the underlying&apos;s realized volatility, not historical
              exchange-quoted option prices — Dhan has no continuous multi-year option-chain history to backtest
              against directly (each contract only trades one expiry cycle). This is the standard fallback
              institutional backtests use when true historical chains aren&apos;t available.
            </div>
            {btError && <ErrorBanner message={btError} />}
          </GlassPanel>

          {btResult && (
            <>
              <div className="tiles">
                <div className="tile"><div className="tile-label">Net Profit</div><div className={`tile-value ${btResult.metrics.net_profit >= 0 ? "gain" : "loss"}`}>{inr(btResult.metrics.net_profit)}</div></div>
                <div className="tile"><div className="tile-label">Trades / Win rate</div><div className="tile-value">{btResult.metrics.total_trades} / {btResult.metrics.win_rate !== null ? `${(btResult.metrics.win_rate * 100).toFixed(0)}%` : "-"}</div></div>
                <div className="tile"><div className="tile-label">Profit Factor</div><div className="tile-value">{btResult.metrics.profit_factor ?? "-"}</div></div>
                <div className="tile"><div className="tile-label">Max Drawdown</div><div className="tile-value loss">{btResult.metrics.max_drawdown_pct}%</div></div>
                <div className="tile"><div className="tile-label">Sharpe</div><div className="tile-value">{btResult.metrics.sharpe ?? "-"}</div></div>
              </div>
              <div className="grid-2">
                <GlassPanel title="Equity curve">
                  <LineChart points={btResult.charts.equity_curve} color="var(--accent)" />
                </GlassPanel>
                <GlassPanel title="Trade P&amp;L distribution">
                  <Histogram buckets={btResult.charts.trade_distribution} />
                </GlassPanel>
              </div>
            </>
          )}
        </>
      )}

      {tab === "lab" && (
        <>
          <GlassPanel title="Option-Buying Lab — 50 strategies, one sweep">
            <div className="form">
              <label>
                Underlying
                <select value={labForm.symbol} onChange={(e) => setLabForm({ ...labForm, symbol: e.target.value })}>
                  {INDICES.map((s) => (
                    <option key={s}>{s}</option>
                  ))}
                </select>
              </label>
              <label>
                Years
                <input type="number" min={1} max={25} value={labForm.years} onChange={(e) => setLabForm({ ...labForm, years: Number(e.target.value) })} />
              </label>
              <label>
                Min win rate %
                <input type="number" min={0} max={100} value={labForm.min_win_rate} onChange={(e) => setLabForm({ ...labForm, min_win_rate: Number(e.target.value) })} />
              </label>
              <label>
                Min ₹/trade
                <input type="number" min={0} step={10} value={labForm.min_expectancy} onChange={(e) => setLabForm({ ...labForm, min_expectancy: Number(e.target.value) })} />
              </label>
              <label>
                ADX gate (0 = off)
                <input type="number" min={0} max={50} value={labForm.adx_regime} onChange={(e) => setLabForm({ ...labForm, adx_regime: Number(e.target.value) })} />
              </label>
              <button onClick={runSweep} disabled={labRunning}>{labRunning ? "Running all 50…" : "Run 50-strategy sweep"}</button>
            </div>
            <div className="footnote">
              15 scalp (5m) + 20 intraday (15m) + 15 swing (1d) premium-buying strategies: a bullish signal buys the
              ATM call, a bearish one the ATM put; the engine applies each style&apos;s DTE, premium stop/target, and
              EOD square-off. Premiums are Black-Scholes-modeled from realized volatility (see the backtest tab note).
              A strategy qualifies when win rate ≥ the gate AND it made at least 10 trades. Scalp strategies run on
              15m bars until the 5m backfill lands (the TF column shows what was actually used).
            </div>
            {labError && <ErrorBanner message={labError} />}
          </GlassPanel>

          {sweep && (
            <>
              <div className="tiles">
                <div className="tile"><div className="tile-label">Qualified</div><div className="tile-value gain">{sweep.qualified_count} / {sweep.strategy_count}</div></div>
                <div className="tile"><div className="tile-label">Gate</div><div className="tile-value">win ≥ {((sweep.min_win_rate ?? 0.4) * 100).toFixed(0)}%, ≥ {sweep.min_trades ?? 10} trades</div></div>
                <div className="tile"><div className="tile-label">Window</div><div className="tile-value">{sweep.symbol} · {sweep.years}y requested</div></div>
                <div className="tile"><div className="tile-label">Sweep</div><div className="tile-value">{sweep.created_at ? new Date(sweep.created_at).toLocaleString() : "-"}</div></div>
              </div>
              <GlassPanel title="Leaderboard">
                <div className="form" style={{ paddingBottom: 0 }}>
                  <label>
                    Show
                    <select value={labFilter} onChange={(e) => setLabFilter(e.target.value as "all" | "qualified")}>
                      <option value="qualified">Qualified only</option>
                      <option value="all">All 50</option>
                    </select>
                  </label>
                </div>
                <div className="table-scroll">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>#</th><th style={{ textAlign: "left" }}>Strategy</th><th>Sym</th><th>Style</th><th>TF</th>
                        <th>Trades</th><th>Win rate</th><th>PF</th><th>Expectancy</th><th>Net P&amp;L</th>
                        <th>Max DD</th><th>Data window</th><th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sweep.results
                        .filter((r) => labFilter === "all" || r.qualified)
                        .map((r, i) => {
                          const m = r.metrics;
                          return (
                            <tr key={`${r.strategy_id}-${(r as any).symbol ?? ""}-${r.timeframe}`}>
                              <td>{i + 1}</td>
                              <td style={{ textAlign: "left" }}>{r.name}</td>
                              <td>{(r as any).symbol ?? sweep.symbol}</td>
                              <td>{r.style}</td>
                              <td>{r.timeframe}{r.timeframe !== r.timeframe_native ? ` (want ${r.timeframe_native})` : ""}</td>
                              {r.error || !m ? (
                                <td colSpan={7} className="loss" style={{ textAlign: "left" }}>{r.error ?? "no result"}</td>
                              ) : (
                                <>
                                  <td>{m.total_trades}</td>
                                  <td className={m.win_rate !== null && m.win_rate >= (sweep.min_win_rate ?? 0.4) ? "gain" : "loss"}>
                                    {m.win_rate !== null ? `${(m.win_rate * 100).toFixed(1)}%` : "-"}
                                  </td>
                                  <td>{m.profit_factor ?? "-"}</td>
                                  <td>{inr(m.expectancy)}</td>
                                  <td className={m.net_profit >= 0 ? "gain" : "loss"}>{inr(m.net_profit)}</td>
                                  <td>{m.max_drawdown_pct}%</td>
                                  <td style={{ fontSize: 10.5 }}>
                                    {r.data_from?.slice(0, 10)} → {r.data_to?.slice(0, 10)}
                                  </td>
                                </>
                              )}
                              <td>{r.qualified ? <span className="badge gain">QUALIFIED</span> : r.error ? <span className="badge loss">ERROR</span> : <span className="badge">—</span>}</td>
                            </tr>
                          );
                        })}
                    </tbody>
                  </table>
                </div>
              </GlassPanel>
            </>
          )}
        </>
      )}

      {tab === "selling" && (
        <>
          <GlassPanel title="Option-Selling Lab — 24 strategies, tail-risk gate">
            <div className="form">
              <label>
                Underlying
                <select value={sellForm.symbol} onChange={(e) => setSellForm({ ...sellForm, symbol: e.target.value })}>
                  {INDICES.map((s) => (<option key={s}>{s}</option>))}
                </select>
              </label>
              <label>
                Years
                <input type="number" min={1} max={25} value={sellForm.years} onChange={(e) => setSellForm({ ...sellForm, years: Number(e.target.value) })} />
              </label>
              <label>
                Min profit factor
                <input type="number" min={0} step={0.1} value={sellForm.min_profit_factor} onChange={(e) => setSellForm({ ...sellForm, min_profit_factor: Number(e.target.value) })} />
              </label>
              <label>
                Min trades
                <input type="number" min={1} value={sellForm.min_trades} onChange={(e) => setSellForm({ ...sellForm, min_trades: Number(e.target.value) })} />
              </label>
              <label>
                Max worst trade %
                <input type="number" min={0.1} step={0.1} value={sellForm.max_worst_trade_pct_capital} onChange={(e) => setSellForm({ ...sellForm, max_worst_trade_pct_capital: Number(e.target.value) })} />
              </label>
              <label>
                Max drawdown %
                <input type="number" min={1} step={1} value={sellForm.max_drawdown_pct} onChange={(e) => setSellForm({ ...sellForm, max_drawdown_pct: Number(e.target.value) })} />
              </label>
              <button onClick={runSellingSweep} disabled={sellRunning}>{sellRunning ? "Running all 24…" : "Run 24-strategy selling sweep"}</button>
            </div>
            <div className="footnote">
              <strong>There is no win-rate gate here, on purpose.</strong> Premium selling routinely shows 70–90% win
              rates while losing money, because its P&amp;L is decided by the size of the rare losers rather than the
              count of the frequent winners — this library&apos;s own <code>sell_coil_strangle</code> wins 83.9% of the
              time at a 0.33 profit factor. A strategy qualifies on profit factor, single-trade tail size, drawdown and
              sample size instead. <strong>Naked structures clear a higher bar</strong> (PF {sellSweep?.gate?.naked_min_profit_factor ?? 1.6},
              worst trade {sellSweep?.gate?.naked_max_worst_trade_pct_capital ?? 1.0}%) because this engine fills stops
              at the stop level, so a naked short&apos;s real gap risk is understated and needs margin to cover it.
              Premiums are Black-Scholes-modeled from realized volatility; margin is a documented SPAN+exposure
              approximation, not an exchange figure. Positional strategies run on daily bars, which only go back
              ~2 years in this database — check the data-window column before trusting a positional result.
            </div>
            {sellError && <ErrorBanner message={sellError} />}
          </GlassPanel>

          {sellSweep && (
            <>
              <div className="tiles">
                <div className="tile"><div className="tile-label">Qualified</div><div className="tile-value gain">{sellSweep.qualified_count} / {sellSweep.strategy_count}</div></div>
                <div className="tile"><div className="tile-label">Gate</div><div className="tile-value" style={{ fontSize: 12 }}>PF ≥ {sellSweep.gate?.min_profit_factor ?? 1.3} · worst ≤ {sellSweep.gate?.max_worst_trade_pct_capital ?? 1.5}% · DD ≤ {sellSweep.gate?.max_drawdown_pct ?? 10}% · ≥ {sellSweep.gate?.min_trades ?? 20} trades</div></div>
                <div className="tile"><div className="tile-label">Window</div><div className="tile-value">{sellSweep.symbol} · {sellSweep.years}y requested</div></div>
                <div className="tile"><div className="tile-label">Sweep</div><div className="tile-value">{sellSweep.created_at ? new Date(sellSweep.created_at).toLocaleString() : "-"}</div></div>
              </div>
              <GlassPanel title="Selling leaderboard">
                <div className="form" style={{ paddingBottom: 0 }}>
                  <label>
                    Show
                    <select value={sellFilter} onChange={(e) => setSellFilter(e.target.value as "all" | "qualified")}>
                      <option value="all">All 24</option>
                      <option value="qualified">Qualified only</option>
                    </select>
                  </label>
                </div>
                <div className="table-scroll">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>#</th><th style={{ textAlign: "left" }}>Strategy</th><th>Style</th><th>Risk</th>
                        <th>Trades</th><th className="muted-col">Win %</th><th>PF</th><th>Net P&amp;L</th>
                        <th>Credit</th><th>Avg margin</th><th>Return on margin</th>
                        <th>Worst trade</th><th>Tail</th><th>Max DD</th><th>Data window</th>
                        <th style={{ textAlign: "left" }}>Verdict</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sellSweep.results
                        .filter((r) => sellFilter === "all" || r.qualified)
                        .map((r, i) => {
                          const m = r.metrics;
                          const s = m?.selling;
                          return (
                            <tr key={r.strategy_id}>
                              <td>{i + 1}</td>
                              <td style={{ textAlign: "left" }}>{r.name}</td>
                              <td>{r.style}</td>
                              <td>
                                {r.naked
                                  ? <span className="badge loss">NAKED</span>
                                  : <span className="badge">DEFINED</span>}
                              </td>
                              {r.error || !m ? (
                                <td colSpan={10} className="loss" style={{ textAlign: "left" }}>{r.error ?? "no result"}</td>
                              ) : (
                                <>
                                  <td>{m.total_trades}</td>
                                  {/* Shown for reference only — deliberately NOT part of the gate. */}
                                  <td className="muted-col">{m.win_rate !== null ? `${(m.win_rate * 100).toFixed(1)}%` : "-"}</td>
                                  <td className={(m.profit_factor ?? 0) >= (sellSweep.gate?.min_profit_factor ?? 1.3) ? "gain" : "loss"}>
                                    {m.profit_factor ?? "-"}
                                  </td>
                                  <td className={m.net_profit >= 0 ? "gain" : "loss"}>{inr(m.net_profit)}</td>
                                  <td>{inr(s?.total_credit_collected)}</td>
                                  <td>{inr(s?.avg_margin)}</td>
                                  <td className={(s?.return_on_margin_pct ?? 0) >= 0 ? "gain" : "loss"}>
                                    {s?.return_on_margin_pct !== null && s?.return_on_margin_pct !== undefined ? `${num(s.return_on_margin_pct, 1)}%` : "-"}
                                  </td>
                                  <td className={(s?.worst_trade_pct_capital ?? 0) > (sellSweep.gate?.max_worst_trade_pct_capital ?? 1.5) ? "loss" : ""}>
                                    {s?.worst_trade_pct_capital !== null && s?.worst_trade_pct_capital !== undefined ? `${num(s.worst_trade_pct_capital)}%` : "-"}
                                  </td>
                                  <td className={(s?.tail_ratio ?? 0) > 3 ? "loss" : ""}>{num(s?.tail_ratio)}</td>
                                  <td>{m.max_drawdown_pct}%</td>
                                  <td style={{ fontSize: 10.5 }}>{r.data_from?.slice(0, 10)} → {r.data_to?.slice(0, 10)}</td>
                                </>
                              )}
                              <td style={{ textAlign: "left", maxWidth: 280 }}>
                                {r.qualified
                                  ? <span className="badge gain">QUALIFIED</span>
                                  : r.error
                                    ? <span className="badge loss">ERROR</span>
                                    : <span className="fail-reason">{(r.gate_failures ?? []).join("; ") || "—"}</span>}
                              </td>
                            </tr>
                          );
                        })}
                    </tbody>
                  </table>
                </div>
              </GlassPanel>
            </>
          )}
        </>
      )}

      <style jsx>{`
        .page { display: flex; flex-direction: column; gap: 18px; }
        .tabs { display: flex; gap: 8px; }
        .tab {
          background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted);
          padding: 9px 16px; border-radius: 9px; font-size: 12.5px; font-weight: 600; cursor: pointer;
        }
        .tab.active { background: var(--purple-dim); border-color: rgba(125, 52, 220, 0.3); color: var(--purple); }
        .form { display: flex; flex-wrap: wrap; gap: 14px; padding: 18px 20px; align-items: flex-end; }
        label { display: flex; flex-direction: column; gap: 6px; font-size: 11.5px; font-weight: 600; color: var(--text-muted); letter-spacing: 0.04em; text-transform: uppercase; }
        input, select { background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 9px; padding: 9px 12px; font-size: 13.5px; min-width: 100px; }
        button { background: linear-gradient(145deg, var(--accent), var(--accent-hover)); color: #241404; font-weight: 700; font-size: 13.5px; border: none; border-radius: 10px; padding: 11px 20px; cursor: pointer; }
        button:disabled { opacity: 0.55; cursor: default; }
        .error { margin: 0 20px 16px; padding: 10px 14px; border-radius: 9px; background: var(--loss-dim); border: 1px solid rgba(217, 45, 63, 0.3); color: var(--loss); font-size: 13px; }
        .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }
        .tile { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 12px; padding: 12px 14px; }
        .tile-label { font-size: 10.5px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; color: var(--text-muted); }
        .tile-value { margin-top: 5px; font-family: var(--font-data); font-variant-numeric: tabular-nums; font-size: 15px; font-weight: 600; }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
        .table-scroll { overflow-x: auto; max-height: 480px; overflow-y: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; }
        .data-table th { text-align: center; padding: 8px 10px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); position: sticky; top: 0; background: var(--panel); }
        .data-table td { padding: 7px 10px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .side-header.call { color: var(--gain); }
        .side-header.put { color: var(--loss); }
        .strike-header, .strike-cell { background: var(--canvas-soft); font-weight: 700; }
        .atm-row td { background: var(--accent-dim); }
        .footnote { padding: 8px 20px 16px; font-size: 11px; color: var(--text-faint); line-height: 1.5; }
        .legs-editor { padding: 16px 20px; display: flex; flex-direction: column; gap: 10px; }
        .leg-row { display: flex; gap: 8px; align-items: center; }
        .leg-row select, .leg-row input { min-width: 80px; }
        .remove-btn { background: var(--loss-dim); color: var(--loss); border: 1px solid rgba(217, 45, 63, 0.26); width: 34px; padding: 9px 0; border-radius: 8px; font-size: 16px; line-height: 1; }
        .leg-actions { display: flex; gap: 10px; margin-top: 4px; }
        .add-btn { background: var(--canvas-soft); color: var(--text); border: 1px solid var(--panel-border); }
        .badge { display: inline-block; padding: 3px 8px; border-radius: 6px; font-size: 10px; font-weight: 700; letter-spacing: 0.05em; background: var(--canvas-soft); border: 1px solid var(--panel-border); }
        .badge.gain { background: rgba(34, 170, 96, 0.12); border-color: rgba(34, 170, 96, 0.3); }
        .badge.loss { background: var(--loss-dim); border-color: rgba(217, 45, 63, 0.3); }
        /* Win rate is shown in the selling leaderboard for reference but is NOT part of
           the gate; dimming it is the cheapest way to stop a reader ranking by it. */
        .muted-col { color: var(--text-faint); font-weight: 400; }
        .fail-reason { font-size: 10.5px; color: var(--text-faint); line-height: 1.45; display: block; }
        .footnote code { font-family: var(--font-data); font-size: 10.5px; padding: 1px 4px; border-radius: 4px; background: var(--canvas-soft); }
        .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
        @media (max-width: 1000px) { .grid-2 { grid-template-columns: 1fr; } }
      `}</style>
    </div>
  );
}
