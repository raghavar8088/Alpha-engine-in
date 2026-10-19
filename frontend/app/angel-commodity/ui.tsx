"use client";

/* Shared formatting and small display pieces for the Angel One Commodity pages. */

import { type ReactNode } from "react";

export const inr = (v: number | null | undefined, dp = 0) =>
  v === null || v === undefined || !Number.isFinite(v)
    ? "–"
    : `₹${v.toLocaleString("en-IN", { minimumFractionDigits: dp, maximumFractionDigits: dp })}`;

export const signed = (v: number | null | undefined, dp = 0) =>
  v === null || v === undefined || !Number.isFinite(v)
    ? "–"
    : `${v >= 0 ? "+" : "−"}₹${Math.abs(v).toLocaleString("en-IN", { minimumFractionDigits: dp, maximumFractionDigits: dp })}`;

export const pct = (v: number | null | undefined, dp = 2) =>
  v === null || v === undefined || !Number.isFinite(v)
    ? "–"
    : `${v >= 0 ? "+" : "−"}${Math.abs(v * 100).toLocaleString("en-IN", { minimumFractionDigits: dp, maximumFractionDigits: dp })}%`;

export const plainPct = (v: number | null | undefined, dp = 1) =>
  v === null || v === undefined || !Number.isFinite(v) ? "–" : `${(v * 100).toFixed(dp)}%`;

export const num = (v: number | null | undefined, dp = 2) =>
  v === null || v === undefined || !Number.isFinite(v) ? "–" : v.toLocaleString("en-IN", { maximumFractionDigits: dp, minimumFractionDigits: dp });

export const tone = (v: number | null | undefined) =>
  v === null || v === undefined || !Number.isFinite(v) || v === 0 ? "" : v > 0 ? "gain" : "loss";

export function holdText(minutes: number | null | undefined, days?: number): string {
  if (days && days > 0) return days === 1 ? "1 day" : `${days} days`;
  if (minutes === null || minutes === undefined) return "same day";
  if (minutes < 60) return `${Math.round(minutes)} min`;
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return m ? `${h} h ${m} min` : `${h} h`;
}

export function downloadCsv(filename: string, rows: Record<string, unknown>[]): void {
  if (!rows.length) return;
  const cols = Array.from(rows.reduce<Set<string>>((s, r) => { Object.keys(r).forEach((k) => s.add(k)); return s; }, new Set()));
  const cell = (v: unknown) => {
    if (v === null || v === undefined) return "";
    const s = typeof v === "object" ? JSON.stringify(v) : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const text = [cols.join(","), ...rows.map((r) => cols.map((c) => cell(r[c])).join(","))].join("\n");
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function Tile({ label, value, sub, valueClass = "" }: { label: string; value: ReactNode; sub?: ReactNode; valueClass?: string }) {
  return (
    <div className="ac-tile">
      <div className="ac-tile-label">{label}</div>
      <div className={`ac-tile-value ${valueClass}`}>{value}</div>
      {sub !== undefined && <div className="ac-tile-sub">{sub}</div>}
      <style jsx>{`
        .ac-tile { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 12px; padding: 13px 15px; min-width: 0; }
        .ac-tile-label { font-size: 10.5px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; color: var(--text-muted); }
        .ac-tile-value { margin-top: 6px; font-size: 19px; font-weight: 700; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
        .ac-tile-sub { margin-top: 4px; font-size: 11px; color: var(--text-faint); line-height: 1.4; }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
      `}</style>
    </div>
  );
}

export function Kv({ k, v, vClass = "" }: { k: ReactNode; v: ReactNode; vClass?: string }) {
  return (
    <div className="ac-kv">
      <span>{k}</span>
      <b className={vClass}>{v}</b>
      <style jsx>{`
        .ac-kv { display: flex; justify-content: space-between; gap: 12px; font-size: 12.5px; padding: 6px 0; border-bottom: 1px solid var(--canvas-soft); }
        .ac-kv span { color: var(--text-muted); }
        .ac-kv b { text-align: right; font-weight: 600; font-variant-numeric: tabular-nums; }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
      `}</style>
    </div>
  );
}

/** Diverging bars for rupee values: sign is shown by POSITION (right of the zero line is a
 *  gain, left a loss) and by the printed value, never by colour alone. One scale for all rows. */
export function BarList({ rows, format = (v: number) => signed(v), emptyNote = "No data yet." }: {
  rows: { key: string; label: ReactNode; value: number; sub?: ReactNode }[];
  format?: (v: number) => string;
  emptyNote?: string;
}) {
  if (!rows.length) return <div className="ac-empty">{emptyNote}<style jsx>{`.ac-empty { padding: 18px; text-align: center; color: var(--text-faint); font-size: 12.5px; }`}</style></div>;
  const max = Math.max(...rows.map((r) => Math.abs(r.value)), 1e-9);
  const hasNeg = rows.some((r) => r.value < 0);
  return (
    <div className="ac-bars">
      {rows.map((r) => {
        const w = (Math.abs(r.value) / max) * (hasNeg ? 50 : 100);
        const left = hasNeg ? (r.value < 0 ? 50 - w : 50) : 0;
        return (
          <div key={r.key} className="ac-bar-row">
            <div className="ac-bar-label">{r.label}{r.sub ? <div className="ac-bar-sub">{r.sub}</div> : null}</div>
            <div className="ac-bar-track">
              {hasNeg && <div className="ac-bar-zero" />}
              <div className={`ac-bar ${r.value >= 0 ? "pos" : "neg"}`} style={{ left: `${left}%`, width: `${Math.max(w, 0.6)}%` }} />
            </div>
            <div className={`ac-bar-value ${r.value > 0 ? "gain" : r.value < 0 ? "loss" : ""}`}>{format(r.value)}</div>
          </div>
        );
      })}
      <style jsx>{`
        .ac-bars { display: flex; flex-direction: column; gap: 6px; }
        .ac-bar-row { display: grid; grid-template-columns: minmax(110px, 34%) 1fr minmax(78px, auto); gap: 10px; align-items: center; }
        .ac-bar-label { font-size: 12px; color: var(--text); min-width: 0; overflow-wrap: anywhere; }
        .ac-bar-sub { font-size: 10.5px; color: var(--text-faint); }
        .ac-bar-track { position: relative; height: 14px; background: var(--canvas-soft); border-radius: 4px; overflow: hidden; }
        .ac-bar-zero { position: absolute; left: 50%; top: 0; bottom: 0; width: 1px; background: var(--panel-border); }
        .ac-bar { position: absolute; top: 2px; bottom: 2px; border-radius: 3px; }
        .ac-bar.pos { background: var(--gain); }
        .ac-bar.neg { background: var(--loss); }
        .ac-bar-value { font-size: 12px; font-weight: 600; text-align: right; font-variant-numeric: tabular-nums; }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
      `}</style>
    </div>
  );
}

/** Calendar of daily net P&L, months as grids of weeks (Mon-Sun). Colour strength follows the
 *  day's size against the largest day shown; every traded day also prints its sign (+/-) and
 *  carries its value in the tooltip, so colour is never the only signal. */
export function CalendarHeat({ days, months = 6 }: { days: { date: string; net: number; roi: number | null }[]; months?: number }) {
  if (!days.length) return <div className="ac-cal-empty">No trading days yet.<style jsx>{`.ac-cal-empty { padding: 18px; text-align: center; color: var(--text-faint); font-size: 12.5px; }`}</style></div>;
  const by = new Map(days.map((d) => [d.date, d]));
  const max = Math.max(...days.map((d) => Math.abs(d.net)), 1e-9);
  const last = new Date(`${days.map((d) => d.date).sort().slice(-1)[0]}T00:00:00`);
  const mlist: Date[] = [];
  for (let i = months - 1; i >= 0; i -= 1) mlist.push(new Date(last.getFullYear(), last.getMonth() - i, 1));
  const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  return (
    <div className="ac-cal">
      {mlist.map((m) => {
        const first = (m.getDay() + 6) % 7;            // Monday = 0
        const n = new Date(m.getFullYear(), m.getMonth() + 1, 0).getDate();
        const cells: (Date | null)[] = Array(first).fill(null);
        for (let d = 1; d <= n; d += 1) cells.push(new Date(m.getFullYear(), m.getMonth(), d));
        const total = Array.from(by.values()).filter((x) => x.date.startsWith(iso(m).slice(0, 7))).reduce((s, x) => s + x.net, 0);
        return (
          <div key={iso(m)} className="ac-month">
            <div className="ac-month-head">
              <b>{m.toLocaleString("en-IN", { month: "short", year: "numeric" })}</b>
              <span className={total > 0 ? "gain" : total < 0 ? "loss" : ""}>{total ? signed(total) : ""}</span>
            </div>
            <div className="ac-grid">
              {["M", "T", "W", "T", "F", "S", "S"].map((w, i) => <div key={`h${i}`} className="ac-wd">{w}</div>)}
              {cells.map((c, i) => {
                if (!c) return <div key={`b${i}`} />;
                const d = by.get(iso(c));
                const strength = d ? Math.round(25 + 65 * Math.min(1, Math.abs(d.net) / max)) : 0;
                const bg = d ? `color-mix(in srgb, ${d.net >= 0 ? "var(--gain)" : "var(--loss)"} ${strength}%, transparent)` : undefined;
                return (
                  <div key={iso(c)} className={`ac-day ${d ? "has" : ""}`} style={{ background: bg }}
                    title={d ? `${iso(c)}: ${signed(d.net)}${d.roi !== null ? ` (${pct(d.roi)})` : ""}` : iso(c)}>
                    {c.getDate()}{d ? <sup>{d.net >= 0 ? "+" : "−"}</sup> : null}
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
      <style jsx>{`
        .ac-cal { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 14px; }
        .ac-month-head { display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 6px; }
        .ac-month-head span { font-variant-numeric: tabular-nums; }
        .ac-grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 3px; }
        .ac-wd { font-size: 9.5px; color: var(--text-faint); text-align: center; }
        .ac-day { aspect-ratio: 1; border-radius: 4px; font-size: 10px; display: flex; align-items: center; justify-content: center; color: var(--text-faint); background: var(--canvas-soft); }
        .ac-day.has { color: var(--text); font-weight: 700; }
        .ac-day sup { font-size: 8px; margin-left: 1px; }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
      `}</style>
    </div>
  );
}
