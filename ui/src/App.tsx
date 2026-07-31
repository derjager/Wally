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

const MODES: { id: string; label: string }[] = [
  { id: "teleop", label: "Manual" },
  { id: "patrol", label: "Patrulla" },
  { id: "follow_cat", label: "Seguir gata" },
  { id: "idle", label: "Parado" },
];

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
  const { state, rttMs, setInput, estop, setMode } = useControlSocket();
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

      <div className="hud hud-vision">
        {telemetry.cat.present && (
          <div className="cat-badge">
            🐱 gata a la vista
            {telemetry.cat.score != null && (
              <span className="pill-sub">{Math.round(telemetry.cat.score * 100)}%</span>
            )}
          </div>
        )}
        {telemetry.detections.length > 0 && (
          <ul className="detections">
            {telemetry.detections.slice(0, 5).map((d, i) => (
              <li key={`${d.label}-${i}`} className={d.label === "cat" ? "is-cat" : ""}>
                <span>{d.label}</span>
                <span className="detections-score">{Math.round(d.score * 100)}%</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="hud hud-modes">
        {MODES.map((m) => (
          <button
            key={m.id}
            className={`mode ${telemetry.mode === m.id ? "is-active" : ""}`}
            onClick={() => setMode(m.id)}
            disabled={!connected}
          >
            {m.label}
          </button>
        ))}
      </div>

      <div className="hud hud-tracks">
        <TrackBar label="I" value={motion.left ?? 0} />
        <TrackBar label="D" value={motion.right ?? 0} />
        {telemetry.mode !== "teleop" && telemetry.mode !== "idle" && (
          <p className="autonomy-hint">
            Autónomo · mueve el joystick para tomar el control
          </p>
        )}
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
