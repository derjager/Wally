"""Servos de los brazos.

Alimentados del riel de potencia a 4.8V (PLAN.md §4.1), no de la Pi: su pico
de arranque provocaría un brownout.
"""

from __future__ import annotations

import logging
import time

from common.config import MotionConfig

log = logging.getLogger("motion.servos")

ANGLE_MIN = 0.0
ANGLE_MAX = 180.0


def angle_to_pulse_us(angle: float, min_us: int, max_us: int) -> int:
    """Mapea 0–180° al ancho de pulso configurado."""
    a = min(max(angle, ANGLE_MIN), ANGLE_MAX)
    span = max_us - min_us
    return int(min_us + span * (a / ANGLE_MAX))


class ServoController:
    def __init__(self, backend, cfg: MotionConfig) -> None:
        self._io = backend
        self._cfg = cfg
        self._pins = {"arm_left": cfg.servo_left, "arm_right": cfg.servo_right}
        self._angles: dict[str, float] = {}
        self._last_move = 0.0
        self._holding = False

    def set(self, joint: str, angle: float) -> None:
        pin = self._pins.get(joint)
        if pin is None:
            log.warning("articulación desconocida: %s", joint)
            return
        pulse = angle_to_pulse_us(angle, self._cfg.servo_min_us, self._cfg.servo_max_us)
        self._io.servo(pin, pulse)
        self._angles[joint] = angle
        self._last_move = time.monotonic()
        self._holding = True

    def update(self) -> None:
        """Corta el pulso tras un rato quieto.

        Un servo con señal activa consume corriente y zumba permanentemente
        sosteniendo la posición. Los brazos no cargan peso, así que soltarlos
        ahorra batería y ruido; mantienen la posición por fricción.
        """
        if not self._holding:
            return
        if time.monotonic() - self._last_move < self._cfg.servo_idle_timeout_s:
            return
        for pin in self._pins.values():
            self._io.servo(pin, 0)
        self._holding = False

    @property
    def angles(self) -> dict[str, float]:
        return dict(self._angles)

    def shutdown(self) -> None:
        for pin in self._pins.values():
            self._io.servo(pin, 0)
        self._holding = False
