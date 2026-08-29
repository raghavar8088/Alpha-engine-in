"use client";

/**
 * Filter and sort controls shared by the two verdict tables.
 *
 * Built as select boxes rather than another row of chips because these are FOUR
 * independent axes. Chips imply one choice at a time; the question people actually ask
 * here is compound — "bullish, buyable, at an all-time high, score over 80" — and four
 * chip rows would take more vertical space than the results.
 *
 * The active-filter count and a clear button are not decoration: a filtered table that
 * looks like an empty one is the single easiest way to make a working screen look broken.
 */

import { ReactNode } from "react";

export interface SortState<K extends string> {
  key: K;
  dir: 1 | -1;
}

/** A sortable header cell. Clicking the active column flips direction. */
export function Th<K extends string>({
  k, sort, setSort, align, numeric, children,
}: {
  k: K;
  sort: SortState<K>;
  setSort: (s: SortState<K>) => void;
  align?: "l";
  /** Numbers read better defaulting to descending — biggest first is what you want. */
  numeric?: boolean;
  children: ReactNode;
}) {
  const on = sort.key === k;
  return (
    <th className={align === "l" ? "l srt" : "srt"}
      onClick={() => setSort(on ? { key: k, dir: (sort.dir === 1 ? -1 : 1) }
                               : { key: k, dir: numeric ? -1 : 1 })}>
      <span className={on ? "on" : ""}>
        {children}
        <i>{on ? (sort.dir === 1 ? "▲" : "▼") : "↕"}</i>
      </span>
      <style jsx>{`
        .srt { cursor: pointer; user-select: none; }
        .srt:hover span { color: var(--text-primary); }
        span { display: inline-flex; align-items: center; gap: 4px; }
        span.on { color: var(--accent); }
        i { font-style: normal; font-size: 9px; opacity: 0.55; }
        span.on i { opacity: 1; }
      `}</style>
    </th>
  );
}

export function Select({ label, value, onChange, options }: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: [string, string][];
}) {
  return (
    <label className="sel">
      <span>{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}
        className={value !== "any" && value !== "0" ? "set" : ""}>
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
      <style jsx>{`
        .sel { display: inline-flex; align-items: center; gap: 6px; font-size: 11.5px; color: var(--text-muted); }
        select {
          padding: 5px 9px; border-radius: 8px; font-size: 12px; cursor: pointer;
          border: 1px solid var(--border); background: var(--canvas-soft);
          color: var(--text-secondary); font-family: inherit;
        }
        select.set { border-color: var(--accent); color: var(--accent); font-weight: 600; }
        select:focus { outline: none; border-color: var(--accent); }
      `}</style>
    </label>
  );
}

export function SearchBox({ value, onChange, placeholder }: {
  value: string; onChange: (v: string) => void; placeholder?: string;
}) {
  return (
    <div className="sb">
      <input value={value} onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder ?? "Find a stock…"} spellCheck={false} />
      {value && <button onClick={() => onChange("")} title="clear">✕</button>}
      <style jsx>{`
        .sb { position: relative; display: inline-flex; }
        input {
          padding: 5px 26px 5px 10px; border-radius: 8px; font-size: 12px; width: 150px;
          border: 1px solid var(--border); background: var(--canvas-soft);
          color: var(--text-primary); font-family: inherit;
        }
        input:focus { outline: none; border-color: var(--accent); }
        button {
          position: absolute; right: 4px; top: 50%; transform: translateY(-50%);
          border: none; background: none; cursor: pointer; font-size: 11px;
          color: var(--text-faint); padding: 2px 4px;
        }
      `}</style>
    </div>
  );
}

export function FilterBar({ active, onClear, children }: {
  active: number; onClear: () => void; children: ReactNode;
}) {
  return (
    <div className="fb">
      {children}
      {active > 0 && (
        <button className="clr" onClick={onClear}>
          clear {active} filter{active === 1 ? "" : "s"}
        </button>
      )}
      <style jsx>{`
        .fb {
          display: flex; flex-wrap: wrap; align-items: center; gap: 10px;
          padding: 10px 12px; margin-bottom: 12px;
          border: 1px solid var(--border); border-radius: 10px;
          background: var(--canvas-soft);
        }
        .clr {
          padding: 5px 11px; border-radius: 8px; font-size: 11.5px; cursor: pointer;
          border: 1px solid var(--accent); background: transparent; color: var(--accent);
          font-weight: 600;
        }
      `}</style>
    </div>
  );
}

/** Compare two values for sorting, with nulls always last regardless of direction. */
export function cmp(a: unknown, b: unknown, dir: 1 | -1): number {
  const an = a === null || a === undefined || a === "";
  const bn = b === null || b === undefined || b === "";
  if (an && bn) return 0;
  // A missing value is not "the smallest" — it is absent, and sinking it to the bottom
  // either way keeps the top of the table full of rows that actually have the column.
  if (an) return 1;
  if (bn) return -1;
  if (typeof a === "number" && typeof b === "number") return (a - b) * dir;
  return String(a).localeCompare(String(b)) * dir;
}
