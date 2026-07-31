"""Tracción diferencial sobre TB6612FNG.

La lógica de rampa y tope vive en funciones puras al principio del módulo para
poder probarla sin GPIO ni tiempo real.

Tabla de verdad del TB6612 por canal:

    IN1  IN2   efecto
     1    0    adelante
     0    1    atrás
     1    1    freno corto (short brake)
     0    0    libre (coast)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from common.config import MotorPins, MotionConfig
from services.motion.backend import GPIOBackend

log = logging.getLogger("motion.motors")


# --------------------------------------------------------------------------
# Lógica pura
# --------------------------------------------------------------------------


def clamp(value: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return min(max(value, lo), hi)


def approach(current: float, target: float, max_delta: float) -> float:
    """Mueve `current` hacia `target` sin pasar de `max_delta` en un paso."""
    if max_delta <= 0:
        return current
    delta = target - current
    if abs(delta) <= max_delta:
        return target
    return current + max_delta * (1 if delta > 0 else -1)


def ramp_step(current: float, target: float, dt: float, up_per_s: float, down_per_s: float) -> float:
    """Un paso de rampa asimétrica.

    Frenar usa una tasa mayor que acelerar: subir despacio protege el driver
    del pico de corriente, bajar rápido es lo que hace útil al watchdog.

    "Frenar" es moverse hacia cero, lo que se detecta por el signo de la
    velocidad frente al del cambio pedido — no comparando magnitudes, que
    trata mal el caso de inversión de marcha (`current=1`, `target=-1`, donde
    ambas valen 1 pero el motor claramente está desacelerando).

    Al invertir marcha esto encadena las dos fases solo: frena rápido hasta
    cero y acelera despacio hacia el otro sentido.
    """
    delta = target - current
    braking = current * delta < 0
    rate = down_per_s if braking else up_per_s
    return approach(current, target, rate * dt)


def mix_arcade(throttle: float, steer: float) -> tuple[float, float]:
    """Convierte (avance, giro) de un joystick en velocidades de oruga.

    Se normaliza cuando la suma se sale de rango, para que girar a fondo
    mientras se avanza a fondo no sature una oruga y deforme la trayectoria.
    """
    left = throttle + steer
    right = throttle - steer
    peak = max(abs(left), abs(right))
    if peak > 1.0:
        left /= peak
        right /= peak
    return (left, right)


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------


@dataclass
class MotorState:
    left: float = 0.0
    right: float = 0.0


class DifferentialDrive:
    def __init__(self, backend: GPIOBackend, cfg: MotionConfig) -> None:
        self._io = backend
        self._cfg = cfg
        self._target = MotorState()
        self._current = MotorState()
        self._estop = False

        for pins in (cfg.left, cfg.right):
            self._io.setup_output(pins.in1)
            self._io.setup_output(pins.in2)
        self._io.setup_output(cfg.standby, initial=0)

        self._apply(cfg.left, 0.0)
        self._apply(cfg.right, 0.0)
        self.enable()

    # -- control ---------------------------------------------------------

    def enable(self) -> None:
        """Habilita el driver (STBY alto)."""
        self._io.write(self._cfg.standby, 1)

    def set_target(self, left: float, right: float) -> None:
        if self._estop:
            return
        self._target = MotorState(clamp(left), clamp(right))

    def stop_target(self) -> None:
        """Pide detención. La rampa de bajada lleva la velocidad a cero."""
        self._target = MotorState(0.0, 0.0)

    def estop(self) -> None:
        """Parada de emergencia: corta el driver por hardware, sin rampa.

        STBY a nivel bajo deshabilita ambos canales del TB6612 de inmediato,
        sin depender de que el PWM responda. Es un camino de seguridad
        independiente del lazo de control.
        """
        self._estop = True
        self._target = MotorState(0.0, 0.0)
        self._current = MotorState(0.0, 0.0)
        self._io.write(self._cfg.standby, 0)
        self._apply(self._cfg.left, 0.0)
        self._apply(self._cfg.right, 0.0)
        log.warning("PARADA DE EMERGENCIA activada")

    def clear_estop(self) -> None:
        if not self._estop:
            return
        self._estop = False
        self.enable()
        log.info("parada de emergencia liberada")

    @property
    def estop_engaged(self) -> bool:
        return self._estop

    @property
    def current(self) -> MotorState:
        return self._current

    # -- lazo ------------------------------------------------------------

    def update(self, dt: float) -> None:
        """Avanza la rampa un paso y escribe a los pines. Llamar a control_hz."""
        if self._estop:
            return
        cfg = self._cfg
        self._current = MotorState(
            ramp_step(self._current.left, self._target.left, dt, cfg.ramp_up_per_s, cfg.ramp_down_per_s),
            ramp_step(self._current.right, self._target.right, dt, cfg.ramp_up_per_s, cfg.ramp_down_per_s),
        )
        self._apply(cfg.left, self._current.left)
        self._apply(cfg.right, self._current.right)

    def _apply(self, pins: MotorPins, value: float) -> None:
        """Traduce una velocidad normalizada a los tres pines del canal."""
        if pins.invert:
            value = -value

        # Umbral por debajo del cual el motor no vence su propia fricción y
        # solo zumba.
        if abs(value) < 0.02:
            # Freno corto en lugar de coast: detención predecible y el robot
            # no rueda solo en un desnivel.
            self._io.write(pins.in1, 1)
            self._io.write(pins.in2, 1)
            self._io.pwm(pins.pwm, self._cfg.pwm_hz, 0.0)
            return

        forward = value > 0
        self._io.write(pins.in1, 1 if forward else 0)
        self._io.write(pins.in2, 0 if forward else 1)
        # El tope se aplica aquí, al convertir a duty físico: es una propiedad
        # de la salida, no del comando. Ver PLAN.md §2.
        self._io.pwm(pins.pwm, self._cfg.pwm_hz, abs(value) * self._cfg.duty_cap)

    def shutdown(self) -> None:
        self._target = MotorState(0.0, 0.0)
        self._current = MotorState(0.0, 0.0)
        self._apply(self._cfg.left, 0.0)
        self._apply(self._cfg.right, 0.0)
        self._io.write(self._cfg.standby, 0)
