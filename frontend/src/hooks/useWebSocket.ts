import { useEffect, useState, useCallback } from "react";
import { wsClient } from "../lib/websocket";

export function useWebSocket<T = Record<string, unknown>>(eventType: string) {
  const [data, setData] = useState<T | null>(null);
  const [messages, setMessages] = useState<T[]>([]);

  useEffect(() => {
    const unsubscribe = wsClient.on(eventType, (msg) => {
      setData(msg as T);
      setMessages((prev) => [msg as T, ...prev].slice(0, 100));
    });
    return unsubscribe;
  }, [eventType]);

  const clear = useCallback(() => {
    setData(null);
    setMessages([]);
  }, []);

  return { data, messages, clear };
}
