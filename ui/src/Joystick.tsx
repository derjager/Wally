import { useCallback, useEffect, useRef, useState } from "react";

interface Props {
  onChange: (v: { throttle: number; steer: number }) => void;
  disabled?: boolean;
}

/**
 * Joystick analógico para pulgar.
 *
 * Vuelve al centro al soltar, y también si el puntero se cancela (una llamada
 * entrante, el gesto de cambiar de app). Sin eso, un dedo que sale de la
 * pantalla dejaría el último valor congelado y el robot en marcha hasta que
 * saltara el watchdog.
 */
export default function Joystick({ onChange, disabled }: Props) {
  const baseRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ x: 0, y: 0 });
  const [active, setActive] = useState(false);
  const pointerId = useRef<number | null>(null);

  const release = useCallback(() => {
    pointerId.current = null;
    setActive(false);
    setPos({ x: 0, y: 0 });
    onChange({ throttle: 0, steer: 0 });
  }, [onChange]);

  const track = useCallback(
    (clientX: number, clientY: number) => {
      const base = baseRef.current;
      if (!base) return;
      const r = base.getBoundingClientRect();
      const radius = r.width / 2;
      let dx = clientX - (r.left + radius);
      let dy = clientY - (r.top + radius);

      const dist = Math.hypot(dx, dy);
      if (dist > radius) {
        dx = (dx / dist) * radius;
        dy = (dy / dist) * radius;
      }
      setPos({ x: dx, y: dy });
      // Y invertida: arriba en la pantalla es avanzar.
      onChange({ throttle: -dy / radius, steer: dx / radius });
    },
    [onChange],
  );

  const onPointerDown = (e: React.PointerEvent) => {
    if (disabled) return;
    pointerId.current = e.pointerId;
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    setActive(true);
    track(e.clientX, e.clientY);
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (pointerId.current !== e.pointerId) return;
    track(e.clientX, e.clientY);
  };

  const onPointerUp = (e: React.PointerEvent) => {
    if (pointerId.current !== e.pointerId) return;
    release();
  };

  // Si la pestaña pasa a segundo plano, soltar. El navegador deja de entregar
  // eventos de puntero y el joystick quedaría clavado en su última posición.
  useEffect(() => {
    const onHide = () => {
      if (document.hidden) release();
    };
    document.addEventListener("visibilitychange", onHide);
    window.addEventListener("blur", release);
    return () => {
      document.removeEventListener("visibilitychange", onHide);
      window.removeEventListener("blur", release);
    };
  }, [release]);

  return (
    <div
      ref={baseRef}
      className={`joystick ${active ? "is-active" : ""} ${disabled ? "is-disabled" : ""}`}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
    >
      <div className="joystick-cross" />
      <div
        className="joystick-nub"
        style={{ transform: `translate(${pos.x}px, ${pos.y}px)` }}
      />
    </div>
  );
}
