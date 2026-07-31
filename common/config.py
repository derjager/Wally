"""Carga de configuración desde TOML, con valores por defecto seguros.

Los defaults de este módulo son los del PLAN.md §3 y §4. Un `wally.toml`
ausente o parcial es válido: solo sobrescribe lo que declara.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "wally.toml"


@dataclass(frozen=True)
class MotorPins:
    """Un canal del TB6612FNG."""

    pwm: int
    in1: int
    in2: int
    invert: bool = False


@dataclass(frozen=True)
class RangeSensorPins:
    """Un HC-SR04. El ECHO llega por divisor resistivo 1kΩ+2kΩ."""

    name: str
    trig: int
    echo: int


@dataclass(frozen=True)
class MotionConfig:
    # --- Pines (BCM), según PLAN.md §4.5 ---
    left: MotorPins = field(default_factory=lambda: MotorPins(pwm=12, in1=20, in2=21))
    right: MotorPins = field(default_factory=lambda: MotorPins(pwm=13, in1=16, in2=26))
    standby: int = 25
    servo_left: int = 18
    servo_right: int = 23
    rangefinders: tuple[RangeSensorPins, ...] = field(
        default_factory=lambda: (
            RangeSensorPins("front", trig=4, echo=17),
            RangeSensorPins("left", trig=5, echo=27),
            RangeSensorPins("right", trig=6, echo=22),
        )
    )

    # --- Seguridad ---
    # Tope de duty absoluto. Los motores FA-130 son de 3V y el riel entrega
    # 4.8V: sin este tope se sobrepasa su tensión nominal. Ver PLAN.md §2.
    duty_cap: float = 0.60
    # Si no llega un cmd/drive en esta ventana, se frena. Ver PLAN.md §6.
    watchdog_ms: int = 500

    # --- Dinámica ---
    pwm_hz: int = 10_000  # sobre el rango audible, evita el zumbido
    control_hz: int = 50
    # Unidades de duty normalizado por segundo. La bajada es más agresiva que
    # la subida: acelerar suave protege el driver, frenar rápido protege todo
    # lo demás.
    ramp_up_per_s: float = 2.0
    ramp_down_per_s: float = 6.0

    # --- Servos ---
    servo_min_us: int = 500
    servo_max_us: int = 2500
    servo_idle_timeout_s: float = 2.0  # tras este tiempo quieto, corta el pulso

    # --- Sensores ---
    range_poll_hz: float = 15.0  # total, repartido round-robin entre sensores
    range_timeout_us: int = 25_000  # ~4 m; más allá se reporta None


@dataclass(frozen=True)
class VisionConfig:
    width: int = 640
    height: int = 480
    fps: float = 15.0
    jpeg_quality: int = 80
    # El montaje de la cámara puede quedar girado según cómo se fije al chasis.
    hflip: bool = False
    vflip: bool = False
    frame_shm: str = "wally_frame"


@dataclass(frozen=True)
class WebConfig:
    host: str = "0.0.0.0"
    port: int = 8080
    # Cadencia con la que el navegador envía el joystick. Debe dejar margen
    # holgado frente a motion.watchdog_ms o el robot se frenará solo en cada
    # microcorte de wifi.
    control_hz: float = 20.0
    # Frecuencia de refresco del panel de telemetría.
    telemetry_hz: float = 5.0
    mjpeg_fps: float = 15.0


@dataclass(frozen=True)
class MqttConfig:
    host: str = "localhost"
    port: int = 1883
    keepalive: int = 30


@dataclass(frozen=True)
class Config:
    mqtt: MqttConfig = field(default_factory=MqttConfig)
    motion: MotionConfig = field(default_factory=MotionConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    web: WebConfig = field(default_factory=WebConfig)
    log_level: str = "INFO"


# Campos que son a su vez dataclasses, por clase contenedora. Se declaran
# explícitamente en lugar de inferirse: `from __future__ import annotations`
# convierte las anotaciones en strings y la introspección de tipos no sirve.
_NESTED: dict[type, dict[str, type]] = {
    Config: {
        "mqtt": MqttConfig,
        "motion": MotionConfig,
        "vision": VisionConfig,
        "web": WebConfig,
    },
    MotionConfig: {"left": MotorPins, "right": MotorPins},
}


def _build(cls: type, data: dict[str, Any]) -> Any:
    """Construye un dataclass desde un dict, recursivamente.

    Ignora claves desconocidas en vez de fallar: un config que traiga opciones
    de otro servicio no debe impedir que este arranque.
    """
    kwargs: dict[str, Any] = {}
    known = {f.name for f in fields(cls)}
    nested = _NESTED.get(cls, {})

    for key, value in data.items():
        if key not in known:
            continue
        if key in nested and isinstance(value, dict):
            kwargs[key] = _build(nested[key], value)
        elif key == "rangefinders" and isinstance(value, list):
            kwargs[key] = tuple(RangeSensorPins(**item) for item in value)
        else:
            kwargs[key] = value

    return cls(**kwargs)


def load(path: Path | str | None = None) -> Config:
    """Carga la configuración. Si el archivo no existe, devuelve los defaults."""
    p = Path(path) if path else DEFAULT_CONFIG_PATH
    if not p.exists():
        return Config()
    with p.open("rb") as fh:
        raw = tomllib.load(fh)
    return _build(Config, raw)
