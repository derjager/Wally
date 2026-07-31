import { useEffect, useState } from "react";

export interface Telemetry {
  motion: {
    left?: number;
    right?: number;
    watchdog?: boolean;
    estop?: boolean;
    servos?: Record<string, number>;
  };
  sensors: Record<string, number | null>;
  age_s: number | null;
}

const EMPTY: Telemetry = { motion: {}, sensors: {}, age_s: null };

/** Panel de estado del robot. Solo lectura, sin efecto sobre el control. */
export function useTelemetry(): Telemetry {
  const [data, setData] = useState<Telemetry>(EMPTY);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let retry: number | undefined;
    let stopped = false;

    const connect = () => {
      const proto = location.protocol === "https:" ? "wss:" : "ws:";
      ws = new WebSocket(`${proto}//${location.host}/ws/telemetry`);
      ws.onmessage = (ev) => {
        try {
          setData(JSON.parse(ev.data));
        } catch {
          /* un frame corrupto no debe tumbar el panel */
        }
      };
      ws.onclose = () => {
        setData(EMPTY);
        if (!stopped) retry = window.setTimeout(connect, 1500);
      };
      ws.onerror = () => ws?.close();
    };

    connect();
    return () => {
      stopped = true;
      if (retry) window.clearTimeout(retry);
      ws?.close();
    };
  }, []);

  return data;
}
