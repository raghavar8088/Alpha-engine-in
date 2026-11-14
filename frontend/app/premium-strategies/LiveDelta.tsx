"use client";

// Real money on Delta Exchange India for Premium strategies (13 Nov 2026; two desks from 14 Nov). The backend is
// app/services/premium_live.py: each desk copies the paper desk's trades of its picks into real Delta orders at the
// owner's size ($5 risked a trade, a $20 daily loss stop), with each trade's stop and target held on Delta. The gold
// desk shows on Premium Strategies (the original /api/premium-paper/live routes); the crypto desk is the Delta Exchange
// Live Trading module (/api/premium-paper/live/desk/crypto). This page shows what a desk did and holds its switches.
// Going live and flattening need the owner's PIN; stopping never does. Live trading has one ON/OFF switch (14 Nov): OFF
// is instant; ON asks for the PIN (or uses one the owner let this device remember) and one confirmation.
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { apiFetch } from "../../lib/api";

type Rec = { trades: number; wins: number; pnl_usd: number; open: number };
type Pick = { acct: string; mkt: string; product: string; name: string; trades: number; sum_r: number; t: number; win: number;
  backtest: string; live: Rec | null; shadow: Rec | null };
type Plan = { price: number; contracts: number; risk_usd: number; notional_usd: number; margin_usd: number; capped: boolean };
export type LiveTrade = { id: string; acct: string; mkt: string; product: string; name: string; mode: "live" | "shadow"; status: string;
  reason?: string; side: number; contracts?: number; fill?: number; stop: number; target: number | null; mark?: number;
  unrealised_usd?: number; pnl_usd?: number; fees?: number; exit_price?: number; close_reason?: string; created_at: number;
  opened_at?: number; closed_at?: number; plan?: Plan; legs?: { stop?: string; stop_limit?: string; target?: string } };
type Totals = { trades: number; wins: number; pnl_usd: number; fees_usd: number; skipped: number; errors: number };
export type LiveStatus = { configured_db: boolean; keys: boolean; pin_set: boolean; mode: "off" | "shadow" | "live"; since?: number;
  armed_at?: number; switched_off?: string | null; last_error?: string | null; last_error_at?: number; errors_in_row?: number;
  last_cycle_at?: number; wallet?: { asset: string | null; balance: number; available: number; blocked: number } | null;
  wallet_at?: number;
  limits: { risk_usd: number; daily_stop_usd: number; max_notional_usd: number; leverage: number; max_lag_s: number;
    drift_frac: number; tick_s: number };
  today: { live: number; shadow: number }; totals: { live: Totals; shadow: Totals }; picked_at: string; picks: Pick[];
  open: LiveTrade[]; recent: LiveTrade[]; notes: string[] };

const usd = (v: number | null | undefined, signed = false) => {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const sign = signed ? (v > 0 ? "+" : v < 0 ? "−" : "") : v < 0 ? "−" : "";
  return `${sign}$${Math.abs(v).toFixed(2)}`;
};
const px = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : v.toLocaleString("en-US", { maximumFractionDigits: v > 1000 ? 1 : 2 });
const tone = (v: number | null | undefined) => (!v ? "" : v > 0 ? "gain" : "loss");
const ist = (t: number | null | undefined) =>
  !t ? "—" : new Date(t * 1000).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short",
    hour: "2-digit", minute: "2-digit", hour12: false });
const ago = (t: number | null | undefined, now: number) => {
  if (!t) return "never";
  const s = Math.max(0, Math.round(now - t));
  return s < 90 ? `${s}s ago` : s < 5400 ? `${Math.round(s / 60)} min ago` : `${Math.round(s / 3600)} h ago`;
};
const MODE: Record<string, { label: string; cls: string; what: string }> = {
  live: { label: "LIVE — real money", cls: "live", what: "Real orders go to Delta for every new signal of these strategies." },
  shadow: { label: "SHADOW — no orders", cls: "shadow", what: "Every decision is made and logged with simulated fills; nothing is sent." },
  off: { label: "OFF", cls: "off", what: "No new trade. Anything still open is managed to its close." },
};
export type Ask = null | "live" | "flatten";
const PIN_KEY = "deltaLivePin";
const readPin = () => { try { return window.localStorage.getItem(PIN_KEY) || ""; } catch { return ""; } };
const keepPin = (p: string | null) => {
  try { if (p) window.localStorage.setItem(PIN_KEY, p); else window.localStorage.removeItem(PIN_KEY); } catch { /* storage blocked */ }
};
const happened = (t: LiveTrade) => {
  if (t.status === "skipped") return `skipped: ${t.reason ?? ""}`;
  if (t.status === "error") return `error: ${t.reason ?? ""}`;
  if (t.status === "closed") return `closed: ${t.close_reason ?? ""}`;
  if (t.status === "entering") return `entering${t.reason ? `: ${t.reason}` : ""}`;
  if (t.status === "closing") return `closing: ${t.close_reason ?? ""}`;
  return "open";
};

/** What the picks' own backtests said, counted from the data (so it stays true when a desk's picks change). */
const verdict = (picks: Pick[]) => {
  const n = picks.length;
  const lose = picks.filter((p) => p.backtest.startsWith("loses")).length;
  const never = picks.filter((p) => p.backtest.startsWith("never")).length;
  const parts: string[] = [];
  if (lose) parts.push(`${lose === n ? "All" : lose} of these ${n} ${lose === 1 ? "loses" : "lose"} in ${lose === 1 ? "its" : "their"} own 2-year backtest${lose === 1 ? "" : "s"}`);
  if (never) parts.push(`${never} ${never === 1 ? "was" : "were"} never backtested`);
  return `${parts.join(" and ")}${parts.length ? ":" : ""} a few good paper trades picked them.`;
};

/** What the page shows, given the desk's status: no state of its own beyond its props. */
export function LiveDeltaView({ s, now, pin, setPin, remember, setRemember, saved, ask, busy, msg, onToggle, onShadow, onFlatten,
  onSubmitPin, onCancel, onForgetPin, intro }: {
  s: LiveStatus; now: number; pin: string; setPin: (v: string) => void; remember: boolean; setRemember: (v: boolean) => void;
  saved: boolean; ask: Ask; busy: string | null; msg: string | null; onToggle: () => void; onShadow: () => void; onFlatten: () => void;
  onSubmitPin: () => void; onCancel: () => void; onForgetPin: () => void; intro?: ReactNode;
}) {
  const isLive = s.mode === "live";
  const m = MODE[s.mode] ?? MODE.off;
  const L = s.limits;
  const live = s.totals.live;
  const dayLeft = L.daily_stop_usd + s.today.live;
  return (
    <div className="ld">
      <div className="ld-warn">
        <b>Real money, on strategies that are not proven.</b>{" "}
        {intro ?? <>Since 8 Nov the paper desk&apos;s bitcoin strategies lost a combined −397R and its gold strategies −166R.</>}{" "}
        {verdict(s.picks)}{" "}
        {`The size is the one chosen for this: ${usd(L.risk_usd)} risked a trade and a ${usd(L.daily_stop_usd)} daily loss stop.`}
      </div>

      <div className="ld-head">
        <span className={`ld-mode ${m.cls}`}>{m.label}</span>
        <span className="ld-what">{m.what}</span>
      </div>
      <div className="ld-facts">
        <span>Delta keys on the server: <b className={s.keys ? "gain" : "loss"}>{s.keys ? "yes" : "no"}</b></span>
        <span>Owner PIN set: <b className={s.pin_set ? "gain" : "loss"}>{s.pin_set ? "yes" : "no"}</b></span>
        <span>Desk checked: <b>{ago(s.last_cycle_at, now)}</b> (every {L.tick_s}s)</span>
        {s.armed_at ? <span>Live since: <b>{ist(s.armed_at)} IST</b></span> : null}
      </div>
      {s.switched_off ? <div className="ld-alert">Switched off: {s.switched_off}</div> : null}
      {s.last_error && s.last_error !== s.switched_off ? (
        <div className="ld-note">Last venue message ({ago(s.last_error_at, now)}): {s.last_error}</div>
      ) : null}

      <div className="ld-tiles">
        <div className="ld-tile">
          <span className="ld-k">Today, real money (IST)</span>
          <span className={`ld-v ${tone(s.today.live)}`}>{usd(s.today.live, true)}</span>
          <span className="ld-s">{dayLeft > 0 ? `${usd(dayLeft)} left before the ${usd(L.daily_stop_usd)} daily stop` : "daily stop reached: no new trade today"}</span>
        </div>
        <div className="ld-tile">
          <span className="ld-k">All real trades</span>
          <span className={`ld-v ${tone(live.pnl_usd)}`}>{usd(live.pnl_usd, true)}</span>
          <span className="ld-s">{`${live.trades} closed · ${live.trades ? Math.round((100 * live.wins) / live.trades) : 0}% won · fees ${usd(live.fees_usd)} · ${live.skipped} skipped`}</span>
        </div>
        <div className="ld-tile">
          <span className="ld-k">Delta wallet</span>
          <span className="ld-v">{s.wallet ? usd(s.wallet.balance) : "—"}</span>
          <span className="ld-s">{s.wallet ? `${usd(s.wallet.available)} free · read ${ago(s.wallet_at, now)}` : "read when the desk goes live"}</span>
        </div>
        <div className="ld-tile">
          <span className="ld-k">Shadow (no orders)</span>
          <span className={`ld-v ${tone(s.totals.shadow.pnl_usd)}`}>{usd(s.totals.shadow.pnl_usd, true)}</span>
          <span className="ld-s">{`${s.totals.shadow.trades} closed · ${s.totals.shadow.skipped} skipped`}</span>
        </div>
      </div>

      <div className="ld-ctl">
        <div className="ld-switch-row">
          <button type="button" role="switch" aria-checked={isLive} aria-label="Live trading"
            className={`ld-switch${isLive ? " on" : ""}`} disabled={!!busy || (!isLive && (!s.keys || !s.pin_set))} onClick={onToggle}>
            <span className="ld-knob" />
          </button>
          <div className="ld-switch-text">
            <b>{isLive ? "Live trading: ON" : "Live trading: OFF"}</b>
            <span>
              {busy === "live" ? "Checking Delta and switching on…" : busy === "off" ? "Switching off…" : isLive
                ? "Real orders go to Delta for every new signal. Switch OFF to stop new trades; a position already open still closes at its stop, its target or its strategy's exit."
                : `Switch ON to start: a real order for every new signal, ${usd(L.risk_usd)} risked a trade, stopping for the day after a ${usd(L.daily_stop_usd)} loss.${s.mode === "shadow" ? " A shadow test is running now: decisions are logged, nothing is sent." : ""}`}
            </span>
          </div>
        </div>
        {ask && (
          <div className="ld-ctl-row">
            <label>{ask === "live" ? "Your PIN, to switch ON" : "Your PIN, to close every position"}
              <input type="password" autoComplete="off" inputMode="numeric" autoFocus value={pin} onChange={(e) => setPin(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") onSubmitPin(); }} />
            </label>
            <label className="ld-check">
              <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} /> Remember the PIN on this device
            </label>
            <button className={`ld-btn${ask === "live" ? " danger" : ""}`} disabled={!!busy || !pin} onClick={onSubmitPin}>
              {ask === "live" ? "Switch ON — real money" : "Close every position now"}
            </button>
            <button className="ld-btn" disabled={!!busy} onClick={onCancel}>Cancel</button>
          </div>
        )}
        <div className="ld-ctl-row ld-more">
          <button className="ld-btn" disabled={!!busy || isLive} onClick={onShadow} title={isLive ? "Switch live trading OFF first" : undefined}>
            {s.mode === "shadow" ? "Stop the shadow test" : "Test without orders (shadow)"}
          </button>
          <button className="ld-btn" disabled={!!busy || !s.pin_set} onClick={onFlatten}>
            {busy === "flatten" ? "Closing…" : "Flatten every position now"}
          </button>
          {saved && <button className="ld-btn" disabled={!!busy} onClick={onForgetPin}>Forget the PIN saved on this device</button>}
        </div>
        {(!s.keys || !s.pin_set) && <p className="ld-dim">Delta API keys or the owner PIN are not on the server yet, so the switch cannot turn ON. The setup script sets both and keeps them off the repository.</p>}
        {msg && <p className="ld-msg">{msg}</p>}
      </div>

      <h4 className="ld-h">{`The ${s.picks.length} strategies (fixed ${ist(Date.parse(s.picked_at) / 1000)} IST)`}</h4>
      <div className="ld-scroll">
        <table className="ld-table">
          <thead>
            <tr><th className="l">Strategy</th><th>Trades on</th><th>Paper record at the pick</th><th className="l">Its 2-year backtest</th><th>Real money</th><th>Shadow</th></tr>
          </thead>
          <tbody>
            {s.picks.map((p) => (
              <tr key={`${p.acct}|${p.mkt}`}>
                <td className="l"><b>{p.acct}</b> {p.name}</td>
                <td>{p.product}</td>
                <td>{`${p.trades} trades · ${p.sum_r >= 0 ? "+" : ""}${p.sum_r.toFixed(1)}R · t ${p.t.toFixed(2)} · ${p.win}% won`}</td>
                <td className={`l ${p.backtest.startsWith("loses") ? "loss" : ""}`}>{p.backtest}</td>
                <td className={tone(p.live?.pnl_usd)}>{p.live ? `${usd(p.live.pnl_usd, true)} · ${p.live.trades}${p.live.open ? ` · ${p.live.open} open` : ""}` : "—"}</td>
                <td className={tone(p.shadow?.pnl_usd)}>{p.shadow ? `${usd(p.shadow.pnl_usd, true)} · ${p.shadow.trades}` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h4 className="ld-h">Open now ({s.open.length})</h4>
      {s.open.length ? (
        <div className="ld-scroll">
          <table className="ld-table">
            <thead>
              <tr><th className="l">Strategy</th><th>Mode</th><th>Side</th><th>Contracts</th><th>Filled</th><th>Stop on Delta</th><th>Target</th><th>Mark</th><th>Open P&amp;L</th></tr>
            </thead>
            <tbody>
              {s.open.map((t) => (
                <tr key={t.id}>
                  <td className="l"><b>{t.acct}</b> {t.product}<div className="ld-dim">{happened(t)}</div></td>
                  <td>{t.mode}</td>
                  <td>{t.side > 0 ? "Long" : "Short"}</td>
                  <td>{t.contracts ?? "—"}</td>
                  <td>{px(t.fill)}</td>
                  <td>{t.legs?.stop ?? px(t.stop)}</td>
                  <td>{t.legs?.target ?? (t.target ? px(t.target) : "paper exit")}</td>
                  <td>{px(t.mark)}</td>
                  <td className={tone(t.unrealised_usd)}>{usd(t.unrealised_usd, true)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <p className="ld-dim">Nothing open.</p>}

      <h4 className="ld-h">Every decision, newest first</h4>
      {s.recent.length ? (
        <div className="ld-scroll">
          <table className="ld-table">
            <thead>
              <tr><th className="l">When (IST)</th><th className="l">Strategy</th><th>Mode</th><th>Side</th><th className="l">What happened</th><th>Contracts</th><th>In → out</th><th>P&amp;L</th></tr>
            </thead>
            <tbody>
              {s.recent.map((t) => (
                <tr key={t.id}>
                  <td className="l">{ist(t.created_at)}</td>
                  <td className="l"><b>{t.acct}</b> {t.product}</td>
                  <td>{t.mode}</td>
                  <td>{t.side > 0 ? "Long" : "Short"}</td>
                  <td className="l ld-why">{happened(t)}</td>
                  <td>{t.contracts ?? t.plan?.contracts ?? "—"}</td>
                  <td>{t.fill ? `${px(t.fill)} → ${t.exit_price ? px(t.exit_price) : "…"}` : "—"}</td>
                  <td className={tone(t.pnl_usd)}>{t.status === "closed" ? usd(t.pnl_usd, true) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <p className="ld-dim">No signal from these strategies yet.</p>}

      <ul className="ld-notes">
        {s.notes.map((n, i) => <li key={i}>{n}</li>)}
        <li>{`Limits: ${usd(L.risk_usd)} risk a trade, ${usd(L.daily_stop_usd)} daily stop, at most ${usd(L.max_notional_usd)} of notional a position, ${L.leverage}x leverage, a signal older than ${Math.round(L.max_lag_s / 60)} minutes or already ${Math.round(L.drift_frac * 100)}% of its risk away is skipped.`}</li>
      </ul>

      {/* global: every selector is under .ld, so nothing outside this tab is touched */}
      <style jsx global>{`
        .ld { display: flex; flex-direction: column; gap: 14px; }
        .ld .ld-warn { font-size: 13px; line-height: 1.6; padding: 12px 16px; border-radius: 12px; color: var(--text);
                       background: var(--loss-dim); border: 1px solid rgba(var(--loss-rgb), 0.35); }
        .ld .ld-head { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
        .ld .ld-mode { font-size: 13px; font-weight: 800; padding: 6px 12px; border-radius: 999px; letter-spacing: 0.02em; }
        .ld .ld-mode.live { background: var(--loss); color: #fff; }
        .ld .ld-mode.shadow { background: var(--brand-dim); color: var(--brand); border: 1px solid var(--brand-border); }
        .ld .ld-mode.off { background: var(--canvas-soft); color: var(--text-muted); border: 1px solid var(--panel-border); }
        .ld .ld-what { font-size: 13px; color: var(--text-muted); }
        .ld .ld-facts { display: flex; flex-wrap: wrap; gap: 6px 18px; font-size: 12.5px; color: var(--text-muted); }
        .ld .ld-facts b { color: var(--text); }
        .ld .ld-alert { font-size: 12.5px; font-weight: 700; color: var(--loss); }
        .ld .ld-note { font-size: 12px; color: var(--text-muted); }
        .ld .ld-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; }
        .ld .ld-tile { display: flex; flex-direction: column; gap: 4px; background: var(--panel); border: 1px solid var(--panel-border);
                       border-radius: 14px; padding: 14px 16px; }
        .ld .ld-k { font-size: 10.5px; font-weight: 800; letter-spacing: 0.06em; text-transform: uppercase; color: var(--text-faint); }
        .ld .ld-v { font-family: var(--font-data); font-size: 22px; font-weight: 700; color: var(--text); font-variant-numeric: tabular-nums; }
        .ld .ld-s { font-size: 12px; color: var(--text-muted); }
        .ld .ld-ctl { display: flex; flex-direction: column; gap: 10px; padding: 14px 16px; border-radius: 14px; background: var(--canvas-soft);
                      border: 1px solid var(--panel-border); }
        .ld .ld-ctl-row { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
        .ld .ld-ctl label { display: flex; flex-direction: column; gap: 4px; font-size: 11.5px; font-weight: 700; color: var(--text-muted); }
        .ld .ld-ctl input { padding: 7px 10px; border-radius: 8px; border: 1px solid var(--panel-border); background: var(--panel);
                            color: var(--text); font-size: 13px; min-width: 180px; }
        .ld .ld-btn { padding: 8px 14px; border-radius: 9px; font-size: 12.5px; font-weight: 700; cursor: pointer; background: var(--panel);
                      border: 1px solid var(--panel-border); color: var(--text); }
        .ld .ld-btn.danger { background: var(--loss); color: #fff; border-color: var(--loss); }
        .ld .ld-btn:disabled { opacity: 0.5; cursor: default; }
        .ld .ld-msg { margin: 0; font-size: 12.5px; font-weight: 700; color: var(--brand); }
        .ld .ld-h { margin: 6px 0 0; font-size: 13.5px; font-weight: 800; color: var(--text); }
        .ld .ld-scroll { overflow-x: auto; }
        .ld .ld-table { width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums; }
        .ld .ld-table th { font-size: 10.5px; font-weight: 800; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-faint);
                           text-align: right; padding: 8px 10px; border-bottom: 1px solid var(--panel-border); white-space: nowrap; }
        .ld .ld-table td { text-align: right; padding: 8px 10px; border-bottom: 1px solid var(--panel-border); vertical-align: top; white-space: nowrap; }
        .ld .ld-table .l { text-align: left; }
        .ld .ld-table td.l { white-space: normal; min-width: 150px; }
        .ld .ld-why { max-width: 420px; }
        .ld .ld-dim { margin: 0; font-size: 12px; color: var(--text-muted); }
        .ld .gain { color: var(--gain); }
        .ld .loss { color: var(--loss); }
        .ld .ld-notes { margin: 4px 0 0; padding-left: 18px; font-size: 12px; line-height: 1.6; color: var(--text-muted); }
        .ld .ld-switch-row { display: flex; align-items: center; gap: 14px; }
        .ld .ld-switch { position: relative; flex: 0 0 auto; width: 62px; height: 34px; border-radius: 999px; padding: 0; border: 0;
                         background: var(--text-faint); cursor: pointer; transition: background 0.15s; }
        .ld .ld-switch.on { background: var(--gain-solid); }
        .ld .ld-switch:disabled { opacity: 0.5; cursor: not-allowed; }
        .ld .ld-switch:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
        .ld .ld-knob { position: absolute; top: 4px; left: 4px; width: 26px; height: 26px; border-radius: 50%; background: var(--on-accent);
                       box-shadow: var(--shadow-sm); transition: left 0.15s; }
        .ld .ld-switch.on .ld-knob { left: 32px; }
        .ld .ld-switch-text { display: flex; flex-direction: column; gap: 2px; font-size: 13px; line-height: 1.45; color: var(--text-muted); }
        .ld .ld-switch-text b { font-size: 15px; color: var(--text); }
        .ld .ld-ctl label.ld-check { flex-direction: row; align-items: center; gap: 6px; font-weight: 600; font-size: 12.5px; }
        .ld .ld-ctl label.ld-check input { min-width: 0; width: auto; padding: 0; }
        @media (max-width: 640px) { .ld .ld-v { font-size: 19px; } .ld .ld-ctl input { min-width: 140px; } }
      `}</style>
    </div>
  );
}

export default function LiveDelta({ desk = "gold", intro }: { desk?: "gold" | "crypto"; intro?: ReactNode }) {
  // the gold desk keeps the original routes (they work on every server build); other desks use /live/desk/{desk}
  const base = desk === "gold" ? "/api/premium-paper/live" : `/api/premium-paper/live/desk/${desk}`;
  const [s, setS] = useState<LiveStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [pin, setPin] = useState("");
  const [remember, setRemember] = useState(false);
  const [saved, setSaved] = useState(false);
  const [ask, setAsk] = useState<Ask>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now() / 1000);

  const load = useCallback(async () => {
    try {
      setS(await apiFetch(base));
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not read the desk.");
    }
    setNow(Date.now() / 1000);
  }, [base]);
  useEffect(() => {
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [load]);

  // a PIN saved on this device (only when the owner ticks "Remember"): the switch then turns ON with one confirmation
  useEffect(() => {
    const p = readPin();
    if (p) { setPin(p); setRemember(true); setSaved(true); }
  }, []);
  const forget = () => { keepPin(null); setSaved(false); setPin(""); setRemember(false); };

  const act = async (key: "shadow" | "live" | "off" | "flatten", usePin = "") => {
    setBusy(key);
    setMsg(null);
    try {
      const r = key === "flatten"
        ? await apiFetch(`${base}/flatten`, { method: "POST", body: JSON.stringify({ pin: usePin }) })
        : await apiFetch(`${base}/mode`, { method: "POST",
            body: JSON.stringify(key === "live" ? { mode: "live", pin: usePin, confirm: "REAL MONEY" } : { mode: key }) });
      if (r?.status) setS(r.status);
      if (r?.ok) {
        setMsg(key === "live" ? "Live trading is ON: a real order goes to Delta for the next signal."
          : key === "flatten" ? "Every position is closed, and live trading is OFF."
          : key === "off" ? "Live trading is OFF: no new trades." : "Shadow test running: decisions are logged, nothing is sent.");
        setAsk(null);
        if (key === "live" || key === "flatten") {
          if (remember) { keepPin(usePin); setSaved(true); } else forget();
        }
      } else {
        const why = r?.why ?? "Refused.";
        setMsg(why);
        if (/wrong PIN|locked/i.test(why)) {   // a saved PIN that no longer works is forgotten, and the PIN is asked again
          forget();
          if (key === "live" || key === "flatten") setAsk(key);
        }
      }
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "The request failed.");
    } finally {
      setBusy(null);
      setNow(Date.now() / 1000);
    }
  };
  const goLive = (p: string) => {
    if (!window.confirm(`Turn live trading ON? A real order goes to Delta Exchange for every new signal of these ${s?.picks.length ?? ""} strategies.`)) return;
    act("live", p);
  };
  const doFlatten = (p: string) => {
    if (!window.confirm("Close every open position this desk holds on Delta now, at the market, and switch live trading OFF?")) return;
    act("flatten", p);
  };
  const onToggle = () => {
    if (s?.mode === "live") { act("off"); return; }   // OFF never needs the PIN: it can only stop new trades
    if (saved && pin) goLive(pin); else setAsk("live");
  };
  const onFlatten = () => { if (saved && pin) doFlatten(pin); else setAsk("flatten"); };
  const onShadow = () => act(s?.mode === "shadow" ? "off" : "shadow");
  const onSubmitPin = () => {
    if (!pin || busy) return;
    if (ask === "live") goLive(pin);
    else if (ask === "flatten") doFlatten(pin);
  };
  const onCancel = () => { setAsk(null); if (!saved) setPin(""); };
  const onForgetPin = () => { forget(); setMsg("The PIN saved on this device is forgotten."); };

  if (err && !s) {
    return (
      <div style={{ fontSize: 13, color: "var(--loss)", padding: "6px 2px" }}>
        {`The Delta desk could not be read: ${err}.`}
        {err === "Not Found" ? " The backend that runs it has not been deployed to the server yet." : ""}
      </div>
    );
  }
  if (!s) return <div style={{ fontSize: 13, color: "var(--text-muted)" }}>Loading the Delta desk…</div>;
  if (!s.configured_db) return <div style={{ fontSize: 13, color: "var(--loss)" }}>The paper desk&apos;s database is not configured on this server.</div>;
  return <LiveDeltaView s={s} now={now} pin={pin} setPin={setPin} remember={remember} setRemember={setRemember} saved={saved} ask={ask}
    busy={busy} msg={msg} onToggle={onToggle} onShadow={onShadow} onFlatten={onFlatten} onSubmitPin={onSubmitPin} onCancel={onCancel}
    onForgetPin={onForgetPin} intro={intro} />;
}
