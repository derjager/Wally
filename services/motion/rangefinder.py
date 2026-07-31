"""Sensores de distancia HC-SR04.

Interfaz deliberadamente estrecha: `RangeArray.distances()` devuelve mm por
nombre de sensor. Migrar a VL53L1X (PLAN.md §10) implica reescribir solo este
módulo.

Dos cosas que el resto del sistema debe saber:

- Los sensores se disparan **de a uno, en round-robin**. Dispararlos a la vez
  produce crosstalk: el eco de uno lo lee otro y ambos mienten.
- El ultrasonido **no detecta a la gata**: el pelaje absorbe el sonido en vez
  de reflejarlo. Su detección viene solo de la cámara (PLAN.md §11).
"""

from __future__ import annotations

import logging
import time

from common.config import MotionConfig, RangeSensorPins

log = logging.getLogger("motion.range")

# Velocidad del sonido a 20 °C: 343 m/s = 0.343 mm/µs. El pulso viaja ida y
# vuelta, de ahí la mitad.
MM_PER_US = 0.343 / 2

# Rango útil del HC-SR04. Fuera de él la lectura no es fiable.
MIN_VALID_MM = 20.0
MAX_VALID_MM = 4000.0


class RangeArray:
    def __init__(self, backend, cfg: MotionConfig) -> None:
        self._io = backend
        self._cfg = cfg
        self._sensors: tuple[RangeSensorPins, ...] = cfg.rangefinders
        self._index = 0
        self._next_fire = 0.0
        self._last_seq: dict[str, int] = {}
        self._distances: dict[str, float | None] = {}

        for s in self._sensors:
            self._io.setup_output(s.trig)
            self._io.watch_echo(s.echo)
            self._last_seq[s.name] = 0
            self._distances[s.name] = None

        # El periodo configurado es el total del array; cada sensor se dispara
        # a range_poll_hz / n.
        self._period = 1.0 / cfg.range_poll_hz if cfg.range_poll_hz > 0 else 0.0

    def update(self) -> None:
        """Recoge el eco pendiente y dispara el siguiente sensor. No bloquea."""
        if not self._sensors or self._period <= 0:
            return

        now = time.monotonic()
        if now < self._next_fire:
            return

        # Antes de disparar el siguiente, leer lo que dejó el anterior.
        self._collect(self._sensors[self._index])

        self._index = (self._index + 1) % len(self._sensors)
        sensor = self._sensors[self._index]
        self._io.trigger(sensor.trig)
        self._next_fire = now + self._period

    def _collect(self, sensor: RangeSensorPins) -> None:
        seq, width_us = self._io.echo_reading(sensor.echo)

        if seq == self._last_seq[sensor.name]:
            # Sin medición nueva: el eco no volvió dentro del plazo. Es un
            # resultado legítimo (nada delante, o superficie absorbente).
            self._distances[sensor.name] = None
            return

        self._last_seq[sensor.name] = seq

        if width_us is None or width_us > self._cfg.range_timeout_us:
            self._distances[sensor.name] = None
            return

        mm = width_us * MM_PER_US
        self._distances[sensor.name] = mm if MIN_VALID_MM <= mm <= MAX_VALID_MM else None

    def distances(self) -> dict[str, float | None]:
        """Última distancia en mm por sensor. `None` = sin lectura fiable."""
        return dict(self._distances)

    def closest(self) -> float | None:
        """Distancia al obstáculo más próximo, o None si no hay lecturas."""
        valid = [d for d in self._distances.values() if d is not None]
        return min(valid) if valid else None
