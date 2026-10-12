"use client";

/** Indian Index Intraday — formatting helpers and the small pieces every tab shares.
 * Styles live once, in page.tsx, scoped under `.iid`. */

import type { IIParams, IIStatus } from "../../lib/indexIntradayApi";

export const dash = "—";

/** Rupees, Indian grouping; signed shows + / −. */
export function inr(v: number | null | undefined, signed = true, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return dash;
  const sign = signed ? (v > 0 ? "+" : v < 0 ? "−" : "") : v < 0 ? "−" : "";
  return `${sign}₹${Math.abs(v).toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

/** Basis points (1 bp = 0.01% of the position's value). */
export function bp(v: number | null | undefined, digits = 2, signed = true): string {
  if (v === null || v === undefined || Number.isNaN(v)) return dash;
  return `${signed && v > 0 ? "+" : ""}${v.toFixed(digits)} bp`;
}

export function num(v: number | null | undefined, digits = 2, signed = false): string {
  if (v === null || v === undefined || Number.isNaN(v)) return dash;
  return `${signed && v > 0 ? "+" : ""}${v.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

/** A fraction shown as a percent (0.4916 -> 49.2%). */
export function frac(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return dash;
  return `${(v * 100).toFixed(digits)}%`;
}

export function pct(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return dash;
  return `${v > 0 ? "+" : ""}${v.toFixed(digits)}%`;
}

/** An index level or price: two decimals, Indian grouping. */
export function px(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v) || v === 0) return dash;
  return v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export const tone = (v: number | null | undefined) => (!v ? "" : v > 0 ? "gain" : "loss");

/** Session minute (0 = 09:15) as clock time. */
export function hhmm(m: number | null | undefined): string {
  if (m === null || m === undefined) return dash;
  const t = 9 * 60 + 15 + m;
  return `${String(Math.floor(t / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`;
}

export function when(iso: string | null | undefined): string {
  if (!iso) return dash;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });
}

export function clock(iso: string | null | undefined): string {
  if (!iso) return dash;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

const PARAM_LABEL: Record<string, string> = {
  orm: "range",
  entry: "entry",
  stop: "stop",
  k: "k",
  vix: "VIX",
  start: "from",
  until: "until",
  signal_end: "signal to",
  enter: "enter",
  from: "from",
  thr: "threshold",
  tf: "tf",
  fast: "fast",
  slow: "slow",
  mode: "mode",
  n: "n",
  mult: "mult",
  adx: "ADX >",
  hi: "hi",
  lo: "lo",
  first: "first",
  at: "at",
};

/** {"tf": 5, "fast": 9} -> "tf 5m · fast 9" */
export function paramText(p: IIParams | null | undefined): string {
  if (!p || !Object.keys(p).length) return "defaults";
  return Object.entries(p)
    .map(([k, v]) => `${PARAM_LABEL[k] ?? k} ${v}${k === "tf" || k === "orm" ? "m" : ""}`)
    .join(" · ");
}

export const INDEX_LABEL: Record<string, string> = {
  NIFTY: "NIFTY 50",
  BANKNIFTY: "BANK NIFTY",
  FINNIFTY: "FINNIFTY",
  NIFTYNXT50: "NIFTY NEXT 50",
  NIFTY100: "NIFTY 100",
  MIDCPNIFTY: "MIDCAP SELECT",
  SENSEX: "SENSEX",
  BANKEX: "BANKEX",
};
export const INDEXES = Object.keys(INDEX_LABEL);

const STATUS_CLASS: Record<IIStatus, string> = {
  Experimental: "st-exp",
  Backtested: "st-bt",
  Validated: "st-val",
  "Paper Trading Approved": "st-ok",
};

export function StatusTag({ status }: { status: IIStatus | null | undefined }) {
  if (!status) return <span className="stag">{dash}</span>;
  return <span className={`stag ${STATUS_CLASS[status] ?? ""}`}>{status}</span>;
}

export function Side({ side }: { side: number }) {
  return <span className={side > 0 ? "side buy" : "side sell"}>{side > 0 ? "LONG" : "SHORT"}</span>;
}

/** A labelled number card. */
export function Stat({
  label,
  value,
  sub,
  cls = "",
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  cls?: string;
}) {
  return (
    <div className="stat">
      <div className="k">{label}</div>
      <div className={`v ${cls}`}>{value}</div>
      {sub !== undefined && <div className="s">{sub}</div>}
    </div>
  );
}

/** Today's date in IST as YYYY-MM-DD (the journal's day key). */
export function todayIST(): string {
  return new Date(Date.now() + 330 * 60000).toISOString().slice(0, 10);    // UTC + 5:30, read as a date
}
