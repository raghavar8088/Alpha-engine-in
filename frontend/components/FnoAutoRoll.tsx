"use client";

import { useCallback, useEffect, useState } from "react";
import {
  FnoAutoRollPreview,
  FnoAutoRollStatus,
  fetchFnoAutoRollPreview,
  fetchFnoAutoRollStatus,
  runFnoAutoRoll,
} from "../lib/api";

/** Status + rehearsal panel for the daily 3 PM ATM short-straddle roll.
 *
 * Shown only on the account the roller actually owns, so the other paper books on this
 * page never imply they are being auto-traded. "Run now" exists because the roll fires
 * once a day at 15:00 — without it the only way to check the wiring is to wait. */
export default function FnoAutoRoll({ accountName }: { accountName: string | null }) {
  const [status, setStatus] = useState<FnoAutoRollStatus | null>(null);
  const [preview, setPreview] = useState<FnoAutoRollPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      const s = await fetchFnoAutoRollStatus();
      setStatus(s);
      setError(null);
      if (s.account_found) setPreview(await fetchFnoAutoRollPreview());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load auto-roll status");
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, [load]);

  // WHEN THE ROLLER IS BOUND TO NOTHING, SAY SO — on whichever account is open.
  //
  // This panel used to hide unless the selected account's name equalled the CONFIGURED
  // name, which is the very comparison that breaks when an account is renamed. The roller
  // skipped every session for eighteen days and the one component that could have said so
  // hid itself for exactly the same reason. A failure must never be invisible because of
  // the check that failed.
  if (status && status.enabled && !status.account_found) {
    return (
      <div className="unbound">
        <b>The daily auto-roll is not running.</b>
        <p>
          It is looking for an account named{" "}
          <code>{status.account_name}</code>, and no account has that name — so nothing is
          being auto-traded. {status.binding_note}
        </p>
        {status.last_run_at && (
          <p className="lastrun">
            Last attempt {new Date(status.last_run_at).toLocaleString()} —{" "}
            {status.last_message}
            {status.last_rolled_on && <> · last successful roll {status.last_rolled_on}.</>}
          </p>
        )}
        <style jsx>{`
          .unbound {
            border: 1px solid var(--loss); background: rgba(220, 38, 38, .07);
            border-radius: 12px; padding: 14px 16px; margin-top: 14px;
          }
          .unbound b { color: var(--loss); font-size: 13.5px; }
          .unbound p { font-size: 12.5px; line-height: 1.6; color: var(--text); margin: 7px 0 0; max-width: 96ch; }
          .unbound .lastrun { color: var(--text-faint); font-size: 11.5px; }
          code { background: var(--canvas-soft); padding: 1px 5px; border-radius: 4px; font-size: 11.5px; }
        `}</style>
      </div>
    );
  }

  // Otherwise surface only on the account it actually manages — matched by the name the
  // roller RESOLVED to, not the one it was configured with.
  const owned = status?.matched_account_name ?? status?.account_name;
  if (!status || !accountName || !owned
      || owned.trim().toLowerCase() !== accountName.trim().toLowerCase()) {
    return null;
  }

  const runNow = async () => {
    if (busy) return;
    const legs = preview?.would_close?.length ?? 0;
    const ok = window.confirm(
      `Run the roll NOW on "${status.account_name}"?\n\n` +
        `This closes ${legs} open leg(s) and sells ${status.lots} lot of the ` +
        `${preview?.target_strike ?? "ATM"} CE and PE of ${preview?.target_expiry ?? "the next-week expiry"}.\n\n` +
        `Paper money only — no real broker order is placed.`,
    );
    if (!ok) return;
    setBusy(true);
    try {
      const r = await runFnoAutoRoll();
      setError(r.status === "rolled" ? null : `${r.status}: ${r.message}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Roll failed");
    } finally {
      setBusy(false);
    }
  };

  const tone = !status.enabled ? "off" : status.rolled_today ? "done" : status.is_trading_day ? "armed" : "idle";
  const label = !status.enabled
    ? "AUTO-ROLL OFF"
    : status.rolled_today
    ? `ROLLED TODAY · ${status.roll_time_ist} IST`
    : status.is_trading_day
    ? `ARMED · rolls at ${status.roll_time_ist} IST`
    : "MARKET CLOSED TODAY";

  return (
    <div className={`ar ${tone}`}>
      <div className="ar-head" onClick={() => setOpen((v) => !v)}>
        <span className="ar-tag">{label}</span>
        <span className="ar-sum">
          Daily: close the open {status.symbol} straddle, then sell {status.lots} lot ATM CE + PE of the
          next-week expiry (≥ {status.min_days_to_expiry} days out) · paper
        </span>
        <span className="ar-toggle">{open ? "hide" : "details"}</span>
      </div>

      {open && (
        <div className="ar-body">
          {error && <div className="ar-err">{error}</div>}

          <div className="ar-grid">
            <div>
              <div className="k">Next roll would close</div>
              {preview?.would_close?.length ? (
                preview.would_close.map((p) => (
                  <div className="v" key={p.position_id}>
                    {p.display_name} <span className="side">{p.side}</span>
                  </div>
                ))
              ) : (
                <div className="v dim">nothing open</div>
              )}
            </div>
            <div>
              <div className="k">…then open</div>
              {preview?.would_open?.length ? (
                preview.would_open.map((s) => (
                  <div className="v" key={s}>
                    {s}
                  </div>
                ))
              ) : (
                <div className="v dim">{preview?.reason ?? "unavailable"}</div>
              )}
            </div>
            <div>
              <div className="k">Spot / expiry / strike</div>
              <div className="v">
                {preview?.spot ? `₹${preview.spot.toLocaleString("en-IN")}` : "-"} ·{" "}
                {preview?.target_expiry ?? "-"} · {preview?.target_strike ?? "-"}
              </div>
              <div className="v dim">{preview?.expiry_note}</div>
            </div>
          </div>

          {status.last_message && (
            <div className="ar-last">
              <b>Last {status.last_status}</b> ({status.last_run_at ? new Date(status.last_run_at).toLocaleString("en-IN") : "-"}):{" "}
              {status.last_message}
            </div>
          )}

          {status.recent.length > 0 && (
            <div className="ar-log">
              {status.recent.slice(0, 6).map((r) => (
                <div className="row" key={r.roll_id}>
                  <span className={`st ${r.status}`}>{r.status}</span>
                  <span className="dt">{r.trading_date}</span>
                  <span className="tr">{r.trigger}</span>
                  <span className="ms">{r.message}</span>
                </div>
              ))}
            </div>
          )}

          <button className="ar-run" onClick={runNow} disabled={busy || !status.account_found}>
            {busy ? "Rolling…" : "Run the roll now (paper)"}
          </button>
        </div>
      )}

      <style jsx>{`
        .ar { border-radius: 12px; border: 1px solid var(--panel-border); background: var(--panel); overflow: hidden; }
        .ar.armed { border-color: rgba(14, 159, 110, 0.3); background: var(--gain-dim); }
        .ar.done { border-color: rgba(125, 52, 220, 0.24); background: var(--purple-dim); }
        .ar.off { border-color: rgba(185, 119, 14, 0.3); background: var(--warn-dim); }
        .ar-head { display: flex; align-items: center; gap: 12px; padding: 10px 14px; cursor: pointer; flex-wrap: wrap; }
        .ar-tag { font-size: 10.5px; font-weight: 800; letter-spacing: 0.05em; white-space: nowrap; }
        .ar.armed .ar-tag { color: var(--gain); }
        .ar.done .ar-tag { color: var(--purple); }
        .ar.off .ar-tag { color: var(--warn); }
        .ar-sum { font-size: 12px; color: var(--text-muted); flex: 1; min-width: 240px; }
        .ar-toggle { font-size: 11.5px; color: var(--text-faint); text-decoration: underline; }
        .ar-body { padding: 0 14px 14px; border-top: 1px solid var(--panel-border); }
        .ar-err { margin-top: 10px; padding: 8px 12px; border-radius: 8px; background: var(--loss-dim); color: var(--loss); font-size: 12px; }
        .ar-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; margin-top: 12px; }
        .k { font-size: 10px; font-weight: 800; letter-spacing: 0.05em; text-transform: uppercase; color: var(--text-muted); margin-bottom: 5px; }
        .v { font-size: 12.5px; font-variant-numeric: tabular-nums; margin: 2px 0; }
        .v.dim { color: var(--text-faint); }
        .side { font-size: 9.5px; font-weight: 800; color: var(--loss); margin-left: 5px; }
        .ar-last { margin-top: 12px; font-size: 12px; color: var(--text-muted); }
        .ar-log { margin-top: 10px; display: flex; flex-direction: column; gap: 3px; }
        .row { display: flex; gap: 9px; font-size: 11.5px; align-items: baseline; }
        .st { font-weight: 800; font-size: 9.5px; text-transform: uppercase; min-width: 54px; }
        .st.rolled { color: var(--gain); }
        .st.failed, .st.aborted { color: var(--loss); }
        .st.skipped { color: var(--text-faint); }
        .dt, .tr { color: var(--text-faint); font-variant-numeric: tabular-nums; }
        .ms { color: var(--text-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .ar-run {
          margin-top: 14px; padding: 7px 14px; border-radius: 9px; font-size: 12.5px; font-weight: 600;
          cursor: pointer; border: 1px solid var(--panel-border); background: var(--panel); color: var(--text);
        }
        .ar-run:disabled { opacity: 0.55; cursor: default; }
      `}</style>
    </div>
  );
}
