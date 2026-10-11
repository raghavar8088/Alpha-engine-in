"use client";

import { useCallback, useEffect, useState } from "react";
import {
  closeAllGoldLab,
  fetchGoldLab,
  fetchGoldLabFills,
  runGoldLab,
  toggleGoldLab,
  type GoldLabFill,
  type GoldLabSummary,
} from "../../lib/api";

const usd = (v: number | null | undefined, signed = true) => {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const s = signed ? (v >= 0 ? "+" : "−") : v < 0 ? "−" : "";
  return `${s}$${Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};
const num = (v: number | null | undefined, d = 2) =>
  v === null || v === undefined || Number.isNaN(v) ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(d)}`;
const tone = (v: number | null | undefined) => (!v ? "" : v > 0 ? "gain" : "loss");
const when = (iso: string | null | undefined) =>
  !iso ? "—" : new Date(iso).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
const CLUSTER: Record<string, string> = { trend: "Trend", shock: "Shock continuation", macro: "Macro reversion" };

/** The Gold Lab: the seven strategies the 2026-10 gold strategy search left standing, as one paper
 * book on Delta XAUTUSD. They are Tier B — profitable after costs in 2004-14, 2015-19 and an
 * untouched 2020-26 holdout, but NOT proven better than holding gold — and three ideas, not seven. */
export default function GoldLabPanel() {
  const [s, setS] = useState<GoldLabSummary | null>(null);
  const [fills, setFills] = useState<GoldLabFill[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [a, b] = await Promise.all([fetchGoldLab(), fetchGoldLabFills(60)]);
      setS(a);
      setFills(b.fills);
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not load the Gold Lab");
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, [load]);

  const act = async (key: string, fn: () => Promise<unknown>, done: string) => {
    setBusy(key);
    setNote(null);
    try {
      await fn();
      setNote(done);
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(null);
    }
  };

  if (err && !s) return <div className="lab-err">Gold Lab unavailable: {err}</div>;
  if (!s) return null;
  const d = s.decision;

  return (
    <div className="lab">
      <div className="tier">
        <b>Tier B — profitable, not proven.</b> {s.tier_note} The seven are <b>three ideas</b>: trend (gl1, gl3,
        gl4, gl5 — they move together), shock continuation (gl6, gl7) and macro fair-value reversion (gl2). Paper
        only; priced on {s.venue} with its real fees and funding.
      </div>

      <div className="head">
        <div className="cards">
          <div className="card">
            <div className="lab-k">Equity</div>
            <div className="lab-v">{usd(s.equity, false)}</div>
            <div className="lab-s">from {usd(s.capital, false)} · {usd(s.sleeve, false)} a strategy</div>
          </div>
          <div className="card">
            <div className="lab-k">Net P&amp;L</div>
            <div className={`lab-v ${tone(s.net_pnl)}`}>{usd(s.net_pnl)}</div>
            <div className="lab-s">{num(s.net_pct, 3)}% · after fees and funding</div>
          </div>
          <div className="card">
            <div className="lab-k">Costs paid</div>
            <div className="lab-v">{usd(s.fees + s.funding, false)}</div>
            <div className="lab-s">fees {usd(s.fees, false)} · funding {usd(s.funding)}</div>
          </div>
          <div className="card">
            <div className="lab-k">Next step</div>
            <div className="lab-v sm">
              {!d
                ? "first decision after a New York close"
                : d.executed
                  ? `rebalanced for the ${d.session} session`
                  : d.skipped
                    ? `skipped: ${d.skip_reason ?? "window missed"}`
                    : `rebalance at the ${d.session} New York open`}
            </div>
            <div className="lab-s">
              {d ? `decided on the ${d.bar_date} close` : "—"}
              {s.last_note ? ` · ${s.last_note}` : ""}
            </div>
          </div>
        </div>
        <div className="ctl">
          <button className="btn" disabled={!!busy || !s.enabled} onClick={() => act("run", runGoldLab, "Lab cycle run.")}>
            {busy === "run" ? "Running…" : "Run cycle"}
          </button>
          <button
            className="btn danger"
            disabled={!!busy || !s.strategies.some((x) => x.contracts !== 0)}
            onClick={() => act("close", closeAllGoldLab, "Lab holdings flattened at the touch.")}
          >
            Close all
          </button>
          <button
            className={`switch ${s.enabled ? "on" : ""}`}
            disabled={!!busy}
            onClick={() => act("toggle", () => toggleGoldLab(!s.enabled), s.enabled ? "Gold Lab OFF." : "Gold Lab ON.")}
            aria-label="Toggle the Gold Lab"
          >
            <span className="knob" />
            <span className="lbl">{s.enabled ? "ON" : "OFF"}</span>
          </button>
        </div>
      </div>
      {note && <div className="lab-note">{note}</div>}

      <div className="tbl">
        <table>
          <thead>
            <tr>
              <th className="l">Strategy</th>
              <th>Target</th>
              <th>Contracts</th>
              <th>Notional</th>
              <th>Net</th>
              <th>% of sleeve</th>
              <th title="Sharpe in the untouched 2020-26 holdout">Holdout SR</th>
              <th title="Sharpe 2004-26 under Delta's funding">Delta SR 04-26</th>
              <th title="Beta to gold">β</th>
              <th>Fills</th>
            </tr>
          </thead>
          <tbody>
            {s.strategies.map((x) => (
              <tr key={x.id}>
                <td className="l">
                  <div className="nm">
                    <span className="sid">{x.id}</span> {x.name}
                    <span className={`chip ${x.cluster}`}>{CLUSTER[x.cluster]}</span>
                  </div>
                  <div className="how">{x.how}</div>
                </td>
                <td>{x.target === null || x.target === undefined ? "—" : x.target.toFixed(2)}</td>
                <td className={x.contracts > 0 ? "gain" : x.contracts < 0 ? "loss" : ""}>{x.contracts}</td>
                <td className="muted">{usd(x.notional, false)}</td>
                <td className={`strong ${tone(x.net)}`}>{usd(x.net)}</td>
                <td className={tone(x.net_pct_of_sleeve)}>{num(x.net_pct_of_sleeve, 2)}%</td>
                <td>{x.evidence.holdout_sharpe.toFixed(2)}</td>
                <td>{x.evidence.delta_full_sharpe.toFixed(2)}</td>
                <td className="muted">{x.evidence.beta.toFixed(2)}</td>
                <td className="muted">{x.fills}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="sub-h">Rebalancing fills</div>
      <div className="tbl">
        <table>
          <thead>
            <tr>
              <th className="l">When</th>
              <th>Strategy</th>
              <th>Contracts</th>
              <th>Price</th>
              <th>Filled</th>
              <th>Target</th>
              <th>Fee</th>
            </tr>
          </thead>
          <tbody>
            {fills.map((f, i) => (
              <tr key={`${f.at}-${f.sid}-${i}`}>
                <td className="l muted">{when(f.at)}</td>
                <td>{f.sid}</td>
                <td className={f.contracts > 0 ? "gain" : "loss"}>{f.contracts > 0 ? `+${f.contracts}` : f.contracts}</td>
                <td>{f.price.toFixed(2)}</td>
                <td className="muted">{f.reason ?? f.basis ?? "—"}</td>
                <td className="muted">{f.target === null || f.target === undefined ? "—" : f.target.toFixed(2)}</td>
                <td className="muted">{f.fee !== undefined ? usd(f.fee, false) : "—"}</td>
              </tr>
            ))}
            {!fills.length && (
              <tr>
                <td className="l empty" colSpan={7}>
                  No fills yet. A decision is taken after each New York close on GLD&rsquo;s bar; the book is
                  rebalanced at the next session&rsquo;s open (09:35&ndash;11:35 New York), never late.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="foot">
        {s.preregistered
          ? `Pre-registered ${when(s.stored_at)} · fingerprint ${s.fingerprint}`
          : "Not pre-registered yet — the rules are stored, with a fingerprint, when the book is first switched on."}
        {` · NYSE calendar through ${s.calendar_through} (no trades past it until extended)`}
        {s.last_run_at ? ` · last cycle ${when(s.last_run_at)}` : ""}
      </div>

      <style jsx>{`
        .lab { display: flex; flex-direction: column; gap: 12px; }
        .lab-err { font-size: 12px; color: var(--text-faint); }
        .tier { font-size: 12.5px; line-height: 1.6; color: var(--text-muted); background: var(--warn-dim);
                border: 1px solid var(--panel-border); border-radius: 10px; padding: 10px 14px; }
        .head { display: flex; gap: 12px; align-items: stretch; justify-content: space-between; flex-wrap: wrap; }
        .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; flex: 1; }
        .card { background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 10px; padding: 10px 12px; }
        .lab-k { font-size: 10px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--text-faint); }
        .lab-v { margin-top: 6px; font-family: var(--font-data); font-size: 17px; font-weight: 700; font-variant-numeric: tabular-nums; }
        .lab-v.sm { font-size: 12.5px; font-weight: 600; }
        .lab-s { margin-top: 4px; font-size: 11px; color: var(--text-muted); }
        .ctl { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
        .btn { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted);
               border-radius: 9px; padding: 8px 14px; font-size: 12.5px; font-weight: 600; cursor: pointer; }
        .btn:hover:not(:disabled) { color: var(--purple); border-color: rgba(125, 52, 220, 0.3); }
        .btn:disabled { opacity: 0.55; cursor: default; }
        .btn.danger:hover:not(:disabled) { color: var(--loss); border-color: rgba(217, 45, 63, 0.3); }
        .switch { position: relative; width: 74px; height: 32px; border-radius: 100px; border: 1px solid var(--panel-border);
                  background: var(--canvas-soft); cursor: pointer; display: flex; align-items: center; }
        .switch.on { background: var(--gain-dim); border-color: rgba(14, 159, 110, 0.35); }
        .switch:disabled { opacity: 0.55; cursor: default; }
        .knob { position: absolute; left: 3px; width: 24px; height: 24px; border-radius: 50%; background: var(--text-faint);
                transition: transform 0.16s ease, background 0.16s ease; }
        .switch.on .knob { transform: translateX(42px); background: var(--gain); }
        .lbl { position: absolute; right: 10px; font-size: 10.5px; font-weight: 800; letter-spacing: 0.06em; color: var(--text-faint); }
        .switch.on .lbl { right: auto; left: 12px; color: var(--gain); }
        .lab-note { font-size: 12px; color: var(--purple); background: var(--purple-dim); border-radius: 8px; padding: 8px 12px; }
        .tbl { overflow-x: auto; }
        table { width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums; }
        th { text-align: center; padding: 8px 10px; font-size: 10px; font-weight: 700; letter-spacing: 0.05em;
             text-transform: uppercase; color: var(--text-faint); border-bottom: 1px solid var(--panel-border); white-space: nowrap; }
        td { padding: 8px 10px; text-align: center; border-bottom: 1px solid var(--canvas-soft); white-space: nowrap; }
        th.l, td.l { text-align: left; }
        .nm { font-weight: 700; white-space: nowrap; }
        .sid { font-family: var(--font-data); color: var(--text-faint); font-weight: 600; margin-right: 4px; }
        .how { font-size: 11px; color: var(--text-muted); white-space: normal; max-width: 520px; margin-top: 3px; }
        .chip { margin-left: 8px; font-size: 9.5px; font-weight: 800; letter-spacing: 0.04em; padding: 1px 7px;
                border-radius: 100px; background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); }
        .chip.trend { color: var(--purple); background: var(--purple-dim); }
        .chip.shock { color: var(--warn); background: var(--warn-dim); }
        .chip.macro { color: var(--gain); background: var(--gain-dim); }
        .sub-h { font-size: 10.5px; font-weight: 800; letter-spacing: 0.06em; text-transform: uppercase; color: var(--text-faint); }
        .strong { font-weight: 700; }
        .muted { color: var(--text-muted); }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
        .empty { color: var(--text-muted); white-space: normal; padding: 14px 10px; }
        .foot { font-size: 10.5px; color: var(--text-faint); }
      `}</style>
    </div>
  );
}
