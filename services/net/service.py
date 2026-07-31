"""wally-net: máquina de estados de red.

Flujo de arranque (PLAN.md §9):

    ¿hay perfiles wifi guardados?
      sí → esperar a que NetworkManager conecte (boot_timeout_s)
           conectó  → MODO CLIENTE, accesible en http://wally.local:8080
           no       → MODO HOTSPOT
      no → MODO HOTSPOT directamente

En modo hotspot el robot publica la red `Wally-Setup`; te conectas, entras a
http://192.168.4.1:8080 y eliges la wifi de casa desde la propia webapp.

Si estando en modo cliente se pierde la red durante `fallback_after_s`, vuelve
al hotspot para poder reconfigurarlo. Ese plazo es generoso a propósito: un
router reiniciándose no debe dejarte sin control del robot.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import asdict
from typing import Any

from common import topics
from common.config import Config
from services.net.nmcli import NetBackend, NetStatus

log = logging.getLogger("net")


class NetService:
    def __init__(self, cfg: Config, backend: NetBackend, bus: Any | None = None) -> None:
        self._cfg = cfg.net
        self._nm = backend
        self._bus = bus
        self._actions: queue.Queue[tuple[str, dict]] = queue.Queue()
        self._running = False
        self._status = NetStatus(mode="disconnected")
        self._networks: list[dict] = []
        self._offline_since: float | None = None
        self._busy = ""
        self._last_error: str | None = None

        if bus is not None:
            bus.subscribe(topics.CMD_NET_SCAN, lambda p: self._enqueue("scan", p))
            bus.subscribe(topics.CMD_NET_CONNECT, lambda p: self._enqueue("connect", p))
            bus.subscribe(topics.CMD_NET_HOTSPOT, lambda p: self._enqueue("hotspot", p))
            bus.subscribe(topics.CMD_NET_FORGET, lambda p: self._enqueue("forget", p))
            # Los mensajes retenidos viven en el broker: si mosquitto se
            # reinicia se pierden, y la webapp se quedaría sin saber en qué
            # modo está la red.
            bus.on_connected(self._publish)

    def _enqueue(self, action: str, payload: dict) -> None:
        self._actions.put((action, payload))

    # -- arranque --------------------------------------------------------

    def bootstrap(self, now: float | None = None) -> str:
        """Decide el modo inicial. Devuelve 'client' o 'hotspot'."""
        known = self._nm.known_ssids()
        if not known:
            log.info("sin redes guardadas, arrancando en modo configuración")
            self._start_hotspot()
            return "hotspot"

        log.info("redes guardadas: %s. Esperando conexión…", ", ".join(known))
        deadline = (now or time.monotonic()) + self._cfg.boot_timeout_s
        while time.monotonic() < deadline:
            st = self._nm.status()
            if st.online:
                self._set_status(st)
                log.info("conectado a %s con IP %s", st.ssid, st.ip)
                return "client"
            time.sleep(1.0)

        log.warning(
            "no se conectó en %.0fs, levantando el hotspot para reconfigurar",
            self._cfg.boot_timeout_s,
        )
        self._start_hotspot()
        return "hotspot"

    # -- acciones --------------------------------------------------------

    def _start_hotspot(self, keep_error: bool = False) -> None:
        """Levanta el AP de configuración.

        `keep_error` conserva el mensaje de un fallo anterior. Al volver aquí
        tras una contraseña incorrecta, el motivo es lo único que explica por
        qué el robot no se conectó; borrarlo dejaría al usuario reintentando
        a ciegas.
        """
        self._busy = "hotspot"
        self._publish()
        ok, msg = self._nm.start_hotspot(self._cfg.ap_ssid, self._cfg.ap_password)
        self._busy = ""
        if ok:
            log.info("%s", msg)
            if not keep_error:
                self._last_error = None
        else:
            log.error("no se pudo levantar el hotspot: %s", msg)
            self._last_error = msg
        self._offline_since = None
        self._set_status(self._nm.status())

    def _do_scan(self) -> None:
        self._busy = "scan"
        self._publish()
        nets = self._nm.scan()
        self._networks = [asdict(n) for n in nets]
        self._busy = ""
        log.info("escaneo: %d redes", len(nets))
        self._publish()

    def _do_connect(self, payload: dict) -> None:
        ssid = str(payload.get("ssid", "")).strip()
        if not ssid:
            log.warning("cmd/net/connect sin ssid")
            return
        password = payload.get("password")

        self._busy = f"connect:{ssid}"
        self._last_error = None
        self._publish()

        log.info("conectando a %s…", ssid)
        ok, msg = self._nm.connect(ssid, password if password else None)
        self._busy = ""

        if ok:
            log.info("%s", msg)
            self._offline_since = None
        else:
            log.error("fallo al conectar con %s: %s", ssid, msg)
            self._last_error = msg
            # Sin red y sin AP el robot queda inalcanzable: hay que volver al
            # modo configuración para poder reintentar, conservando el motivo
            # del fallo para poder mostrarlo.
            self._start_hotspot(keep_error=True)
            return

        self._set_status(self._nm.status())

    def _do_forget(self, payload: dict) -> None:
        ssid = str(payload.get("ssid", "")).strip()
        if ssid and self._nm.forget(ssid):
            log.info("perfil de %s eliminado", ssid)
        self._publish()

    # -- lazo ------------------------------------------------------------

    def step(self, now: float) -> None:
        """Un ciclo: procesa acciones pendientes y vigila la conectividad."""
        while True:
            try:
                action, payload = self._actions.get_nowait()
            except queue.Empty:
                break
            if action == "scan":
                self._do_scan()
            elif action == "connect":
                self._do_connect(payload)
            elif action == "hotspot":
                self._start_hotspot()
            elif action == "forget":
                self._do_forget(payload)

        st = self._nm.status()
        self._set_status(st)

        if st.mode == "hotspot":
            self._offline_since = None
            return

        if st.online:
            if self._offline_since is not None:
                log.info("conexión recuperada")
            self._offline_since = None
            return

        # Sin conexión y sin hotspot.
        if self._offline_since is None:
            self._offline_since = now
            log.warning("conexión perdida, esperando a que NetworkManager reconecte")
            return

        if self._cfg.fallback_after_s <= 0:
            return

        if now - self._offline_since >= self._cfg.fallback_after_s:
            log.warning(
                "sin red desde hace %.0fs, volviendo al modo configuración",
                now - self._offline_since,
            )
            self._start_hotspot()

    def run(self) -> None:
        self._running = True
        self.bootstrap()
        self._do_scan()

        while self._running:
            self.step(time.monotonic())
            time.sleep(self._cfg.poll_s)

    def stop(self) -> None:
        self._running = False

    # -- estado ----------------------------------------------------------

    def _set_status(self, st: NetStatus) -> None:
        changed = st != self._status
        self._status = st
        if changed:
            self._publish()

    def snapshot(self) -> dict[str, Any]:
        return {
            "mode": self._status.mode,
            "ssid": self._status.ssid,
            "ip": self._status.ip,
            "online": self._status.online,
            "busy": self._busy,
            "error": self._last_error,
            "ap_ssid": self._cfg.ap_ssid,
        }

    def _publish(self) -> None:
        if self._bus is None:
            return
        # Retenido: la webapp recibe el estado al suscribirse, sin esperar al
        # siguiente ciclo de sondeo.
        self._bus.publish(topics.NET_STATUS, self.snapshot(), retain=True)
        self._bus.publish(topics.NET_NETWORKS, {"networks": self._networks}, retain=True)
