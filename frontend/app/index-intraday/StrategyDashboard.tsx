"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import LineChart from "../../components/charts/LineChart";
import {
  fetchIIDeployments,
  fetchIIFamilies,
  fetchIIStrategies,
  fetchIIStrategy,
  setIIDeployment,
  type IIDeployment,
  type IIFamily,
  type IIModel,
  type IIResearch,
  type IIStats,
  type IIStrategy,
} from "../../lib/indexIntradayApi";
import { INDEXES, INDEX_LABEL, StatusTag, bp, dash, frac, num, paramText, tone } from "./ui";

const SORTS: [string, string][] = [
  ["sv_sharpe", "Sharpe, 2016–23"],
  ["sv_net", "Net bp a trade, 2016–23"],
  ["sel_sharpe", "Sharpe, selection 2016–21"],
  ["dsr", "Deflated Sharpe"],
];
const PAGE = 60;

/** The Strategy Dashboard: every variant the research tested, how far each got, and why it stopped.
 * Nothing here is a recommendation: no strategy reached Validated. */
export default function StrategyDashboard({
  research,
  onBacktest,
}: {
  research: IIResearch | null;
  onBacktest: (sid: string) => void;
}) {
  const [families, setFamilies] = useState<IIFamily[]>([]);
  const [finalists, setFinalists] = useState<IIStrategy[]>([]);
  const [rows, setRows] = useState<IIStrategy[]>([]);
  const [matched, setMatched] = useState(0);
  const [deps, setDeps] = useState<IIDeployment[]>([]);
  const [index, setIndex] = useState("");
  const [family, setFamily] = useState("");
  const [minTrades, setMinTrades] = useState(150);
  const [sort, setSort] = useState("sv_sharpe");
  const [limit, setLimit] = useState(PAGE);
  const [open, setOpen] = useState<IIStrategy | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([fetchIIFamilies(), fetchIIStrategies({ stage: 2, sort: "dsr", limit: 50 }), fetchIIDeployments()])
      .then(([f, s, d]) => {
        setFamilies(f.families);
        setFinalists(s.strategies);
        setDeps(d.deployments);
      })
      .catch((e) => setErr(e instanceof Error ? e.message : "Could not load the research."));
  }, []);

  const loadRows = useCallback(async () => {
    try {
      const r = await fetchIIStrategies({ index, family, min_trades: minTrades, sort, limit });
      setRows(r.strategies);
      setMatched(r.matched);
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not load the catalogue.");
    }
  }, [index, family, minTrades, sort, limit]);

  useEffect(() => {
    loadRows();
  }, [loadRows]);

  const funnel = useMemo(() => {
    const variants = families.reduce((a, f) => a + f.variants, 0);
    return {
      variants,
      stage1: families.reduce((a, f) => a + f.stage1, 0),
      stage2: families.reduce((a, f) => a + f.stage2, 0),
    };
  }, [families]);

  // what stopped the strategies that reached the last stage — read from their record, never typed in
  const last = useMemo(() => {
    const idx = Array.from(new Set(finalists.map((s) => INDEX_LABEL[s.index] ?? s.index)));
    const luck = finalists.filter((s) => (s.dsr ?? 0) < 0.95).length;
    const withEtf = finalists.filter((s) => s.stage3?.etf_2023_net_bp !== null && s.stage3?.etf_2023_net_bp !== undefined);
    const etfLoss = withEtf.filter((s) => (s.stage3?.etf_2023_net_bp ?? 0) <= 0).length;
    return { idx, luck, etfLoss, withEtf: withEtf.length };
  }, [finalists]);

  const noData = useMemo(
    () => Object.entries(research?.history_starts ?? {}).filter(([, d]) => d > "2021-12-31"),
    [research],
  );

  const show = async (sid: string) => {
    try {
      setOpen(await fetchIIStrategy(sid));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not load that strategy.");
    }
  };

  return (
    <div className="stack">
      {err && <div className="warnbox">{err}</div>}

      {/* ── the headline ─────────────────────────────────────────────────────── */}
      <div className="stats">
        <div className="stat">
          <div className="k">Variants tested</div>
          <div className="v">{research?.trials?.toLocaleString("en-IN") ?? dash}</div>
          <div className="s">
            14 families × parameters × exits × 8 indexes · {research?.trials_100_trades?.toLocaleString("en-IN") ?? dash}{" "}
            with 100+ trades
          </div>
        </div>
        <div className="stat">
          <div className="k">Passed selection</div>
          <div className="v">{funnel.stage1 || dash}</div>
          <div className="s">
            2016–21: 150+ trades, +1 bp a trade after costs, Sharpe 0.5, profit factor 1.1, 4 of 6 years up, still positive
            at 1.5× costs
          </div>
        </div>
        <div className="stat">
          <div className="k">Passed validation</div>
          <div className="v">{funnel.stage2 || dash}</div>
          <div className="s">still profitable after costs on 2022–23, data they were not chosen on</div>
        </div>
        <div className="stat">
          <div className="k">Validated</div>
          <div className="v loss">{research?.validated ?? 0}</div>
          <div className="s">
            {finalists.length
              ? `${finalists.length} reached the last stage (${last.idx.join(", ")}): ${last.luck} failed the luck test` +
                (last.withEtf ? ` and ${last.etfLoss} of ${last.withEtf} lost money traded on the ETF itself` : "") +
                " — so none is Paper Trading Approved"
              : "none reached the last stage — so none is Paper Trading Approved"}
          </div>
        </div>
      </div>

      <div className="verdict">
        <strong>Why “luck”:</strong> {research?.trials?.toLocaleString("en-IN") ?? "1,208"} variants behave like about{" "}
        {research?.effective_trials ?? 68} independent ones, and the best of {research?.effective_trials ?? 68} coin-flip
        strategies would show an annual Sharpe of about {research?.luck_sharpe ?? 0.85} by chance alone. A variant had to
        beat that with 95% confidence (the deflated Sharpe ratio). The untouched holdout,{" "}
        {research?.periods?.holdout ?? "2024-01 .. 2026-10"}, was kept for strategies that passed every test — none did, so
        it was never looked at.
        {noData.length > 0 && (
          <>
            {" "}
            {noData.map(([k, d]) => `${INDEX_LABEL[k] ?? k} (from ${d})`).join(" and ")} have no one-minute history in the
            2016–21 selection period, so their {research?.no_data ?? 0} variants could not be put through the protocol at all.
          </>
        )}
      </div>

      {/* ── those that reached the last stage ───────────────────────────────── */}
      <GlassPanel
        title={`The last stage — the ${finalists.length} that survived 2022–23`}
        note="every gate shown, not only the first failure"
      >
        <div className="tscroll">
          <table className="tbl">
            <thead>
              <tr>
                <th className="l">Strategy</th>
                <th className="l">Index</th>
                <th>2016–21 net</th>
                <th>2022–23 net</th>
                <th title="needs 0.95">Deflated Sharpe</th>
                <th title="needs > 0: the same rules traded on the ETF's own prices, 2020-23">On the ETF itself</th>
                <th title="needs 2 related indexes positive">Breadth</th>
                <th title="re-picking the best parameters every 6 months, 2018-23">Walk-forward</th>
                <th title="median Sharpe of nearby parameter sets">Neighbours</th>
                <th title="bootstrap of daily returns">P(losing year)</th>
                <th className="l" />
              </tr>
            </thead>
            <tbody>
              {finalists.map((s) => {
                const t = s.stage3;
                return (
                  <tr key={s.id} className="click" onClick={() => show(s.id)}>
                    <td className="l">
                      <div className="strong">{s.family_label}</div>
                      <div className="faint">
                        {s.id} · {paramText(s.params)} · {s.exit_label}
                      </div>
                    </td>
                    <td className="l">{INDEX_LABEL[s.index] ?? s.index}</td>
                    <td className={tone(s.sel.mean_net_bp)}>{bp(s.sel.mean_net_bp)}</td>
                    <td className={tone(s.val.mean_net_bp)}>{bp(s.val.mean_net_bp)}</td>
                    <td className={(s.dsr ?? 0) >= 0.95 ? "gain" : "loss"}>{num(s.dsr, 3)}</td>
                    <td className={t?.etf_2023_net_bp === null || t?.etf_2023_net_bp === undefined ? "muted" : t.etf_2023_net_bp > 0 ? "gain" : "loss"}>
                      {t?.etf_2023_net_bp === null || t?.etf_2023_net_bp === undefined ? "no ETF" : bp(t.etf_2023_net_bp)}
                    </td>
                    <td className={(t?.breadth_pos ?? 0) >= 2 ? "gain" : "loss"}>
                      {t ? `${num(t.breadth_pos, 0)} of ${num(t.breadth_tested, 0)}` : dash}
                    </td>
                    <td className={tone(t?.wf_bp)}>{t ? bp(t.wf_bp, 0) : dash}</td>
                    <td>{num(t?.nb_median_sharpe)}</td>
                    <td>{frac(t?.mc_p_losing_year)}</td>
                    <td className="l">
                      <button
                        className="btn sm"
                        onClick={(e) => {
                          e.stopPropagation();
                          onBacktest(s.id);
                        }}
                      >
                        Backtest
                      </button>
                    </td>
                  </tr>
                );
              })}
              {!finalists.length && (
                <tr>
                  <td className="l empty" colSpan={11}>
                    {families.length ? "No variant survived validation." : "Loading…"}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <p className="foot">
          Net is the mean result of a trade after Angel One&rsquo;s charges and the spread, in basis points of the position
          (100 bp = 1%). A deflated Sharpe of 0.95 means a 95% chance the edge is not luck, after accounting for how many
          variants were tried. &ldquo;On the ETF itself&rdquo; replays the rules on the tracking ETF&rsquo;s own one-minute
          prices — what a real order could have traded. On NIFTY NEXT 50 the index&rsquo;s minute prices lag its
          constituents (its one-minute returns are positively autocorrelated, +0.08 in 2022–23, where JUNIORBEES&rsquo;s are
          −0.32), so a breakout on the index looks like momentum that a real order cannot capture.
        </p>
      </GlassPanel>

      {/* ── the families ─────────────────────────────────────────────────────── */}
      <GlassPanel title="Strategy families" note="how far each idea got">
        <div className="tscroll">
          <table className="tbl">
            <thead>
              <tr>
                <th className="l">Family</th>
                <th>Variants</th>
                <th>Passed selection</th>
                <th>Passed validation</th>
                <th>Best Sharpe 2016–23</th>
                <th className="l">Best variant</th>
                <th className="l">Where it stopped</th>
              </tr>
            </thead>
            <tbody>
              {families.map((f) => (
                <tr key={f.family}>
                  <td className="l strong">{f.label}</td>
                  <td>{f.variants}</td>
                  <td className={f.stage1 ? "" : "muted"}>{f.stage1}</td>
                  <td className={f.stage2 ? "" : "muted"}>{f.stage2}</td>
                  <td className={tone(f.best_sv_sharpe)}>{num(f.best_sv_sharpe)}</td>
                  <td className="l">
                    {f.best ? (
                      <button className="linkish" onClick={() => show(f.best!.id)}>
                        {INDEX_LABEL[f.best.index] ?? f.best.index} · {paramText(f.best.params)} · {bp(f.best.net_bp)}
                      </button>
                    ) : (
                      dash
                    )}
                  </td>
                  <td className="l muted wrap">{f.best?.failed ?? dash}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </GlassPanel>

      {/* ── the catalogue ────────────────────────────────────────────────────── */}
      <GlassPanel title="All tested variants" note={`${matched.toLocaleString("en-IN")} match`}>
        <div className="filters">
          <label>
            Index
            <select value={index} onChange={(e) => { setIndex(e.target.value); setLimit(PAGE); }}>
              <option value="">all</option>
              {INDEXES.map((k) => (
                <option key={k} value={k}>
                  {INDEX_LABEL[k]}
                </option>
              ))}
            </select>
          </label>
          <label>
            Family
            <select value={family} onChange={(e) => { setFamily(e.target.value); setLimit(PAGE); }}>
              <option value="">all</option>
              {families.map((f) => (
                <option key={f.family} value={f.family}>
                  {f.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Trades 2016–23
            <select value={minTrades} onChange={(e) => { setMinTrades(Number(e.target.value)); setLimit(PAGE); }}>
              <option value={0}>any</option>
              <option value={100}>100+</option>
              <option value={150}>150+ (the selection bar)</option>
              <option value={300}>300+</option>
            </select>
          </label>
          <label>
            Sort by
            <select value={sort} onChange={(e) => setSort(e.target.value)}>
              {SORTS.map(([k, l]) => (
                <option key={k} value={k}>
                  {l}
                </option>
              ))}
            </select>
          </label>
        </div>
        {minTrades === 0 && (
          <div className="note">
            Without a trade minimum the top of a Sharpe sort is small samples — a 16-trade variant can show a Sharpe of 1.9
            by chance.
          </div>
        )}
        <div className="tscroll">
          <table className="tbl">
            <thead>
              <tr>
                <th className="l">Strategy</th>
                <th className="l">Index</th>
                <th className="l">Status</th>
                <th>Trades</th>
                <th>Win rate</th>
                <th>Net / trade</th>
                <th>Profit factor</th>
                <th>Sharpe</th>
                <th>2022–23 net</th>
                <th className="l">First gate failed</th>
                <th className="l" />
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => {
                const on = deps.find((d) => d.sid === s.id);
                return (
                  <tr key={s.id} className="click" onClick={() => show(s.id)}>
                    <td className="l">
                      <div className="strong">
                        {s.family_label}
                        {on && <span className="chip run">paper · {on.model}</span>}
                      </div>
                      <div className="faint">
                        {s.id} · {paramText(s.params)} · {s.exit_label}
                      </div>
                    </td>
                    <td className="l">{INDEX_LABEL[s.index] ?? s.index}</td>
                    <td className="l">
                      <StatusTag status={s.status} />
                    </td>
                    <td>{num(s.sv.trades, 0)}</td>
                    <td>{frac(s.sv.win_rate)}</td>
                    <td className={tone(s.sv.mean_net_bp)}>{bp(s.sv.mean_net_bp)}</td>
                    <td>{num(s.sv.profit_factor)}</td>
                    <td className={tone(s.sv.sharpe)}>{num(s.sv.sharpe)}</td>
                    <td className={tone(s.val.mean_net_bp)}>{bp(s.val.mean_net_bp)}</td>
                    <td className="l muted wrap">{s.failed ?? dash}</td>
                    <td className="l">
                      <button
                        className="btn sm"
                        onClick={(e) => {
                          e.stopPropagation();
                          onBacktest(s.id);
                        }}
                      >
                        Backtest
                      </button>
                    </td>
                  </tr>
                );
              })}
              {!rows.length && (
                <tr>
                  <td className="l empty" colSpan={11}>
                    No variant matches.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {rows.length < matched && (
          <button className="btn more" onClick={() => setLimit((l) => l + PAGE)}>
            Show {Math.min(PAGE, matched - rows.length)} more
          </button>
        )}
      </GlassPanel>

      {open && (
        <StrategyDetail
          s={open}
          deployment={deps.find((d) => d.sid === open.id) ?? null}
          onClose={() => setOpen(null)}
          onBacktest={onBacktest}
          onDeployed={setDeps}
        />
      )}
    </div>
  );
}

const PERIOD_ROWS: [string, keyof IIStats, (v: number | null | undefined) => string][] = [
  ["Trades", "trades", (v) => num(v, 0)],
  ["Trades a day", "trades_per_day", (v) => num(v, 2)],
  ["Win rate", "win_rate", (v) => frac(v)],
  ["Net a trade (after costs)", "mean_net_bp", (v) => bp(v)],
  ["Gross a trade (before costs)", "mean_gross_bp", (v) => bp(v)],
  ["Profit factor", "profit_factor", (v) => num(v)],
  ["Avg win ÷ avg loss", "rr", (v) => num(v)],
  ["Sharpe (annual)", "sharpe", (v) => num(v)],
  ["Sortino", "sortino", (v) => num(v)],
  ["Return a year", "ann_bp", (v) => bp(v, 0)],
  ["Worst drawdown", "max_dd_bp", (v) => (v === null || v === undefined ? dash : `−${v.toFixed(0)} bp`)],
  ["Months positive", "months_positive", (v) => frac(v, 0)],
  ["Years positive", "years_positive", (v) => num(v, 0)],
];

function StrategyDetail({
  s,
  deployment,
  onClose,
  onBacktest,
  onDeployed,
}: {
  s: IIStrategy;
  deployment: IIDeployment | null;
  onClose: () => void;
  onBacktest: (sid: string) => void;
  onDeployed: (d: IIDeployment[]) => void;
}) {
  const hasEtf = s.index !== "BANKEX";
  const [model, setModel] = useState<IIModel>(deployment?.model ?? (hasEtf ? "etf" : "index"));
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const t = s.stage3;
  const curve = useMemo(() => {
    let acc = 0;
    return (s.monthly ?? []).map(([m, v]) => ({ ts: m, value: (acc += v) }));
  }, [s.monthly]);

  const toggle = async (enabled: boolean) => {
    setBusy(true);
    setMsg(null);
    try {
      const r = await setIIDeployment(s.id, enabled, model);
      onDeployed(r.deployments);
      setMsg(enabled ? `Running in paper on the ${model === "etf" ? "ETF" : "index simulation"} model.` : "Switched off.");
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Could not change it.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="drawer-wrap" onClick={onClose}>
      <div className="drawer" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-head">
          <div>
            <div className="faint">
              {s.id} · round {s.round} · {INDEX_LABEL[s.index] ?? s.index}
            </div>
            <div className="dtitle">{s.family_label}</div>
            <div className="muted">
              {paramText(s.params)} · {s.exit_label}
            </div>
          </div>
          <button className="btn" onClick={onClose}>
            Close
          </button>
        </div>

        <div className="dstatus">
          <StatusTag status={s.status} />
          <span className="wrap">{s.failed ? `Stopped at — ${s.failed}` : "Passed every gate."}</span>
        </div>

        <table className="tbl small">
          <thead>
            <tr>
              <th className="l" />
              <th>Selection 2016–21</th>
              <th>Validation 2022–23</th>
              <th>Both</th>
            </tr>
          </thead>
          <tbody>
            {PERIOD_ROWS.map(([label, key, fmt]) => (
              <tr key={key}>
                <td className="l muted">{label}</td>
                <td>{fmt(s.sel[key] as number | null | undefined)}</td>
                <td>{fmt(s.val[key] as number | null | undefined)}</td>
                <td>{fmt(s.sv[key] as number | null | undefined)}</td>
              </tr>
            ))}
            <tr>
              <td className="l muted">Deflated Sharpe (needs 0.95)</td>
              <td colSpan={3} className={(s.dsr ?? 0) >= 0.95 ? "gain" : ""}>
                {num(s.dsr, 3)}
              </td>
            </tr>
          </tbody>
        </table>

        {t && (
          <>
            <div className="dsec">The last stage</div>
            <table className="tbl small">
              <tbody>
                <tr>
                  <td className="l muted">Traded on the ETF itself, 2020–23 (needs &gt; 0)</td>
                  <td className={tone(t.etf_2023_net_bp)}>
                    {t.etf_2023_net_bp === null ? "no ETF" : `${bp(t.etf_2023_net_bp)} net · ${bp(t.etf_2023_gross_bp)} gross · ${num(t.etf_2023_trades, 0)} trades`}
                  </td>
                </tr>
                <tr>
                  <td className="l muted">Same rules on the index, 2020–23</td>
                  <td className={tone(t.idx_2023_net_bp)}>
                    {bp(t.idx_2023_net_bp)} · {num(t.idx_2023_trades, 0)} trades
                  </td>
                </tr>
                <tr>
                  <td className="l muted">Breadth (needs 2 related indexes positive)</td>
                  <td>
                    {num(t.breadth_pos, 0)} of {num(t.breadth_tested, 0)}
                  </td>
                </tr>
                <tr>
                  <td className="l muted">Walk-forward, re-picked every 6 months</td>
                  <td className={tone(t.wf_bp)}>{bp(t.wf_bp, 0)} in total</td>
                </tr>
                <tr>
                  <td className="l muted">Nearby parameters, median Sharpe</td>
                  <td>{num(t.nb_median_sharpe)}</td>
                </tr>
                <tr>
                  <td className="l muted">Monte Carlo year (bootstrap)</td>
                  <td>
                    median {bp(t.mc_median_year_bp, 0)} · worst 5% {bp(t.mc_p5_year_bp, 0)} · P(losing year){" "}
                    {frac(t.mc_p_losing_year)} · 95% drawdown {bp(t.mc_dd95_bp, 0)}
                  </td>
                </tr>
              </tbody>
            </table>
          </>
        )}

        {curve.length > 1 && (
          <>
            <div className="dsec">Cumulative net, 2016–23 (bp of the position, summed by month)</div>
            <LineChart points={curve} height={180} valueSuffix=" bp" fillToZero />
          </>
        )}

        <div className="dsec">Paper trading</div>
        <div className="deploy">
          <p className="wrap">
            {s.status === "Paper Trading Approved"
              ? "Approved for paper trading."
              : `Not approved — it is ${s.status}. Running it in paper is an observation of a strategy the research rejected, and is labelled so on every trade.`}
          </p>
          <div className="row">
            <label>
              Model
              <select value={model} disabled={!!deployment} onChange={(e) => setModel(e.target.value as IIModel)}>
                {hasEtf && <option value="etf">ETF — fills at the live bid / ask</option>}
                <option value="index">Index simulation — index points, ETF costs</option>
              </select>
            </label>
            {deployment ? (
              <button className="btn danger" disabled={busy} onClick={() => toggle(false)}>
                Stop paper ({deployment.model})
              </button>
            ) : (
              <button className="btn primary" disabled={busy} onClick={() => toggle(true)}>
                Run in paper
              </button>
            )}
            <button className="btn" onClick={() => onBacktest(s.id)}>
              Open in the Backtesting Lab
            </button>
          </div>
          {msg && <div className="note">{msg}</div>}
        </div>
      </div>
    </div>
  );
}
