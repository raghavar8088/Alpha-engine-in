"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ChartResolution, chartStreamUrl } from "../../lib/api";

export type StreamStatus =
  | "off"          // nothing selected, or streaming turned off
  | "unsupported"  // resolution has no live equivalent (weekly)
  | "connecting"
  | "live"
  | "reconnecting"
  | "stale";       // connected, but nothing has arrived for a while

export interface StreamBar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  final: boolean;
}

/** Weekly bars have no live bucket in the feed — see `stream_timeframe` server-side. */
const STREAMABLE: ChartResolution[] = ["1", "5", "15", "60", "D"];

// The server sends a keepalive every 15s, so silence well past that means the
// link is dead even though EventSource hasn't noticed yet.
const STALE_AFTER_MS = 45_000;

export const DEFAULT_SESSION = "0915-1530";

/** Whether the instrument's own session is currently open, in IST. Used only to
 * label the pill honestly — nothing is gated on it, so an exchange holiday just
 * shows a quiet stream. `session` comes from the symbol endpoint, so an MCX
 * contract trading at 21:00 IST isn't reported as closed. */
export function isMarketOpen(session: string = DEFAULT_SESSION, now = new Date()): boolean {
  const ist = new Date(now.getTime() + (now.getTimezoneOffset() + 330) * 60_000);
  const day = ist.getDay();
  if (day === 0 || day === 6) return false;
  const [openPart, closePart] = session.split("-");
  const toMinutes = (hhmm: string) => Number(hhmm.slice(0, 2)) * 60 + Number(hhmm.slice(2));
  const minutes = ist.getHours() * 60 + ist.getMinutes();
  return minutes >= toMinutes(openPart) && minutes <= toMinutes(closePart);
}

interface Params {
  securityId: string | null;
  exchangeSegment: string | null;
  resolution: ChartResolution;
  enabled: boolean;
  /** "HHMM-HHMM" IST from the symbol endpoint; falls back to equity hours. */
  session?: string;
}

export function useChartStream({ securityId, exchangeSegment, resolution, enabled, session }: Params) {
  const [status, setStatus] = useState<StreamStatus>("off");
  const [bar, setBar] = useState<StreamBar | null>(null);
  const lastMessageRef = useRef<number>(0);

  const supported = STREAMABLE.includes(resolution);

  useEffect(() => {
    setBar(null);
    if (!enabled || !securityId || !exchangeSegment) {
      setStatus("off");
      return;
    }
    if (!supported) {
      setStatus("unsupported");
      return;
    }

    setStatus("connecting");
    lastMessageRef.current = Date.now();

    let source: EventSource;
    try {
      source = new EventSource(chartStreamUrl(securityId, exchangeSegment, resolution));
    } catch (err) {
      console.warn("[chart stream] could not open", err);
      setStatus("off");
      return;
    }

    source.onmessage = (event) => {
      lastMessageRef.current = Date.now();
      let payload: { type?: string } & Partial<StreamBar>;
      try {
        payload = JSON.parse(event.data);
      } catch {
        return;
      }
      setStatus("live");
      if (payload.type === "bar" && typeof payload.time === "number") {
        setBar(payload as StreamBar);
      }
    };

    // EventSource reconnects on its own; surface the gap rather than tearing the
    // subscription down and re-registering the symbol on the server each blip.
    source.onerror = () => setStatus((prev) => (prev === "live" ? "reconnecting" : prev));

    const staleTimer = setInterval(() => {
      if (Date.now() - lastMessageRef.current > STALE_AFTER_MS) {
        setStatus((prev) => (prev === "off" || prev === "unsupported" ? prev : "stale"));
      }
    }, 5_000);

    return () => {
      clearInterval(staleTimer);
      source.close(); // server's `finally` deregisters the symbol from live_watchlist
    };
  }, [securityId, exchangeSegment, resolution, enabled, supported]);

  const marketOpen = useMemo(() => isMarketOpen(session ?? DEFAULT_SESSION), [session, bar, status]);

  return { status, bar, marketOpen };
}
