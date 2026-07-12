"use client";

import { useEffect, useRef, useState } from "react";
import { brokerOrdersWsUrl } from "./api";

export function useBrokerOrdersSocket() {
  const [updates, setUpdates] = useState<unknown[]>([]);
  const socketRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const ws = new WebSocket(brokerOrdersWsUrl());
    socketRef.current = ws;

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
