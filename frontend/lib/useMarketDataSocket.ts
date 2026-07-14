"use client";

import { useEffect, useRef, useState } from "react";
import { MarketDataSnapshot, marketDataWsUrl } from "./api";

export function useMarketDataSocket(initial: MarketDataSnapshot[]) {
  const [rows, setRows] = useState<Record<string, MarketDataSnapshot>>(() =>
    Object.fromEntries(initial.map((row) => [row.symbol, row]))
  );
  const socketRef = useRef<WebSocket | null>(null);

  // The useState initializer above only runs on the first render, when `initial`
  // is still empty (the parent fetches it asynchronously). Without this sync the
  // fetched/polled snapshot never reaches state on any page where the live socket
  // isn't available — e.g. https production behind the same-origin HTTP proxy,
  // which can't carry WebSocket upgrades — leaving the UI stuck on "no data yet".
  // Latest fetch wins per symbol so HTTP polling drives price updates there.
  useEffect(() => {
    if (initial.length === 0) return;
    setRows((prev) => {
      const next = { ...prev };
      for (const row of initial) next[row.symbol] = row;
      return next;
    });
  }, [initial]);

  useEffect(() => {
    const url = marketDataWsUrl();
    // Only open a socket when there is a real ws://|wss:// endpoint. In same-origin
    // proxy mode (NEXT_PUBLIC_API_URL=""), marketDataWsUrl() returns a path like
    // "/ws/market-data" that the browser resolves to wss://<vercel-host>/… — which
    // the HTTP-only proxy can't serve — so skip it and let HTTP polling drive.
    if (!/^wss?:\/\//.test(url)) {
      return;
    }
    // Browsers throw synchronously (uncaught SecurityError) when constructing a
    // ws:// socket from an https:// page — that crash takes the whole page down.
    // The backend has no TLS listener yet, so there's no wss:// to fall back to;
    // skip the live socket rather than crash and let initial/polled data stand.
    if (typeof window !== "undefined" && window.location.protocol === "https:" && url.startsWith("ws://")) {
      console.warn("[market-data ws] skipped: insecure ws:// from an https page");
      return;
    }

    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch (err) {
      console.warn("[market-data ws] failed to open", err);
      return;
    }
    socketRef.current = ws;
    ws.onerror = () => {};

    ws.onmessage = (event) => {
      const payload = JSON.parse(event.data);
      if (payload.type === "snapshot") {
        const snapshot: MarketDataSnapshot[] = payload.data;
        setRows(Object.fromEntries(snapshot.map((row) => [row.symbol, row])));
      } else if (payload.type === "update") {
        const row: MarketDataSnapshot = payload.data;
        setRows((prev) => ({ ...prev, [row.symbol]: row }));
      }
    };

    return () => ws.close();
  }, []);

  return Object.values(rows).sort((a, b) => a.symbol.localeCompare(b.symbol));
}
