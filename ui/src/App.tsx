import { useCallback, useEffect, useState } from "react";
import Joystick from "./Joystick";
import NetworkSetup from "./NetworkSetup";
import { useControlSocket } from "./useControlSocket";
import { useTelemetry } from "./useTelemetry";

const SENSOR_LABELS: Record<string, string> = {
  front: "Frontal",
  left: "Izq",
  right: "Der",
};

function formatDistance(mm: number | null | undefined) {
  if (mm === null || mm === undefined) return "—";
  if (mm >= 1000) return `${(mm / 1000).toFixed(2)} m`;
  return `${Math.round(mm)} mm`;
}

/** Barra de velocidad de una oruga, bipolar (adelante y atrás). */
function TrackBar({ label, value }: { label: string; value: number }) {
  const pct = Math.min(Math.abs(value), 1) * 50;
  return (
    <div className="track">
      <span className="track-label">{label}</span>
      <div className="track-rail">
        <div className="track-zero" />
        <div
          className={`track-fill ${value < 0 ? "is-reverse" : ""}`}
          style={{
            width: `${pct}%`,
            left: value >= 0 ? "50%" : `${50 - pct}%`,
          }}
        />
      </div>
      <span className="track-value">{value >= 0 ? "+" : ""}{value.toFixed(2)}</span>
    </div>
  );
}

export default function App() {
  const { state, rttMs, setInput, estop } = useControlSocket();
  const telemetry = useTelemetry();
  const [videoOk, setVideoOk] = useState(true);
  const [estopOn, setEstopOn] = useState(false);
  const [showSetup, setShowSetup] = useState(false);

  // En modo hotspot el robot está recién sacado de la caja o perdió la wifi:
  // lo único útil que se puede hacer es configurar la red, así que se abre
  // sola esa pantalla.
  useEffect(() => {
    fetch("/api/net/status")
      .then((r) => r.json())
      .then((s) => {
        if (s.mode === "hotspot") setShowSetup(true);
      })
      .catch(() => {});
  }, []);

  const handleJoystick = useCallback(
    (v: { throttle: number; steer: number }) => setInput(v),
    [setInput],
  );

  const toggleEstop = () => {
    const next = !estopOn;
    setEstopOn(next);
    estop(next);
  };

  const connected = state === "open";
  const motion = telemetry.motion;
  const watchdogTripped = motion.watchdog ?? true;

  return (
    <div className="app">
      <div className="video">
        {videoOk ? (
          <img
            src="/stream.mjpeg"
            alt="Cámara de Wally"
            onError={() => setVideoOk(false)}
          />
        ) : (
          <div className="video-fallback">
            <p>Sin vídeo</p>
            <small>¿Está corriendo wally-vision?</small>
            <button onClick={() => setVideoOk(true)}>Reintentar</button>
          </div>
        )}
      </div>

      <header className="hud hud-top">
        <div className={`pill ${connected ? "is-ok" : "is-bad"}`}>
          {connected ? "conectado" : state === "connecting" ? "conectando…" : "sin conexión"}
          {connected && rttMs !== null && <span className="pill-sub">{rttMs} ms</span>}
        </div>

        {motion.estop ? (
          <div className="pill is-bad">PARADA DE EMERGENCIA</div>
        ) : watchdogTripped ? (
          <div className="pill is-warn">frenado · sin comandos</div>
        ) : (
          <div className="pill is-ok">en marcha</div>
        )}

        <div className="sensors">
          {Object.entries(telemetry.sensors).map(([name, mm]) => (
            <div key={name} className={`sensor ${mm !== null && mm < 200 ? "is-close" : ""}`}>
              <span className="sensor-name">{SENSOR_LABELS[name] ?? name}</span>
              <span className="sensor-value">{formatDistance(mm)}</span>
            </div>
          ))}
        </div>

        <button className="pill pill-button" onClick={() => setShowSetup(true)}>
          Red
        </button>
      </header>

      <div className="hud hud-tracks">
        <TrackBar label="I" value={motion.left ?? 0} />
        <TrackBar label="D" value={motion.right ?? 0} />
      </div>

      <div className="hud hud-controls">
        <button
          className={`estop ${estopOn ? "is-engaged" : ""}`}
          onClick={toggleEstop}
        >
          {estopOn ? "LIBERAR" : "PARAR"}
        </button>

        <Joystick onChange={handleJoystick} disabled={!connected || estopOn} />
      </div>

      {showSetup && <NetworkSetup onClose={() => setShowSetup(false)} />}
    </div>
  );
}
