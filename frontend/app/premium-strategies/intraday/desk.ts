// Data hooks and formatting for Premium Strategies -> Premium Intraday Strategies. Everything here reads the desk's
// OWN routes (/api/premium-intraday/*); nothing in this folder is imported by the Premium Strategies page, so opening
// that page never loads this code or calls these routes.
import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch } from "../../../lib/api";

export const API = "/api/premium-intraday";

function istMinutes(): number {
  const now = new Date(Date.now() + 5.5 * 3600 * 1000);
  return now.getUTCHours() * 60 + now.getUTCMinutes();
}

/** In market hours (09:00-15:45 IST) a live view re-reads every `everyMs`; outside them it reads once. */
export function useDesk<T = any>(path: string | null, everyMs = 60_000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const alive = useRef(true);
  const load = useCallback(async (fresh = false) => {
    if (!path) return;
    setLoading(true);
    try {
      const d = await apiFetch(fresh ? `${path}${path.includes("?") ? "&" : "?"}fresh=true` : path);
      if (alive.current) {
        setData(d);
        setError(null);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Could not load";
      // Until the desk's server part is deployed, the backend answers its routes with 404 "Not Found".
      if (alive.current) setError(/^(Not Found|Request failed: 404)$/.test(msg)
        ? "Not available yet: the desk's server part is not deployed on the backend (or the backend is restarting)."
        : msg);
    } finally {
      if (alive.current) setLoading(false);
    }
  }, [path]);
  useEffect(() => {
    alive.current = true;
    load();
    const id = setInterval(() => {
      const m = istMinutes();
      if (m >= 9 * 60 && m <= 15 * 60 + 45) load();
    }, everyMs);
    return () => {
      alive.current = false;
      clearInterval(id);
    };
  }, [load, everyMs]);
  return { data, error, loading, reload: () => load(true) };
}

export const num = (x: any, d = 2) => (x === null || x === undefined || Number.isNaN(x) ? "—" : Number(x).toFixed(d));
export const pct = (x: any, d = 2) => (x === null || x === undefined ? "—" : `${x > 0 ? "+" : ""}${Number(x).toFixed(d)}%`);
export const share = (x: any) => (x === null || x === undefined ? "—" : `${Math.round(Number(x) * 100)}%`);
export const R = (x: any, d = 3) => (x === null || x === undefined ? "—" : `${x > 0 ? "+" : ""}${Number(x).toFixed(d)}R`);
export const bp = (x: any) => (x === null || x === undefined ? "—" : `${x > 0 ? "+" : ""}${Number(x).toFixed(1)} bp`);
export const tone = (x: any) => (x === null || x === undefined ? "" : x > 0 ? "pis-up" : x < 0 ? "pis-down" : "");
export function inr(x: any, d = 0): string {
  if (x === null || x === undefined) return "—";
  const v = Number(x);
  const s = Math.abs(v).toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: d });
  return `${v < 0 ? "−" : ""}₹${s}`;
}
export function hm(epoch: any): string {
  if (!epoch) return "—";
  const t = new Date(Number(epoch) * 1000 + 5.5 * 3600 * 1000);
  return `${String(t.getUTCHours()).padStart(2, "0")}:${String(t.getUTCMinutes()).padStart(2, "0")}`;
}
export function statusClass(s: string | undefined): string {
  const v = (s || "").toLowerCase();
  if (v.startsWith("portfolio eligible")) return "pis-pill pis-pill-good";
  if (v.startsWith("forward") || v.startsWith("backtest qualified")) return "pis-pill pis-pill-info";
  if (v.startsWith("paused") || v.startsWith("rejected")) return "pis-pill pis-pill-bad";
  return "pis-pill pis-pill-neutral";
}
export const LEVEL: Record<string, string> = {
  L0: "rule alone", L1: "+ sector confirmation", L2: "+ 09:40 checkpoint", L3: "+ news",
};

/** "3 min ago" from an ISO string or epoch seconds. */
export function ago(t: any): string {
  if (!t) return "never";
  const ms = typeof t === "number" ? t * 1000 : Date.parse(t);
  if (!Number.isFinite(ms)) return "—";
  const s = Math.max(0, Math.round((Date.now() - ms) / 1000));
  if (s < 90) return `${s}s ago`;
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 172800) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} days ago`;
}
