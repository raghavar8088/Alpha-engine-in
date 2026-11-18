"use client";

// Real money on Delta Exchange India for Premium strategies (13 Nov 2026; two desks from 14 Nov). The backend is
// app/services/premium_live.py: each desk copies the paper desk's trades of its picks into real Delta orders at the
// owner's size (from 15 Nov one contract a trade, the smallest order, or $1 to $5 of risk picked here with the PIN;
// a $20 daily loss stop), with each trade's stop and target held on Delta. Both desks show on the Delta Exchange Live
// Trading module (16 Nov; the gold desk also on Premium Strategies, its original /api/premium-paper/live routes; the
// crypto desk at /api/premium-paper/live/desk/crypto). This page shows what a desk did and holds its switches.
// Live trading has one ON/OFF switch (14 Nov): OFF is instant, ON asks for one confirmation. A PIN is asked (for ON, the
// trade size and flatten) only when the server says one is required (pin_required); the owner chose none on 15 Nov.
// The view was redesigned on 16 Nov 2026 (status and controls first, then the numbers, open positions, the strategies,
// the trade log with filters, and the desk's notes folded away). LiveDelta - every request this page sends - is unchanged.
// 19 Nov 2026: each strategy's own paper side beside the real one (the server's paper view): "Paper now" (in a paper
// trade, its R now, or waiting) and "Paper so far" in the strategies table, with filters; a table of the strategies'
// latest paper trades with what the desk did with each (copied, skipped and why, not copied); no t under five trades.
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { apiFetch } from "../../lib/api";

type Rec = { trades: number; wins: number; pnl_usd: number; open: number };
/** A pick's own paper trades now (18 Nov): its closed record since the paper desk started it, and its open trades. */
type PaperOpen = { id: string; side: number; entry: number | null; stop: number | null; target: number | null; entry_t: number;
  r_now: number | null };
type PaperRec = { trades: number; wins: number; sum_r: number; open: PaperOpen[]; last_t: number | null };
type Pick = { acct: string; mkt: string; product: string; name: string; trades: number; sum_r: number; t: number; win: number;
  backtest: string; live: Rec | null; shadow: Rec | null; picked_at?: string | null;
  src?: string; template?: string | null;   // src "gold_h1": a Gold Desk H1 template (18 Nov), else a Premium book
  paper?: PaperRec | null };                // undefined on an older server, null when the paper side cannot be read
/** One of the strategies' latest paper trades, with what this desk did with it (18 Nov). */
export type Signal = { id: string; acct: string; mkt: string; src?: string; side: number; entry_t: number; entry: number | null;
  stop: number | null; target: number | null; open: boolean; exit: number | null; exit_t: number | null; reason: string | null;
  r: number | null; r_now: number | null;
  desk: { status: string; why?: string | null; pnl_usd?: number | null; unrealised_usd?: number | null; mode?: string;
    contracts?: number | null } };
type Plan = { price: number; contracts: number; risk_usd: number; notional_usd: number; margin_usd: number; capped: boolean };
export type LiveTrade = { id: string; acct: string; mkt: string; product: string; name: string; mode: "live" | "shadow"; status: string;
  reason?: string; side: number; contracts?: number; fill?: number; stop: number; target: number | null; mark?: number;
  unrealised_usd?: number; pnl_usd?: number; fees?: number; exit_price?: number; close_reason?: string; created_at: number;
  opened_at?: number; closed_at?: number; plan?: Plan; legs?: { stop?: string; stop_limit?: string; target?: string } };
type Totals = { trades: number; wins: number; pnl_usd: number; fees_usd: number; skipped: number; errors: number };
export type LiveStatus = { configured_db: boolean; keys: boolean; pin_set: boolean; pin_required?: boolean; mode: "off" | "shadow" | "live"; since?: number;
  armed_at?: number; switched_off?: string | null; last_error?: string | null; last_error_at?: number; errors_in_row?: number;
  last_cycle_at?: number; wallet?: { asset: string | null; balance: number; available: number; blocked: number } | null;
  wallet_at?: number;
  limits: { risk_usd: number; daily_stop_usd: number; max_notional_usd: number; leverage: number; max_lag_s: number;
    drift_frac: number; tick_s: number; risk_cap_usd?: number; risk_min_usd?: number; risk_set_at?: number | null;
    sizing?: "min" | "risk" };
  today: { live: number; shadow: number }; totals: { live: Totals; shadow: Totals }; picked_at: string; picks: Pick[];
  open: LiveTrade[]; recent: LiveTrade[]; notes: string[]; desk?: string; title?: string; products?: Record<string, unknown>;
  signals?: Signal[] | null; paper_view?: { at?: number; paper_age_s?: number | null; gold_desk_age_s?: number | null } | null };

export const usd = (v: number | null | undefined, signed = false) => {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const sign = signed ? (v > 0 ? "+" : v < 0 ? "−" : "") : v < 0 ? "−" : "";
  // a one-contract gold trade moves fractions of a cent: show them rather than "$0.00"
  const a = Math.abs(v);
  return `${sign}$${a > 0 && a < 0.01 ? a.toFixed(4) : a.toFixed(2)}`;
};
const sizeLabel = (r: number | "min" | null) => (r === "min" ? "1 contract a trade" : `${usd(r)} a trade`);
const px = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : v.toLocaleString("en-US", { maximumFractionDigits: v > 1000 ? 1 : 2 });
export const tone = (v: number | null | undefined) => (!v ? "" : v > 0 ? "gain" : "loss");
export const ist = (t: number | null | undefined) =>
  !t ? "—" : new Date(t * 1000).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short",
    hour: "2-digit", minute: "2-digit", hour12: false });
export const ago = (t: number | null | undefined, now: number) => {
  if (!t) return "never";
  const s = Math.max(0, Math.round(now - t));
  return s < 90 ? `${s}s ago` : s < 5400 ? `${Math.round(s / 60)} min ago` : `${Math.round(s / 3600)} h ago`;
};
export const MODE: Record<string, { label: string; cls: string; what: string }> = {
  live: { label: "LIVE — real money", cls: "live", what: "Real orders go to Delta for every new signal of these strategies." },
  shadow: { label: "SHADOW — no orders", cls: "shadow", what: "Every decision is made and logged with simulated fills; nothing is sent." },
  off: { label: "OFF", cls: "off", what: "No new trade. Anything still open is managed to its close." },
};
export type Ask = null | "live" | "flatten" | "risk";
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
/** The one-word state of a decision, for its badge; the reason is shown under it. */
const STATE: Record<string, { label: string; cls: string }> = {
  open: { label: "Open", cls: "open" }, entering: { label: "Entering", cls: "open" }, closing: { label: "Closing", cls: "open" },
  closed: { label: "Closed", cls: "closed" }, skipped: { label: "Skipped", cls: "skipped" }, error: { label: "Error", cls: "error" },
};
const why = (t: LiveTrade) => (t.status === "closed" || t.status === "closing" ? t.close_reason : t.reason) ?? "";
type Filter = "all" | "real" | "skipped" | "error";

/** What the picks' own backtests said, counted from the data (so it stays true when a desk's picks change). */
const verdict = (picks: Pick[]) => {
  const n = picks.length;
  const count = (w: string) => picks.filter((p) => p.backtest.startsWith(w)).length;
  const lose = count("loses"), earn = count("earns"), never = count("never"), pooled = count("pooled");
  const parts: string[] = [];
  if (lose) parts.push(`${lose === n ? "All" : lose} of these ${n} ${lose === 1 ? "loses" : "lose"} in ${lose === 1 ? "its" : "their"} own 2-year backtest${lose === 1 ? "" : "s"}`);
  if (earn) parts.push(`${earn} ${earn === 1 ? "earns" : "earn"} too little in ${earn === 1 ? "its" : "their"} own to mean anything`);
  if (never) parts.push(`${never} ${never === 1 ? "was" : "were"} never backtested`);
  if (pooled) parts.push(`${pooled} ${pooled === 1 ? "was" : "were"} tested only as a family`);
  const said = parts.length > 1 ? `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}` : parts.join("");
  return `${said}${parts.length ? ":" : ""} a few good paper trades picked them.`;
};

/** A pick's backtest badge, from the server's wording: "loses ...", "earns ..., not significant", "never backtested",
 *  or "pooled only" (the Gold Desk's H1 templates, replayed only as a family). */
const btBadge = (b: string): [string, string] =>
  b.startsWith("loses") ? ["error", "loses"] : b.startsWith("earns") ? ["skipped", "not significant"]
    : b.startsWith("pooled") ? ["skipped", "family only"] : ["skipped", "not tested"];

const rr = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(2)}R`);
const pct = (n: number, d: number) => (d ? `${Math.round((100 * n) / d)}%` : "—");
const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;
/** The record at the pick: a t-stat of under five trades means nothing (two near-equal trades give a t in the hundreds). */
const pickRecord = (p: Pick) =>
  `${plural(p.trades, "trade")} · ${p.sum_r >= 0 ? "+" : ""}${p.sum_r.toFixed(1)}R · ${p.trades >= 5 ? `t ${p.t.toFixed(2)}` : "too few for a t"} · ${p.win}% won`;
type PFilter = "all" | "inTrade" | "real" | "waiting";
const inTrade = (p: Pick) => !!p.paper && p.paper.open.length > 0;
/** What this desk did with a paper trade, as a badge (the reason goes under it). */
const DESK_STATE: Record<string, { label: string; cls: string }> = {
  open: { label: "Copied · open", cls: "open" }, entering: { label: "Copied · entering", cls: "open" },
  closing: { label: "Copied · closing", cls: "open" }, closed: { label: "Copied · closed", cls: "closed" },
  skipped: { label: "Skipped", cls: "skipped" }, error: { label: "Error", cls: "error" },
  before: { label: "Not copied", cls: "skipped" }, off: { label: "Not copied", cls: "skipped" },
  pending: { label: "Deciding", cls: "open" },
};
type SFilter = "all" | "copied" | "skipped" | "not";
const copied = (x: Signal) => ["open", "entering", "closing", "closed"].includes(x.desk.status);
const notCopied = (x: Signal) => ["before", "off"].includes(x.desk.status);

/** What the page shows, given the desk's status: no state of its own beyond its props (and the trade-log filter). */
export function LiveDeltaView({ s, now, pin, setPin, remember, setRemember, saved, ask, pendingRisk, busy, msg, onToggle,
  onShadow, onFlatten, onRisk, onSubmitPin, onCancel, onForgetPin, intro }: {
  s: LiveStatus; now: number; pin: string; setPin: (v: string) => void; remember: boolean; setRemember: (v: boolean) => void;
  saved: boolean; ask: Ask; pendingRisk: number | "min" | null; busy: string | null; msg: string | null; onToggle: () => void;
  onShadow: () => void; onFlatten: () => void; onRisk: (r: number | "min") => void; onSubmitPin: () => void; onCancel: () => void;
  onForgetPin: () => void; intro?: ReactNode;
}) {
  const [filter, setFilter] = useState<Filter>("all");
  const isLive = s.mode === "live";
  const pinNeeded = s.pin_required !== false;     // an older server, or one with PREMIUM_LIVE_REQUIRE_PIN=1
  const m = MODE[s.mode] ?? MODE.off;
  const L = s.limits;
  // the risk a trade the owner picks, whole dollars from the server's minimum to its cap; shown once the server offers it
  const risks = L.risk_cap_usd ? [1, 2, 3, 4, 5].filter((r) => r >= (L.risk_min_usd ?? 1) && r <= (L.risk_cap_usd ?? 5)) : [];
  const oneContract = L.sizing === "min";       // one contract a trade, the smallest order (the default from 15 Nov)
  const sizeText = oneContract ? "1 contract a trade (the smallest order Delta allows)" : `${usd(L.risk_usd)} risked a trade`;
  const mixed = s.picks.some((p) => p.picked_at);   // some picks joined later: each record is as of its own pick
  const live = s.totals.live;
  const dayLeft = L.daily_stop_usd + s.today.live;
  const dayUsed = Math.min(100, Math.max(0, (-s.today.live / (L.daily_stop_usd || 1)) * 100));
  const openPnl = s.open.reduce((a, t) => a + (t.unrealised_usd ?? 0), 0);
  const showShadow = s.mode === "shadow" || s.totals.shadow.trades > 0 || s.totals.shadow.skipped > 0;
  const counts = useMemo(() => ({
    all: s.recent.length,
    real: s.recent.filter((t) => t.status !== "skipped" && t.status !== "error").length,
    skipped: s.recent.filter((t) => t.status === "skipped").length,
    error: s.recent.filter((t) => t.status === "error").length,
  }), [s.recent]);
  const shown = s.recent.filter((t) => filter === "all" ? true : filter === "real" ? t.status !== "skipped" && t.status !== "error"
    : t.status === filter);
  // the strategies' own paper side (18 Nov): undefined on an older server, null when it could not be read
  const [pf, setPf] = useState<PFilter>("all");
  const [sf, setSf] = useState<SFilter>("all");
  const hasPaper = s.picks.some((p) => p.paper !== undefined);
  const pCounts = {
    all: s.picks.length, inTrade: s.picks.filter(inTrade).length,
    real: s.picks.filter((p) => (p.live?.trades ?? 0) + (p.live?.open ?? 0) > 0).length,
    waiting: s.picks.filter((p) => !inTrade(p)).length,
  };
  const picksShown = s.picks.filter((p) => pf === "all" ? true : pf === "inTrade" ? inTrade(p)
    : pf === "real" ? (p.live?.trades ?? 0) + (p.live?.open ?? 0) > 0 : !inTrade(p));
  const sig = s.signals ?? [];
  const sCounts = { all: sig.length, copied: sig.filter(copied).length, skipped: sig.filter((x) => x.desk.status === "skipped"
    || x.desk.status === "error").length, not: sig.filter(notCopied).length };
  const sigShown = sig.filter((x) => sf === "all" ? true : sf === "copied" ? copied(x)
    : sf === "skipped" ? x.desk.status === "skipped" || x.desk.status === "error" : notCopied(x));
  const pv = s.paper_view;
  return (
    <div className="ld">
      <div className="ld-warn" role="note">
        <b>Real money, on strategies that are not proven.</b>{" "}
        {intro ?? <>Since 8 Nov the paper desk&apos;s bitcoin strategies lost a combined −397R and its gold strategies −166R.</>}{" "}
        {verdict(s.picks)}{" "}
        {`The size is the one chosen for this: ${sizeText} and a ${usd(L.daily_stop_usd)} daily loss stop.`}
      </div>

      <section className={`ld-card ld-status ${m.cls}`} aria-label="Desk status and controls">
        <div className="ld-status-top">
          <div className="ld-head">
            <span className={`ld-mode ${m.cls}`}>{m.label}</span>
            <span className="ld-what">{m.what}</span>
          </div>
          <div className="ld-facts">
            <span>Delta keys <b className={s.keys ? "gain" : "loss"}>{s.keys ? "yes" : "no"}</b></span>
            {pinNeeded ? <span>Owner PIN set: <b className={s.pin_set ? "gain" : "loss"}>{s.pin_set ? "yes" : "no"}</b></span>
              : <span>PIN: <b>not needed</b></span>}
            <span>Checked <b>{ago(s.last_cycle_at, now)}</b> (every {L.tick_s}s)</span>
            {isLive && s.armed_at ? <span>Live since <b>{ist(s.armed_at)} IST</b></span> : null}
            {s.errors_in_row ? <span>Venue errors in a row <b className="loss">{s.errors_in_row}</b> (3 switch it off)</span> : null}
          </div>
        </div>
        {s.switched_off ? <div className="ld-alert" role="alert">Switched off: {s.switched_off}</div> : null}
        {s.last_error && s.last_error !== s.switched_off ? (
          <div className="ld-note">Last venue message ({ago(s.last_error_at, now)}): {s.last_error}</div>
        ) : null}

        <div className="ld-ctl">
          <div className="ld-switch-row">
            <button type="button" role="switch" aria-checked={isLive} aria-label="Live trading"
              className={`ld-switch${isLive ? " on" : ""}`} disabled={!!busy || (!isLive && (!s.keys || (pinNeeded && !s.pin_set)))} onClick={onToggle}>
              <span className="ld-knob" />
            </button>
            <div className="ld-switch-text">
              <b>{isLive ? "Live trading: ON" : "Live trading: OFF"}</b>
              <span>
                {busy === "live" ? "Checking Delta and switching on…" : busy === "off" ? "Switching off…" : isLive
                  ? "Real orders go to Delta for every new signal. Switch OFF to stop new trades; a position already open still closes at its stop, its target or its strategy's exit."
                  : `Switch ON to start: a real order for every new signal, ${sizeText}, stopping for the day after a ${usd(L.daily_stop_usd)} loss.${s.mode === "shadow" ? " A shadow test is running now: decisions are logged, nothing is sent." : ""}`}
              </span>
            </div>
          </div>
          {risks.length > 0 && (
            <div className="ld-risk-row">
              <span className="ld-risk-k" id={`ld-risk-k-${s.desk ?? "desk"}`}>Trade size</span>
              <div className="ld-seg" role="radiogroup" aria-labelledby={`ld-risk-k-${s.desk ?? "desk"}`}>
                {L.sizing !== undefined && (
                  <button type="button" role="radio" aria-checked={oneContract} className={`ld-seg-b${oneContract ? " on" : ""}`}
                    disabled={!!busy} onClick={() => onRisk("min")}>1 contract</button>
                )}
                {risks.map((r) => {
                  const on = !oneContract && Math.abs(L.risk_usd - r) < 0.005;
                  return (
                    <button key={r} type="button" role="radio" aria-checked={on} className={`ld-seg-b${on ? " on" : ""}`}
                      disabled={!!busy} onClick={() => onRisk(r)}>${r}</button>
                  );
                })}
              </div>
              <span className="ld-risk-s">
                {busy === "risk" ? "Saving…" : oneContract
                  ? "Every trade is 1 contract, the smallest order Delta allows. What it loses at its stop depends on how far away the stop is: on bitcoin usually $0.20-0.60, on gold under 5 cents, plus fees. A trade whose one contract would lose more than $5 is skipped."
                  : "A dollar amount is the most one trade loses if its stop is hit, plus about $0.10-0.30 of fees. A trade whose smallest order (one contract) would lose more is skipped."}
              </span>
            </div>
          )}
          {ask && (
            <div className="ld-ctl-row">
              <label>{ask === "live" ? "Your PIN, to switch ON" : ask === "risk" ? `Your PIN, to set ${sizeLabel(pendingRisk)}` : "Your PIN, to close every position"}
                <input type="password" autoComplete="off" inputMode="numeric" autoFocus value={pin} onChange={(e) => setPin(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") onSubmitPin(); }} />
              </label>
              <label className="ld-check">
                <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} /> Remember the PIN on this device
              </label>
              <button className={`ld-btn${ask === "live" ? " danger" : ""}`} disabled={!!busy || !pin} onClick={onSubmitPin}>
                {ask === "live" ? "Switch ON — real money" : ask === "risk" ? `Set ${sizeLabel(pendingRisk)}` : "Close every position now"}
              </button>
              <button className="ld-btn" disabled={!!busy} onClick={onCancel}>Cancel</button>
            </div>
          )}
          <div className="ld-ctl-row ld-more">
            <button className="ld-btn" disabled={!!busy || isLive} onClick={onShadow} title={isLive ? "Switch live trading OFF first" : undefined}>
              {s.mode === "shadow" ? "Stop the shadow test" : "Test without orders (shadow)"}
            </button>
            <button className="ld-btn ld-btn-warn" disabled={!!busy || (pinNeeded && !s.pin_set)} onClick={onFlatten}>
              {busy === "flatten" ? "Closing…" : "Flatten every position now"}
            </button>
            {saved && pinNeeded && <button className="ld-btn" disabled={!!busy} onClick={onForgetPin}>Forget the PIN saved on this device</button>}
          </div>
          {(!s.keys || (pinNeeded && !s.pin_set)) && <p className="ld-dim">Delta API keys or the owner PIN are not on the server yet, so the switch cannot turn ON. The setup script sets both and keeps them off the repository.</p>}
          {msg && <p className="ld-msg" role="status">{msg}</p>}
        </div>
      </section>

      <div className="ld-tiles">
        <div className="ld-tile">
          <span className="ld-k">Today, real money (IST)</span>
          <span className={`ld-v ${tone(s.today.live)}`}>{usd(s.today.live, true)}</span>
          <span className="ld-bar" aria-hidden="true"><span style={{ width: `${dayUsed}%` }} className={dayUsed >= 75 ? "hot" : ""} /></span>
          <span className="ld-s">{dayLeft > 0 ? `${usd(dayLeft)} left before the ${usd(L.daily_stop_usd)} daily stop` : "daily stop reached: no new trade today"}</span>
        </div>
        <div className="ld-tile">
          <span className="ld-k">All real trades</span>
          <span className={`ld-v ${tone(live.pnl_usd)}`}>{usd(live.pnl_usd, true)}</span>
          <span className="ld-s">{`${live.trades} closed · ${live.trades ? Math.round((100 * live.wins) / live.trades) : 0}% won · fees ${usd(live.fees_usd)}`}</span>
        </div>
        <div className="ld-tile">
          <span className="ld-k">Open now</span>
          <span className={`ld-v ${s.open.length ? tone(openPnl) : ""}`}>{s.open.length ? usd(openPnl, true) : "0"}</span>
          <span className="ld-s">{s.open.length ? `${s.open.length} position${s.open.length === 1 ? "" : "s"} open, marked at Delta's price` : "no position open"}</span>
        </div>
        {hasPaper && (
          <div className="ld-tile">
            <span className="ld-k">On paper now</span>
            <span className="ld-v">{`${pCounts.inTrade} / ${pCounts.all}`}</span>
            <span className="ld-s">{pv ? `strategies in a paper trade · paper desk ${ago(pv.at ? pv.at - (pv.paper_age_s ?? 0) : null, now)}`
              : "the paper desk could not be read just now"}</span>
          </div>
        )}
        <div className="ld-tile">
          <span className="ld-k">Signals not taken</span>
          <span className="ld-v">{live.skipped}</span>
          <span className="ld-s">{`skipped as late, drifted or too big${live.errors ? ` · ${live.errors} error${live.errors === 1 ? "" : "s"}` : ""}`}</span>
        </div>
        <div className="ld-tile">
          <span className="ld-k">Delta wallet</span>
          <span className="ld-v">{s.wallet ? usd(s.wallet.balance) : "—"}</span>
          <span className="ld-s">{s.wallet ? `${usd(s.wallet.available)} free · read ${ago(s.wallet_at, now)}` : "read when the desk goes live"}</span>
        </div>
        {showShadow && (
          <div className="ld-tile">
            <span className="ld-k">Shadow (no orders)</span>
            <span className={`ld-v ${tone(s.totals.shadow.pnl_usd)}`}>{usd(s.totals.shadow.pnl_usd, true)}</span>
            <span className="ld-s">{`${s.totals.shadow.trades} closed · ${s.totals.shadow.skipped} skipped`}</span>
          </div>
        )}
      </div>

      <h4 className="ld-h ld-h-row">
        <span>{mixed ? `The ${s.picks.length} strategies (each record as of its own pick)` : `The ${s.picks.length} strategies (fixed ${ist(Date.parse(s.picked_at) / 1000)} IST)`}</span>
        {hasPaper && (
          <span className="ld-filters" role="group" aria-label="Show strategies">
            {([["all", "All"], ["inTrade", "In a paper trade"], ["real", "With real trades"], ["waiting", "Waiting"]] as [PFilter, string][]).map(([k, label]) => (
              <button key={k} type="button" className={`ld-fchip${pf === k ? " on" : ""}`} aria-pressed={pf === k}
                onClick={() => setPf(k)}>{label} <span>{pCounts[k]}</span></button>
            ))}
          </span>
        )}
      </h4>
      <div className="ld-card ld-scroll">
        <table className="ld-table ld-strats">
          <thead>
            <tr><th className="l">Strategy</th>{hasPaper && <><th className="l">Paper now</th><th className="l">Paper so far</th></>}
              <th>Real money</th><th className="l">Record at the pick</th><th className="l">Its 2-year backtest</th></tr>
          </thead>
          <tbody>
            {picksShown.map((p) => {
              const o = p.paper?.open?.[0];
              const lv = p.live;
              return (
                <tr key={`${p.acct}|${p.mkt}`} className={inTrade(p) ? "ld-row-on" : ""}>
                  <td className="l ld-strat">
                    <b>{p.acct}</b> <span className="ld-chip">{p.product}</span>
                    {p.src === "gold_h1" ? <span className="ld-chip ld-chip-src">Gold Desk H1</span> : null}
                    <div className="ld-sub">{p.name}</div>
                  </td>
                  {hasPaper && (
                    <>
                      <td className="l">
                        {p.paper === null || p.paper === undefined ? <span className="ld-dim">—</span> : o ? (
                          <>
                            <span className="ld-badge open">In a trade</span>{" "}
                            <span className={`ld-side ${o.side > 0 ? "long" : "short"}`}>{o.side > 0 ? "Long" : "Short"}</span>
                            <div className="ld-sub">{`since ${ist(o.entry_t)} · ${o.r_now !== null ? `${rr(o.r_now)} now` : "marked at the next bar"}${p.paper.open.length > 1 ? ` · ${p.paper.open.length} open` : ""}`}</div>
                          </>
                        ) : (
                          <>
                            <span className="ld-badge skipped">Waiting</span>
                            <div className="ld-sub">{p.paper.last_t ? `last signal ${ist(p.paper.last_t)}` : "no paper trade yet"}</div>
                          </>
                        )}
                      </td>
                      <td className="l">
                        {p.paper ? (
                          <>
                            <span className={`ld-num ${tone(p.paper.sum_r)}`}>{p.paper.trades ? rr(p.paper.sum_r) : "—"}</span>
                            <div className="ld-sub">{p.paper.trades ? `${plural(p.paper.trades, "trade")} · ${pct(p.paper.wins, p.paper.trades)} won` : "no closed trade yet"}</div>
                          </>
                        ) : <span className="ld-dim">—</span>}
                      </td>
                    </>
                  )}
                  <td>
                    <span className={`ld-num ${tone(lv?.pnl_usd)}`}>{lv && (lv.trades || lv.open) ? usd(lv.pnl_usd, true) : "—"}</span>
                    <div className="ld-sub">{lv && lv.trades ? `${plural(lv.trades, "trade")} · ${pct(lv.wins, lv.trades)} won` : "no real trade yet"}</div>
                    {lv?.open ? <span className="ld-badge open">{lv.open} open</span> : null}
                  </td>
                  <td className="l">{pickRecord(p)}
                    {mixed ? <div className="ld-sub">{`picked ${ist(Date.parse(p.picked_at || s.picked_at) / 1000)}`}</div> : null}</td>
                  <td className="l"><span className={`ld-badge ${btBadge(p.backtest)[0]}`}>
                    {btBadge(p.backtest)[1]}</span><div className="ld-sub">{p.backtest}</div></td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {!picksShown.length && <p className="ld-dim ld-pad">None of these strategies is in this state right now.</p>}
        {showShadow && (
          <p className="ld-foot">{`Shadow: ${s.picks.filter((p) => p.shadow).map((p) => `${p.acct} ${usd(p.shadow!.pnl_usd, true)} (${p.shadow!.trades})`).join(" · ") || "no shadow trade yet"}`}</p>
        )}
      </div>

      {s.signals !== undefined && (
        <>
          <h4 className="ld-h ld-h-row">
            <span>The strategies&apos; paper trades, newest first, and what this desk did</span>
            {s.signals ? (
              <span className="ld-filters" role="group" aria-label="Show paper trades">
                {([["all", "All"], ["copied", "Copied"], ["skipped", "Skipped"], ["not", "Not copied"]] as [SFilter, string][]).map(([k, label]) => (
                  <button key={k} type="button" className={`ld-fchip${sf === k ? " on" : ""}`} aria-pressed={sf === k}
                    onClick={() => setSf(k)}>{label} <span>{sCounts[k]}</span></button>
                ))}
              </span>
            ) : null}
          </h4>
          {s.signals === null ? (
            <p className="ld-dim ld-empty">The paper desk could not be read just now; its trades show again on the next refresh.</p>
          ) : sigShown.length ? (
            <div className="ld-card ld-scroll ld-log">
              <table className="ld-table ld-signals">
                <thead>
                  <tr><th className="l">Entered (IST)</th><th className="l">Strategy</th><th>Side</th><th>Paper entry → exit</th>
                    <th>Paper result</th><th className="l">This desk</th><th>Real P&amp;L</th></tr>
                </thead>
                <tbody>
                  {sigShown.map((x) => {
                    const ds = DESK_STATE[x.desk.status] ?? { label: x.desk.status, cls: "skipped" };
                    const real = x.desk.status === "closed" ? x.desk.pnl_usd : x.desk.status === "open" ? x.desk.unrealised_usd : null;
                    return (
                      <tr key={x.id} className={notCopied(x) ? "ld-row-dim" : ""}>
                        <td className="l">{ist(x.entry_t)}</td>
                        <td className="l"><b>{x.acct}</b>{x.src === "gold_h1" ? <span className="ld-chip ld-chip-src">H1</span> : null}</td>
                        <td><span className={`ld-side ${x.side > 0 ? "long" : "short"}`}>{x.side > 0 ? "Long" : "Short"}</span></td>
                        <td>{`${px(x.entry)} → ${x.open ? "open" : px(x.exit)}`}</td>
                        <td className={`ld-num ${tone(x.open ? x.r_now : x.r)}`}>
                          {x.open ? <span className="ld-sub">{x.r_now !== null ? `${rr(x.r_now)} now` : "open"}</span> : rr(x.r)}
                          {!x.open && x.reason ? <div className="ld-sub">{x.reason}</div> : null}
                        </td>
                        <td className="l ld-why"><span className={`ld-badge ${ds.cls}`}>{x.desk.mode === "shadow" ? `${ds.label} (shadow)` : ds.label}</span>
                          {x.desk.why ? <div className="ld-sub">{x.desk.why}</div> : null}</td>
                        <td className={`ld-num ${tone(real)}`}>{real !== null && real !== undefined ? (x.desk.status === "open"
                          ? <span className="ld-sub">{usd(real, true)} open</span> : usd(real, true)) : "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : <p className="ld-dim ld-empty">{sig.length ? "Nothing of this kind in the latest paper trades." : "No paper trade from these strategies yet."}</p>}
        </>
      )}

      <h4 className="ld-h ld-h-row">
        <span>Real positions open ({s.open.length})</span>
        {s.open.length ? <span className={`ld-h-aside ${tone(openPnl)}`}>{usd(openPnl, true)} open P&amp;L</span> : null}
      </h4>
      {s.open.length ? (
        <div className="ld-pos-grid">
          {s.open.map((t) => (
            <div key={t.id} className={`ld-card ld-pos ${t.side > 0 ? "long" : "short"}`}>
              <div className="ld-pos-top">
                <span><b>{t.acct}</b> <span className="ld-chip">{t.product}</span></span>
                <span className={`ld-side ${t.side > 0 ? "long" : "short"}`}>{t.side > 0 ? "Long" : "Short"}</span>
              </div>
              <div className={`ld-pos-pnl ${tone(t.unrealised_usd)}`}>{usd(t.unrealised_usd, true)}</div>
              <dl className="ld-pos-dl">
                <div><dt>Contracts</dt><dd>{t.contracts ?? "—"}</dd></div>
                <div><dt>Filled</dt><dd>{px(t.fill)}</dd></div>
                <div><dt>Mark</dt><dd>{px(t.mark)}</dd></div>
                <div><dt>Stop on Delta</dt><dd>{t.legs?.stop ?? px(t.stop)}</dd></div>
                <div><dt>Target</dt><dd>{t.legs?.target ?? (t.target ? px(t.target) : "paper exit")}</dd></div>
                <div><dt>Since</dt><dd>{ist(t.opened_at ?? t.created_at)}</dd></div>
              </dl>
              <div className="ld-sub">{t.mode === "shadow" ? "shadow · " : ""}{happened(t)}</div>
            </div>
          ))}
        </div>
      ) : <p className="ld-dim ld-empty">Nothing open. A position opens when one of these strategies enters on the paper desk.</p>}

      <h4 className="ld-h ld-h-row">
        <span>Real-money decisions, newest first</span>
        <span className="ld-filters" role="group" aria-label="Show">
          {([["all", "All"], ["real", "Trades"], ["skipped", "Skipped"], ["error", "Errors"]] as [Filter, string][]).map(([k, label]) => (
            <button key={k} type="button" className={`ld-fchip${filter === k ? " on" : ""}`} aria-pressed={filter === k}
              onClick={() => setFilter(k)}>{label} <span>{counts[k]}</span></button>
          ))}
        </span>
      </h4>
      {shown.length ? (
        <div className="ld-card ld-scroll ld-log">
          <table className="ld-table">
            <thead>
              <tr><th className="l">When (IST)</th><th className="l">Strategy</th><th>Side</th><th className="l">What happened</th>
                <th>Contracts</th><th>In → out</th><th>Fees</th><th>P&amp;L</th></tr>
            </thead>
            <tbody>
              {shown.map((t) => {
                const st = STATE[t.status] ?? { label: t.status, cls: "skipped" };
                return (
                  <tr key={t.id} className={t.status === "skipped" ? "ld-row-dim" : ""}>
                    <td className="l">{ist(t.created_at)}</td>
                    <td className="l"><b>{t.acct}</b> <span className="ld-chip">{t.product}</span>{t.mode === "shadow" ? <span className="ld-chip">shadow</span> : null}</td>
                    <td><span className={`ld-side ${t.side > 0 ? "long" : "short"}`}>{t.side > 0 ? "Long" : "Short"}</span></td>
                    <td className="l ld-why"><span className={`ld-badge ${st.cls}`}>{st.label}</span>{why(t) ? <div className="ld-sub">{why(t)}</div> : null}</td>
                    <td>{t.contracts ?? t.plan?.contracts ?? "—"}</td>
                    <td>{t.fill ? `${px(t.fill)} → ${t.exit_price ? px(t.exit_price) : "…"}` : "—"}</td>
                    <td>{t.fees != null ? usd(t.fees) : "—"}</td>
                    <td className={`ld-num ${tone(t.pnl_usd)}`}>{t.status === "closed" ? usd(t.pnl_usd, true) : t.status === "open" && t.unrealised_usd != null ? <span className="ld-sub">{usd(t.unrealised_usd, true)} open</span> : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : <p className="ld-dim ld-empty">{s.recent.length ? "Nothing of this kind in the latest decisions." : "No signal from these strategies yet."}</p>}

      <details className="ld-card ld-more-info">
        <summary>How this desk works, and its limits</summary>
        <ul className="ld-notes">
          {s.notes.map((n, i) => <li key={i}>{n}</li>)}
          <li>{`Limits: ${oneContract ? `1 contract a trade (skipped if it would lose more than ${usd(L.risk_cap_usd)})` : `${usd(L.risk_usd)} risk a trade`}, ${usd(L.daily_stop_usd)} daily stop, at most ${usd(L.max_notional_usd)} of notional a position, ${L.leverage}x leverage, a signal older than ${Math.round(L.max_lag_s / 60)} minutes or already ${Math.round(L.drift_frac * 100)}% of its risk away is skipped.`}</li>
        </ul>
      </details>

      {/* global: every selector is under .ld, so nothing outside the desk is touched */}
      <style jsx global>{`
        .ld { display: flex; flex-direction: column; gap: 14px; }
        .ld .gain { color: var(--gain); }
        .ld .loss { color: var(--loss); }
        .ld .ld-card { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 14px; }
        .ld .ld-warn { font-size: 12.5px; line-height: 1.55; padding: 10px 14px; border-radius: 12px; color: var(--text-secondary);
                       background: var(--loss-dim); border: 1px solid rgba(var(--loss-rgb), 0.3); }
        .ld .ld-warn b { color: var(--loss); }
        .ld .ld-status { padding: 16px 18px; display: flex; flex-direction: column; gap: 12px; border-left: 4px solid var(--panel-border); }
        .ld .ld-status.live { border-left-color: var(--loss); }
        .ld .ld-status.shadow { border-left-color: var(--brand); }
        .ld .ld-status-top { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 8px 18px; }
        .ld .ld-head { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
        .ld .ld-mode { font-size: 12.5px; font-weight: 800; padding: 6px 12px; border-radius: 999px; letter-spacing: 0.02em; white-space: nowrap; }
        .ld .ld-mode.live { background: var(--loss); color: #fff; }
        .ld .ld-mode.shadow { background: var(--brand-dim); color: var(--brand); border: 1px solid var(--brand-border); }
        .ld .ld-mode.off { background: var(--canvas-soft); color: var(--text-muted); border: 1px solid var(--panel-border); }
        .ld .ld-what { font-size: 13px; color: var(--text-muted); }
        .ld .ld-facts { display: flex; flex-wrap: wrap; gap: 4px 16px; font-size: 12px; color: var(--text-muted); }
        .ld .ld-facts b { color: var(--text); }
        .ld .ld-alert { font-size: 12.5px; font-weight: 700; color: var(--loss); padding: 8px 12px; border-radius: 10px; background: var(--loss-dim); }
        .ld .ld-note { font-size: 12px; color: var(--text-muted); padding: 8px 12px; border-radius: 10px; background: var(--warn-dim);
                       border: 1px solid var(--warn-border); overflow-wrap: anywhere; }
        .ld .ld-ctl { display: flex; flex-direction: column; gap: 12px; padding: 14px 16px; border-radius: 12px; background: var(--canvas-soft);
                      border: 1px solid var(--panel-border); }
        .ld .ld-ctl-row { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
        .ld .ld-ctl label { display: flex; flex-direction: column; gap: 4px; font-size: 11.5px; font-weight: 700; color: var(--text-muted); }
        .ld .ld-ctl input { padding: 7px 10px; border-radius: 8px; border: 1px solid var(--panel-border); background: var(--panel);
                            color: var(--text); font-size: 13px; min-width: 180px; }
        .ld .ld-btn { padding: 8px 14px; border-radius: 9px; font-size: 12.5px; font-weight: 700; cursor: pointer; background: var(--panel);
                      border: 1px solid var(--panel-border); color: var(--text); }
        .ld .ld-btn:hover:not(:disabled) { border-color: var(--panel-border-hover); }
        .ld .ld-btn.danger { background: var(--loss); color: #fff; border-color: var(--loss); }
        .ld .ld-btn.ld-btn-warn { color: var(--loss); border-color: rgba(var(--loss-rgb), 0.4); }
        .ld .ld-btn:disabled { opacity: 0.5; cursor: default; }
        .ld .ld-btn:focus-visible, .ld .ld-fchip:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
        .ld .ld-msg { margin: 0; font-size: 12.5px; font-weight: 700; color: var(--brand); }
        .ld .ld-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(165px, 1fr)); gap: 12px; }
        .ld .ld-tile { display: flex; flex-direction: column; gap: 5px; background: var(--panel); border: 1px solid var(--panel-border);
                       border-radius: 14px; padding: 14px 16px; min-width: 0; }
        .ld .ld-k { font-size: 10.5px; font-weight: 800; letter-spacing: 0.06em; text-transform: uppercase; color: var(--text-faint); }
        .ld .ld-v { font-family: var(--font-data); font-size: 22px; font-weight: 700; color: var(--text); font-variant-numeric: tabular-nums; }
        .ld .ld-v.gain { color: var(--gain); }
        .ld .ld-v.loss { color: var(--loss); }
        .ld .ld-s { font-size: 12px; color: var(--text-muted); }
        .ld .ld-bar { display: block; height: 5px; border-radius: 999px; background: var(--canvas-soft); overflow: hidden; }
        .ld .ld-bar span { display: block; height: 100%; background: var(--warn); border-radius: 999px; }
        .ld .ld-bar span.hot { background: var(--loss); }
        .ld .ld-h { margin: 6px 0 0; font-size: 14px; font-weight: 800; color: var(--text); }
        .ld .ld-h-row { display: flex; align-items: center; justify-content: space-between; gap: 8px 14px; flex-wrap: wrap; }
        .ld .ld-h-aside { font-family: var(--font-data); font-size: 13px; font-weight: 700; }
        .ld .ld-scroll { overflow-x: auto; }
        .ld .ld-log { max-height: 560px; overflow-y: auto; }
        .ld .ld-table { width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums; }
        .ld .ld-table th { font-size: 10.5px; font-weight: 800; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-faint);
                           text-align: right; padding: 10px 12px; border-bottom: 1px solid var(--panel-border); white-space: nowrap;
                           position: sticky; top: 0; background: var(--panel); z-index: 1; }
        .ld .ld-table td { text-align: right; padding: 9px 12px; border-bottom: 1px solid var(--border-soft, var(--panel-border));
                           vertical-align: top; white-space: nowrap; }
        .ld .ld-table tbody tr:last-child td { border-bottom: 0; }
        .ld .ld-table tbody tr:hover td { background: var(--panel-tint, var(--canvas-soft)); }
        .ld .ld-table .l { text-align: left; }
        .ld .ld-table td.l { white-space: normal; min-width: 150px; }
        .ld .ld-num { font-family: var(--font-data); font-weight: 700; }
        .ld .ld-row-dim td { color: var(--text-muted); }
        .ld .ld-why { max-width: 420px; }
        .ld .ld-sub { font-size: 11.5px; color: var(--text-muted); line-height: 1.45; margin-top: 2px; white-space: normal; }
        .ld .ld-chip { display: inline-block; font-size: 10.5px; font-weight: 700; padding: 1px 7px; border-radius: 999px; margin-left: 4px;
                       background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); }
        .ld .ld-badge { display: inline-block; font-size: 11px; font-weight: 800; padding: 2px 8px; border-radius: 999px; white-space: nowrap; }
        .ld .ld-badge.open { background: var(--brand-dim); color: var(--brand); }
        .ld .ld-badge.closed { background: var(--gain-dim); color: var(--gain); }
        .ld .ld-badge.skipped { background: var(--canvas-soft); color: var(--text-muted); border: 1px solid var(--panel-border); }
        .ld .ld-badge.error { background: var(--loss-dim); color: var(--loss); }
        .ld .ld-side { display: inline-block; font-size: 11px; font-weight: 800; padding: 2px 8px; border-radius: 6px; }
        .ld .ld-side.long { background: var(--gain-dim); color: var(--gain); }
        .ld .ld-side.short { background: var(--loss-dim); color: var(--loss); }
        .ld .ld-foot { margin: 0; padding: 8px 12px; font-size: 11.5px; color: var(--text-muted); border-top: 1px solid var(--panel-border); }
        .ld .ld-pos-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }
        .ld .ld-pos { padding: 14px 16px; display: flex; flex-direction: column; gap: 8px; border-top: 3px solid var(--panel-border); }
        .ld .ld-pos.long { border-top-color: var(--gain); }
        .ld .ld-pos.short { border-top-color: var(--loss); }
        .ld .ld-pos-top { display: flex; justify-content: space-between; align-items: center; gap: 8px; font-size: 13px; }
        .ld .ld-pos-pnl { font-family: var(--font-data); font-size: 20px; font-weight: 700; }
        .ld .ld-pos-dl { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px 10px; margin: 0; }
        .ld .ld-pos-dl dt { font-size: 10px; font-weight: 800; letter-spacing: 0.05em; text-transform: uppercase; color: var(--text-faint); }
        .ld .ld-pos-dl dd { margin: 0; font-family: var(--font-data); font-size: 12.5px; color: var(--text); overflow-wrap: anywhere; }
        .ld .ld-filters { display: inline-flex; flex-wrap: wrap; gap: 6px; }
        .ld .ld-fchip { font-size: 12px; font-weight: 700; padding: 5px 11px; border-radius: 999px; cursor: pointer; background: var(--panel);
                        border: 1px solid var(--panel-border); color: var(--text-muted); }
        .ld .ld-fchip span { font-family: var(--font-data); margin-left: 3px; color: var(--text-faint); }
        .ld .ld-fchip.on { background: var(--text); color: var(--panel); border-color: var(--text); }
        .ld .ld-fchip.on span { color: var(--panel); }
        .ld .ld-dim { margin: 0; font-size: 12px; color: var(--text-muted); }
        .ld .ld-empty { padding: 14px 16px; border-radius: 14px; border: 1px dashed var(--panel-border); }
        .ld .ld-more-info { padding: 12px 16px; }
        .ld .ld-more-info summary { cursor: pointer; font-size: 13px; font-weight: 800; color: var(--text); }
        .ld .ld-notes { margin: 10px 0 0; padding-left: 18px; font-size: 12px; line-height: 1.6; color: var(--text-muted); }
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
        .ld .ld-risk-row { display: flex; align-items: center; gap: 8px 12px; flex-wrap: wrap; }
        .ld .ld-risk-k { font-size: 12.5px; font-weight: 800; color: var(--text); }
        .ld .ld-seg { display: inline-flex; border: 1px solid var(--panel-border); border-radius: 10px; overflow: hidden;
                      background: var(--panel); }
        .ld .ld-seg-b { padding: 7px 14px; font-size: 13px; font-weight: 700; border: 0; border-left: 1px solid var(--panel-border);
                        background: transparent; color: var(--text); cursor: pointer; font-variant-numeric: tabular-nums; white-space: nowrap; }
        .ld .ld-seg-b:first-child { border-left: 0; }
        .ld .ld-seg-b.on { background: var(--text); color: var(--panel); }
        .ld .ld-seg-b:disabled { cursor: default; opacity: 0.6; }
        .ld .ld-seg-b:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
        .ld .ld-risk-s { flex: 1 1 260px; font-size: 12px; line-height: 1.45; color: var(--text-muted); }
        .ld .ld-strats td.ld-strat { min-width: 220px; max-width: 320px; }
        .ld .ld-strats td { vertical-align: top; }
        .ld .ld-strats td .ld-badge + .ld-side { margin-left: 4px; }
        .ld .ld-row-on td { background: var(--brand-dim); }
        .ld .ld-row-on td:first-child { box-shadow: inset 3px 0 0 var(--brand); }
        .ld .ld-table tbody tr.ld-row-on:hover td { background: var(--brand-dim); }
        .ld .ld-chip-src { background: var(--warn-dim); border-color: var(--warn-border); color: var(--text-secondary); }
        .ld .ld-pad { padding: 12px 14px; }
        .ld .ld-signals td:nth-child(4) { font-family: var(--font-data); }
        .ld .ld-table td.ld-num.gain { color: var(--gain); }      /* a result keeps its colour in a dimmed row */
        .ld .ld-table td.ld-num.loss { color: var(--loss); }
        @media (max-width: 640px) {
          .ld .ld-v { font-size: 19px; } .ld .ld-ctl input { min-width: 140px; } .ld .ld-seg-b { padding: 7px 10px; }
          .ld .ld-status { padding: 14px; } .ld .ld-pos-dl { grid-template-columns: repeat(2, minmax(0, 1fr)); }
          .ld .ld-tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; } .ld .ld-tile { padding: 12px; }
        }
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
  const [pendingRisk, setPendingRisk] = useState<number | "min" | null>(null);
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

  const act = async (key: "shadow" | "live" | "off" | "flatten" | "risk", usePin = "", riskUsd: number | "min" = 0) => {
    setBusy(key);
    setMsg(null);
    try {
      const r = key === "flatten"
        ? await apiFetch(`${base}/flatten`, { method: "POST", body: JSON.stringify({ pin: usePin }) })
        : key === "risk"
          ? await apiFetch(`${base}/risk`, { method: "POST", body: JSON.stringify({ risk_usd: riskUsd, pin: usePin }) })
          : await apiFetch(`${base}/mode`, { method: "POST",
              body: JSON.stringify(key === "live" ? { mode: "live", pin: usePin, confirm: "REAL MONEY" } : { mode: key }) });
      if (r?.status) setS(r.status);
      const pinned = key === "live" || key === "flatten" || key === "risk";
      if (r?.ok) {
        setMsg(key === "live" ? "Live trading is ON: a real order goes to Delta for the next signal."
          : key === "flatten" ? "Every position is closed, and live trading is OFF."
          : key === "risk" ? (riskUsd === "min" ? "From the next signal, every trade is 1 contract, the smallest order."
            : `From the next signal, a trade loses at most ${usd(riskUsd)} at its stop, plus fees.`)
          : key === "off" ? "Live trading is OFF: no new trades." : "Shadow test running: decisions are logged, nothing is sent.");
        setAsk(null);
        setPendingRisk(null);
        if (pinned && usePin) {
          if (remember) { keepPin(usePin); setSaved(true); } else forget();
        }
      } else {
        const why = r?.why ?? "Refused.";
        setMsg(why);
        if (/wrong PIN|locked/i.test(why)) {   // a saved PIN that no longer works is forgotten, and the PIN is asked again
          forget();
          if (pinned) setAsk(key as Ask);
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
    if (s?.pin_required === false) goLive(""); else if (saved && pin) goLive(pin); else setAsk("live");
  };
  const onFlatten = () => { if (s?.pin_required === false) doFlatten(""); else if (saved && pin) doFlatten(pin); else setAsk("flatten"); };
  const onShadow = () => act(s?.mode === "shadow" ? "off" : "shadow");
  const isCurrent = (r: number | "min") => !!s && (r === "min" ? s.limits.sizing === "min"
    : s.limits.sizing !== "min" && Math.abs(r - s.limits.risk_usd) < 0.005);
  const setRisk = (r: number | "min", p: string) => {
    // one contract, or a lower amount, is always safe; a dollar amount above the current size asks once, since a trade
    // that hits its stop then loses more
    if (typeof r === "number" && (s?.limits.sizing === "min" || r > (s?.limits.risk_usd ?? 0))
      && !window.confirm(`Raise the size to ${usd(r)} of risk a trade? A trade that hits its stop then loses up to ${usd(r)}.`)) return;
    act("risk", p, r);
  };
  const onRisk = (r: number | "min") => {
    if (!s || isCurrent(r)) return;
    if (s?.pin_required === false) { setRisk(r, ""); return; }
    if (saved && pin) { setRisk(r, pin); return; }
    setPendingRisk(r);
    setAsk("risk");
  };
  const onSubmitPin = () => {
    if (!pin || busy) return;
    if (ask === "live") goLive(pin);
    else if (ask === "flatten") doFlatten(pin);
    else if (ask === "risk" && pendingRisk !== null) setRisk(pendingRisk, pin);
  };
  const onCancel = () => { setAsk(null); setPendingRisk(null); if (!saved) setPin(""); };
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
    pendingRisk={pendingRisk} busy={busy} msg={msg} onToggle={onToggle} onShadow={onShadow} onFlatten={onFlatten} onRisk={onRisk}
    onSubmitPin={onSubmitPin} onCancel={onCancel} onForgetPin={onForgetPin} intro={intro} />;
}
