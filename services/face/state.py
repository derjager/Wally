"""Estado de ánimo de la cara, sin dependencia de pygame.

Separado del render para poder probarlo: aquí vive la parte con reglas y
temporizadores, que es donde de verdad se puede meter un error.

La idea central es que la cara **reacciona sola** a lo que le pasa al robot.
Si solo obedeciera a `cmd/mood`, alguien tendría que acordarse de mandar el
gesto adecuado en cada situación, y el robot parecería apagado la mayor parte
del tiempo.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from services.face import expressions as ex
from services.face.expressions import Expression

# Prioridad de las reglas automáticas. Un valor más alto gana.
PRIORITY = {
    "estop": 100,
    "commanded": 80,
    "obstacle": 60,
    "driving": 40,
    "idle_timeout": 20,
    "default": 0,
}

# Distancia a la que un obstáculo pasa a preocupar.
OBSTACLE_MM = 250.0

TRANSITION_S = 0.45


@dataclass
class Inputs:
    """Lo que la cara sabe del resto del robot."""

    estop: bool = False
    moving: bool = False
    closest_mm: float | None = None
    speaking: bool = False


class FaceState:
    def __init__(self, cfg, rng: random.Random | None = None) -> None:
        self._cfg = cfg
        self._rng = rng or random.Random()

        self.mood = ex.DEFAULT_MOOD
        self._from = ex.get(ex.DEFAULT_MOOD)
        self._to = ex.get(ex.DEFAULT_MOOD)
        self._transition = 1.0

        self._commanded: str | None = None
        self._commanded_until = 0.0

        self._inputs = Inputs()
        # None hasta la primera actualización. No vale inicializarlo a 0.0:
        # `time.monotonic()` ya lleva rato corriendo cuando arranca el
        # proceso, así que la resta superaría el umbral de golpe y la cara
        # aparecería dormida nada más encender el robot.
        self._last_activity: float | None = None

        self._next_blink = 0.0
        self._blink_t: float | None = None
        self._speech_phase = 0.0

        self.look_x = 0.0
        self.look_y = 0.0
        self._next_glance = 0.0

    # -- entradas --------------------------------------------------------

    def command_mood(self, mood: str, hold_s: float, now: float) -> None:
        """Fija un ánimo explícito durante un rato."""
        if mood not in ex.EXPRESSIONS:
            return
        self._commanded = mood
        self._commanded_until = now + max(0.5, hold_s)
        self._last_activity = now

    def set_inputs(self, inputs: Inputs, now: float) -> None:
        if self._last_activity is None or inputs.moving or inputs.speaking or inputs.estop:
            self._last_activity = now
        self._inputs = inputs

    def look_at(self, x: float, y: float) -> None:
        self.look_x = max(-1.0, min(1.0, x))
        self.look_y = max(-1.0, min(1.0, y))

    # -- reglas ----------------------------------------------------------

    def resolve_mood(self, now: float) -> str:
        """Decide el ánimo actual según las reglas, por prioridad."""
        if self._inputs.estop:
            return "grumpy"

        if self._commanded and now < self._commanded_until:
            return self._commanded

        closest = self._inputs.closest_mm
        if closest is not None and closest < OBSTACLE_MM:
            return "alert"

        if self._inputs.moving:
            return "teleop"

        if self._last_activity is not None and now - self._last_activity > self._cfg.sleepy_after_s:
            return "sleepy"

        return "idle"

    # -- lazo ------------------------------------------------------------

    def update(self, dt: float, now: float) -> Expression:
        target = self.resolve_mood(now)

        if target != self.mood:
            # Se arranca la transición desde la expresión que se ve ahora, no
            # desde la de destino anterior: si el ánimo cambia dos veces
            # seguidas, el gesto no da un salto a mitad de camino.
            self._from = self._current_blend()
            self._to = ex.get(target)
            self._transition = 0.0
            self.mood = target

        if self._transition < 1.0:
            self._transition = min(1.0, self._transition + dt / TRANSITION_S)

        expr = self._current_blend()
        expr = self._apply_blink(expr, dt, now)

        if self._inputs.speaking:
            self._speech_phase = (self._speech_phase + dt * 4.5) % 1.0
        expr = ex.with_speech(expr, self._speech_phase, self._inputs.speaking)

        self._wander_gaze(now)
        return expr

    def _current_blend(self) -> Expression:
        return ex.blend(self._from, self._to, self._transition)

    def _apply_blink(self, expr: Expression, dt: float, now: float) -> Expression:
        if self.mood == "sleepy":
            # Ya tiene los párpados caídos; parpadear encima se ve raro.
            return expr

        if self._next_blink == 0.0:
            self._schedule_blink(now)

        if self._blink_t is not None:
            self._blink_t += dt / 0.16
            if self._blink_t >= 1.0:
                self._blink_t = None
                self._schedule_blink(now)
            else:
                return ex.with_blink(expr, ex.blink_curve(self._blink_t))
        elif now >= self._next_blink:
            self._blink_t = 0.0

        return expr

    def _schedule_blink(self, now: float) -> None:
        jitter = self._rng.uniform(0.0, self._cfg.blink_jitter_s)
        self._next_blink = now + self._cfg.blink_every_s + jitter

    def _wander_gaze(self, now: float) -> None:
        """Micro-desplazamientos de la mirada.

        Unos ojos perfectamente quietos parecen los de un muñeco. Estas
        sacadas ocasionales bastan para que la cara parezca atenta.
        """
        if self.mood in ("sleepy", "teleop"):
            self.look_x = self.look_y = 0.0
            return
        if now >= self._next_glance:
            self.look_x = self._rng.uniform(-0.6, 0.6)
            self.look_y = self._rng.uniform(-0.4, 0.4)
            self._next_glance = now + self._rng.uniform(1.5, 4.0)
