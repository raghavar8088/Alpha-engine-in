"use client";

import { useEffect, useRef, useState } from "react";
import { brokerOrdersWsUrl } from "./api";

export function useBrokerOrdersSocket() {
  const [updates, setUpdates] = useState<unknown[]>([]);
  const socketRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const url = brokerOrdersWsUrl();
    // See useMarketDataSocket.ts — same insecure ws://-from-https crash guard.
    if (typeof window !== "undefined" && window.location.protocol === "https:" && url.startsWith("ws://")) {
      console.warn("[broker-orders ws] skipped: insecure ws:// from an https page");
      return;
    }

    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch (err) {
      console.warn("[broker-orders ws] failed to open", err);
      return;
    }
    socketRef.current = ws;
    ws.onerror = () => {};

    ws.onmessage = (event) => {
      const payload = JSON.parse(event.data);
      if (payload.type === "order_update") {
        setUpdates((prev) => [payload.data, ...prev].slice(0, 50));
      }
    };

    return () => ws.close();
  }, []);

  return updates;
}
