"""Traducción de la entrada del joystick a comandos de tracción.

La propiedad de seguridad importante de este módulo es lo que **no** hace:
nunca reenvía el último comando por su cuenta. Si el navegador deja de hablar
—pestaña cerrada, wifi caído, móvil bloqueado— aquí se deja de publicar y el
watchdog de `wally-motion` frena el robot 500 ms después. Un "mantener último
valor" bienintencionado aquí rompería esa cadena entera.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from services.motion.motors import clamp, mix_arcade

log = logging.getLogger("web.control")


# Marca de origen. `wally-brain` la usa para distinguir sus propios comandos
# de los de un humano: al ver uno ajeno, se aparta unos segundos para que el
# joystick tenga prioridad sin necesidad de cambiar de modo a mano.
SOURCE = "web"


@dataclass(frozen=True)
class DriveCommand:
    left: float
    right: float

    def as_payload(self) -> dict[str, float | str]:
        return {"left": round(self.left, 4), "right": round(self.right, 4), "src": SOURCE}


def parse_joystick(msg: dict) -> DriveCommand | None:
    """Convierte un mensaje del navegador en velocidades de oruga.

    Acepta dos formatos: `{throttle, steer}` desde el joystick, o `{left,
    right}` para control directo desde herramientas. Devuelve None si el
    mensaje no es interpretable, y en ese caso quien llama no debe publicar
    nada — un mensaje corrupto no puede contar como señal de vida.
    """
    try:
        if "throttle" in msg or "steer" in msg:
            throttle = clamp(float(msg.get("throttle", 0.0)))
            steer = clamp(float(msg.get("steer", 0.0)))
            left, right = mix_arcade(throttle, steer)
            return DriveCommand(left, right)
        if "left" in msg and "right" in msg:
            return DriveCommand(clamp(float(msg["left"])), clamp(float(msg["right"])))
    except (TypeError, ValueError):
        log.warning("mensaje de control inválido: %r", msg)
        return None
    return None
