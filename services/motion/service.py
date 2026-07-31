"""Servicio de movimiento: lazo de control, watchdog y puente con MQTT.

Es el único proceso que toca GPIO. Su responsabilidad crítica es que el robot
se detenga solo cuando algo va mal — red caída, pestaña cerrada, `wally-brain`
muerto. Todo lo demás es secundario a eso.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

from common import topics
from common.config import Config
from services.motion.backend import GPIOBackend
from services.motion.motors import DifferentialDrive
from services.motion.rangefinder import RangeArray
from services.motion.servos import ServoController

log = logging.getLogger("motion")

STATE_PUBLISH_HZ = 10.0


@dataclass
class _Shared:
    """Estado que cruza del hilo de red al lazo de control."""

    drive_left: float = 0.0
    drive_right: float = 0.0
    drive_ts: float = 0.0  # 0 = aún no llegó ningún comando
    servo_cmds: dict[str, float] | None = None
    estop_requested: bool | None = None


class MotionService:
    def __init__(self, cfg: Config, backend: GPIOBackend, bus: Any | None = None) -> None:
        self._cfg = cfg
        self._io = backend
        self._bus = bus
        self._lock = threading.Lock()
        self._shared = _Shared()
        self._running = False
        self._watchdog_tripped = True  # arranca frenado, hasta que llegue un comando

        self.drive = DifferentialDrive(backend, cfg.motion)
        self.servos = ServoController(backend, cfg.motion)
        self.ranges = RangeArray(backend, cfg.motion)

        if bus is not None:
            bus.subscribe(topics.CMD_DRIVE, self._on_drive)
            bus.subscribe(topics.CMD_SERVO, self._on_servo)
            bus.subscribe(topics.CMD_ESTOP, self._on_estop)

    # -- handlers MQTT (hilo de red) -------------------------------------

    def _on_drive(self, payload: dict[str, Any]) -> None:
        try:
            left = float(payload["left"])
            right = float(payload["right"])
        except (KeyError, TypeError, ValueError):
            log.warning("cmd/drive inválido: %r", payload)
            return
        with self._lock:
            self._shared.drive_left = left
            self._shared.drive_right = right
            self._shared.drive_ts = time.monotonic()

    def _on_servo(self, payload: dict[str, Any]) -> None:
        cmds: dict[str, float] = {}
        for joint in ("arm_left", "arm_right"):
            if joint in payload:
                try:
                    cmds[joint] = float(payload[joint])
                except (TypeError, ValueError):
                    log.warning("ángulo inválido para %s: %r", joint, payload[joint])
        if cmds:
            with self._lock:
                self._shared.servo_cmds = cmds

    def _on_estop(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self._shared.estop_requested = bool(payload.get("engaged", True))

    # -- lazo de control (hilo principal) --------------------------------

    def step(self, dt: float, now: float) -> None:
        """Un paso del lazo. Separado de `run` para poder probarlo."""
        with self._lock:
            shared = _Shared(**vars(self._shared))
            self._shared.servo_cmds = None
            self._shared.estop_requested = None

        if shared.estop_requested is True:
            self.drive.estop()
        elif shared.estop_requested is False:
            self.drive.clear_estop()

        # Watchdog: sin comando fresco, el robot frena. Ver PLAN.md §6.
        expired = (now - shared.drive_ts) * 1000.0 > self._cfg.motion.watchdog_ms
        stale = shared.drive_ts == 0.0 or expired

        if stale:
            if not self._watchdog_tripped:
                log.warning("watchdog: sin comandos, frenando")
                self._watchdog_tripped = True
            self.drive.stop_target()
        else:
            if self._watchdog_tripped:
                log.info("watchdog liberado, comandos fluyendo")
                self._watchdog_tripped = False
            self.drive.set_target(shared.drive_left, shared.drive_right)

        if shared.servo_cmds:
            for joint, angle in shared.servo_cmds.items():
                self.servos.set(joint, angle)

        self.drive.update(dt)
        self.servos.update()
        self.ranges.update()

    def run(self) -> None:
        self._running = True
        period = 1.0 / self._cfg.motion.control_hz
        publish_period = 1.0 / STATE_PUBLISH_HZ

        log.info(
            "lazo a %d Hz · watchdog %d ms · tope de duty %.0f%%",
            self._cfg.motion.control_hz,
            self._cfg.motion.watchdog_ms,
            self._cfg.motion.duty_cap * 100,
        )

        now = time.monotonic()
        next_tick = now
        next_publish = now
        last = now

        while self._running:
            now = time.monotonic()
            dt = now - last
            last = now

            self.step(dt, now)

            if now >= next_publish:
                self._publish_state()
                next_publish = now + publish_period

            next_tick += period
            sleep_for = next_tick - time.monotonic()
            if sleep_for > 0:
                time.sleep(sleep_for)
            else:
                # Nos atrasamos: resincronizar en vez de acumular deuda y
                # entrar en un bucle sin pausa.
                next_tick = time.monotonic()

    def stop(self) -> None:
        self._running = False

    def _publish_state(self) -> None:
        if self._bus is None:
            return
        cur = self.drive.current
        self._bus.publish(
            topics.STATE_MOTION,
            {
                "left": round(cur.left, 3),
                "right": round(cur.right, 3),
                "watchdog": self._watchdog_tripped,
                "estop": self.drive.estop_engaged,
                "servos": self.servos.angles,
            },
        )
        self._bus.publish(
            topics.STATE_SENSORS,
            {k: (round(v, 1) if v is not None else None) for k, v in self.ranges.distances().items()},
        )

    def shutdown(self) -> None:
        log.info("apagando: motores a cero, servos liberados")
        self.drive.shutdown()
        self.servos.shutdown()
        self._io.close()
