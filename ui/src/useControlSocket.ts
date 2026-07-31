import { useCallback, useEffect, useRef, useState } from "react";

export type ConnState = "connecting" | "open" | "closed";

export interface DriveInput {
  throttle: number;
  steer: number;
}

const SEND_HZ = 20;
const RECONNECT_MS = 1000;

/**
 * Canal de control con el robot.
 *
 * Envía el estado del joystick continuamente mientras el socket esté abierto,
 * incluso en reposo. Eso es deliberado: `wally-motion` frena si no recibe un
 * comando en 500 ms, así que este flujo constante es lo que le dice "sigo
 * aquí". Al cerrarse la pestaña el socket muere, el flujo cesa y el robot se
 * detiene solo — esa es la cadena de seguridad, no un extra.
 */
export function useControlSocket() {
  const [state, setState] = useState<ConnState>("connecting");
  const [rttMs, setRttMs] = useState<number | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const inputRef = useRef<DriveInput>({ throttle: 0, steer: 0 });
  const closedByUs = useRef(false);

  const setInput = useCallback((next: DriveInput) => {
    inputRef.current = next;
  }, []);

  const sendRaw = useCallback((msg: unknown) => {
    const ws = socketRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(msg));
    }
  }, []);

  const estop = useCallback(
    (engaged: boolean) => sendRaw({ type: "estop", engaged }),
    [sendRaw],
  );

  const setArm = useCallback(
    (joint: "arm_left" | "arm_right", angle: number) =>
      sendRaw({ type: "servo", [joint]: angle }),
    [sendRaw],
  );

  const setMode = useCallback(
    (mode: string) => sendRaw({ type: "mode", mode }),
    [sendRaw],
  );

  useEffect(() => {
    let timer: number | undefined;
    let ticker: number | undefined;

    const connect = () => {
      const proto = location.protocol === "https:" ? "wss:" : "ws:";
      const ws = new WebSocket(`${proto}//${location.host}/ws/control`);
      socketRef.current = ws;
      setState("connecting");

      ws.onopen = () => {
        setState("open");
        let lastSent = performance.now();
        ticker = window.setInterval(() => {
          const now = performance.now();
          setRttMs(Math.round(now - lastSent));
          lastSent = now;
          const { throttle, steer } = inputRef.current;
          ws.send(JSON.stringify({ throttle, steer }));
        }, 1000 / SEND_HZ);
      };

      ws.onclose = () => {
        setState("closed");
        if (ticker) window.clearInterval(ticker);
        if (!closedByUs.current) {
          timer = window.setTimeout(connect, RECONNECT_MS);
        }
      };

      ws.onerror = () => ws.close();
    };

    connect();

    return () => {
      closedByUs.current = true;
      if (timer) window.clearTimeout(timer);
      if (ticker) window.clearInterval(ticker);
      socketRef.current?.close();
    };
  }, []);

  return { state, rttMs, setInput, estop, setArm, setMode };
}
