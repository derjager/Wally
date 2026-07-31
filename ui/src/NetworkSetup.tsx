import { useCallback, useEffect, useState } from "react";

interface Network {
  ssid: string;
  signal: number;
  security: string;
}

interface NetStatus {
  mode: string;
  ssid: string | null;
  ip: string | null;
  online: boolean;
  busy: string;
  error: string | null;
  ap_ssid?: string;
}

function bars(signal: number) {
  if (signal >= 70) return "▮▮▮▮";
  if (signal >= 50) return "▮▮▮▯";
  if (signal >= 30) return "▮▮▯▯";
  return "▮▯▯▯";
}

export default function NetworkSetup({ onClose }: { onClose: () => void }) {
  const [status, setStatus] = useState<NetStatus | null>(null);
  const [networks, setNetworks] = useState<Network[]>([]);
  const [selected, setSelected] = useState<Network | null>(null);
  const [password, setPassword] = useState("");
  const [scanning, setScanning] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [s, n] = await Promise.all([
        fetch("/api/net/status").then((r) => r.json()),
        fetch("/api/net/networks").then((r) => r.json()),
      ]);
      setStatus(s);
      setNetworks(n.networks ?? []);
      if (s.busy === "") setScanning(false);
    } catch {
      /* al cambiar de red la petición falla; el sondeo lo reintenta */
    }
  }, []);

  // Sondeo continuo: durante un cambio de red el robot se vuelve
  // inalcanzable un rato, y esta es la forma de detectar que volvió.
  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 2000);
    return () => clearInterval(id);
  }, [refresh]);

  const scan = async () => {
    setScanning(true);
    await fetch("/api/net/scan", { method: "POST" });
  };

  const connect = async () => {
    if (!selected) return;
    setSubmitted(true);
    await fetch("/api/net/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ssid: selected.ssid, password }),
    });
    setPassword("");
  };

  const isHotspot = status?.mode === "hotspot";
  const busy = status?.busy ?? "";

  return (
    <div className="setup">
      <div className="setup-panel">
        <header className="setup-head">
          <h1>Red</h1>
          <button className="ghost" onClick={onClose}>
            Cerrar
          </button>
        </header>

        <div className={`setup-status ${status?.online ? "is-ok" : isHotspot ? "is-warn" : ""}`}>
          {status === null && <span>Consultando…</span>}
          {status?.online && (
            <span>
              Conectado a <strong>{status.ssid}</strong> · {status.ip}
            </span>
          )}
          {isHotspot && (
            <span>
              Modo configuración · red <strong>{status?.ap_ssid ?? "Wally-Setup"}</strong>
            </span>
          )}
          {status && !status.online && !isHotspot && <span>Sin conexión</span>}
        </div>

        {status?.error && <div className="setup-error">{status.error}</div>}

        {busy.startsWith("connect") && (
          <div className="setup-note">
            Conectando… El robot cambiará de red, así que esta página puede
            quedarse sin respuesta. Si estás en <strong>{status?.ap_ssid}</strong>,
            vuelve a tu wifi de casa y entra en <code>http://wally.local:8080</code>.
          </div>
        )}

        {submitted && !busy && !status?.error && !status?.online && (
          <div className="setup-note">
            Si el robot se conectó, ya no es alcanzable desde esta red. Cambia a
            tu wifi y abre <code>http://wally.local:8080</code>.
          </div>
        )}

        <div className="setup-actions">
          <button onClick={scan} disabled={scanning || busy !== ""}>
            {scanning || busy === "scan" ? "Buscando…" : "Buscar redes"}
          </button>
          {!isHotspot && (
            <button className="ghost" onClick={() => fetch("/api/net/hotspot", { method: "POST" })}>
              Modo configuración
            </button>
          )}
        </div>

        <ul className="netlist">
          {networks.length === 0 && (
            <li className="netlist-empty">
              No hay redes todavía. Pulsa «Buscar redes».
            </li>
          )}
          {networks.map((n) => (
            <li key={n.ssid}>
              <button
                className={`netitem ${selected?.ssid === n.ssid ? "is-selected" : ""}`}
                onClick={() => {
                  setSelected(n);
                  setSubmitted(false);
                }}
              >
                <span className="netitem-ssid">{n.ssid}</span>
                <span className="netitem-meta">
                  {n.security && n.security !== "--" ? "🔒" : ""} {bars(n.signal)}
                </span>
              </button>
            </li>
          ))}
        </ul>

        {selected && (
          <form
            className="setup-form"
            onSubmit={(e) => {
              e.preventDefault();
              connect();
            }}
          >
            <label>
              Contraseña de <strong>{selected.ssid}</strong>
              <input
                type="password"
                value={password}
                autoComplete="off"
                placeholder={selected.security && selected.security !== "--" ? "" : "red abierta"}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
            <button type="submit" disabled={busy !== ""}>
              Conectar
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
