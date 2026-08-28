"use client";

/**
 * The All Time High desk's pre-entry gate.
 *
 * The panel leads with the mode, not the results, because the same table means two
 * different things depending on it: in `observe` these are trades that HAPPENED anyway,
 * in `enforce` they are trades that would not have. Reading the rows without knowing
 * which is a straightforward way to misjudge the desk.
 *
 * Four verdicts, not three. `unknown` is rendered distinctly from `pass` everywhere —
 * NSE is the flakiest feed the app touches, and a surveillance outage must never look
 * like a clean bill of health.
 */

import { Fragment, useCallback, useEffect, useState } from "react";
import GlassPanel from "./GlassPanel";
import EmptyState from "./EmptyState";
import Skeleton from "./Skeleton";
import {
  fetchAthGate, setAthGateMode, refreshAthNse, AthGateReport, AthGateRow,
} from "../lib/api";

const TONE: Record<string, string> = {
  pass: "ok", warn: "warn", fail: "bad", unknown: "unk",
};
const MODE_HELP: Record<string, string> = {
  observe: "Scores every signal and records the verdict, but still trades. Start here — a gate that blocks trades leaves them with no outcome, so it can never be shown to work.",
  enforce: "Blocks any signal with a failing check. Blocked signals are still recorded, with the price they would have paid.",
  off: "The checks are not run at all.",
};

const inr = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;

export default function AthGate() {
  const [rep, setRep] = useState<AthGateReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [only, setOnly] = useState<"all" | "fail" | "warn">("all");

  const load = useCallback(async (fresh = false) => {
    setBusy(true);
    try { setRep(await fetchAthGate(fresh)); setErr(null); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const changeMode = async (m: string) => {
    setBusy(true);
    try { await setAthGateMode(m); await load(true); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  const reNse = async () => {
    setBusy(true);
    try { await refreshAthNse(); await load(true); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  if (!rep) {
    return (
      <GlassPanel title="Pre-entry checks">
        {err ? <EmptyState title="Could not load the gate" note={err} />
             : <div className="sk">{Array.from({ length: 6 }).map((_, i) =>
                 <Skeleton key={i} height={30} />)}</div>}
        <style jsx>{`.sk { display: flex; flex-direction: column; gap: 8px; }`}</style>
      </GlassPanel>
    );
  }

  const rows: AthGateRow[] = rep.rows.filter((r) =>
    only === "all" ? true : only === "fail" ? !r.passed : r.passed && r.warn_count > 0);

  return (
    <div className="gate">
      {err && <div className="err">{err}</div>}

      {/* ── mode first: it changes what the table below means ─────────────── */}
      <GlassPanel title="How the gate is running">
        <div className="modes">
          {(["observe", "enforce", "off"] as const).map((m) => (
            <button key={m} className={`mode ${rep.mode === m ? "on" : ""}`}
              disabled={busy} onClick={() => changeMode(m)}>
              {m}
            </button>
          ))}
          <div className="modehelp">{MODE_HELP[rep.mode]}</div>
        </div>
      </GlassPanel>

      {/* ── the headline ─────────────────────────────────────────────────── */}
      <div className="stats">
        <Cell label="Positions scored" value={String(rep.open_scored)} />
        <Cell label="Would fail" value={String(rep.open_failing)} tone="bad"
          note={rep.mode === "enforce" ? "blocked from here on" : "still held — observe mode"} />
        <Cell label="Pass with caution" value={String(rep.open_warning)} tone="warn" />
        <Cell label="Clean" value={String(rep.open_clean)} tone="ok" />
        <Cell label="Market regime"
          value={rep.regime.above === null ? "unknown" : rep.regime.above ? "uptrend" : "downtrend"}
          tone={rep.regime.above === null ? undefined : rep.regime.above ? "ok" : "bad"}
          note={rep.regime.distance_pct !== null
            ? `Nifty ${rep.regime.distance_pct >= 0 ? "+" : ""}${rep.regime.distance_pct}% vs its 200-day`
            : "not enough history"} />
        <Cell label="NSE data"
          value={rep.surveillance.ok ? `${rep.surveillance.bands} bands` : "unavailable"}
          tone={rep.surveillance.ok ? "ok" : "warn"}
          note={rep.surveillance.ok
            ? `${rep.surveillance.asm} ASM · ${rep.surveillance.gsm} GSM · ${rep.surveillance.age_hours ?? "?"}h old`
            : "checks degrade to unknown"} />
      </div>

      {/* ── does the gate actually help? ─────────────────────────────────── */}
      <GlassPanel title="Has the gate earned its keep?"
        note={`${rep.review.graded_trades} graded trades`}>
        <div className="review">
          <p className="verdict">{rep.review.verdict}</p>
          <div className="tw">
            <table>
              <thead><tr>
                <th className="l">Bought under</th><th>Trades</th><th>Win rate</th><th>Net P&amp;L</th>
              </tr></thead>
              <tbody>
                {Object.entries(rep.review.buckets).map(([k, b]) => (
                  <tr key={k}>
                    <td className="l">
                      {k === "passed" ? "a passing verdict"
                       : k === "failed" ? "a failing verdict"
                       : "no verdict (opened before the gate)"}
                    </td>
                    <td>{b.trades}</td>
                    <td>{b.win_rate === null ? "—" : `${b.win_rate}%`}</td>
                    <td className={b.pnl > 0 ? "gain" : b.pnl < 0 ? "loss" : ""}>{inr(b.pnl)}</td>
                  </tr>
                ))}
                {!Object.keys(rep.review.buckets).length && (
                  <tr><td className="l" colSpan={4}>No closed trades yet.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </GlassPanel>

      {/* ── the book, scored ─────────────────────────────────────────────── */}
      <GlassPanel title="Every open position, scored now"
        note={`${rows.length} shown`} onRefresh={() => load(true)} refreshing={busy}>
        <div className="filters">
          {(["all", "fail", "warn"] as const).map((f) => (
            <button key={f} className={only === f ? "on" : ""} onClick={() => setOnly(f)}>
              {f === "all" ? "All" : f === "fail" ? "Failing only" : "Cautions only"}
            </button>
          ))}
          <button className="nse" onClick={reNse} disabled={busy}>Re-read NSE</button>
        </div>

        <p className="note">
          These were all bought before the checks existed, so none carries a verdict from
          its own entry. Scoring them now says what the gate <i>claims</i> — it is not
          evidence that the claim is right. That comes from the table above, once graded
          trades close.
        </p>

        {!rows.length ? <EmptyState title="Nothing matches that filter" /> : (
          <div className="tw">
            <table>
              <thead><tr>
                <th className="l">Symbol</th><th>Score</th><th className="l">Verdict</th>
                <th>Entry</th><th>P&amp;L</th><th></th>
              </tr></thead>
              <tbody>
                {rows.map((r) => (
                  <Fragment key={r.symbol}>
                    <tr className={r.passed ? "" : "failing"}>
                      <td className="l sym">
                        {r.symbol}
                        {r.entry_reason === "manual" && <span className="tag">manual</span>}
                      </td>
                      <td><span className={`score ${r.passed ? (r.warn_count ? "warn" : "ok") : "bad"}`}>
                        {r.score}</span></td>
                      <td className="l why">{r.summary}</td>
                      <td>{inr(r.entry)}</td>
                      <td className={(r.unrealised_pnl ?? 0) > 0 ? "gain"
                        : (r.unrealised_pnl ?? 0) < 0 ? "loss" : ""}>{inr(r.unrealised_pnl)}</td>
                      <td>
                        <button className="exp"
                          onClick={() => setOpen(open === r.symbol ? null : r.symbol)}>
                          {open === r.symbol ? "hide" : "checks"}
                        </button>
                      </td>
                    </tr>
                    {open === r.symbol && (
                      <tr className="detail">
                        <td colSpan={6}>
                          <div className="checks">
                            {r.checks.map((c) => (
                              <div key={c.key} className={`chk ${TONE[c.verdict]}`}>
                                <div className="chkhead">
                                  <span className="dot" />
                                  <b>{c.label}</b>
                                  <span className="vd">{c.verdict}</span>
                                </div>
                                <div className="chkdetail">{c.detail}</div>
                              </div>
                            ))}
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>

      <style jsx>{`
        .gate { display: flex; flex-direction: column; gap: 16px; }
        .err {
          border: 1px solid var(--loss); background: rgba(220, 38, 38, 0.08);
          color: var(--loss); border-radius: 10px; padding: 10px 14px; font-size: 12.5px;
        }
        .modes { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
        .mode {
          padding: 7px 16px; border-radius: 8px; font-size: 12.5px; font-weight: 600;
          border: 1px solid var(--border); background: var(--canvas-soft);
          color: var(--text-secondary); cursor: pointer; text-transform: capitalize;
        }
        .mode.on { background: var(--accent); border-color: var(--accent); color: #fff; }
        .mode:disabled { opacity: 0.5; cursor: default; }
        .modehelp {
          flex: 1 1 340px; font-size: 12px; line-height: 1.55; color: var(--text-muted);
        }
        .stats {
          display: grid; gap: 10px;
          grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
        }
        .review .verdict {
          font-size: 12.5px; line-height: 1.6; color: var(--text-secondary);
          margin: 0 0 12px;
        }
        .filters { display: flex; flex-wrap: wrap; gap: 7px; margin-bottom: 12px; }
        .filters button {
          padding: 5px 13px; border-radius: 999px; font-size: 12px;
          border: 1px solid var(--border); background: var(--canvas-soft);
          color: var(--text-secondary); cursor: pointer;
        }
        .filters button.on { background: var(--accent); border-color: var(--accent); color: #fff; }
        .filters .nse { margin-left: auto; }
        .note {
          font-size: 12px; line-height: 1.6; color: var(--text-muted);
          margin: 0 0 12px; max-width: 76ch;
        }
        .tw { overflow-x: auto; }
        .tw table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
        .tw th {
          text-align: right; padding: 8px 10px; font-weight: 600; font-size: 11px;
          text-transform: uppercase; letter-spacing: 0.04em; color: var(--text-muted);
          border-bottom: 1px solid var(--border); white-space: nowrap;
        }
        .tw th.l, .tw td.l { text-align: left; }
        .tw td {
          text-align: right; padding: 8px 10px;
          border-bottom: 1px solid var(--border-soft, var(--border));
          color: var(--text-secondary); vertical-align: top;
        }
        .tw td.sym { font-weight: 650; color: var(--text-primary); white-space: nowrap; }
        .tw td.why {
          color: var(--text-muted); font-size: 12px; line-height: 1.5;
          min-width: 280px; max-width: 620px;
        }
        .tw tr.failing td.sym { color: var(--loss); }
        .tw tr.detail td { background: var(--canvas-soft); }
        .tag {
          margin-left: 6px; padding: 1px 6px; border-radius: 4px; font-size: 10px;
          font-weight: 600; background: var(--canvas-soft); color: var(--text-faint);
          border: 1px solid var(--border);
        }
        .score {
          display: inline-block; min-width: 34px; padding: 2px 7px; border-radius: 6px;
          font-weight: 700; font-size: 12px;
        }
        .score.ok { background: rgba(22, 163, 74, 0.14); color: var(--gain); }
        .score.warn { background: rgba(217, 119, 6, 0.14); color: #b45309; }
        .score.bad { background: rgba(220, 38, 38, 0.14); color: var(--loss); }
        .exp {
          padding: 3px 10px; border-radius: 6px; font-size: 11px;
          border: 1px solid var(--border); background: var(--canvas);
          color: var(--text-secondary); cursor: pointer;
        }
        .checks {
          display: grid; gap: 8px; padding: 6px 0;
          grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
        }
        .chk {
          border: 1px solid var(--border); border-radius: 9px; padding: 9px 11px;
          background: var(--canvas);
        }
        .chkhead {
          display: flex; align-items: center; gap: 7px; font-size: 12px;
          margin-bottom: 4px; color: var(--text-primary);
        }
        .chkhead .vd {
          margin-left: auto; font-size: 10px; text-transform: uppercase;
          letter-spacing: 0.05em; font-weight: 700;
        }
        .chkdetail { font-size: 11.5px; line-height: 1.55; color: var(--text-muted); }
        .dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
        .chk.ok .dot { background: var(--gain); }
        .chk.ok .vd { color: var(--gain); }
        .chk.warn .dot { background: #d97706; }
        .chk.warn .vd { color: #b45309; }
        .chk.bad .dot { background: var(--loss); }
        .chk.bad .vd { color: var(--loss); }
        /* unknown is deliberately NOT green and NOT red — it is an absence of evidence,
           and rendering it as either would be a claim the data does not support. */
        .chk.unk .dot { background: var(--text-faint); }
        .chk.unk .vd { color: var(--text-faint); }
        .chk.unk { border-style: dashed; }
        .gain { color: var(--gain); font-weight: 600; }
        .loss { color: var(--loss); font-weight: 600; }
      `}</style>
    </div>
  );
}

function Cell({ label, value, note, tone }: {
  label: string; value: string; note?: string; tone?: string;
}) {
  return (
    <div className="cell">
      <div className="lab">{label}</div>
      <div className={`val ${tone ?? ""}`}>{value}</div>
      {note && <div className="note">{note}</div>}
      <style jsx>{`
        .cell {
          border: 1px solid var(--border); border-radius: 12px;
          padding: 12px 14px; background: var(--canvas);
        }
        .lab {
          font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.05em;
          color: var(--text-muted); margin-bottom: 5px;
        }
        .val { font-size: 20px; font-weight: 700; color: var(--text-primary); }
        .val.ok { color: var(--gain); }
        .val.bad { color: var(--loss); }
        .val.warn { color: #b45309; }
        .note { font-size: 11px; color: var(--text-faint); margin-top: 4px; line-height: 1.45; }
      `}</style>
    </div>
  );
}
