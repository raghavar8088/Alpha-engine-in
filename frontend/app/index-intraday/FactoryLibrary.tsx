"use client";

/** The Strategy Factory's strategies, traded intraday on the indexes (backend index_intraday/factory.py).
 *
 * All 69 factory hypotheses (chart patterns, candlesticks, price structure, indicators, multi-condition)
 * on all 8 timeframes — 546 strategies on every index. The decision is the factory's own evaluate(); the
 * trading is this module's: entries 09:20–14:30 at bar closes, flat by 15:12, the ETF's costs. NIFTY and
 * BANK NIFTY were run over 2019–23 and graded with the factory's 1–5 rules (in sample 2019–21, out of
 * sample 2022–23); the 2024–26 holdout was never used. Other indexes list the same strategies ungraded —
 * any of them runs in the Backtesting Lab. Paper is an observation, as for every strategy here. */

import { useCallback, useEffect, useMemo, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import LineChart from "../../components/charts/LineChart";
import {
  fetchIISFActivity,
  fetchIISFHeader,
  fetchIISFHypotheses,
  fetchIISFStrategies,
  fetchIISFStrategy,
  setIIDeployment,
  type IIModel,
  type IISFActivity,
  type IISFHeader,
  type IISFHypothesis,
  type IISFStats,
  type IISFStrategy,
} from "../../lib/indexIntradayApi";
import { INDEXES, INDEX_LABEL, Side, StatusTag, bp, dash, frac, hhmm, inr, num, px, tone, when } from "./ui";

const FAMILIES: [string, string][] = [
  ["", "All"],
  ["chart", "Chart Pattern"],
  ["candlestick", "Candlestick"],
  ["structure", "Price Structure"],
  ["indicator", "Indicator"],
  ["hybrid", "Multi-Condition"],
];
const TFS = ["", "1m", "5m", "15m", "30m", "45m", "1h", "4h", "1d"];
const GRADE_FILTERS: [string, string][] = [
  ["", "All"],
  ["5", "5"],
  ["4", "4"],
  ["3", "3"],
  ["2", "2"],
  ["1", "1"],
  ["ungraded", "ungraded"],
];
const SORTS: [string, string][] = [
  ["grade", "Grade, then Sharpe"],
  ["sharpe", "Sharpe, 2019–23"],
  ["net", "Net return, 2019–23"],
  ["oos", "Out of sample, 2022–23"],
  ["dsr", "Deflated Sharpe"],
  ["pf", "Profit factor"],
  ["trades", "Trades"],
  ["id", "Catalogue order"],
];
const GRADE_NOTE: Record<number, string> = {
  5: "production candidate",
  4: "strong",
  3: "acceptable",
  2: "likely overfit or too thin",
  1: "rejected",
};
const REJECT_LABEL: Record<string, string> = {
  bars: "not enough history",
  regime: "market regime not the one it trades",
  detector: "setup not present",
  confirmation: "a confirmation failed",
  levels: "stop / target geometry unusable",
};
type Sub = "library" | "hypotheses" | "positions" | "signals";
const PAGE = 60;

export function Grade({ g }: { g: number | null | undefined }) {
  if (g === null || g === undefined) return <span className="grade g0">—</span>;
  return <span className={`grade g${g}`}>{g}</span>;
}

const tfLabel = (tf: string) => (tf === "1d" ? "1d (next day)" : tf);

export default function FactoryLibrary({ onBacktest }: { onBacktest: (sid: string) => void }) {
  const [index, setIndex] = useState("NIFTY");
  const [head, setHead] = useState<IISFHeader | null>(null);
  const [sub, setSub] = useState<Sub>("library");
  const [family, setFamily] = useState("");
  const [tf, setTf] = useState("");
  const [grade, setGrade] = useState("");
  const [sort, setSort] = useState("grade");
  const [q, setQ] = useState("");
  const [limit, setLimit] = useState(PAGE);
  const [rows, setRows] = useState<IISFStrategy[]>([]);
  const [matched, setMatched] = useState(0);
  const [hyps, setHyps] = useState<IISFHypothesis[]>([]);
  const [act, setAct] = useState<IISFActivity | null>(null);
  const [open, setOpen] = useState<IISFStrategy | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    fetchIISFHeader(index)
      .then((h) => {
        setHead(h);
        setErr(null);
      })
      .catch((e) => setErr(e instanceof Error ? e.message : "Could not load the factory library."));
  }, [index]);

  const loadRows = useCallback(async () => {
    try {
      const r = await fetchIISFStrategies({ index, family, timeframe: tf, grade, sort, q, limit });
      setRows(r.strategies);
      setMatched(r.matched);
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not load the strategies.");
    }
  }, [index, family, tf, grade, sort, q, limit]);

  useEffect(() => {
    if (sub === "library") loadRows();
  }, [sub, loadRows]);

  useEffect(() => {
    if (sub !== "hypotheses") return;
    fetchIISFHypotheses(index)
      .then((h) => setHyps(h.hypotheses))
      .catch((e) => setErr(e instanceof Error ? e.message : "Could not load the hypotheses."));
  }, [sub, index]);

  const loadActivity = useCallback(() => {
    fetchIISFActivity(150)
      .then(setAct)
      .catch((e) => setErr(e instanceof Error ? e.message : "Could not load paper activity."));
  }, []);

  useEffect(() => {
    if (sub === "positions" || sub === "signals") {
      loadActivity();
      const t = setInterval(loadActivity, 30000);
      return () => clearInterval(t);
    }
  }, [sub, loadActivity]);

  const show = async (sid: string) => {
    try {
      setOpen(await fetchIISFStrategy(sid));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not load that strategy.");
    }
  };

  const dist = head?.distribution;
  const covered = dist?.covered ?? false;
  const graded3 = dist ? Number(dist.grades["5"] ?? 0) + Number(dist.grades["4"] ?? 0) + Number(dist.grades["3"] ?? 0) : 0;
  const pickGrade = (g: string) => {
    setGrade((cur) => (cur === g ? "" : g));
    setLimit(PAGE);
    setSub("library");
  };

  return (
    <div className="stack">
      {err && <div className="warnbox">{err}</div>}

      <div className="observe">
        <strong>The Strategy Factory&rsquo;s {head?.strategies_per_index ?? 546} strategies, traded intraday.</strong>{" "}
        All {head?.hypotheses ?? 69} hypotheses — chart patterns, candlesticks, price structure, indicators and
        multi-condition combinations — on all 8 timeframes. The signal is the factory&rsquo;s own code; the trading is this
        module&rsquo;s: a decision at a bar&rsquo;s close from 09:20 to 14:30, filled at the next minute, every position flat
        by 15:12, the ETF&rsquo;s charges and spread. A daily (1d) strategy trades yesterday&rsquo;s pattern from 09:20 today. An
        index prints no volume, so volume rules read the tracking ETF&rsquo;s.
      </div>

      <div className="row spread">
        <label className="pickidx">
          Index
          <select
            value={index}
            onChange={(e) => {
              setIndex(e.target.value);
              setLimit(PAGE);
            }}
          >
            {INDEXES.map((ix) => (
              <option key={ix} value={ix}>
                {INDEX_LABEL[ix]}
                {head?.indexes && !head.indexes.includes(ix) ? " — not graded" : ""}
              </option>
            ))}
          </select>
        </label>
        <div className="faint">
          {head?.generated ? `Catalogue run ${when(head.generated)} · ` : ""}
          {head?.periods
            ? `in sample ${head.periods.in_sample.join(" → ")} · out of sample ${head.periods.out_of_sample.join(" → ")} · holdout 2024–26 never used`
            : ""}
        </div>
      </div>

      <div className="stats">
        <div className="stat">
          <div className="k">Strategies on {INDEX_LABEL[index]}</div>
          <div className="v">{dist?.strategies ?? dash}</div>
          <div className="s">
            {head?.hypotheses ?? 69} hypotheses × 8 timeframes (session ideas skip 1d) — the factory&rsquo;s whole library
          </div>
        </div>
        <div className="stat">
          <div className="k">Graded 3 or better</div>
          <div className={`v ${graded3 ? "" : "loss"}`}>{covered ? graded3 : dash}</div>
          <div className="s">
            {covered
              ? "profitable after costs over 2019–23, still profitable out of sample (2022–23), profit factor 1.15+"
              : "this index was not in the catalogue run — run any strategy in the Backtesting Lab"}
          </div>
        </div>
        <div className="stat">
          <div className="k">Costs a round trip</div>
          <div className="v sm">
            {head?.costs?.[index]
              ? bp(head.costs[index].fee_rt_bp + 2 * head.costs[index].slip_bp_a_side)
              : dash}
          </div>
          <div className="s">
            {head?.costs?.[index]
              ? `Angel's charges ${bp(head.costs[index].fee_rt_bp)} + ${bp(head.costs[index].slip_bp_a_side)} spread a side (${head.costs[index].etf ?? "no ETF"})`
              : "the index route's measured costs"}
          </div>
        </div>
        <div className="stat">
          <div className="k">Approved for paper</div>
          <div className="v loss">0</div>
          <div className="s">
            a grade is the factory&rsquo;s verdict, not this module&rsquo;s Validated protocol — paper runs are observations
          </div>
        </div>
      </div>

      <GlassPanel title="Grade distribution" note="grade 5 = production candidate · grade 1 = rejected">
        <div className="gradebar">
          {["5", "4", "3", "2", "1"].map((g) => (
            <button key={g} className={`gchip g${g} ${grade === g ? "on" : ""}`} onClick={() => pickGrade(g)}>
              <span className="gk">GRADE {g}</span>
              <span className="gv">{dist ? dist.grades[g] ?? 0 : dash}</span>
            </button>
          ))}
          <button className={`gchip g0 ${grade === "ungraded" ? "on" : ""}`} onClick={() => pickGrade("ungraded")}>
            <span className="gk">NOT BACKTESTED</span>
            <span className="gv">{dist ? dist.ungraded : dash}</span>
          </button>
        </div>
        <p className="foot">
          Grading never uses win rate alone: a strategy must be profitable after costs over 2019–23 with a profit factor above
          1 and at least 20 trades, and <strong>survive out of sample</strong> (2022–23, years it was never fitted on — the
          factory&rsquo;s rules were fixed before this run). Failing out of sample caps it at grade 2, named as likely overfit.
          Grade 5 also needs profit factor 1.6+, drawdown under 15% and a Sharpe of 1+. The deflated Sharpe column corrects
          for having tried all of them.
        </p>
      </GlassPanel>

      <div className="subtabs">
        {(
          [
            ["library", "Strategy Library"],
            ["hypotheses", `The ${head?.hypotheses ?? 69} Hypotheses`],
            ["positions", "Paper Positions"],
            ["signals", "Signal Feed"],
          ] as [Sub, string][]
        ).map(([k, label]) => (
          <button key={k} className={sub === k ? "stab on" : "stab"} onClick={() => setSub(k)}>
            {label}
          </button>
        ))}
      </div>

      {sub === "library" && (
        <GlassPanel
          title="Strategy library"
          note={`${matched.toLocaleString("en-IN")} shown · click a row for its rules and backtest`}
        >
          <div className="pillrow">
            <span className="pk">Family</span>
            {FAMILIES.map(([k, label]) => (
              <button
                key={k || "all"}
                className={family === k ? "pill on" : "pill"}
                onClick={() => {
                  setFamily(k);
                  setLimit(PAGE);
                }}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="pillrow">
            <span className="pk">Timeframe</span>
            {TFS.map((k) => (
              <button
                key={k || "all"}
                className={tf === k ? "pill on" : "pill"}
                onClick={() => {
                  setTf(k);
                  setLimit(PAGE);
                }}
              >
                {k || "All"}
              </button>
            ))}
          </div>
          <div className="pillrow">
            <span className="pk">Grade</span>
            {GRADE_FILTERS.map(([k, label]) => (
              <button
                key={k || "all"}
                className={grade === k ? "pill on" : "pill"}
                onClick={() => {
                  setGrade(k);
                  setLimit(PAGE);
                }}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="filters">
            <label className="wide">
              Search
              <input
                value={q}
                placeholder="name, setup or id — e.g. engulfing, SF0123"
                onChange={(e) => {
                  setQ(e.target.value);
                  setLimit(PAGE);
                }}
              />
            </label>
            <label>
              Sort
              <select value={sort} onChange={(e) => setSort(e.target.value)}>
                {SORTS.map(([k, label]) => (
                  <option key={k} value={k}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="tscroll">
            <table className="tbl">
              <thead>
                <tr>
                  <th className="l">Strategy</th>
                  <th>Family</th>
                  <th>TF</th>
                  <th>Grade</th>
                  <th>Trades</th>
                  <th>Win</th>
                  <th>Net a trade</th>
                  <th>Total 2019–23</th>
                  <th>Profit factor</th>
                  <th>Sharpe</th>
                  <th>2022–23</th>
                  <th>Deflated</th>
                  <th>Paper</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((s) => (
                  <tr key={s.id} className="click" onClick={() => show(s.id)}>
                    <td className="l">
                      <div className="strong">{s.hypothesis_name}</div>
                      <div className="faint">
                        {s.id}
                        {s.volume_dependent ? ` · volume from ${s.etf ?? "— (none)"}` : ""}
                      </div>
                    </td>
                    <td>{s.family_label}</td>
                    <td>{s.timeframe}</td>
                    <td>
                      <Grade g={s.grade} />
                    </td>
                    <td>{num(s.all.trades, 0)}</td>
                    <td>{frac(s.all.win_rate)}</td>
                    <td className={tone(s.all.mean_net_bp)}>{bp(s.all.mean_net_bp)}</td>
                    <td className={tone(s.all.total_bp)}>{bp(s.all.total_bp, 1)}</td>
                    <td>{num(s.all.profit_factor)}</td>
                    <td className={tone(s.all.sharpe)}>{num(s.all.sharpe)}</td>
                    <td className={tone(s.oos.total_bp)}>{bp(s.oos.total_bp, 1)}</td>
                    <td>{num(s.dsr, 2)}</td>
                    <td>{s.deployed ? <span className="chip run">{s.deployed}</span> : <span className="faint">—</span>}</td>
                  </tr>
                ))}
                {!rows.length && (
                  <tr>
                    <td className="l empty" colSpan={13}>
                      No strategy matches.
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
      )}

      {sub === "hypotheses" && (
        <GlassPanel
          title={`The ${hyps.length || 69} hypotheses`}
          note={`each on 8 timeframes · grades on ${INDEX_LABEL[index]} · click a grade to open that strategy`}
        >
          <div className="tscroll">
            <table className="tbl">
              <thead>
                <tr>
                  <th className="l">Hypothesis</th>
                  <th className="l">Why it should work</th>
                  <th className="l">Setup · confirmations</th>
                  <th>Reward</th>
                  {TFS.slice(1).map((t) => (
                    <th key={t}>{t}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {hyps.map((h) => (
                  <tr key={h.key}>
                    <td className="l">
                      <div className="strong">{h.name}</div>
                      <div className="faint">
                        {h.family_label} · {h.sub_family}
                        {h.intraday_only ? " · session idea" : ""}
                      </div>
                    </td>
                    <td className="l wrap hyp">{h.hypothesis}</td>
                    <td className="l wrap">
                      <code>{h.detector}</code>
                      {h.confirmations.length ? ` + ${h.confirmations.join(", ")}` : ""}
                      {h.regimes.length ? <div className="faint">regimes: {h.regimes.join(", ")}</div> : null}
                    </td>
                    <td>{num(h.target_r, 1)}R</td>
                    {TFS.slice(1).map((t) => {
                      const c = h.timeframes.find((x) => x.timeframe === t);
                      return (
                        <td key={t}>
                          {c ? (
                            <button className="linkish" title={c.id} onClick={() => show(c.id)}>
                              <Grade g={c.grade} />
                            </button>
                          ) : (
                            <span className="faint">n/a</span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="foot">
            &ldquo;n/a&rdquo;: a session idea (the opening range, session VWAP, yesterday&rsquo;s levels, the gap) has no
            meaning on a daily bar, so the factory does not build it there.
          </p>
        </GlassPanel>
      )}

      {sub === "positions" && <Positions act={act} onOpen={show} onChanged={loadActivity} />}

      {sub === "signals" && (
        <GlassPanel title="Signal feed" note="the paper engine's entries, exits, refusals and misses for factory strategies">
          {!act?.events?.length ? (
            <div className="empty-block">
              Nothing yet. Switch a strategy on in its drawer (Run in paper); the engine evaluates it at every bar close
              from 09:20 and logs what it does here.
            </div>
          ) : (
            <ul className="events">
              {act.events.map((e, k) => (
                <li key={k}>
                  <span className="faint">{when(e.at)}</span>
                  <span className={`chip ${e.kind === "entry" ? "good" : e.kind === "exit" ? "" : "bad"}`}>{e.kind}</span>
                  {e.sid ? (
                    <button className="linkish" onClick={() => show(e.sid!)}>
                      {e.text}
                    </button>
                  ) : (
                    <span>{e.text}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </GlassPanel>
      )}

      {open && (
        <FactoryDetail
          s={open}
          onClose={() => setOpen(null)}
          onBacktest={onBacktest}
          onChanged={(m) => {
            setOpen({ ...open, deployed: m });
            if (sub === "library") loadRows();
            if (sub === "positions") loadActivity();
          }}
        />
      )}
    </div>
  );
}

function Positions({
  act,
  onOpen,
  onChanged,
}: {
  act: IISFActivity | null;
  onOpen: (sid: string) => void;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const stop = async (sid: string, model: IIModel) => {
    setBusy(sid);
    try {
      await setIIDeployment(sid, false, model);
      onChanged();
    } finally {
      setBusy(null);
    }
  };
  return (
    <>
      <GlassPanel title="Running in paper" note="factory strategies switched on — each is evaluated at every bar close">
        {!act?.deployments?.length ? (
          <div className="empty-block">No factory strategy is running. Open one from the library and choose Run in paper.</div>
        ) : (
          <table className="tbl small">
            <thead>
              <tr>
                <th className="l">Strategy</th>
                <th>Index</th>
                <th>Model</th>
                <th>Grade</th>
                <th>Status</th>
                <th>Since</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {act.deployments.map((d) => (
                <tr key={d.sid}>
                  <td className="l">
                    <button className="linkish" onClick={() => onOpen(d.sid)}>
                      {d.name ?? d.sid}
                    </button>
                    <div className="faint">{d.sid}</div>
                  </td>
                  <td>{INDEX_LABEL[d.index] ?? d.index}</td>
                  <td>{d.model}</td>
                  <td>
                    <Grade g={d.grade} />
                  </td>
                  <td>
                    <StatusTag status={d.status} />
                  </td>
                  <td>{when(d.added_at)}</td>
                  <td>
                    <button className="btn sm danger" disabled={busy === d.sid} onClick={() => stop(d.sid, d.model)}>
                      Stop
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </GlassPanel>

      <GlassPanel title="Open positions" note="marked at the last price; the factory's stop and target, re-anchored to the fill">
        {!act?.open_positions?.length ? (
          <div className="empty-block">No open factory position.</div>
        ) : (
          <div className="tscroll">
            <table className="tbl small">
              <thead>
                <tr>
                  <th className="l">Strategy</th>
                  <th>Side</th>
                  <th>Entered</th>
                  <th>Fill</th>
                  <th>Stop</th>
                  <th>Target</th>
                  <th>Mark</th>
                  <th>Open P&amp;L</th>
                  <th className="l">Setup</th>
                </tr>
              </thead>
              <tbody>
                {act.open_positions.map((p, k) => (
                  <tr key={k}>
                    <td className="l">
                      <button className="linkish" onClick={() => onOpen(p.sid)}>
                        {p.name ?? p.sid}
                      </button>
                      <div className="faint">
                        {p.instrument} · {p.model}
                      </div>
                    </td>
                    <td>
                      <Side side={p.side} />
                    </td>
                    <td>{hhmm(p.entry_min)}</td>
                    <td>{px(p.fill)}</td>
                    <td>{px(p.stop)}</td>
                    <td>{px(p.target)}</td>
                    <td>{px(p.mark)}</td>
                    <td className={tone(p.unrealized)}>{inr(p.unrealized)}</td>
                    <td className="l wrap">{p.signal ? `${p.signal.pattern} — ${p.signal.detail}` : dash}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>

      <GlassPanel title="Closed trades" note="after Angel's charges and the spread">
        {!act?.trades?.length ? (
          <div className="empty-block">No factory trade has closed yet.</div>
        ) : (
          <div className="tscroll">
            <table className="tbl small">
              <thead>
                <tr>
                  <th className="l">Strategy</th>
                  <th>Day</th>
                  <th>Side</th>
                  <th>In</th>
                  <th>Out</th>
                  <th>Exit</th>
                  <th>Net</th>
                  <th>Net %</th>
                </tr>
              </thead>
              <tbody>
                {act.trades.map((t, k) => (
                  <tr key={k}>
                    <td className="l">
                      <button className="linkish" onClick={() => onOpen(t.sid)}>
                        {t.name ?? t.sid}
                      </button>
                    </td>
                    <td>{t.day}</td>
                    <td>
                      <Side side={t.side} />
                    </td>
                    <td>
                      {hhmm(t.entry_min)} @ {px(t.entry)}
                    </td>
                    <td>
                      {hhmm(t.exit_min)} @ {px(t.exit)}
                    </td>
                    <td>{t.exit_reason}</td>
                    <td className={tone(t.net)}>{inr(t.net)}</td>
                    <td className={tone(t.net_bp)}>{bp(t.net_bp)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>
    </>
  );
}

const PERIOD_ROWS: [string, keyof IISFStats, (v: number | null | undefined) => string][] = [
  ["Trades", "trades", (v) => num(v, 0)],
  ["Trades a day", "trades_per_day", (v) => num(v, 2)],
  ["Win rate", "win_rate", (v) => frac(v)],
  ["Net a trade (after costs)", "mean_net_bp", (v) => bp(v)],
  ["Gross a trade (before costs)", "mean_gross_bp", (v) => bp(v)],
  ["Profit factor", "profit_factor", (v) => num(v)],
  ["Sharpe (annual)", "sharpe", (v) => num(v)],
  ["Total (one position, no leverage)", "total_bp", (v) => bp(v, 1)],
  ["Return a year", "ann_bp", (v) => bp(v, 1)],
  ["Worst drawdown", "max_dd_bp", (v) => (v === null || v === undefined ? dash : `−${(v / 100).toFixed(2)}%`)],
  ["Months positive", "months_positive", (v) => frac(v, 0)],
];

function FactoryDetail({
  s,
  onClose,
  onBacktest,
  onChanged,
}: {
  s: IISFStrategy;
  onClose: () => void;
  onBacktest: (sid: string) => void;
  onChanged: (model: IIModel | null) => void;
}) {
  const hasEtf = !!s.etf;
  const [model, setModel] = useState<IIModel>(s.deployed ?? (hasEtf ? "etf" : "index"));
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const curve = useMemo(() => {
    const m = s.monthly;
    if (!m?.start || !m.bp?.length) return [];
    const [y0, m0] = m.start.split("-").map(Number);
    let acc = 0;
    return m.bp.map((v, k) => {
      const y = y0 + Math.floor((m0 - 1 + k) / 12);
      const mo = ((m0 - 1 + k) % 12) + 1;
      acc += v;
      return { ts: `${y}-${String(mo).padStart(2, "0")}`, value: acc / 100 };
    });
  }, [s.monthly]);
  const rej = Object.entries(s.rejections ?? {}).sort((a, b) => b[1] - a[1]);
  const rejTotal = rej.reduce((a, [, n]) => a + n, 0);

  const toggle = async (enabled: boolean) => {
    setBusy(true);
    setMsg(null);
    try {
      await setIIDeployment(s.id, enabled, model);
      onChanged(enabled ? model : null);
      setMsg(
        enabled
          ? `Running in paper on the ${model === "etf" ? "ETF" : "index simulation"} model — evaluated at every ${s.timeframe} close from 09:20.`
          : "Switched off.",
      );
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
              {s.id} · {INDEX_LABEL[s.index] ?? s.index} · {s.family_label} · {s.sub_family}
            </div>
            <div className="dtitle">{s.name}</div>
            <div className="muted wrap">{s.hypothesis}</div>
          </div>
          <button className="btn" onClick={onClose}>
            Close
          </button>
        </div>

        <div className="dstatus">
          <Grade g={s.grade} />
          <StatusTag status={s.status} />
          <span className="wrap">
            {s.grade ? `Grade ${s.grade} — ${GRADE_NOTE[s.grade]}. ` : ""}
            {s.grade_reasons.join("; ")}
          </span>
        </div>

        <div className="dsec">The rules</div>
        <table className="tbl small">
          <tbody>
            <tr>
              <td className="l muted">Setup (the factory&rsquo;s detector)</td>
              <td className="l">
                <code>{s.detector}</code> on {tfLabel(s.timeframe)} bars of the index, anchored at 09:15
              </td>
            </tr>
            <tr>
              <td className="l muted">Confirmations (every one must pass)</td>
              <td className="l wrap">
                {s.confirmations.length ? s.confirmations.join(", ") : "none"}
                {s.htf ? ` · higher timeframe ${s.htf} (closed bars only)` : ""}
              </td>
            </tr>
            <tr>
              <td className="l muted">Market regimes it trades</td>
              <td className="l wrap">{s.regimes.length ? s.regimes.join(", ") : "any"}</td>
            </tr>
            <tr>
              <td className="l muted">Stop · target</td>
              <td className="l wrap">
                the pattern&rsquo;s structural stop (kept within 0.35–6 ATR) · its measured move, else {num(s.target_r, 1)}R —
                both re-anchored to the fill
              </td>
            </tr>
            <tr>
              <td className="l muted">When</td>
              <td className="l wrap">
                {s.timeframe === "1d"
                  ? "yesterday's daily bar decides; entry at 09:20 today"
                  : s.timeframe === "4h"
                    ? "one decision a day, at 13:15 (the close of the 09:15–13:15 bar)"
                    : `at each ${s.timeframe} close from 09:20 to 14:30, filled at the next minute's open`}{" "}
                · at most {s.max_trades_a_day} a day, one at a time · flat by 15:12
                {s.max_hold_min ? ` · held at most ${s.max_hold_min} minutes` : ""}
              </td>
            </tr>
            <tr>
              <td className="l muted">Each decision sees</td>
              <td className="l">the last {s.lookback_bars} bars</td>
            </tr>
            {s.volume_dependent && (
              <tr>
                <td className="l muted">Volume</td>
                <td className="l wrap">
                  {s.etf
                    ? `an index has none — read from ${s.etf}'s traded volume in the same minutes`
                    : "an index has none and BANKEX has no ETF — this strategy cannot fire here"}
                </td>
              </tr>
            )}
          </tbody>
        </table>

        {s.all?.trades !== undefined && (
          <>
            <div className="dsec">The record (index level, the ETF&rsquo;s costs)</div>
            <table className="tbl small">
              <thead>
                <tr>
                  <th className="l" />
                  <th>In sample 2019–21</th>
                  <th>Out of sample 2022–23</th>
                  <th>2019–23</th>
                </tr>
              </thead>
              <tbody>
                {PERIOD_ROWS.map(([label, key, fmt]) => (
                  <tr key={key}>
                    <td className="l muted">{label}</td>
                    <td>{fmt(s.is?.[key] as number | null | undefined)}</td>
                    <td>{fmt(s.oos?.[key] as number | null | undefined)}</td>
                    <td>{fmt(s.all?.[key] as number | null | undefined)}</td>
                  </tr>
                ))}
                <tr>
                  <td className="l muted">Deflated Sharpe (luck-corrected over every strategy on this index)</td>
                  <td colSpan={3} className={(s.dsr ?? 0) >= 0.95 ? "gain" : ""}>
                    {num(s.dsr, 3)}
                    {s.dsr !== null && s.dsr < 0.95 ? " — not enough to rule out luck (needs 0.95)" : ""}
                  </td>
                </tr>
              </tbody>
            </table>
          </>
        )}

        {curve.length > 1 && (
          <>
            <div className="dsec">Cumulative net, 2019–23 (% of the position, summed by month)</div>
            <LineChart points={curve} height={180} valueSuffix="%" fillToZero />
          </>
        )}

        {(Object.keys(s.exits ?? {}).length > 0 || rejTotal > 0) && (
          <div className="twocol">
            {Object.keys(s.exits ?? {}).length > 0 && (
              <div>
                <div className="dsec">How trades ended</div>
                <div className="chips">
                  {Object.entries(s.exits).map(([k, n]) => (
                    <span key={k} className="chip">
                      {k.replace("_", "-")} {n}
                    </span>
                  ))}
                </div>
              </div>
            )}
            {rejTotal > 0 && (
              <div>
                <div className="dsec">Why a bar did not trade</div>
                <div className="chips">
                  {rej.map(([k, n]) => (
                    <span key={k} className="chip" title={REJECT_LABEL[k] ?? k}>
                      {REJECT_LABEL[k] ?? k} {((n / rejTotal) * 100).toFixed(0)}%
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        <div className="dsec">Paper trading</div>
        <div className="deploy">
          <p className="wrap">
            {s.grade && s.grade >= 3
              ? `Graded ${s.grade} by the Strategy Factory's rules — still not Paper Trading Approved: it has not been through this module's Validated protocol (luck bar, the ETF track, walk-forward).`
              : `Not approved — ${s.status}${s.grade ? `, grade ${s.grade}` : ""}.`}{" "}
            Running it in paper is an observation, labelled so on every trade.
          </p>
          <div className="row">
            <label>
              Model
              <select value={model} disabled={!!s.deployed} onChange={(e) => setModel(e.target.value as IIModel)}>
                {hasEtf && <option value="etf">ETF — fills at the live bid / ask</option>}
                <option value="index">Index simulation — index points, ETF costs</option>
              </select>
            </label>
            {s.deployed ? (
              <button className="btn danger" disabled={busy} onClick={() => toggle(false)}>
                Stop paper ({s.deployed})
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
