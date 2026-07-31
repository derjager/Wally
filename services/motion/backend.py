"""Acceso a GPIO, con implementación real y simulada.

`wally-motion` es el único proceso que toca GPIO (PLAN.md §6). Todo pasa por
esta interfaz, de modo que la lógica de control se ejercita en un portátil sin
hardware conectado — que es como se validan el watchdog y las rampas antes de
que exista el robot.
"""

from __future__ import annotations

import logging
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

log = logging.getLogger("motion.gpio")

# Pines con PWM por hardware en la Pi 4. En el resto, pigpio usa PWM temporizado
# por DMA, que sigue siendo estable pero consume más recursos.
HARDWARE_PWM_PINS = frozenset({12, 13, 18, 19})


class GPIOBackend(ABC):
    """Contrato mínimo que necesita el servicio de movimiento."""

    @abstractmethod
    def setup_output(self, pin: int, initial: int = 0) -> None: ...

    @abstractmethod
    def write(self, pin: int, value: int) -> None: ...

    @abstractmethod
    def pwm(self, pin: int, freq_hz: int, duty: float) -> None:
        """Duty normalizado 0.0–1.0."""

    @abstractmethod
    def servo(self, pin: int, pulse_us: int) -> None:
        """Ancho de pulso en µs. 0 desactiva la señal y libera el servo."""

    @abstractmethod
    def watch_echo(self, pin: int) -> None:
        """Prepara un pin ECHO para capturar anchos de pulso."""

    @abstractmethod
    def trigger(self, pin: int, pulse_us: int = 10) -> None: ...

    @abstractmethod
    def echo_reading(self, pin: int) -> tuple[int, float | None]:
        """Devuelve (secuencia, ancho_us). La secuencia permite distinguir una
        medición nueva de la repetición de la anterior."""

    @abstractmethod
    def close(self) -> None: ...


# --------------------------------------------------------------------------
# Implementación real
# --------------------------------------------------------------------------


@dataclass
class _EchoState:
    rise_tick: int | None = None
    width_us: float | None = None
    seq: int = 0


class PigpioBackend(GPIOBackend):
    """Usa pigpio, que temporiza por DMA en lugar de por el planificador del
    kernel. Es lo que evita el jitter en los servos y da precisión de µs al
    medir los ecos de los HC-SR04.

    Requiere `pigpiod` corriendo.
    """

    def __init__(self, host: str = "localhost", port: int = 8888) -> None:
        import pigpio  # import diferido: no existe fuera de la Pi

        self._pigpio = pigpio
        self._pi = pigpio.pi(host, port)
        if not self._pi.connected:
            raise RuntimeError(
                "no se pudo conectar a pigpiod. Arráncalo con: sudo systemctl start pigpiod"
            )
        self._echo: dict[int, _EchoState] = {}
        self._callbacks: list = []
        self._pwm_pins: set[int] = set()

    def setup_output(self, pin: int, initial: int = 0) -> None:
        self._pi.set_mode(pin, self._pigpio.OUTPUT)
        self._pi.write(pin, initial)

    def write(self, pin: int, value: int) -> None:
        self._pi.write(pin, 1 if value else 0)

    def pwm(self, pin: int, freq_hz: int, duty: float) -> None:
        duty = min(max(duty, 0.0), 1.0)
        self._pwm_pins.add(pin)
        if pin in HARDWARE_PWM_PINS:
            self._pi.hardware_PWM(pin, freq_hz, int(duty * 1_000_000))
        else:
            self._pi.set_PWM_frequency(pin, freq_hz)
            self._pi.set_PWM_range(pin, 255)
            self._pi.set_PWM_dutycycle(pin, int(duty * 255))

    def servo(self, pin: int, pulse_us: int) -> None:
        self._pi.set_servo_pulsewidth(pin, pulse_us)

    def watch_echo(self, pin: int) -> None:
        self._pi.set_mode(pin, self._pigpio.INPUT)
        self._pi.set_pull_up_down(pin, self._pigpio.PUD_DOWN)
        self._echo[pin] = _EchoState()
        self._callbacks.append(
            self._pi.callback(pin, self._pigpio.EITHER_EDGE, self._on_echo_edge)
        )

    def trigger(self, pin: int, pulse_us: int = 10) -> None:
        self._pi.gpio_trigger(pin, pulse_us, 1)

    def echo_reading(self, pin: int) -> tuple[int, float | None]:
        st = self._echo.get(pin)
        if st is None:
            return (0, None)
        return (st.seq, st.width_us)

    def _on_echo_edge(self, gpio: int, level: int, tick: int) -> None:
        st = self._echo.get(gpio)
        if st is None:
            return
        if level == 1:
            st.rise_tick = tick
        elif level == 0 and st.rise_tick is not None:
            # tickDiff maneja el desbordamiento del contador de 32 bits.
            st.width_us = float(self._pigpio.tickDiff(st.rise_tick, tick))
            st.rise_tick = None
            st.seq += 1

    def close(self) -> None:
        for cb in self._callbacks:
            cb.cancel()
        self._callbacks.clear()
        for pin in self._pwm_pins:
            if pin in HARDWARE_PWM_PINS:
                self._pi.hardware_PWM(pin, 0, 0)
            else:
                self._pi.set_PWM_dutycycle(pin, 0)
        self._pi.stop()


# --------------------------------------------------------------------------
# Simulación
# --------------------------------------------------------------------------


@dataclass
class SimBackend(GPIOBackend):
    """Backend sin hardware. Registra el último valor escrito en cada pin y
    fabrica lecturas de distancia plausibles.

    Permite ejercitar el servicio completo, watchdog incluido, en un portátil.
    """

    verbose: bool = False
    outputs: dict[int, int] = field(default_factory=dict)
    duties: dict[int, float] = field(default_factory=dict)
    servos: dict[int, int] = field(default_factory=dict)
    _echo_seq: dict[int, int] = field(default_factory=dict)
    _sim_distance_mm: dict[int, float] = field(default_factory=dict)

    def setup_output(self, pin: int, initial: int = 0) -> None:
        self.outputs[pin] = initial

    def write(self, pin: int, value: int) -> None:
        self.outputs[pin] = 1 if value else 0

    def pwm(self, pin: int, freq_hz: int, duty: float) -> None:
        self.duties[pin] = min(max(duty, 0.0), 1.0)
        if self.verbose:
            log.debug("sim pwm gpio%d = %.1f%%", pin, self.duties[pin] * 100)

    def servo(self, pin: int, pulse_us: int) -> None:
        self.servos[pin] = pulse_us

    def watch_echo(self, pin: int) -> None:
        self._echo_seq[pin] = 0
        # Cada sensor arranca "viendo" algo a una distancia distinta.
        self._sim_distance_mm[pin] = random.uniform(300.0, 1500.0)

    def trigger(self, pin: int, pulse_us: int = 10) -> None:
        # El disparo es por TRIG pero la lectura llega por ECHO; en simulación
        # basta con avanzar todos los sensores un paso.
        for echo_pin in self._echo_seq:
            self._echo_seq[echo_pin] += 1
            d = self._sim_distance_mm[echo_pin] + random.uniform(-40.0, 40.0)
            self._sim_distance_mm[echo_pin] = min(max(d, 50.0), 3000.0)

    def echo_reading(self, pin: int) -> tuple[int, float | None]:
        seq = self._echo_seq.get(pin, 0)
        if seq == 0:
            return (0, None)
        # Un 5% de lecturas perdidas, como en la realidad (superficies blandas,
        # ángulos malos). El código de arriba debe tolerarlo.
        if random.random() < 0.05:
            return (seq, None)
        return (seq, self._sim_distance_mm[pin] / 0.1715)

    def close(self) -> None:
        self.duties.clear()
        self.servos.clear()


def create(sim: bool = False, **kwargs) -> GPIOBackend:
    """Crea el backend adecuado. Cae a simulación si pigpio no está disponible."""
    if sim:
        return SimBackend(**kwargs)
    try:
        return PigpioBackend()
    except Exception as exc:
        raise RuntimeError(
            f"backend de GPIO no disponible ({exc}). Usa --sim para correr sin hardware."
        ) from exc
