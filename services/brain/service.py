"""wally-brain: máquina de estados de comportamiento.

Modos: `idle`, `teleop`, `patrol`, `follow_cat`.

**Arbitraje con el mando manual.** Brain y la webapp escriben en el mismo
`wally/cmd/drive`, así que hace falta decidir quién manda. En vez de obligar a
cambiar de modo a mano, cualquier comando ajeno hace que brain calle durante
unos segundos: mueves el joystick y el robot te obedece al instante, y cuando
lo sueltas retoma lo que estaba haciendo. Los comandos se marcan con `src`
para que brain distinga los suyos y no se ceda el paso a sí mismo.

**Por qué publica también cuando decide no moverse.** `wally-motion` frena si
no recibe nada en 500 ms. Publicar ceros explícitos mantiene viva la cadena y
distingue "quieto a propósito" de "se murió el que mandaba".
"""

from __future__ import annotations

import logging
import time
from typing import Any

from common import topics
from common.config import Config
from services.brain.behaviors import Drive, PatrolBehavior, Perception, follow_cat

log = logging.getLogger("brain")

SOURCE = "brain"

MODES = ("idle", "teleop", "patrol", "follow_cat")

# Qué cara pone en cada modo. La cara ya reacciona sola a obstáculos y a la
# gata; esto solo aporta el matiz del modo.
MODE_MOOD = {
    "patrol": "curious",
    "follow_cat": "happy",
}


class BrainService:
    def __init__(self, cfg: Config, bus: Any | None = None) -> None:
        self._cfg = cfg.brain
        self._bus = bus
        self.mode = cfg.brain.start_mode if cfg.brain.start_mode in MODES else "idle"

        self._perception = Perception()
        self._patrol = PatrolBehavior(cfg.brain)
        self._manual_until = 0.0
        self._last_mood: str | None = None
        self._cat_seen_at: float | None = None
        self._announced_cat = False

        if bus is not None:
            bus.subscribe(topics.CMD_MODE, self._on_mode)
            bus.subscribe(topics.STATE_SENSORS, self._on_sensors)
            bus.subscribe(topics.VISION_CAT, self._on_cat)
            bus.subscribe(topics.CMD_DRIVE, self._on_drive)

    # -- entradas --------------------------------------------------------

    def _on_mode(self, payload: dict[str, Any]) -> None:
        mode = str(payload.get("mode", ""))
        if mode in MODES:
            self.set_mode(mode, time.monotonic())
        else:
            log.warning("modo desconocido: %r", mode)

    def _on_sensors(self, payload: dict[str, Any]) -> None:
        def mm(name: str) -> float | None:
            v = payload.get(name)
            return float(v) if isinstance(v, (int, float)) else None

        p = self._perception
        self._perception = Perception(
            front_mm=mm("front"), left_mm=mm("left"), right_mm=mm("right"),
            cat_present=p.cat_present, cat_offset_x=p.cat_offset_x, cat_area=p.cat_area,
        )

    def _on_cat(self, payload: dict[str, Any]) -> None:
        present = bool(payload.get("present", False))
        offset = payload.get("offset_x")
        bbox = payload.get("bbox")
        area = (float(bbox[2]) * float(bbox[3])) if isinstance(bbox, list) and len(bbox) == 4 else None

        p = self._perception
        self._perception = Perception(
            front_mm=p.front_mm, left_mm=p.left_mm, right_mm=p.right_mm,
            cat_present=present,
            cat_offset_x=float(offset) if isinstance(offset, (int, float)) else None,
            cat_area=area,
        )

        if present:
            self._cat_seen_at = time.monotonic()
        else:
            self._announced_cat = False

    def _on_drive(self, payload: dict[str, Any]) -> None:
        """Detecta mando manual y cede el control temporalmente."""
        if payload.get("src") == SOURCE:
            return
        if self.mode in ("idle", "teleop"):
            return
        self._manual_until = time.monotonic() + self._cfg.manual_override_s

    # -- control ---------------------------------------------------------

    def set_mode(self, mode: str, now: float) -> None:
        if mode == self.mode:
            return
        log.info("modo: %s -> %s", self.mode, mode)
        self.mode = mode
        self._patrol.reset()
        self._manual_until = 0.0
        self._announced_cat = False

        if self._bus is not None:
            self._bus.publish(topics.STATE_MODE, {"mode": mode}, retain=True)

    @property
    def manual_override(self) -> bool:
        return time.monotonic() < self._manual_until

    def decide(self, now: float) -> Drive | None:
        """Qué hacer ahora. `None` significa "no publicar nada"."""
        if self.mode in ("idle", "teleop"):
            return None

        # Alguien está conduciendo a mano: no estorbar.
        if now < self._manual_until:
            return None

        p = self._perception

        if self.mode == "follow_cat":
            if p.cat_present:
                return follow_cat(p, self._cfg)
            # Sin gata a la vista: esperar quieto un rato antes de rendirse.
            if (
                self._cat_seen_at is not None
                and now - self._cat_seen_at < self._cfg.cat_patience_s
            ):
                return Drive.stop()
            if self._cfg.patrol_when_no_cat:
                return self._patrol.update(p, now)
            return Drive.stop()

        if self.mode == "patrol":
            # Aunque esté patrullando, ver a la gata manda: es el objetivo.
            if p.cat_present and self._cfg.follow_cat_while_patrolling:
                return follow_cat(p, self._cfg)
            return self._patrol.update(p, now)

        return None

    # -- lazo ------------------------------------------------------------

    def step(self, now: float) -> Drive | None:
        drive = self.decide(now)

        if self._bus is not None and drive is not None:
            payload = drive.as_payload()
            payload["src"] = SOURCE
            self._bus.publish(topics.CMD_DRIVE, payload)

        self._update_expression(now)
        return drive

    def _update_expression(self, now: float) -> None:
        if self._bus is None:
            return

        # Anunciar a la gata una sola vez por avistamiento.
        if self._perception.cat_present and not self._announced_cat:
            self._announced_cat = True
            if self._cfg.announce_cat:
                self._bus.publish(topics.CMD_SAY, {"text": self._cfg.cat_greeting})

        mood = MODE_MOOD.get(self.mode)
        if mood and mood != self._last_mood and not self.manual_override:
            self._last_mood = mood
            self._bus.publish(topics.CMD_MOOD, {"mood": mood, "hold_s": 3.0})

    def snapshot(self) -> dict[str, Any]:
        p = self._perception
        return {
            "mode": self.mode,
            "manual_override": self.manual_override,
            "patrol_phase": self._patrol.phase.value,
            "cat_present": p.cat_present,
            "front_mm": p.front_mm,
        }
