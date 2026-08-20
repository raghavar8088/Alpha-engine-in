"use client";

import { useEffect } from "react";

/**
 * Makes every table in the app sortable, without touching any of them.
 *
 * There are 93 tables here. Converting each to a shared <SortableTable> would mean
 * rewriting 93 blocks of JSX and their data flow — a very large mechanical change with a
 * real chance of breaking pages that currently work. This mounts once in the root layout
 * and upgrades tables in place: it adds the sort affordance to each header and reorders
 * the existing rows on click. A table added later is picked up automatically, so this
 * cannot fall out of date the way an enumerated list would.
 *
 * WHY REORDERING DOM ROWS IS SAFE HERE. React identifies rows by key, not by DOM position,
 * and updates cell text in place. Moving a <tr> does not confuse that. What DOES undo the
 * order is React replacing the row set on a data refresh — which is what the
 * MutationObserver is for: after any change to a tbody, the active sort is re-applied.
 *
 * VALUE PARSING IS THE WHOLE PROBLEM. These tables are full of "₹1,04,305", "+2.4%",
 * "−₹738", "2026-08-20" and "—". Sorting those as strings puts ₹9 above ₹1,00,000 and
 * scatters negatives. So each cell is parsed to a number where it plausibly is one —
 * stripping the rupee sign, Indian digit grouping, percent signs and the U+2212 minus this
 * app renders — and blanks always sink to the bottom regardless of direction, because an
 * empty cell is not "smallest", it is "unknown".
 */

const NUM_RE = /^[+\-−(]?\s*[₹$]?\s*[\d,]*\.?\d+\s*%?\)?$/;

function parseCell(raw: string): number | string | null {
  const t = raw.trim();
  if (!t || t === "—" || t === "-" || t === "–" || t === "n/a" || t === "N/A") return null;

  // ISO dates sort correctly as strings and must not be mistaken for numbers.
  if (/^\d{4}-\d{2}-\d{2}/.test(t)) return t;

  if (NUM_RE.test(t)) {
    const neg = t.startsWith("-") || t.startsWith("−") || t.startsWith("(");
    const cleaned = t.replace(/[₹$,%()\s+\-−]/g, "");
    if (cleaned === "") return null;
    const n = Number(cleaned);
    if (Number.isFinite(n)) return neg ? -n : n;
  }
  return t.toLowerCase();
}

function compare(a: number | string | null, b: number | string | null, dir: 1 | -1): number {
  // Unknowns sink, always — flipping direction should not promote missing data to the top.
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  if (typeof a === "number" && typeof b === "number") return (a - b) * dir;
  return String(a).localeCompare(String(b)) * dir;
}

type State = { index: number; dir: 1 | -1 };
const active = new WeakMap<HTMLTableElement, State>();
const wired = new WeakSet<HTMLTableElement>();

function applySort(table: HTMLTableElement) {
  const st = active.get(table);
  const tbody = table.tBodies[0];
  if (!st || !tbody) return;
  const rows = Array.from(tbody.rows);
  if (rows.length < 2) return;

  const keyed = rows.map((row) => ({
    row,
    key: parseCell(row.cells[st.index]?.textContent ?? ""),
  }));
  // Stable: equal keys keep the order the page produced them in.
  keyed.sort((x, y) => compare(x.key, y.key, st.dir));
  const frag = document.createDocumentFragment();
  for (const k of keyed) frag.appendChild(k.row);
  tbody.appendChild(frag);
}

function paintHeaders(table: HTMLTableElement) {
  const st = active.get(table);
  const head = table.tHead?.rows[0];
  if (!head) return;
  Array.from(head.cells).forEach((th, i) => {
    const mark = th.querySelector<HTMLElement>("[data-sort-mark]");
    if (!mark) return;
    if (st && st.index === i) {
      mark.textContent = st.dir === 1 ? "▲" : "▼";
      mark.style.opacity = "1";
    } else {
      mark.textContent = "▲▼";
      mark.style.opacity = "0.28";
    }
  });
}

function wire(table: HTMLTableElement) {
  if (wired.has(table)) return;
  const head = table.tHead?.rows[0];
  const tbody = table.tBodies[0];
  if (!head || !tbody || tbody.rows.length === 0) return;   // wait for real content
  wired.add(table);

  Array.from(head.cells).forEach((th, i) => {
    if (th.querySelector("[data-sort-mark]")) return;
    th.style.cursor = "pointer";
    th.style.userSelect = "none";
    th.title = "Sort by this column";
    const mark = document.createElement("span");
    mark.setAttribute("data-sort-mark", "");
    mark.textContent = "▲▼";
    mark.style.cssText = "margin-left:5px;font-size:8.5px;letter-spacing:-1px;opacity:.28;";
    th.appendChild(mark);

    th.addEventListener("click", () => {
      const cur = active.get(table);
      // Same column toggles direction; a new column starts ascending.
      const next: State =
        cur && cur.index === i ? { index: i, dir: cur.dir === 1 ? -1 : 1 } : { index: i, dir: 1 };
      active.set(table, next);
      applySort(table);
      paintHeaders(table);
    });
  });

  // React swaps row contents on every refresh; re-apply whatever the user chose.
  const obs = new MutationObserver(() => {
    if (!active.get(table)) return;
    window.requestAnimationFrame(() => applySort(table));
  });
  obs.observe(tbody, { childList: true });
}

export default function SortableTables() {
  useEffect(() => {
    const scan = () => document.querySelectorAll<HTMLTableElement>("table").forEach(wire);
    scan();
    // Tables mount late (tab switches, async loads), so keep watching the tree.
    const obs = new MutationObserver(() => window.requestAnimationFrame(scan));
    obs.observe(document.body, { childList: true, subtree: true });
    return () => obs.disconnect();
  }, []);
  return null;
}
