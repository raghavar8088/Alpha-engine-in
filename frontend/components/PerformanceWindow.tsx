"use client";

/**
 * "How much has this account made since a date, and what is that per day?"
 *
 * Shared by the Commodity and F&O paper desks. Both answer the same question from the
 * same server shape, and two copies of this markup would drift — the attribution notes
 * below are the part that must not.
 *
 * The date PREVIEWS before it saves. Trying a window should not mean editing the account,
 * so moving the calendar recomputes against the server and only the explicit save commits.
 */

import { CmpPerformance } from "../lib/api";

export default function PerformanceWindow({
  perf, since, busy, saved, onPreview, onSave, compact, signed,
}: {
  perf: CmpPerformance | null;
  since: string;
  busy: boolean;
  saved: boolean;
  onPreview: (d: string) => void;
  onSave: () => void;
  /** The host page's own money formatters, so the numbers match the rest of its screen. */
  compact: (v?: number | null) => string;
  signed: (v?: number | null) => string;
}) {
  const today = new Date().toISOString().slice(0, 10);
  const quick = (n: number) => {
    const d = new Date();
    d.setDate(d.getDate() - n);
    onPreview(d.toISOString().slice(0, 10));
  };

  return (
    <div className="pw">
      <div className="sincebar">
        <label>
          <span>Measure from</span>
          <input type="date" value={since} max={today}
            onChange={(e) => onPreview(e.target.value)} />
        </label>
        <div className="quick">
          {([["7 days", 7], ["30 days", 30], ["90 days", 90]] as const).map(([l, n]) => (
            <button key={n} type="button" disabled={busy} onClick={() => quick(n)}>{l}</button>
          ))}
        </div>
        <button className="savebtn" type="button"
          disabled={busy || !since || (since === perf?.start_date && saved)}
          onClick={onSave}>
          {busy ? "Working…" : saved ? "Saved ✓" : "Save as this account's start"}
        </button>
      </div>

      {perf && (
        <>
          <div className="ptiles">
            <PTile label="Avg per day" value={signed(perf.avg_per_day)}
              tone={perf.avg_per_day >= 0 ? "gain" : "loss"}
              sub={`${compact(perf.pnl_in_window)} over ${perf.days} day${perf.days === 1 ? "" : "s"}`} />
            <PTile label="Avg per trading day" value={signed(perf.avg_per_trading_day)}
              tone={perf.avg_per_trading_day >= 0 ? "gain" : "loss"}
              sub={`${perf.trading_days} trading day${perf.trading_days === 1 ? "" : "s"} in the window`} />
            <PTile label="Profit in window" value={signed(perf.pnl_in_window)}
              tone={perf.pnl_in_window >= 0 ? "gain" : "loss"}
              sub={`${signed(perf.realised_in_window)} realised · ${signed(perf.unrealised_in_window)} open`} />
            <PTile label="ROI in window"
              value={perf.roi_pct === null ? "—"
                : `${perf.roi_pct >= 0 ? "+" : ""}${perf.roi_pct.toFixed(2)}%`}
              tone={(perf.roi_pct ?? 0) >= 0 ? "gain" : "loss"}
              sub={perf.avg_roi_pct_per_day === null ? "no capital set"
                : `${perf.avg_roi_pct_per_day >= 0 ? "+" : ""}${perf.avg_roi_pct_per_day.toFixed(3)}% a day on ${compact(perf.initial_capital)}`} />
            <PTile label="Trades in window"
              value={`${perf.opened_in_window} / ${perf.closed_in_window}`}
              sub="opened / closed" />
          </div>

          {perf.carried_note && <div className="carried">{perf.carried_note}</div>}
          <div className="pnote">{perf.note}</div>
        </>
      )}

      <style jsx>{`
        .sincebar { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-bottom: 14px; }
        .sincebar label { display: inline-flex; align-items: center; gap: 8px; font-size: 12px; color: var(--text-faint); }
        .sincebar input[type="date"] {
          padding: 7px 10px; border-radius: 9px; font-size: 13px; font-family: inherit;
          border: 1px solid var(--panel-border); background: var(--panel); color: var(--text);
        }
        .sincebar input[type="date"]:focus { outline: none; border-color: var(--purple); }
        .quick { display: flex; gap: 6px; }
        .quick button {
          padding: 6px 12px; border-radius: 999px; font-size: 11.5px; cursor: pointer;
          border: 1px solid var(--panel-border); background: var(--panel); color: var(--text-faint);
        }
        .quick button:hover:not(:disabled) { border-color: var(--purple); color: var(--text); }
        .savebtn {
          margin-left: auto; padding: 7px 16px; border-radius: 9px; font-size: 12.5px;
          font-weight: 650; cursor: pointer; border: 1px solid var(--purple);
          background: var(--purple); color: #fff;
        }
        .savebtn:disabled { opacity: .5; cursor: default; }
        .ptiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(175px, 1fr)); gap: 10px; }
        .carried {
          margin-top: 12px; padding: 9px 12px; border-radius: 9px; font-size: 11.5px;
          line-height: 1.55; color: #b45309;
          border: 1px dashed rgba(217, 119, 6, .4); background: rgba(217, 119, 6, .07);
        }
        .pnote { margin-top: 10px; font-size: 11px; line-height: 1.55; color: var(--text-faint); max-width: 96ch; }
      `}</style>
    </div>
  );
}

function PTile({ label, value, sub, tone }: {
  label: string; value: string; sub?: string; tone?: "gain" | "loss";
}) {
  return (
    <div className="ptile">
      <div className="pl">{label}</div>
      <div className={`pv ${tone ?? ""}`}>{value}</div>
      {sub && <div className="ps">{sub}</div>}
      <style jsx>{`
        .ptile { border: 1px solid var(--panel-border); border-radius: 11px; padding: 11px 13px; background: var(--panel); }
        .pl { font-size: 10px; text-transform: uppercase; letter-spacing: .05em; color: var(--text-faint); margin-bottom: 5px; }
        .pv { font-size: 19px; font-weight: 750; color: var(--text); }
        .pv.gain { color: var(--gain); }
        .pv.loss { color: var(--loss); }
        .ps { font-size: 10.5px; color: var(--text-faint); margin-top: 4px; line-height: 1.45; }
      `}</style>
    </div>
  );
}
