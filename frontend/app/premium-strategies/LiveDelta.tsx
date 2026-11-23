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
// 21 Nov 2026: the strategies table shows each one's REAL-money results from the server (trades, win %, PF, t, net P&L,
// return % on the most margin it held at once, trading days, avg % a trading day, open now) in place of the record at
// the pick and the 2-year backtest; one value a cell, so the app-wide sorter sorts them as numbers. Above it, the desk's
// results (12 figures); below it, the desk day by day.
// 23 Nov 2026: the strategies table gains the server's Rank (expected net R a trade from the backtest, the paper record
// and the real copies; rows in rank order), the expected R and its chance of being positive, and each strategy's own
// controls: Trading ON/OFF (default ON) and Lots, the contracts a new trade takes (default 1, − and + then Save). OFF and
// lowering are instant; switching ON and raising ask once (the server needs the words REAL MONEY, which the page sends).
// An older server without them shows the values read-only.
// 23 Nov 2026 (later): a second sideways scrollbar ABOVE the strategies table (ScrollX), moving with the one under it; it stays at
// the top of the screen while the table is in view, so the 99-row gold table scrolls sideways from any row.
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { apiFetch } from "../../lib/api";

type Rec = { trades: number; wins: number; pnl_usd: number; open: number };
/** A pick's own paper trades now (18 Nov): its closed record since the paper desk started it, and its open trades. */
type PaperOpen = { id: string; side: number; entry: number | null; stop: number | null; target: number | null; entry_t: number;
  r_now: number | null };
type PaperRec = { trades: number; wins: number; sum_r: number; open: PaperOpen[]; last_t: number | null };
/** Real-money results (21 Nov), counted by the server from every trade of a strategy or a desk. Return % = net P&L / the
 *  most margin held at one time; a trading day = an IST day on which one of its real trades closed. */
export type Results = { trades: number; wins: number; open: number; win_pct: number | null; net_usd: number; fees_usd: number;
  won_usd: number; lost_usd: number; pf: number | null; t: number | null; peak_margin_usd: number; return_pct: number | null;
  days: number; avg_day_pct: number | null; avg_day_usd: number | null; avg_trade_usd: number | null;
  avg_trade_pct: number | null; best_usd: number | null; worst_usd: number | null; max_dd_usd: number;
  avg_hold_s: number | null; open_usd: number; first_at: number | null; last_at: number | null };
export type DeskResults = Results & { green_days: number;
  by_day: { day: string; trades: number; wins: number; pnl_usd: number; return_pct: number | null }[] };
type Pick = { acct: string; mkt: string; product: string; name: string; trades: number; sum_r: number; t: number; win: number;
  backtest: string; live: Rec | null; shadow: Rec | null; picked_at?: string | null;
  src?: string; template?: string | null;   // src "gold_h1": a Gold Desk H1 template (18 Nov); "gold_sf": a Gold Desk
  //                                           Strategy Factory strategy (19 Nov); else a Premium book
  paper?: PaperRec | null;                  // undefined on an older server, null when the paper side cannot be read
  results?: Results | null;                 // null until it has a real trade (21 Nov)
  cfg?: PickCfg | null;                     // its own lots and switch (23 Nov); undefined on an older server
  rank?: Rank | null };                     // the server's rank (23 Nov); null when the paper side cannot be read
/** A strategy's own size and switch (23 Nov): the contracts a new real trade takes, 1..max, and whether it trades. */
export type PickCfg = { contracts: number; on: boolean; max: number; at?: number | null };
/** The server's rank (23 Nov): pos 1 = best by edge_r, the expected net R a trade, and its parts. */
export type Rank = { pos: number; of: number; edge_r: number; sd_r: number; p_pos: number; prior_r: number; prior_sd: number;
  prior: "backtest" | "untested" | "pooled"; pre_n: number; post_n: number; post_r: number | null; paper_r: number;
  gap_r: number; gap_n: number };
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
    sizing?: "min" | "risk"; follow_all?: boolean; waiting?: number;
    // false on a desk that copies every signal (19 Nov): no daily loss stop, no cap on what one contract may lose
    daily_stop_on?: boolean; contract_cap_on?: boolean;
    // true on a server that takes each strategy's own lots and switch (23 Nov)
    pick_cfg?: boolean; lots_default?: number; lots_max?: Record<string, number> };
  rank_method?: string;
  pick_log?: { key: string; at: number; from: { contracts: number; on: boolean }; to: { contracts: number; on: boolean } }[];
  today: { live: number; shadow: number }; totals: { live: Totals; shadow: Totals }; picked_at: string; picks: Pick[];
  open: LiveTrade[]; recent: LiveTrade[]; notes: string[]; desk?: string; title?: string; products?: Record<string, unknown>;
  signals?: Signal[] | null; paper_view?: { at?: number; paper_age_s?: number | null; gold_desk_age_s?: number | null;
    factory_age_s?: number | null } | null; results?: DeskResults | null };

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
/** A signed percent with the U+2212 minus (the app's table sorter reads both). */
export const spct = (v: number | null | undefined, d = 2) =>
  v === null || v === undefined || Number.isNaN(v) ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(d)}%`;
/** No t-stat under this many trades: two near-equal trades give a t in the hundreds. */
export const MIN_T = 5;
const num = (v: number | null | undefined, d = 2) => (v === null || v === undefined ? "—" : v.toFixed(d));
const holdText = (s: number | null | undefined) =>
  s === null || s === undefined ? "—" : s < 5400 ? `${Math.round(s / 60)} min` : s < 172800 ? `${(s / 3600).toFixed(1)} h` : `${(s / 86400).toFixed(1)} days`;
/** IST calendar days from the first real trade to today, both counted. */
export const spanDays = (first: number | null | undefined, now: number) => {
  if (!first) return 0;
  const d = (t: number) => Math.floor((t + 19800) / 86400);
  return d(now) - d(first) + 1;
};
const dayText = (iso: string) => new Date(`${iso}T12:00:00+05:30`).toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata",
  weekday: "short", day: "2-digit", month: "short" });
export const dateText = (t: number | null | undefined) => (!t ? "—" : new Date(t * 1000).toLocaleDateString("en-IN",
  { timeZone: "Asia/Kolkata", day: "2-digit", month: "short" }));
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
export type Ask = null | "live" | "flatten" | "risk" | "pick";
/** A change to one strategy's own lots or switch (23 Nov), waiting for the PIN when the server asks for one. */
export type PickChange = { key: string; acct: string; contracts?: number; on?: boolean; raises?: boolean };
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
  const factory = count("factory");
  const parts: string[] = [];
  if (lose) parts.push(`${lose === n ? "All" : lose} of these ${n} ${lose === 1 ? "loses" : "lose"} in ${lose === 1 ? "its" : "their"} own 2-year backtest${lose === 1 ? "" : "s"}`);
  if (earn) parts.push(`${earn} ${earn === 1 ? "earns" : "earn"} too little in ${earn === 1 ? "its" : "their"} own to mean anything`);
  if (never) parts.push(`${never} ${never === 1 ? "was" : "were"} never backtested`);
  if (pooled) parts.push(`${pooled} ${pooled === 1 ? "was" : "were"} tested only as a family`);
  if (factory) parts.push(`${factory} ${factory === 1 ? "was" : "were"} graded only by the Strategy Factory's own backtest`);
  const said = parts.length > 1 ? `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}` : parts.join("");
  return `${said}${parts.length ? ":" : ""} a few good paper trades picked them.`;
};

const rr = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(2)}R`);
const pct = (n: number, d: number) => (d ? `${Math.round((100 * n) / d)}%` : "—");
const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;
type PFilter = "all" | "inTrade" | "real" | "waiting" | "off";
const inTrade = (p: Pick) => !!p.paper && p.paper.open.length > 0;
const isOff = (p: Pick) => p.cfg?.on === false;
const pkey = (p: Pick) => `${p.acct}|${p.mkt}`;
/** R with its sign, the page's minus: "+0.12R". */
const sr = (v: number | null | undefined, d = 2) =>
  (v === null || v === undefined ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(d)}R`);
/** One number a cell, so the app-wide sorter sorts it: "+0.12" (the unit is in the heading). */
const sn = (v: number | null | undefined, d = 2) =>
  (v === null || v === undefined ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(d)}`);
const rankCls = (k: Rank) => (k.p_pos >= 0.7 ? "hi" : k.p_pos >= 0.5 ? "mid" : "lo");
const rankTip = (k: Rank) => [
  `Rank ${k.pos} of ${k.of}: expected ${sr(k.edge_r)} a trade (± ${k.sd_r.toFixed(2)}R), ${Math.round(100 * k.p_pos)}% likely above zero.`,
  `Starting point: ${k.prior === "backtest" ? `its own backtest, ${sr(k.prior_r)} a trade` : k.prior === "pooled"
    ? "the H1 templates' pooled test, 0R" : `untested, so its desk's average backtest, ${sr(k.prior_r)}`} (± ${k.prior_sd.toFixed(2)}R).`,
  `Paper record: ${k.post_n} trade${k.post_n === 1 ? "" : "s"} since it was picked${k.post_r !== null ? ` (${sr(k.post_r)} each)` : ""}`
    + ` and ${k.pre_n} before (counted a quarter): ${sr(k.paper_r)} a trade.`,
  `Real copies against their paper twins: ${sr(k.gap_r)} a trade${k.gap_n ? ` (${k.gap_n} of its own, pulled toward the desk's)` : " (the desk's average)"}.`,
].join("\n");

/** A strategy's lots: − and + (or type a number), then Save; Undo puts it back. The visually hidden number keeps the
 *  cell sortable by the app-wide sorter (an input's value is not text). */
function LotCtl({ value, max, disabled, title, onSave }: { value: number; max: number; disabled: boolean; title: string;
  onSave: (n: number) => void }) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const clamp = (n: number) => Math.min(max, Math.max(1, Math.round(n)));
  const dirty = draft !== value;
  return (
    <span className={`ld-lot${dirty ? " dirty" : ""}`} title={title}>
      <span className="ld-sr" aria-hidden="true">{draft}</span>
      <button type="button" className="ld-lot-b ld-dec" aria-label="One contract fewer" disabled={disabled || draft <= 1}
        onClick={() => setDraft(clamp(draft - 1))} />
      <input type="number" className="ld-lot-v" aria-label="Contracts a trade" min={1} max={max} step={1} value={draft} disabled={disabled}
        onChange={(e) => { const n = Number(e.target.value); if (Number.isFinite(n) && e.target.value !== "") setDraft(clamp(n)); }}
        onKeyDown={(e) => { if (e.key === "Enter" && dirty && !disabled) onSave(draft); if (e.key === "Escape") setDraft(value); }} />
      <button type="button" className="ld-lot-b ld-inc" aria-label="One contract more" disabled={disabled || draft >= max}
        onClick={() => setDraft(clamp(draft + 1))} />
      {dirty && (
        <>
          <button type="button" className="ld-lot-save" disabled={disabled} onClick={() => onSave(draft)}>Save</button>
          <button type="button" className="ld-lot-b ld-undo" aria-label="Undo" disabled={disabled} onClick={() => setDraft(value)} />
        </>
      )}
    </span>
  );
}
/** What this desk did with a paper trade, as a badge (the reason goes under it). */
const DESK_STATE: Record<string, { label: string; cls: string }> = {
  open: { label: "Copied · open", cls: "open" }, entering: { label: "Copied · entering", cls: "open" },
  closing: { label: "Copied · closing", cls: "open" }, closed: { label: "Copied · closed", cls: "closed" },
  skipped: { label: "Skipped", cls: "skipped" }, error: { label: "Error", cls: "error" },
  before: { label: "Not copied", cls: "skipped" }, off: { label: "Not copied", cls: "skipped" },
  pending: { label: "Deciding", cls: "open" },
  // a desk that copies every paper trade (gold, 19 Nov): a copy that cannot go in yet waits; one whose paper trade
  // closed first, unseen by this desk, was missed
  waiting: { label: "Waiting to copy", cls: "open" }, missed: { label: "Not copied", cls: "skipped" },
};
/** A card that scrolls sideways, with a second scrollbar above it as well as the one under it (23 Nov 2026, the owner's
 *  ask for the strategies table). The two move together; the top one takes the content's width, hides when nothing
 *  overflows, and sticks to the top of the screen while the card is in view. It is a mirror, so it is kept out of the
 *  tab order and from screen readers: the card itself still scrolls as before. */
function ScrollX({ className, children }: { className: string; children: ReactNode }) {
  const top = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(0);                       // the content's width when it overflows; 0 = no top bar
  useEffect(() => {
    const b = box.current;
    if (!b) return;
    const measure = () => setW(b.scrollWidth > b.clientWidth + 1 ? b.scrollWidth : 0);
    measure();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", measure);
      return () => window.removeEventListener("resize", measure);
    }
    const ro = new ResizeObserver(measure);
    ro.observe(b);                                     // the card (the window's width) ...
    for (const el of Array.from(b.children)) ro.observe(el);   // ... and the table (its columns and rows)
    return () => ro.disconnect();
  }, []);
  useEffect(() => {                                    // a bar that just appeared starts where the card is
    if (top.current && box.current) top.current.scrollLeft = box.current.scrollLeft;
  }, [w]);
  const follow = (from: HTMLDivElement | null, to: HTMLDivElement | null) => {
    if (from && to && Math.abs(to.scrollLeft - from.scrollLeft) > 0.5) to.scrollLeft = from.scrollLeft;
  };
  return (
    <div className="ld-xwrap">
      <div ref={top} className="ld-xtop" hidden={!w} aria-hidden="true" tabIndex={-1}
        onScroll={() => follow(top.current, box.current)}>
        <div style={{ width: w }} />
      </div>
      <div ref={box} className={className} onScroll={() => follow(box.current, top.current)}>{children}</div>
    </div>
  );
}

type SFilter = "all" | "copied" | "skipped" | "not";
const copied = (x: Signal) => ["open", "entering", "closing", "closed"].includes(x.desk.status);
const notCopied = (x: Signal) => ["before", "off", "missed"].includes(x.desk.status);

/** What the page shows, given the desk's status: no state of its own beyond its props (and the trade-log filter). */
export function LiveDeltaView({ s, now, pin, setPin, remember, setRemember, saved, ask, pendingRisk, busy, msg, onToggle,
  onShadow, onFlatten, onRisk, onSubmitPin, onCancel, onForgetPin, intro, onPick, pickBusy = null, pendingPick = null, pickMsg = null }: {
  s: LiveStatus; now: number; pin: string; setPin: (v: string) => void; remember: boolean; setRemember: (v: boolean) => void;
  saved: boolean; ask: Ask; pendingRisk: number | "min" | null; busy: string | null; msg: string | null; onToggle: () => void;
  onShadow: () => void; onFlatten: () => void; onRisk: (r: number | "min") => void; onSubmitPin: () => void; onCancel: () => void;
  onForgetPin: () => void; intro?: ReactNode;
  // each strategy's own lots and switch (23 Nov): absent, the table shows them read-only
  onPick?: (p: Pick, change: { contracts?: number; on?: boolean }) => void; pickBusy?: string | null; pendingPick?: PickChange | null;
  pickMsg?: string | null;
}) {
  const [filter, setFilter] = useState<Filter>("all");
  const isLive = s.mode === "live";
  const pinNeeded = s.pin_required !== false;     // an older server, or one with PREMIUM_LIVE_REQUIRE_PIN=1
  const m = MODE[s.mode] ?? MODE.off;
  const L = s.limits;
  // the risk a trade the owner picks, whole dollars from the server's minimum to its cap; shown once the server offers it
  const risks = L.risk_cap_usd ? [1, 2, 3, 4, 5].filter((r) => r >= (L.risk_min_usd ?? 1) && r <= (L.risk_cap_usd ?? 5)) : [];
  const oneContract = L.sizing === "min";       // one contract a trade, the smallest order (the default from 15 Nov)
  const lotsSet = s.picks.filter((p) => (p.cfg?.contracts ?? 1) > 1).length;     // strategies set above one contract (23 Nov)
  const offN = s.picks.filter(isOff).length;
  const sizeText = oneContract
    ? (lotsSet ? `each strategy's own lots, 1 contract unless set higher in the strategies table (${lotsSet} ${lotsSet === 1 ? "strategy" : "strategies"} set higher)`
      : "1 contract a trade (the smallest order Delta allows)")
    : `${usd(L.risk_usd)} risked a trade`;
  const canPick = !!L.pick_cfg && !!onPick;     // a server that takes each strategy's own lots and switch
  const noDayStop = L.daily_stop_on === false;   // a desk that copies every signal (19 Nov)
  const noCap = L.contract_cap_on === false;
  const live = s.totals.live;
  const R = s.results;                          // the desk's real-money results (21 Nov); undefined on an older server
  const oneMargin = s.recent.find((t) => t.contracts === 1 && t.plan?.margin_usd)?.plan?.margin_usd;
  const span = spanDays(R?.first_at, now);
  const days = R?.by_day ?? [];
  const best = days.reduce<(typeof days)[number] | null>((a, d) => (!a || d.pnl_usd > a.pnl_usd ? d : a), null);
  const worst = days.reduce<(typeof days)[number] | null>((a, d) => (!a || d.pnl_usd < a.pnl_usd ? d : a), null);
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
    waiting: s.picks.filter((p) => !inTrade(p)).length, off: offN,
  };
  const hasRank = s.picks.some((p) => !!p.rank);
  const hasCfg = s.picks.some((p) => p.cfg !== undefined);
  // in rank order when the server ranks them (23 Nov); the app-wide sorter can re-sort by any column
  const picksShown = s.picks.filter((p) => pf === "all" ? true : pf === "inTrade" ? inTrade(p)
    : pf === "real" ? (p.live?.trades ?? 0) + (p.live?.open ?? 0) > 0 : pf === "off" ? isOff(p) : !inTrade(p))
    .slice().sort((a, b) => (a.rank?.pos ?? 1e9) - (b.rank?.pos ?? 1e9));
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
        {noDayStop ? `The size is the one chosen for this: ${sizeText}, and every signal becomes a real position: no daily loss stop.`
          : `The size is the one chosen for this: ${sizeText} and a ${usd(L.daily_stop_usd)} daily loss stop.`}
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
                  : `Switch ON to start: a real order for every new signal, ${sizeText}${noDayStop ? "" : `, stopping for the day after a ${usd(L.daily_stop_usd)} loss`}.${s.mode === "shadow" ? " A shadow test is running now: decisions are logged, nothing is sent." : ""}`}
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
                  ? `Every trade is 1 contract, the smallest order Delta allows${canPick ? ", unless you set a strategy's own lots higher in the strategies table" : ""}. What one contract loses at its stop depends on how far away the stop is: on bitcoin usually $0.20-0.60, on gold under 5 cents, plus fees. ${noCap ? "Every signal is taken at one contract, however far its stop (a stop more than 7% away is pulled in to 7%, inside the point where Delta would liquidate at 10x)." : "A trade whose one contract would lose more than $5 is skipped."}`
                  : "A dollar amount is the most one trade loses if its stop is hit, plus about $0.10-0.30 of fees. A trade whose smallest order (one contract) would lose more is skipped."}
              </span>
            </div>
          )}
          {ask && (
            <div className="ld-ctl-row">
              <label>{ask === "live" ? "Your PIN, to switch ON" : ask === "risk" ? `Your PIN, to set ${sizeLabel(pendingRisk)}`
                : ask === "pick" ? `Your PIN, to change ${pendingPick?.acct ?? "this strategy"}` : "Your PIN, to close every position"}
                <input type="password" autoComplete="off" inputMode="numeric" autoFocus value={pin} onChange={(e) => setPin(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") onSubmitPin(); }} />
              </label>
              <label className="ld-check">
                <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} /> Remember the PIN on this device
              </label>
              <button className={`ld-btn${ask === "live" ? " danger" : ""}`} disabled={!!busy || !pin} onClick={onSubmitPin}>
                {ask === "live" ? "Switch ON — real money" : ask === "risk" ? `Set ${sizeLabel(pendingRisk)}`
                  : ask === "pick" ? `Save ${pendingPick?.acct ?? "the change"}` : "Close every position now"}
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
          <span className="ld-s">{noDayStop ? "no daily loss stop: every signal is copied" : dayLeft > 0 ? `${usd(dayLeft)} left before the ${usd(L.daily_stop_usd)} daily stop` : "daily stop reached: no new trade today"}</span>
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
          <span className="ld-s">{`${L.follow_all ? "skipped: closed on paper first, too big or no balance" : "skipped as late, drifted or too big"}${live.errors ? ` · ${live.errors} error${live.errors === 1 ? "" : "s"}` : ""}`}</span>
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

      {R && R.trades > 0 && (
        <section className="ld-card ld-res" aria-label="Desk results, real money">
          <div className="ld-res-head">
            <b>Desk results, real money</b>
            <span>{`${R.trades} closed trades since ${dateText(R.first_at)} · return % is net P&L ÷ the most margin the desk held at one time, ${usd(R.peak_margin_usd)} at ${L.leverage}x`}</span>
          </div>
          <dl className="ld-res-grid">
            <div><dt>Trading days</dt><dd>{R.days}</dd><dd className="ld-res-s">{`of ${plural(span, "day")} since ${dateText(R.first_at)}`}</dd></div>
            <div><dt>Net P&amp;L</dt><dd className={tone(R.net_usd)}>{usd(R.net_usd, true)}</dd><dd className="ld-res-s">{`closed trades · fees ${usd(R.fees_usd)}`}</dd></div>
            <div><dt>Total return</dt><dd className={tone(R.return_pct)}>{spct(R.return_pct)}</dd><dd className="ld-res-s">{`on ${usd(R.peak_margin_usd)} of peak margin`}</dd></div>
            <div><dt>Avg % / trading day</dt><dd className={tone(R.avg_day_pct)}>{spct(R.avg_day_pct)}</dd><dd className="ld-res-s">{`${usd(R.avg_day_usd, true)} a trading day`}</dd></div>
            <div><dt>Avg % a trade</dt><dd className={tone(R.avg_trade_pct)}>{spct(R.avg_trade_pct, 3)}</dd><dd className="ld-res-s">{`${usd(R.avg_trade_usd, true)} a trade`}</dd></div>
            <div><dt>Win rate</dt><dd>{R.win_pct === null ? "—" : `${R.win_pct.toFixed(1)}%`}</dd><dd className="ld-res-s">{`${R.wins} of ${R.trades} won`}</dd></div>
            <div><dt>Profit factor</dt><dd>{R.pf === null ? "—" : num(R.pf)}</dd><dd className="ld-res-s">{R.pf === null ? "no losing trade yet" : `won ${usd(R.won_usd)} · lost ${usd(R.lost_usd)}`}</dd></div>
            <div><dt>t-stat</dt><dd>{R.trades >= MIN_T && R.t !== null ? num(R.t) : "—"}</dd><dd className="ld-res-s">{R.trades >= MIN_T ? "2 or more would hint at a real edge" : `none under ${MIN_T} trades`}</dd></div>
            <div><dt>Green days</dt><dd>{`${R.green_days} / ${R.days}`}</dd><dd className="ld-res-s">{best && worst ? `best ${usd(best.pnl_usd, true)} · worst ${usd(worst.pnl_usd, true)}` : "—"}</dd></div>
            <div><dt>Max drawdown</dt><dd className={tone(R.max_dd_usd)}>{usd(R.max_dd_usd, true)}</dd><dd className="ld-res-s">worst fall from a high, closed trades</dd></div>
            <div><dt>Best / worst trade</dt><dd>{`${usd(R.best_usd, true)} / ${usd(R.worst_usd, true)}`}</dd><dd className="ld-res-s">{`average hold ${holdText(R.avg_hold_s)}`}</dd></div>
            <div><dt>Open now</dt><dd className={R.open ? tone(R.open_usd) : ""}>{R.open ? usd(R.open_usd, true) : "0"}</dd><dd className="ld-res-s">{R.open ? `${plural(R.open, "trade")}, not in the results yet` : "no trade open"}</dd></div>
          </dl>
        </section>
      )}

      <h4 className="ld-h ld-h-row">
        <span>{`The ${s.picks.length} strategies, real-money results`}</span>
        {hasPaper && (
          <span className="ld-filters" role="group" aria-label="Show strategies">
            {([["all", "All"], ["inTrade", "In a paper trade"], ["real", "With real trades"], ["waiting", "Waiting"],
              ...(hasCfg ? [["off", "Switched off"] as [PFilter, string]] : [])] as [PFilter, string][]).map(([k, label]) => (
              <button key={k} type="button" className={`ld-fchip${pf === k ? " on" : ""}`} aria-pressed={pf === k}
                onClick={() => setPf(k)}>{label} <span>{pCounts[k]}</span></button>
            ))}
          </span>
        )}
      </h4>
      {pickMsg && <div className="ld-note ld-pickmsg" role="status">{pickMsg}</div>}
      <ScrollX className="ld-card ld-scroll">
        <table className="ld-table ld-strats">
          <thead>
            <tr>{hasRank && <th title="1 = most likely to make money from here (see the note under the table)">Rank</th>}
              <th className="l">Strategy</th>
              {hasCfg && <th title="ON: every new signal of this strategy becomes a real trade. OFF: none; one already open still closes at its stop, target or exit.">Trading</th>}
              {hasCfg && <th title="Contracts a new real trade of this strategy takes">Lots</th>}
              {hasRank && <th title="Expected net R a trade (R = what a trade risks at its stop)">Exp. R / trade</th>}
              {hasRank && <th title="How likely the expected R is above zero">Chance &gt; 0</th>}
              {hasPaper && <th className="l">Paper now</th>}
              <th>Trades</th><th>Win %</th><th>PF</th><th>t‑stat</th><th>Net P&amp;L</th><th>Return %</th><th>Trading days</th>
              <th>Avg % / trading day</th><th>Open now</th>{hasPaper && <th className="l">Paper so far</th>}</tr>
          </thead>
          <tbody>
            {picksShown.map((p) => {
              const o = p.paper?.open?.[0];
              const lv = p.live;
              // the server's results (21 Nov); an older server gives only the live record
              const r = p.results;
              const n = r ? r.trades : lv?.trades ?? 0;
              const wins = r ? r.wins : lv?.wins ?? 0;
              const net = r ? r.net_usd : lv?.pnl_usd ?? 0;
              const openN = r ? r.open : lv?.open ?? 0;
              const k = p.rank;
              const c = p.cfg;
              const key = pkey(p);
              const lock = !canPick || !c || !!busy || pickBusy === key;
              const lotsNote = !canPick ? "Shown read-only: the server does not take changes yet"
                : !oneContract ? `Not used while the desk sizes every trade by ${usd(L.risk_usd)} of risk`
                : `${c?.contracts ?? 1} contract${(c?.contracts ?? 1) === 1 ? "" : "s"} a trade; 1 to ${c?.max ?? 1}. A trade already open keeps its size.`;
              return (
                <tr key={key} className={`${inTrade(p) ? "ld-row-on" : ""}${isOff(p) ? " ld-row-off" : ""}`}>
                  {hasRank && (
                    <td className={k ? `ld-rk ${rankCls(k)}` : "ld-dim"} title={k ? rankTip(k) : "not ranked: the paper side could not be read"}>
                      {k ? k.pos : "—"}</td>
                  )}
                  <td className="l ld-strat">
                    <b>{p.acct}</b> <span className="ld-chip">{p.product}</span>
                    {p.src === "gold_h1" ? <span className="ld-chip ld-chip-src">Gold Desk H1</span> : null}
                    {p.src === "gold_sf" ? <span className="ld-chip ld-chip-src">Strategy Factory</span> : null}
                    <div className="ld-sub">{p.name}</div>
                  </td>
                  {hasCfg && (
                    <td className="ld-onoff">
                      <button type="button" role="switch" aria-checked={c?.on !== false} aria-label={`${p.acct} ${p.product} trading`}
                        className={`ld-mini${c?.on !== false ? " on" : ""}`} disabled={lock}
                        title={c?.on !== false ? "ON: its next signal places a real order. Click to switch it OFF." : "OFF: no new real trade. Click to switch it ON."}
                        onClick={() => onPick?.(p, { on: c?.on === false })}>
                        <span className="ld-mini-k" aria-hidden="true" />
                        <span className="ld-mini-t">{c?.on !== false ? "On" : "Off"}</span>
                      </button>
                    </td>
                  )}
                  {hasCfg && (
                    <td className="ld-lots-c">
                      <LotCtl value={c?.contracts ?? 1} max={c?.max ?? 1} disabled={lock || !oneContract} title={lotsNote}
                        onSave={(n) => onPick?.(p, { contracts: n })} />
                    </td>
                  )}
                  {hasRank && (
                    <td className={`ld-num ${k ? tone(k.edge_r) : ""}`} title={k ? rankTip(k) : undefined}>{k ? sn(k.edge_r) : "—"}</td>
                  )}
                  {hasRank && <td title={k ? rankTip(k) : undefined}>{k ? `${Math.round(100 * k.p_pos)}%` : "—"}</td>}
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
                    </>
                  )}
                  <td>{n || openN ? n : "—"}</td>
                  <td>{n ? `${(r?.win_pct ?? (100 * wins) / n).toFixed(1)}%` : "—"}</td>
                  <td title={r && n && r.pf === null ? "no losing trade yet" : undefined}>{r && n && r.pf !== null ? num(r.pf) : "—"}</td>
                  <td title={n && n < MIN_T ? `no t under ${MIN_T} trades` : undefined}>{r && n >= MIN_T && r.t !== null ? num(r.t) : "—"}</td>
                  <td className={`ld-num ${n ? tone(net) : ""}`}>{n ? usd(net, true) : "—"}</td>
                  <td className={`ld-num ${tone(r?.return_pct)}`} title={r && n ? `on ${usd(r.peak_margin_usd)} of peak margin` : undefined}>
                    {r && n ? spct(r.return_pct) : "—"}</td>
                  <td>{r && n ? r.days : "—"}</td>
                  <td className={`ld-num ${tone(r?.avg_day_pct)}`}>{r && n ? spct(r.avg_day_pct, 3) : "—"}</td>
                  <td className={`ld-num ${r && openN ? tone(r.open_usd) : ""}`} title={openN ? `${plural(openN, "real trade")} open` : undefined}>
                    {openN ? (r ? usd(r.open_usd, true) : `${openN} open`) : "—"}</td>
                  {hasPaper && (
                    <td className="l">
                      {p.paper ? (
                        <>
                          <span className={`ld-num ${tone(p.paper.sum_r)}`}>{p.paper.trades ? rr(p.paper.sum_r) : "—"}</span>
                          <div className="ld-sub">{p.paper.trades ? `${plural(p.paper.trades, "trade")} · ${pct(p.paper.wins, p.paper.trades)} won` : "no closed trade yet"}</div>
                        </>
                      ) : <span className="ld-dim">—</span>}
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
        {!picksShown.length && <p className="ld-dim ld-pad">None of these strategies is in this state right now.</p>}
        <p className="ld-foot">
          Real money only, closed trades, after Delta&apos;s fees. Return % = net P&amp;L ÷ the most margin the strategy held at
          one time{oneMargin ? ` (one contract at ${L.leverage}x holds about ${usd(oneMargin)} now)` : ""}; avg % /
          trading day = return % ÷ trading days, the IST days on which one of its real trades closed. No t-stat under {MIN_T} trades,
          and no profit factor before a losing trade.
        </p>
        {hasRank && s.rank_method && (
          <p className="ld-foot">{`${s.rank_method} Hover a rank for its parts. Green = 70% or more likely positive, amber 50-70%, grey under 50%. It is an estimate from short records, not a promise.`}</p>
        )}
        {hasCfg && (
          <p className="ld-foot">
            {`Trading ON/OFF and Lots are each strategy's own. OFF takes no new real trade for that strategy (its open paper trades wait, so ON again copies one still open); a real trade already open still closes at its stop, its target or its strategy's exit. Lots = the contracts each new real trade takes, 1 up to ${Object.entries(L.lots_max ?? {}).map(([sym, n]) => `${n} on ${sym}`).join(", ")}; a trade already open keeps its size. Switching ON and raising the lots ask you once; OFF and lowering are instant.${!oneContract ? ` Lots are not used while the desk sizes every trade by ${usd(L.risk_usd)} of risk (Trade size above).` : ""}${!canPick ? " The server running now does not take these changes yet, so they are shown read-only." : ""}`}
          </p>
        )}
        {showShadow && (
          <p className="ld-foot">{`Shadow: ${s.picks.filter((p) => p.shadow).map((p) => `${p.acct} ${usd(p.shadow!.pnl_usd, true)} (${p.shadow!.trades})`).join(" · ") || "no shadow trade yet"}`}</p>
        )}
      </ScrollX>

      {days.length > 0 && (
        <>
          <h4 className="ld-h">Day by day, real money (IST)</h4>
          <div className="ld-card ld-scroll">
            <table className="ld-table ld-days">
              <thead>
                <tr><th className="l">Day</th><th>Trades</th><th>Won</th><th>Win %</th><th>Net P&amp;L</th><th>Return %</th></tr>
              </thead>
              <tbody>
                {[...days].reverse().map((d) => (
                  <tr key={d.day}>
                    <td className="l">{dayText(d.day)}</td>
                    <td>{d.trades}</td>
                    <td>{d.wins}</td>
                    <td>{d.trades ? `${((100 * d.wins) / d.trades).toFixed(1)}%` : "—"}</td>
                    <td className={`ld-num ${tone(d.pnl_usd)}`}>{usd(d.pnl_usd, true)}</td>
                    <td className={`ld-num ${tone(d.return_pct)}`}>{spct(d.return_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="ld-foot">{`A day's return % is its net P&L ÷ the desk's ${usd(R?.peak_margin_usd)} of peak margin.`}</p>
          </div>
        </>
      )}

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
                        <td className="l"><b>{x.acct}</b>{x.src === "gold_h1" ? <span className="ld-chip ld-chip-src">H1</span>
                          : x.src === "gold_sf" ? <span className="ld-chip ld-chip-src">SF</span> : null}</td>
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
          <li>{`Limits: ${oneContract ? (noCap ? "1 contract a trade, its stop at most 7% from the price" : `1 contract a trade (skipped if it would lose more than ${usd(L.risk_cap_usd)})`) : `${usd(L.risk_usd)} risk a trade`}, ${noDayStop ? "no daily stop" : `${usd(L.daily_stop_usd)} daily stop`}, at most ${usd(L.max_notional_usd)} of notional a position, ${L.leverage}x leverage, ${L.follow_all ? "every open paper trade copied however late or far (it waits while the price is not inside its stop and target, or for free margin)" : `a signal older than ${Math.round(L.max_lag_s / 60)} minutes or already ${Math.round(L.drift_frac * 100)}% of its risk away is skipped`}.`}</li>
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
        .ld .ld-strats td.ld-strat { min-width: 200px; max-width: 280px; }
        .ld .ld-strats td { vertical-align: top; }
        .ld .ld-strats td .ld-badge + .ld-side { margin-left: 4px; }
        .ld .ld-row-on td { background: var(--brand-dim); }
        .ld .ld-row-on td:first-child { box-shadow: inset 3px 0 0 var(--brand); }
        .ld .ld-table tbody tr.ld-row-on:hover td { background: var(--brand-dim); }
        .ld .ld-chip-src { background: var(--warn-dim); border-color: var(--warn-border); color: var(--text-secondary); }
        .ld .ld-pad { padding: 12px 14px; }
        .ld .ld-res { padding: 14px 16px; display: flex; flex-direction: column; gap: 12px; }
        .ld .ld-res-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 12px; }
        .ld .ld-res-head b { font-size: 14px; font-weight: 800; color: var(--text); }
        .ld .ld-res-head span { font-size: 12px; color: var(--text-muted); }
        .ld .ld-res-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 14px 16px; margin: 0; }
        .ld .ld-res-grid > div { display: flex; flex-direction: column; gap: 2px; min-width: 0; padding-left: 10px;
                                 border-left: 2px solid var(--panel-border); }
        .ld .ld-res-grid dt { font-size: 10px; font-weight: 800; letter-spacing: 0.05em; text-transform: uppercase; color: var(--text-faint); }
        .ld .ld-res-grid dd { margin: 0; font-family: var(--font-data); font-size: 17px; font-weight: 700; color: var(--text);
                              font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
        .ld .ld-res-grid dd.gain { color: var(--gain); }
        .ld .ld-res-grid dd.loss { color: var(--loss); }
        .ld .ld-res-grid dd.ld-res-s { font-family: inherit; font-size: 11.5px; font-weight: 400; color: var(--text-muted); line-height: 1.4; }
        .ld .ld-strats th { white-space: normal; line-height: 1.3; vertical-align: bottom; padding: 10px 9px; }
        .ld .ld-strats th:not(.l) { max-width: 86px; }
        .ld .ld-strats td { padding: 9px 9px; }
        .ld .ld-strats td.ld-num { white-space: nowrap; }
        .ld .ld-strats td.l { min-width: 118px; }
        .ld .ld-signals td:nth-child(4) { font-family: var(--font-data); }
        .ld .ld-table td.ld-num.gain { color: var(--gain); }      /* a result keeps its colour in a dimmed row */
        .ld .ld-table td.ld-num.loss { color: var(--loss); }
        /* 23 Nov: rank, each strategy's own switch and lots */
        .ld .ld-strats td.ld-rk { font-family: var(--font-data); font-weight: 800; font-size: 13.5px; text-align: center; cursor: help; }
        .ld .ld-strats td.ld-rk.hi { color: var(--gain); }
        .ld .ld-strats td.ld-rk.mid { color: var(--warn); }
        .ld .ld-strats td.ld-rk.lo { color: var(--text-faint); }
        .ld .ld-strats td.ld-onoff, .ld .ld-strats td.ld-lots-c { text-align: left; white-space: nowrap; }
        .ld .ld-mini { display: inline-flex; align-items: center; gap: 6px; padding: 2px 8px 2px 2px; border-radius: 999px; cursor: pointer;
                       border: 1px solid var(--panel-border); background: var(--canvas-soft); color: var(--text-muted);
                       font-size: 11.5px; font-weight: 800; transition: background 0.15s; }
        .ld .ld-mini-k { width: 16px; height: 16px; border-radius: 50%; background: var(--text-faint); transition: background 0.15s; }
        .ld .ld-mini.on { background: var(--gain-dim); border-color: var(--gain); color: var(--gain); }
        .ld .ld-mini.on .ld-mini-k { background: var(--gain-solid); }
        .ld .ld-mini:disabled { cursor: not-allowed; opacity: 0.6; }
        .ld .ld-mini:focus-visible, .ld .ld-lot-b:focus-visible, .ld .ld-lot-v:focus-visible, .ld .ld-lot-save:focus-visible {
          outline: 2px solid var(--accent); outline-offset: 2px; }
        .ld .ld-lot { position: relative; display: inline-flex; align-items: center; gap: 3px; }
        .ld .ld-sr { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0 0 0 0);
                     white-space: nowrap; border: 0; }
        .ld .ld-lot-b { width: 22px; height: 22px; border-radius: 6px; border: 1px solid var(--panel-border); background: var(--panel);
                        color: var(--text); cursor: pointer; font-size: 14px; font-weight: 800; line-height: 1; padding: 0; }
        .ld .ld-lot-b:disabled { cursor: not-allowed; opacity: 0.4; }
        .ld .ld-dec::before { content: "−"; }
        .ld .ld-inc::before { content: "+"; }
        .ld .ld-undo::before { content: "✕"; font-size: 11px; }
        .ld .ld-lot-v { width: 44px; height: 22px; padding: 0 4px; border-radius: 6px; border: 1px solid var(--panel-border);
                        background: var(--panel); color: var(--text); font-family: var(--font-data); font-size: 12.5px;
                        font-weight: 700; text-align: center; -moz-appearance: textfield; }
        .ld .ld-lot-v::-webkit-outer-spin-button, .ld .ld-lot-v::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
        .ld .ld-lot-v:disabled { opacity: 0.7; }
        .ld .ld-lot.dirty .ld-lot-v { border-color: var(--warn-border); background: var(--warn-dim); }
        .ld .ld-lot-save { height: 22px; padding: 0 9px; border-radius: 6px; border: 0; background: var(--text); color: var(--panel);
                           font-size: 11.5px; font-weight: 800; cursor: pointer; }
        .ld .ld-lot-save:disabled { opacity: 0.5; cursor: not-allowed; }
        .ld .ld-row-off td:not(.ld-onoff):not(.ld-lots-c):not(.ld-rk) { opacity: 0.55; }
        .ld .ld-pickmsg { margin: 0 0 8px; }
        .ld .ld-xtop { position: sticky; top: 0; z-index: 3; overflow-x: auto; overflow-y: hidden; margin: 0 1px;
                       padding-top: 3px; background: var(--canvas); }
        .ld .ld-xtop[hidden] { display: none; }
        .ld .ld-xtop > div { height: 1px; }
        @media (max-width: 640px) {
          .ld .ld-v { font-size: 19px; } .ld .ld-ctl input { min-width: 140px; } .ld .ld-seg-b { padding: 7px 10px; }
          .ld .ld-status { padding: 14px; } .ld .ld-pos-dl { grid-template-columns: repeat(2, minmax(0, 1fr)); }
          .ld .ld-tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; } .ld .ld-tile { padding: 12px; }
          .ld .ld-res { padding: 12px; } .ld .ld-res-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
          .ld .ld-res-grid dd { font-size: 15px; }
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
  const [pickBusy, setPickBusy] = useState<string | null>(null);      // the strategy whose change is being saved
  const [pendingPick, setPendingPick] = useState<PickChange | null>(null);
  const [pickMsg, setPickMsg] = useState<string | null>(null);   // the last strategy change, shown above its table

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
    else if (ask === "pick" && pendingPick) sendPick(pendingPick, pin, !!pendingPick.raises);
  };
  // one strategy's own lots or switch (23 Nov): OFF and lowering are instant; ON and raising ask once, and send the
  // words the server needs for them (and the PIN, when the server requires one)
  const sendPick = async (ch: PickChange, usePin: string, raises: boolean) => {
    setPickBusy(ch.key);
    setPickMsg(null);
    try {
      const r = await apiFetch(`${base}/pick`, { method: "POST", body: JSON.stringify({ key: ch.key, contracts: ch.contracts, on: ch.on,
        pin: usePin, ...(raises ? { confirm: "REAL MONEY" } : {}) }) });
      if (r?.status) setS(r.status);
      if (r?.ok) {
        setPickMsg(ch.on === false ? `${ch.acct} is OFF: no new real trade (one already open still closes as usual).`
          : ch.on === true ? `${ch.acct} is ON: real orders on Delta again (a paper trade of it still open is copied at the next check).`
          : `${ch.acct}: ${ch.contracts} contract${ch.contracts === 1 ? "" : "s"} a trade from its next signal.`);
        setAsk(null);
        setPendingPick(null);
        if (usePin) { if (remember) { keepPin(usePin); setSaved(true); } else forget(); }
      } else {
        const why = r?.why ?? "Refused.";
        setPickMsg(`${ch.acct}: ${why}`);
        if (/wrong PIN|locked/i.test(why)) { forget(); setPendingPick(ch); setAsk("pick"); }
      }
    } catch (e) {
      setPickMsg(e instanceof Error ? e.message : "The request failed.");
    } finally {
      setPickBusy(null);
      setNow(Date.now() / 1000);
    }
  };
  const onPick = (p: Pick, change: { contracts?: number; on?: boolean }) => {
    if (!s || busy || pickBusy) return;
    const cur = p.cfg ?? { contracts: 1, on: true, max: 1 };
    const ch: PickChange = { key: pkey(p), acct: p.acct, ...change };
    const raises = (change.contracts !== undefined && change.contracts > cur.contracts) || (change.on === true && !cur.on);
    if (raises) {
      const recentPlan = s.recent.find((t) => t.product === p.product && t.plan?.margin_usd && t.plan?.contracts)?.plan;
      const perMargin = recentPlan ? recentPlan.margin_usd / recentPlan.contracts : null;
      const n = change.contracts ?? cur.contracts;
      const text = change.on === true
        ? `Switch ${p.acct} (${p.product}) ON? ${inTrade(p) ? "Its paper trade open now is copied to Delta Exchange at once, at the price then, and each"
          : "Its"} next signal places a real order on Delta Exchange, ${n} contract${n === 1 ? "" : "s"} a trade.`
        : `Trade ${n} contracts a trade on ${p.acct} (${p.product}) with real money? Each new signal then risks ${n} times what one contract `
          + `loses at its stop${perMargin ? `, and holds about ${usd(perMargin * n)} of margin` : ""}. A trade already open keeps its size.`;
      if (!window.confirm(text)) return;
    }
    // lowering or OFF only takes risk away: never a PIN (as switching the desk off); none at all when the owner chose so (15 Nov)
    if (!raises || s.pin_required === false) { sendPick(ch, "", raises); return; }
    if (saved && pin) { sendPick(ch, pin, raises); return; }
    setPendingPick({ ...ch, raises });
    setAsk("pick");
  };
  const onCancel = () => { setAsk(null); setPendingRisk(null); setPendingPick(null); if (!saved) setPin(""); };
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
    onSubmitPin={onSubmitPin} onCancel={onCancel} onForgetPin={onForgetPin} intro={intro}
    onPick={onPick} pickBusy={pickBusy} pendingPick={pendingPick} pickMsg={pickMsg} />;
}
