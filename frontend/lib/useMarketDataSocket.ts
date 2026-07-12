"use client";

import { useEffect, useRef, useState } from "react";
import { MarketDataSnapshot, marketDataWsUrl } from "./api";

export function useMarketDataSocket(initial: MarketDataSnapshot[]) {
  const [rows, setRows] = useState<Record<string, MarketDataSnapshot>>(() =>
    Object.fromEntries(initial.map((row) => [row.symbol, row]))
  );
  const socketRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const ws = new WebSocket(marketDataWsUrl());
    socketRef.current = ws;

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
