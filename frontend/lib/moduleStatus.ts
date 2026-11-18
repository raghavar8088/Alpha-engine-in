// One shared copy of every module's switch + state, for the ON/OFF control in each page header.
//
// Every page header reads the same small `/api/main-control/status` body through this store, so
// opening a page costs at most one request per 20 s however many components ask. A toggle
// publishes the server's answer to every subscriber at once, so the header and Main Control
// never disagree.
//
// It also tells `apiFetch` which API prefixes belong to PAUSED modules: their rows are frozen,
// so the browser can answer repeat polls from memory instead of asking a busy server again.

import type { ModuleSwitches } from "./api";
import { apiFetch, fetchMainControl, setMainControlModule, setPausedApiPrefixes } from "./api";

export type ModuleState = "active" | "stopping" | "paused";

export interface ModuleStatusRow {
  label: string;
  href: string;
  hrefs: string[];
  enabled: boolean;
  state: ModuleState;
  open_positions: number | null;
  drains: boolean;
  real_money: boolean;
  group?: string;
  shared?: boolean;
  api_prefixes?: string[];
}

export interface ModuleStatusMap {
  modules: Record<string, ModuleStatusRow>;
  states: Record<string, string>;
  /** "drain" = OFF manages open positions to their exits. "freeze" = an older server. */
  semantics: "drain" | "freeze";
}

const FRESH_MS = 20_000;
const FALLBACK_STATES: Record<string, string> = {
  active: "Active",
  stopping: "Stopping — managing open positions",
  paused: "Paused",
};

let cache: { at: number; data: ModuleStatusMap } | null = null;
let inflight: Promise<ModuleStatusMap> | null = null;
const listeners = new Set<(d: ModuleStatusMap) => void>();

/** Modules that place real orders: switching one OFF asks for an explicit confirmation. The server
 *  says so itself (`real_money`); this list covers a server from before it did. */
export const REAL_MONEY_MODULES: ReadonlySet<string> = new Set(["live_trading", "delta_live"]);

function publish(data: ModuleStatusMap) {
  cache = { at: Date.now(), data };
  const paused: string[] = [];
  const active: string[] = [];
  for (const m of Object.values(data.modules)) {
    (m.state === "paused" ? paused : active).push(...(m.api_prefixes ?? []));
  }
  setPausedApiPrefixes(paused, active);
  listeners.forEach((fn) => fn(data));
}

/** Main Control's full snapshot -> the compact map (after a toggle, or from an older server). */
export function fromSnapshot(snap: ModuleSwitches): ModuleStatusMap {
  const modules: Record<string, ModuleStatusRow> = {};
  const drainServer = snap.semantics === "drain";
  for (const r of snap.modules ?? []) {
    modules[r.module] = {
      label: r.label,
      href: r.href,
      hrefs: r.hrefs ?? [],
      enabled: r.enabled,
      state: (r.state as ModuleState) ?? (r.enabled ? "active" : "paused"),
      open_positions: r.open_positions ?? null,
      drains: drainServer ? !!r.drains : false,
      real_money: r.real_money ?? REAL_MONEY_MODULES.has(r.module),
      group: r.group,
      shared: r.shared,
      api_prefixes: r.api_prefixes ?? [],
    };
  }
  return { modules, states: snap.states ?? FALLBACK_STATES, semantics: drainServer ? "drain" : "freeze" };
}

export function currentModuleStatus(): ModuleStatusMap | null {
  return cache?.data ?? null;
}

export async function loadModuleStatus(force = false): Promise<ModuleStatusMap> {
  if (!force && cache && Date.now() - cache.at < FRESH_MS) return cache.data;
  if (inflight) return inflight;
  inflight = (async () => {
    try {
      let data: ModuleStatusMap;
      try {
        const raw = await apiFetch(`/api/main-control/status${force ? "?fresh=true" : ""}`);
        data = {
          modules: raw.modules ?? {},
          states: raw.states ?? FALLBACK_STATES,
          semantics: raw.semantics === "drain" ? "drain" : "freeze",
        };
      } catch {
        // A server from before /status: read the full snapshot and derive the states from it.
        data = fromSnapshot(await fetchMainControl());
      }
      publish(data);
      return data;
    } finally {
      inflight = null;
    }
  })();
  return inflight;
}

export function subscribeModuleStatus(fn: (d: ModuleStatusMap) => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

/** Flip one module and publish the server's answer everywhere. */
export async function toggleModule(key: string, enabled: boolean): Promise<ModuleStatusMap> {
  const snap = await setMainControlModule(key, enabled);
  const data = fromSnapshot(snap);
  publish(data);
  return data;
}

/** Feed a full snapshot (e.g. from Main Control) into the shared store. */
export function publishSnapshot(snap: ModuleSwitches) {
  publish(fromSnapshot(snap));
}

/** Module keys whose page is this browser path. Shared app-wide services are left out of
 *  page headers - they have no page of their own and belong to Main Control. */
export function modulesForPath(map: ModuleStatusMap, pathname: string): string[] {
  const path = (pathname || "/").replace(/\/+$/, "") || "/";
  const out: string[] = [];
  for (const [key, m] of Object.entries(map.modules)) {
    if (m.shared && m.group === "System") continue;
    const pages = [m.href, ...(m.hrefs ?? [])].filter(Boolean);
    if (pages.some((h) => path === h || path.startsWith(h.replace(/\/+$/, "") + "/"))) out.push(key);
  }
  return out;
}

export function stateText(m: ModuleStatusRow, states: Record<string, string>): string {
  if (m.state === "stopping") {
    const n = m.open_positions;
    return n != null && n > 0
      ? `Stopping — managing ${n} open position${n === 1 ? "" : "s"}`
      : states.stopping ?? FALLBACK_STATES.stopping;
  }
  return states[m.state] ?? FALLBACK_STATES[m.state] ?? m.state;
}

/** What switching this module OFF will do, in one or two sentences - shown before it happens. */
export function offConsequence(m: ModuleStatusRow, semantics: "drain" | "freeze"): string {
  if (semantics === "drain" && m.drains) {
    return (
      "New entries stop now. Positions already open keep being managed — stops, targets, " +
      "exits and the mandatory square-off — and once it is flat it pauses completely: no " +
      "polling, no broker calls, no background work."
    );
  }
  return (
    "It pauses at once: no polling, no new trades, no background work. Any positions it " +
    "holds are left as they are and are NOT managed while it is off — square off first if " +
    "that matters."
  );
}
