"use client";

import { useCallback, useEffect, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import {
  fetchIIEvents,
  fetchIITerminal,
  freshII,
  runIITick,
  setIIDeployment,
  type IIEvent,
  type IITerminal,
} from "../../lib/indexIntradayApi";
import { INDEX_LABEL, Side, StatusTag, bp, dash, hhmm, inr, num, paramText, px, tone, when } from "./ui";

const REFRESH_MS = 15000;

/** The Paper Trading Terminal: the account, what runs, what is open, what closed today. */
export default function TradingTerminal({ onOpenStrategies }: { onOpenStrategies: () => void }) {
  const [t, setT] = useState<IITerminal | null>(null);
  const [events, setEvents] = useState<IIEvent[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [a, b] = await Promise.all([fetchIITerminal(), fetchIIEvents(40)]);
      setT(a);
      setEvents(b.events);
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not load the terminal.");
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  const act = async (key: string, fn: () => Promise<string>) => {
    setBusy(key);
    setNote(null);
    try {
      setNote(await fn());
      await freshII(load);
    } catch (e) {
      setNote(e instanceof Error ? e.message : "That did not work.");
    } finally {
      setBusy(null);
    }
  };

  if (!t) return <div className="muted pad">{err ?? "Loading the terminal…"}</div>;

  const a = t.account;
  const d = t.day;
  const r = t.risk;
  const state = r.emergency_stop
    ? { label: "EMERGENCY STOP", cls: "loss", sub: "every entry blocked — switch it off in Risk Management" }
    : d.halted
      ? { label: "Halted", cls: "loss", sub: `drawdown beyond ${r.max_drawdown_pct}% of peak — reset in Risk Management` }
      : d.paused_until
        ? { label: `Paused to ${d.paused_until}`, cls: "warn", sub: `${r.loss_streak} losses in a row` }
        : { label: "Accepting entries", cls: "gain", sub: "inside the entry window, under every limit" };

  return (
    <div className="stack">
      {err && <div className="warnbox">Showing the last good read — {err}</div>}

      <div className="observe">
        <strong>Observation, not approval.</strong> No strategy passed the research, so none is Paper Trading Approved.
        Anything running here was switched on by you, runs on simulated money, and every position carries its research
        status. Nothing is ever sent to a broker.
      </div>

      <div className="stats">
        <div className="stat">
          <div className="k">Equity</div>
          <div className="v">{inr(a.equity, false)}</div>
          <div className="s">from {inr(a.capital, false)} virtual capital</div>
        </div>
        <div className="stat">
          <div className="k">Realised P&amp;L</div>
          <div className={`v ${tone(a.realized)}`}>{inr(a.realized)}</div>
          <div className="s">all closed trades, after charges and spread</div>
        </div>
        <div className="stat">
          <div className="k">Open P&amp;L</div>
          <div className={`v ${tone(a.unrealized)}`}>{inr(a.unrealized)}</div>
          <div className="s">{a.open_positions} open · at the last price</div>
        </div>
        <div className="stat">
          <div className="k">Today</div>
          <div className={`v ${tone(d.realized)}`}>{inr(d.realized)}</div>
          <div className="s">
            {d.trades} of {r.max_trades_per_day} entries · loss limit {inr(-(r.max_daily_loss_pct / 100) * r.capital)}
          </div>
        </div>
        <div className="stat">
          <div className="k">Risk state</div>
          <div className={`v sm ${state.cls}`}>{state.label}</div>
          <div className="s">{state.sub}</div>
        </div>
      </div>

      <GlassPanel title="Engine" note="ticks five seconds after every minute, 09:16–15:20 on trading days">
        <div className="row spread">
          <div className="muted">
            Last tick {t.engine.last_tick ? when(t.engine.last_tick) : "— never"}
            {t.engine.last_tick ? ` · opened ${t.engine.last_opened}, closed ${t.engine.last_closed}` : ""}. Entries{" "}
            {r.entry_from}–{r.entry_until}, square-off {r.square_off}.
          </div>
          <button
            className="btn"
            disabled={!!busy}
            onClick={() =>
              act("tick", async () => {
                const x = await runIITick();
                return `Tick: ${x.opened} opened, ${x.closed} closed${x.notes?.length ? ` — ${x.notes.slice(0, 3).join("; ")}` : ""}.`;
              })
            }
          >
            {busy === "tick" ? "Running…" : "Run a tick now"}
          </button>
        </div>
        {t.engine.notes.length > 0 && (
          <ul className="notes">
            {t.engine.notes.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        )}
        {note && <div className="note">{note}</div>}
      </GlassPanel>

      <GlassPanel title="Running in paper" note={`${t.deployments.length} strateg${t.deployments.length === 1 ? "y" : "ies"}`}>
        {t.deployments.length ? (
          <div className="tscroll">
            <table className="tbl">
              <thead>
                <tr>
                  <th className="l">Strategy</th>
                  <th className="l">Index</th>
                  <th className="l">Model</th>
                  <th className="l">Research status</th>
                  <th>Since</th>
                  <th className="l" />
                </tr>
              </thead>
              <tbody>
                {t.deployments.map((x) => (
                  <tr key={x.sid}>
                    <td className="l">
                      <div className="strong">{x.family === "sf" ? x.name ?? x.sid : x.family}</div>
                      <div className="faint">
                        {x.family === "sf"
                          ? `${x.sid} · Strategy Factory${x.grade ? ` · grade ${x.grade}` : ""}`
                          : `${x.sid} · ${paramText(x.params)} · ${x.exit}`}
                      </div>
                    </td>
                    <td className="l">{INDEX_LABEL[x.index] ?? x.index}</td>
                    <td className="l">{x.model === "etf" ? "ETF (live bid / ask)" : "index simulation"}</td>
                    <td className="l">
                      <StatusTag status={x.status} />
                    </td>
                    <td className="muted">{when(x.added_at)}</td>
                    <td className="l">
                      <button
                        className="btn sm danger"
                        disabled={!!busy}
                        onClick={() =>
                          act(`off-${x.sid}`, async () => {
                            await setIIDeployment(x.sid, false, x.model);
                            return `${x.sid} switched off — an open position still runs to its exit.`;
                          })
                        }
                      >
                        Stop
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty-block">
            Nothing is running. Pick a strategy in the{" "}
            <button className="linkish" onClick={onOpenStrategies}>
              Strategy Dashboard
            </button>{" "}
            and choose <em>Run in paper</em> to observe it here.
          </div>
        )}
      </GlassPanel>

      <GlassPanel title="Open positions" note="exits are checked on every completed minute">
        <div className="tscroll">
          <table className="tbl">
            <thead>
              <tr>
                <th className="l">Strategy</th>
                <th className="l">Instrument</th>
                <th>Side</th>
                <th>Units</th>
                <th>Entry</th>
                <th>Mark</th>
                <th title="stop / target on the index level the strategy watches">Stop · Target</th>
                <th>Value</th>
                <th>Open P&amp;L</th>
                <th>Entered</th>
                <th className="l">Sized by</th>
              </tr>
            </thead>
            <tbody>
              {t.open_positions.map((p) => (
                <tr key={`${p.sid}-${p.opened_at}`}>
                  <td className="l">
                    <div className="strong">{p.sid}</div>
                    <div className="faint">{p.family === "sf" ? p.name ?? "Strategy Factory" : p.family}</div>
                  </td>
                  <td className="l">
                    {p.instrument}
                    <span className="faint"> · {p.model}</span>
                  </td>
                  <td>
                    <Side side={p.side} />
                  </td>
                  <td>{num(p.units, p.model === "etf" ? 0 : 2)}</td>
                  <td>{px(p.fill)}</td>
                  <td>{px(p.mark)}</td>
                  <td className="muted">
                    {px(p.stop)} · {px(p.target)}
                    {p.trail ? ` · trail ${num(p.trail)}` : ""}
                  </td>
                  <td>{inr(p.notional, false)}</td>
                  <td className={`strong ${tone(p.unrealized)}`}>{inr(p.unrealized)}</td>
                  <td className="muted">{hhmm(p.entry_min)}</td>
                  <td className="l muted wrap">{p.sizing}</td>
                </tr>
              ))}
              {!t.open_positions.length && (
                <tr>
                  <td className="l empty" colSpan={11}>
                    Nothing open. Every position is opened by its strategy&rsquo;s signal and closed by its stop, target, trail,
                    signal, time limit or the {r.square_off} square-off.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </GlassPanel>

      <GlassPanel title="Closed today" note={`${t.today_trades.length} trades`}>
        <div className="tscroll">
          <table className="tbl">
            <thead>
              <tr>
                <th className="l">Strategy</th>
                <th className="l">Instrument</th>
                <th>Side</th>
                <th>In → out</th>
                <th>Entry</th>
                <th>Exit</th>
                <th className="l">Why</th>
                <th>Gross</th>
                <th>Costs</th>
                <th>Net</th>
                <th>Net / value</th>
              </tr>
            </thead>
            <tbody>
              {t.today_trades.map((x) => (
                <tr key={`${x.sid}-${x.closed_at}`}>
                  <td className="l">
                    <div className="strong">{x.sid}</div>
                    <div className="faint">{x.family === "sf" ? x.name ?? "Strategy Factory" : x.family}</div>
                  </td>
                  <td className="l">
                    {x.instrument}
                    <span className="faint"> · {x.model}</span>
                  </td>
                  <td>
                    <Side side={x.side} />
                  </td>
                  <td className="muted">
                    {hhmm(x.entry_min)} → {hhmm(x.exit_min)}
                  </td>
                  <td>{px(x.entry)}</td>
                  <td>{px(x.exit)}</td>
                  <td className="l">
                    <span className={`chip ${x.exit_reason === "target" ? "good" : x.exit_reason === "stop" ? "bad" : ""}`}>
                      {x.exit_reason.replace("_", " ")}
                    </span>
                  </td>
                  <td className={tone(x.gross)}>{inr(x.gross)}</td>
                  <td className="muted">{inr(x.costs, false)}</td>
                  <td className={`strong ${tone(x.net)}`}>{inr(x.net)}</td>
                  <td className={tone(x.net_bp)}>{bp(x.net_bp, 1)}</td>
                </tr>
              ))}
              {!t.today_trades.length && (
                <tr>
                  <td className="l empty" colSpan={11}>
                    No trade has closed today.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </GlassPanel>

      <GlassPanel title="What the engine did" note="entries, exits, refusals, missed signals, switches">
        {events.length ? (
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
          </ul>
        ) : (
          <div className="empty-block">{dash} nothing yet.</div>
        )}
      </GlassPanel>
    </div>
  );
}
