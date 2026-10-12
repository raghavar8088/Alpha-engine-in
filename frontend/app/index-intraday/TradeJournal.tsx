"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import LineChart from "../../components/charts/LineChart";
import {
  fetchIIEquity,
  fetchIIEvents,
  fetchIIJournal,
  fetchIIReport,
  type IIEquityPoint,
  type IIEvent,
  type IIReport,
  type IITrade,
} from "../../lib/indexIntradayApi";
import { INDEX_LABEL, Side, StatusTag, bp, hhmm, inr, num, px, todayIST, tone, when } from "./ui";

const COLUMNS: [string, (t: IITrade) => string | number | null][] = [
  ["day", (t) => t.day],
  ["strategy", (t) => t.sid],
  ["key", (t) => t.key],
  ["index", (t) => t.index],
  ["model", (t) => t.model],
  ["instrument", (t) => t.instrument],
  ["side", (t) => (t.side > 0 ? "LONG" : "SHORT")],
  ["units", (t) => t.units],
  ["entry_time", (t) => hhmm(t.entry_min)],
  ["exit_time", (t) => hhmm(t.exit_min)],
  ["entry", (t) => t.entry],
  ["exit", (t) => t.exit],
  ["exit_reason", (t) => t.exit_reason],
  ["gross_rs", (t) => t.gross],
  ["costs_rs", (t) => t.costs],
  ["net_rs", (t) => t.net],
  ["net_bp", (t) => t.net_bp],
  ["research_status", (t) => t.research_status],
];

/** How many missing history days the after-close heal filled (its report is per symbol). */
function healedDays(healed: unknown): number {
  if (!healed || typeof healed !== "object") return 0;
  return Object.values(healed as Record<string, { filled?: string[] }>).reduce(
    (a, v) => a + (v && typeof v === "object" && Array.isArray(v.filled) ? v.filled.length : 0),
    0,
  );
}

function downloadCsv(rows: IITrade[]) {
  const esc = (v: string | number | null) => {
    const s = v === null || v === undefined ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const text = [COLUMNS.map(([h]) => h).join(","), ...rows.map((t) => COLUMNS.map(([, f]) => esc(f(t))).join(","))].join("\n");
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `index-intraday-journal-${todayIST()}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

/** The Trade Journal: every paper trade, the day's report, the equity curve and the engine's log. */
export default function TradeJournal() {
  const [day, setDay] = useState(todayIST());
  const [report, setReport] = useState<IIReport | null>(null);
  const [trades, setTrades] = useState<IITrade[]>([]);
  const [equity, setEquity] = useState<IIEquityPoint[]>([]);
  const [events, setEvents] = useState<IIEvent[]>([]);
  const [sid, setSid] = useState("");
  const [onlyDay, setOnlyDay] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [r, j, e, ev] = await Promise.all([
        fetchIIReport(day),
        fetchIIJournal({ sid: sid.trim() || undefined, day: onlyDay ? day : undefined, limit: 1000 }),
        fetchIIEquity(5000),
        fetchIIEvents(300),
      ]);
      setReport(r);
      setTrades(j.trades);
      setEquity(e.equity);
      setEvents(ev.events);
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not load the journal.");
    }
  }, [day, sid, onlyDay]);

  useEffect(() => {
    load();
  }, [load]);

  const curve = useMemo(() => equity.map((p) => ({ ts: p.at, value: p.equity })), [equity]);
  const totals = useMemo(() => {
    const net = trades.reduce((a, t) => a + t.net, 0);
    const costs = trades.reduce((a, t) => a + t.costs, 0);
    const wins = trades.filter((t) => t.net > 0).length;
    return { net, costs, wins };
  }, [trades]);

  return (
    <div className="stack">
      {err && <div className="warnbox">{err}</div>}

      <GlassPanel title="Daily report" note="written after each close at 15:40; any day can be read">
        <div className="filters">
          <label>
            Day
            <input type="date" value={day} onChange={(e) => setDay(e.target.value)} />
          </label>
        </div>
        {report && report.trades > 0 ? (
          <>
            <div className="stats">
              <div className="stat">
                <div className="k">Trades</div>
                <div className="v">{report.trades}</div>
                <div className="s">{report.wins} won after costs</div>
              </div>
              <div className="stat">
                <div className="k">Gross</div>
                <div className={`v ${tone(report.gross)}`}>{inr(report.gross)}</div>
                <div className="s">before charges and spread</div>
              </div>
              <div className="stat">
                <div className="k">Costs</div>
                <div className="v">{inr(report.costs, false)}</div>
                <div className="s">ETF model: Angel&rsquo;s charges · index model: the ETF&rsquo;s</div>
              </div>
              <div className="stat">
                <div className="k">Net</div>
                <div className={`v ${tone(report.net)}`}>{inr(report.net)}</div>
                <div className="s">
                  {Object.entries(report.exit_reasons)
                    .map(([k, v]) => `${k.replace("_", " ")} ${v}`)
                    .join(" · ")}
                </div>
              </div>
            </div>
            <div className="tscroll">
              <table className="tbl">
                <thead>
                  <tr>
                    <th className="l">Strategy</th>
                    <th className="l">Index</th>
                    <th className="l">Model</th>
                    <th>Trades</th>
                    <th>Won</th>
                    <th>Gross</th>
                    <th>Costs</th>
                    <th>Net</th>
                  </tr>
                </thead>
                <tbody>
                  {report.by_strategy.map((s) => (
                    <tr key={`${s.sid}-${s.model}`}>
                      <td className="l">
                        <div className="strong">{s.sid}</div>
                        <div className="faint">{s.key}</div>
                      </td>
                      <td className="l">{INDEX_LABEL[s.index] ?? s.index}</td>
                      <td className="l">{s.model}</td>
                      <td>{s.trades}</td>
                      <td>{s.wins}</td>
                      <td className={tone(s.gross)}>{inr(s.gross)}</td>
                      <td className="muted">{inr(s.costs, false)}</td>
                      <td className={`strong ${tone(s.net)}`}>{inr(s.net)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <div className="empty-block">No paper trade closed on {day}.</div>
        )}
        {report?.history_appended && Object.keys(report.history_appended).length > 0 && (
          <p className="foot">
            After the close the session&rsquo;s one-minute candles were added to the history store:{" "}
            {Object.entries(report.history_appended)
              .filter(([k, v]) => k !== "healed" && (typeof v === "number" || typeof v === "string"))
              .map(([k, v]) => `${k} ${typeof v === "number" ? `${v} min` : v}`)
              .join(" · ")}
            .
            {healedDays(report.history_appended.healed) > 0 &&
              ` ${healedDays(report.history_appended.healed)} missing earlier day(s) were filled in as well.`}
          </p>
        )}
      </GlassPanel>

      <GlassPanel title="Equity" note="sampled every five minutes while the engine runs">
        {curve.length > 1 ? (
          <LineChart points={curve} height={200} formatValue={(v) => inr(v, false)} />
        ) : (
          <div className="empty-block">The curve starts once the engine has run with something deployed.</div>
        )}
      </GlassPanel>

      <GlassPanel title="Every paper trade" note={`${trades.length} shown · net ${inr(totals.net)} after ${inr(totals.costs, false)} of costs`}>
        <div className="filters">
          <label>
            Strategy id
            <input value={sid} onChange={(e) => setSid(e.target.value)} placeholder="all" />
          </label>
          <label className="check">
            <input type="checkbox" checked={onlyDay} onChange={(e) => setOnlyDay(e.target.checked)} />
            only {day}
          </label>
          <button className="btn" disabled={!trades.length} onClick={() => downloadCsv(trades)}>
            Download CSV
          </button>
        </div>
        <div className="tscroll">
          <table className="tbl">
            <thead>
              <tr>
                <th className="l">Day</th>
                <th className="l">Strategy</th>
                <th className="l">Instrument</th>
                <th>Side</th>
                <th>Units</th>
                <th>In → out</th>
                <th>Entry</th>
                <th>Exit</th>
                <th className="l">Why</th>
                <th>Gross</th>
                <th>Costs</th>
                <th>Net</th>
                <th>Net / value</th>
                <th className="l">Research status</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t) => (
                <tr key={`${t.sid}-${t.closed_at}`}>
                  <td className="l">{t.day}</td>
                  <td className="l">
                    <div className="strong">{t.sid}</div>
                    <div className="faint">{t.key}</div>
                  </td>
                  <td className="l">
                    {t.instrument}
                    <span className="faint"> · {t.model}</span>
                  </td>
                  <td>
                    <Side side={t.side} />
                  </td>
                  <td>{num(t.units, t.model === "etf" ? 0 : 2)}</td>
                  <td className="muted">
                    {hhmm(t.entry_min)} → {hhmm(t.exit_min)}
                  </td>
                  <td>{px(t.entry)}</td>
                  <td>{px(t.exit)}</td>
                  <td className="l">
                    <span
                      className={`chip ${t.exit_reason === "target" ? "good" : t.exit_reason === "stop" ? "bad" : ""}`}
                      title={t.exit_basis}
                    >
                      {t.exit_reason.replace("_", " ")}
                    </span>
                  </td>
                  <td className={tone(t.gross)}>{inr(t.gross)}</td>
                  <td className="muted">{inr(t.costs, false)}</td>
                  <td className={`strong ${tone(t.net)}`}>{inr(t.net)}</td>
                  <td className={tone(t.net_bp)}>{bp(t.net_bp, 1)}</td>
                  <td className="l">
                    <StatusTag status={t.research_status} />
                  </td>
                </tr>
              ))}
              {!trades.length && (
                <tr>
                  <td className="l empty" colSpan={14}>
                    No paper trades yet — they appear here as the strategies you run close their positions.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </GlassPanel>

      <GlassPanel title="Engine log" note={`the last ${events.length} events`}>
        <ul className="events">
          {events.map((e, i) => (
            <li key={i}>
              <span className="faint">{when(e.at)}</span>
              <span className={`chip ${e.kind === "exit" || e.kind === "entry" ? "run" : e.kind === "refused" || e.kind === "missed" ? "bad" : ""}`}>
                {e.kind}
              </span>
              <span>{e.text}</span>
            </li>
          ))}
          {!events.length && <li className="muted">Nothing logged yet.</li>}
        </ul>
      </GlassPanel>
    </div>
  );
}
