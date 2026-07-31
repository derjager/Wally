"""Comportamientos autónomos, como lógica pura.

Separado del servicio para poder probarlo: aquí se decide a qué velocidad va
cada oruga dadas unas distancias y una gata, sin MQTT ni relojes reales.

Dos límites del hardware que condicionan todo lo de aquí (PLAN.md §11):

- **El ultrasonido no ve a la gata.** El pelaje absorbe el sonido en lugar de
  reflejarlo. Por eso `follow_cat` va despacio y frena por tamaño de la caja
  en la imagen, nunca fiándose de los sensores de distancia.
- **Un `None` del sensor significa "sin eco"**, que casi siempre es "nada
  delante" pero también puede ser una superficie blanda —un sofá, una
  cortina— que no rebota. Se trata como libre porque es lo habitual, y la
  protección real es que la velocidad de patrulla es baja.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class Perception:
    """Lo que el robot sabe del mundo en un instante."""

    front_mm: float | None = None
    left_mm: float | None = None
    right_mm: float | None = None
    cat_present: bool = False
    cat_offset_x: float | None = None   # -1 izquierda, +1 derecha
    cat_area: float | None = None       # fracción del encuadre que ocupa

    def blocked(self, threshold_mm: float) -> bool:
        return self.front_mm is not None and self.front_mm < threshold_mm

    def freest_side(self) -> int:
        """+1 gira a la derecha, -1 a la izquierda.

        Sin lecturas fiables devuelve +1: da igual el sentido mientras sea
        consistente, y alternar al azar produce bailes en las esquinas.
        """
        izq = self.left_mm if self.left_mm is not None else float("inf")
        der = self.right_mm if self.right_mm is not None else float("inf")
        if izq == der:
            return 1
        return 1 if der > izq else -1


@dataclass(frozen=True)
class Drive:
    left: float
    right: float

    @staticmethod
    def stop() -> "Drive":
        return Drive(0.0, 0.0)

    @staticmethod
    def forward(speed: float) -> "Drive":
        return Drive(speed, speed)

    @staticmethod
    def backward(speed: float) -> "Drive":
        return Drive(-speed, -speed)

    @staticmethod
    def spin(speed: float, direction: int) -> "Drive":
        """Giro sobre el sitio. `direction` +1 derecha, -1 izquierda."""
        return Drive(speed * direction, -speed * direction)

    def as_payload(self) -> dict:
        return {"left": round(self.left, 3), "right": round(self.right, 3)}


class PatrolPhase(Enum):
    CRUISE = "cruise"
    BACKUP = "backup"
    TURN = "turn"


class PatrolBehavior:
    """Avanza evitando obstáculos.

    Tres fases con temporizadores mínimos. Los temporizadores son la parte que
    de verdad importa: sin ellos, el robot que ve un obstáculo gira un
    instante, lo deja de ver, avanza, lo vuelve a ver, y se queda vibrando
    contra la pared en lugar de rodearla.
    """

    def __init__(self, cfg) -> None:
        self._cfg = cfg
        self.phase = PatrolPhase.CRUISE
        self._until = 0.0
        self._direction = 1

    def reset(self) -> None:
        self.phase = PatrolPhase.CRUISE
        self._until = 0.0

    def update(self, p: Perception, now: float) -> Drive:
        cfg = self._cfg

        if self.phase == PatrolPhase.BACKUP:
            if now < self._until:
                return Drive.backward(cfg.backup_speed)
            self._enter_turn(p, now)

        if self.phase == PatrolPhase.TURN:
            # Acercarse demasiado *mientras* se gira interrumpe el giro. Girar
            # a esta distancia haría que las orugas rocen el obstáculo, y sin
            # esta comprobación el robot seguiría raspando hasta que venciera
            # el turn_timeout, varios segundos después.
            if p.blocked(cfg.backup_mm):
                self._enter_backup(now)
                return Drive.backward(cfg.backup_speed)

            # Se gira durante un tiempo mínimo y, pasado ese margen, hasta que
            # el frente quede despejado de verdad.
            despejado = not p.blocked(cfg.clear_mm)
            if now < self._until or not despejado:
                if now >= self._until + cfg.turn_timeout_s:
                    # Girando demasiado: probablemente encerrado. Retroceder.
                    self._enter_backup(now)
                    return Drive.backward(cfg.backup_speed)
                return Drive.spin(cfg.turn_speed, self._direction)
            self.phase = PatrolPhase.CRUISE

        # CRUISE
        if p.blocked(cfg.backup_mm):
            # Demasiado cerca para girar sin rozar: primero atrás.
            self._enter_backup(now)
            return Drive.backward(cfg.backup_speed)

        if p.blocked(cfg.stop_mm):
            self._enter_turn(p, now)
            return Drive.spin(cfg.turn_speed, self._direction)

        return Drive.forward(cfg.cruise_speed)

    def _enter_backup(self, now: float) -> None:
        self.phase = PatrolPhase.BACKUP
        self._until = now + self._cfg.backup_s

    def _enter_turn(self, p: Perception, now: float) -> None:
        self.phase = PatrolPhase.TURN
        self._until = now + self._cfg.turn_min_s
        # La dirección se fija al entrar en el giro y no se recalcula: si se
        # reevaluase cada ciclo, el robot cambiaría de idea a media maniobra.
        self._direction = p.freest_side()


def follow_cat(p: Perception, cfg) -> Drive:
    """Se orienta hacia la gata y se acerca con cuidado.

    Frena por el **tamaño de la caja en la imagen**, no por los sensores de
    distancia: el ultrasonido no detecta pelaje, así que confiar en él para no
    atropellarla sería exactamente el error que no se puede cometer.
    """
    if not p.cat_present or p.cat_offset_x is None:
        return Drive.stop()

    # Suficientemente cerca: quedarse quieto y mirarla.
    if p.cat_area is not None and p.cat_area >= cfg.follow_stop_area:
        return Drive.stop()

    # Obstáculo real en el camino: la gata no es lo único que hay delante.
    if p.blocked(cfg.stop_mm):
        return Drive.stop()

    offset = max(-1.0, min(1.0, p.cat_offset_x))

    # Muy descentrada: girar sobre el sitio hasta encararla.
    if abs(offset) > cfg.follow_align_tol:
        return Drive.spin(cfg.follow_turn_speed, 1 if offset > 0 else -1)

    # Encarada: avanzar despacio corrigiendo el rumbo.
    correccion = offset * cfg.follow_steer_gain
    izq = cfg.follow_speed + correccion
    der = cfg.follow_speed - correccion
    pico = max(abs(izq), abs(der))
    if pico > 1.0:
        izq /= pico
        der /= pico
    return Drive(izq, der)
