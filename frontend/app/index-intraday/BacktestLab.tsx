"use client";

import { useEffect, useMemo, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import LineChart from "../../components/charts/LineChart";
import {
  fetchIIFamilies,
  fetchIISFStrategy,
  fetchIIStrategy,
  isSFId,
  runIIBacktest,
  type IISFStrategy,
  type IIBacktest,
  type IIBacktestRequest,
  type IIFamily,
  type IIParams,
  type IIStrategy,
} from "../../lib/indexIntradayApi";
import { INDEXES, INDEX_LABEL, Side, StatusTag, bp, dash, frac, hhmm, inr, num, paramText, px, tone } from "./ui";

const EXITS: [string, string][] = [
  ["eod", "held to the 15:12 square-off"],
  ["atr_eod", "0.5 ATR stop, else square-off"],
  ["r2", "0.5 ATR stop, 2R target"],
  ["trail", "0.5 ATR stop, 0.5 ATR trail"],
  ["trail_wide", "0.75 ATR stop, 1 ATR trail"],
  ["sig", "0.75 ATR stop, signal exit"],
  ["sig_nostop", "signal exit only"],
  ["time60", "0.5 ATR stop, signal exit, 60-minute limit"],
];
const WINDOWS: [string, string, string][] = [
  ["Validation 2022–23", "2022-01-01", "2023-12-31"],
  ["Selection, last 3 years (2019–21)", "2019-01-01", "2021-12-31"],
  ["2020–21", "2020-01-01", "2021-12-31"],
];
const HOLDOUT_FROM = "2024-01-01";
// A Strategy Factory strategy evaluates every bar in Python: its runs are capped shorter on fast timeframes.
const SF_SPAN_DAYS: Record<string, number> = { "1m": 92, "5m": 366 };
const SF_WINDOW: Record<string, [string, string]> = { "1m": ["2023-10-01", "2023-12-31"], "5m": ["2023-01-01", "2023-12-31"] };
const RS_PER_BP = 100; // 1 bp of a ₹10 lakh position

function daysAgo(n: number): string {
  return new Date(Date.now() + 330 * 60000 - n * 86400000).toISOString().slice(0, 10);
}

/** The Backtesting Lab: the research's simulator, on any window of the stored minutes. */
export default function BacktestLab({ initialSid }: { initialSid: string | null }) {
  const [mode, setMode] = useState<"catalogue" | "custom">("catalogue");
  const [sid, setSid] = useState(initialSid ?? "ii1045");
  const [strategy, setStrategy] = useState<IIStrategy | null>(null);
  const [sfStrategy, setSfStrategy] = useState<IISFStrategy | null>(null);
  const [families, setFamilies] = useState<IIFamily[]>([]);
  const [family, setFamily] = useState("volbreak");
  const [paramsText, setParamsText] = useState('{"k": 0.5}');
  const [exit, setExit] = useState("r2");
  const [index, setIndex] = useState("NIFTY");
  const [start, setStart] = useState("2022-01-01");
  const [end, setEnd] = useState("2023-12-31");
  const [basis, setBasis] = useState<"measured" | "research">("research");
  const [scale, setScale] = useState(1);
  const [res, setRes] = useState<IIBacktest | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (initialSid) {
      setSid(initialSid);
      setMode("catalogue");
    }
  }, [initialSid]);

  useEffect(() => {
    fetchIIFamilies()
      .then((f) => setFamilies(f.families))
      .catch(() => setFamilies([]));
  }, []);

  useEffect(() => {
    if (mode !== "catalogue" || !/^ii\d{4}$/.test(sid)) {
      setStrategy(null);
      return;
    }
    fetchIIStrategy(sid)
      .then(setStrategy)
      .catch(() => setStrategy(null));
  }, [sid, mode]);

  // a Strategy Factory id: show it, and start from a window its timeframe can run, on the catalogue's costs
  useEffect(() => {
    if (mode !== "catalogue" || !isSFId(sid)) {
      setSfStrategy(null);
      return;
    }
    fetchIISFStrategy(sid.trim())
      .then((x) => {
        setSfStrategy(x);
        const [a, b] = SF_WINDOW[x.timeframe] ?? ["2022-01-01", "2023-12-31"];
        setStart(a);
        setEnd(b);
        setBasis("measured");
      })
      .catch(() => setSfStrategy(null));
  }, [sid, mode]);

  const pickFamily = (f: string) => {
    setFamily(f);
    const best = families.find((x) => x.family === f)?.best;
    if (best) {
      setParamsText(JSON.stringify(best.params));
      setIndex(best.index);
    }
  };

  const holdout = end >= HOLDOUT_FROM;
  const spanCap = sfStrategy ? (SF_SPAN_DAYS[sfStrategy.timeframe] ?? 3 * 366) : 3 * 366;
  const tooLong = (new Date(end).getTime() - new Date(start).getTime()) / 86400000 > spanCap;

  const run = async () => {
    setErr(null);
    let req: IIBacktestRequest = { start, end, cost_basis: basis, cost_scale: scale };
    if (mode === "catalogue") {
      req = { ...req, sid: sid.trim() };
    } else {
      let params: IIParams;
      try {
        params = JSON.parse(paramsText);
      } catch {
        setErr('Parameters must be JSON, e.g. {"k": 0.5}.');
        return;
      }
      req = { ...req, family, params, exit, index };
    }
    setBusy(true);
    try {
      setRes(await runIIBacktest(req));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "The backtest failed.");
    } finally {
      setBusy(false);
    }
  };

  const equity = useMemo(() => (res?.equity_bp ?? []).map(([d, v]) => ({ ts: d, value: v / 100 })), [res]);
  const drawdown = useMemo(() => (res?.drawdown_bp ?? []).map(([d, v]) => ({ ts: d, value: v / 100 })), [res]);
  const st = res?.stats;
  const total = st?.total_bp ?? (equity.length ? equity[equity.length - 1].value : null);

  return (
    <div className="stack">
      <GlassPanel title="Run a backtest" note="the research's own simulator and cost model">
        <div className="filters">
          <label>
            What
            <select value={mode} onChange={(e) => setMode(e.target.value as "catalogue" | "custom")}>
              <option value="catalogue">a tested variant (by id)</option>
              <option value="custom">a family with my own parameters</option>
            </select>
          </label>
          {mode === "catalogue" ? (
            <label>
              Strategy id
              <input value={sid} onChange={(e) => setSid(e.target.value)} placeholder="ii1045 or SF0123-NIFTY" />
            </label>
          ) : (
            <>
              <label>
                Family
                <select value={family} onChange={(e) => pickFamily(e.target.value)}>
                  {families.map((f) => (
                    <option key={f.family} value={f.family}>
                      {f.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="wide">
                Parameters (JSON)
                <input value={paramsText} onChange={(e) => setParamsText(e.target.value)} />
              </label>
              <label>
                Exit
                <select value={exit} onChange={(e) => setExit(e.target.value)}>
                  {EXITS.map(([k, l]) => (
                    <option key={k} value={k}>
                      {l}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Index
                <select value={index} onChange={(e) => setIndex(e.target.value)}>
                  {INDEXES.map((k) => (
                    <option key={k} value={k}>
                      {INDEX_LABEL[k]}
                    </option>
                  ))}
                </select>
              </label>
            </>
          )}
        </div>

        <div className="filters">
          <label>
            From
            <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
          </label>
          <label>
            To
            <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
          </label>
          <label>
            Costs
            <select value={basis} onChange={(e) => setBasis(e.target.value as "measured" | "research")}>
              <option value="research">research table (reproduces the catalogue)</option>
              <option value="measured">measured spreads (what a trade costs today)</option>
            </select>
          </label>
          <label>
            Cost multiple
            <select value={scale} onChange={(e) => setScale(Number(e.target.value))}>
              <option value={1}>1× (as modelled)</option>
              <option value={1.5}>1.5× (stress)</option>
              <option value={2}>2×</option>
              <option value={0.5}>0.5× (optimistic)</option>
            </select>
          </label>
          <button className="btn primary" disabled={busy || tooLong} onClick={run}>
            {busy ? "Running…" : "Run"}
          </button>
        </div>
        <div className="quick">
          {WINDOWS.map(([l, a, b]) => (
            <button key={l} className="btn sm" onClick={() => { setStart(a); setEnd(b); }}>
              {l}
            </button>
          ))}
          <button className="btn sm" onClick={() => { setStart(daysAgo(365)); setEnd(daysAgo(0)); }}>
            Last 12 months (holdout period)
          </button>
        </div>

        {mode === "catalogue" && strategy && (
          <div className="sel-sum">
            <StatusTag status={strategy.status} />
            <span className="strong">{strategy.family_label}</span>
            <span className="muted">
              {INDEX_LABEL[strategy.index] ?? strategy.index} · {paramText(strategy.params)} · {strategy.exit_label}
            </span>
            <span className="muted">
              · catalogue: 2016–21 {bp(strategy.sel.mean_net_bp)} ({num(strategy.sel.trades, 0)} trades), 2022–23{" "}
              {bp(strategy.val.mean_net_bp)} ({num(strategy.val.trades, 0)} trades)
            </span>
          </div>
        )}
        {mode === "catalogue" && sfStrategy && (
          <div className="sel-sum">
            <StatusTag status={sfStrategy.status} />
            <span className="strong">{sfStrategy.name}</span>
            <span className="muted">
              {INDEX_LABEL[sfStrategy.index] ?? sfStrategy.index} · Strategy Factory · {sfStrategy.family_label}
              {sfStrategy.grade ? ` · grade ${sfStrategy.grade}` : " · not graded on this index"}
            </span>
            {sfStrategy.all?.trades !== undefined && (
              <span className="muted">
                · catalogue: 2019–21 {bp(sfStrategy.is?.mean_net_bp)} ({num(sfStrategy.is?.trades, 0)} trades), 2022–23{" "}
                {bp(sfStrategy.oos?.mean_net_bp)} ({num(sfStrategy.oos?.trades, 0)} trades) on measured costs
              </span>
            )}
          </div>
        )}
        {tooLong && (
          <div className="warnbox">
            {sfStrategy && SF_SPAN_DAYS[sfStrategy.timeframe]
              ? `A ${sfStrategy.timeframe} factory strategy runs at most ${SF_SPAN_DAYS[sfStrategy.timeframe]} days at a time — it evaluates every bar.`
              : "At most three years a run."}
          </div>
        )}
        {holdout && (
          <div className="warnbox">
            This window reaches into 2024–26, the period the research kept untouched as its final test. A run here is
            exploration: it cannot validate anything, and choosing a strategy because it looks good here is exactly the
            selection the holdout exists to prevent.
          </div>
        )}
        {err && <div className="warnbox">{err}</div>}
      </GlassPanel>

      {res && st && (st.trades ?? 0) > 0 && (
        <>
          <div className="stats">
            <div className="stat">
              <div className="k">Trades</div>
              <div className="v">{num(st.trades, 0)}</div>
              <div className="s">
                {res.days} sessions · {res.start} → {res.end}
              </div>
            </div>
            <div className="stat">
              <div className="k">Net a trade</div>
              <div className={`v ${tone(st.mean_net_bp)}`}>{bp(st.mean_net_bp)}</div>
              <div className="s">gross {bp(st.mean_gross_bp)} − costs</div>
            </div>
            <div className="stat">
              <div className="k">Total, ₹10 lakh a trade</div>
              <div className={`v ${tone(total)}`}>{total === null || total === undefined ? dash : inr(total * RS_PER_BP)}</div>
              <div className="s">{bp(total, 0)} summed, before compounding</div>
            </div>
            <div className="stat">
              <div className="k">Win rate · profit factor</div>
              <div className="v">
                {frac(st.win_rate)} · {num(st.profit_factor)}
              </div>
              <div className="s">avg win ÷ avg loss {num(st.rr)}</div>
            </div>
            <div className="stat">
              <div className="k">Sharpe · Sortino</div>
              <div className={`v ${tone(st.sharpe)}`}>
                {num(st.sharpe)} · {num(st.sortino)}
              </div>
              <div className="s">annual, from daily returns</div>
            </div>
            <div className="stat">
              <div className="k">Worst drawdown</div>
              <div className="v loss">{st.max_dd_bp === null || st.max_dd_bp === undefined ? dash : `−${(st.max_dd_bp / 100).toFixed(2)}%`}</div>
              <div className="s">
                months positive {frac(st.months_positive, 0)} · years {num(st.years_positive, 0)} of {num(st.years, 0)}
              </div>
            </div>
          </div>

          <GlassPanel
            title="Cumulative net"
            note={`% of the position · charges ${(res.costs.fee_rt_bp / 100).toFixed(3)}% a round trip + spread ${(res.costs.slip_bp_a_side / 100).toFixed(3)}% a side (${res.costs.basis}, ${res.costs.scale}×)`}
          >
            <LineChart points={equity} height={220} valueSuffix="%" fillToZero />
          </GlassPanel>
          <GlassPanel title="Drawdown" note="percentage below the running peak">
            <LineChart points={drawdown} height={140} valueSuffix="%" color="var(--loss)" />
          </GlassPanel>

          <GlassPanel title="Trades" note={`the last ${res.trades.length} of ${num(st.trades, 0)}`}>
            <div className="chips">
              {Object.entries(res.exit_reasons ?? {}).map(([k, v]) => (
                <span key={k} className="chip">
                  {k.replace("_", " ")} {v}
                </span>
              ))}
            </div>
            <div className="tscroll">
              <table className="tbl">
                <thead>
                  <tr>
                    <th className="l">Day</th>
                    <th>Side</th>
                    <th>In → out</th>
                    <th>Entry</th>
                    <th>Exit</th>
                    <th className="l">Why</th>
                    <th>Gross</th>
                    <th>Net</th>
                  </tr>
                </thead>
                <tbody>
                  {[...res.trades].reverse().map((t, i) => (
                    <tr key={i}>
                      <td className="l">{t.day}</td>
                      <td>
                        <Side side={t.side} />
                      </td>
                      <td className="muted">
                        {hhmm(t.entry_min)} → {hhmm(t.exit_min)}
                      </td>
                      <td>{px(t.entry)}</td>
                      <td>{px(t.exit)}</td>
                      <td className="l">
                        <span className={`chip ${t.reason === "target" ? "good" : t.reason === "stop" ? "bad" : ""}`}>
                          {t.reason.replace("_", " ")}
                        </span>
                      </td>
                      <td className={tone(t.gross_bp)}>{bp(t.gross_bp)}</td>
                      <td className={`strong ${tone(t.net_bp)}`}>{bp(t.net_bp)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {res.rejections && Object.keys(res.rejections).length > 0 && (
              <p className="foot">
                Bars that did not trade:{" "}
                {Object.entries(res.rejections)
                  .sort((x, y) => y[1] - x[1])
                  .map(([k, v]) => `${k} ${v.toLocaleString("en-IN")}`)
                  .join(" · ")}
                {res.volume_from ? ` · volume read from ${res.volume_from}` : ""}
              </p>
            )}
            <p className="foot">{res.note}</p>
          </GlassPanel>
        </>
      )}
      {res && !st?.trades && <div className="note">No trade in this window.</div>}
    </div>
  );
}
