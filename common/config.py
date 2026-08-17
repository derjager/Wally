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
    # GPIO25/17 se los quedó la pantalla SPI MPI3201 (RST y touch IRQ, ver
    # PLAN.md §3, pinout confirmado por el datasheet de LCDWIKI): STBY se
    # movió a GPIO19 y el ECHO frontal a GPIO15 (antes UART de depuración).
    # GPIO18 sigue libre: esta pantalla no usa GPIO para el backlight.
    standby: int = 19
    servo_left: int = 18
    servo_right: int = 23
    rangefinders: tuple[RangeSensorPins, ...] = field(
        default_factory=lambda: (
            RangeSensorPins("front", trig=4, echo=15),
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

    # --- Detección ---
    model: str = "models/efficientdet_lite0.tflite"
    labels: str = "models/coco_labels.txt"
    # Muy por debajo de la captura: detectar cuesta ~100 ms en una Pi 4 y no
    # hace falta más para reaccionar a un gato. Subirlo se come la CPU que
    # necesitan el vídeo y el control.
    inference_fps: float = 5.0
    min_score: float = 0.45
    threads: int = 4
    draw_overlay: bool = True

    # --- Presencia ---
    # Qué se sigue con histéresis. `cat` de COCO basta: no hay otros gatos en
    # casa, así que no hace falta identificación individual.
    track_label: str = "cat"
    # Asimétrico a propósito: aparecer exige poca evidencia, desaparecer
    # mucha. Que la gata se tape un momento no significa que se haya ido.
    appear_hits: int = 3
    disappear_misses: int = 12


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
class FaceConfig:
    # Resolución lógica del pixel art. Se escala por el mayor factor entero
    # que quepa en la pantalla: así los píxeles salen cuadrados y nítidos en
    # lugar de emborronados por un escalado fraccionario.
    logical_width: int = 160
    # 120 en vez de 106: la pantalla de 3.2" es 320x240 (4:3), y con este alto
    # el factor ×2 llena el panel exacto, sin franjas negras arriba/abajo.
    logical_height: int = 120
    fps: int = 30
    # La 3.2" SPI es 320x240; en desarrollo se abre una ventana escalada.
    window_scale: int = 2
    # Cada cuánto parpadea, con algo de azar para que no parezca un metrónomo.
    blink_every_s: float = 4.0
    blink_jitter_s: float = 2.5
    # Sin actividad durante este tiempo, la cara se adormece.
    sleepy_after_s: float = 90.0

    # --- Pantalla física (SPI, no HDMI/DRM) ---
    # MPI3201 (ILI9341), instalada con goodtft/LCD-show (`sudo ./LCD32-show`,
    # ver README C10). Ese instalador expone un framebuffer clásico, no un
    # dispositivo DRM/KMS, así que `_init_display` no puede usar kmsdrm a
    # secas. LCD-show suele remapear la consola al framebuffer nuevo como
    # /dev/fb0 (no /dev/fb1) — confirmar con `ls /dev/fb*` tras instalar y
    # ajustar aquí si el device real es otro.
    sdl_video_driver: str = "fbcon"
    fb_device: str = "/dev/fb0"

    # --- Gestos táctiles ---
    # No requieren calibración de coordenadas: solo miden cuánto duró el
    # toque, no dónde ocurrió.
    touch_tap_max_s: float = 0.6
    touch_hold_s: float = 3.0
    # Orden de ciclo del toque corto, publicado en CMD_MODE.
    touch_mode_cycle: tuple[str, ...] = ("idle", "patrol", "follow_cat")


@dataclass(frozen=True)
class VoiceConfig:
    # Modelo Piper (.onnx). Instalar en assets/voices/.
    model: str = "assets/voices/es_ES-davefx-medium.onnx"
    piper_bin: str = "piper"
    # Reproductor de audio. En Bookworm, aplay viene con alsa-utils.
    player: str = "aplay"
    # Descarta frases repetidas dentro de esta ventana: evita que el robot
    # repita "obstáculo" veinte veces seguidas acercándose a una pared.
    dedupe_window_s: float = 8.0
    max_queue: int = 12


@dataclass(frozen=True)
class BrainConfig:
    """Comportamiento autónomo.

    ⚠️ Estas constantes son **estimaciones de partida**. Dependen de cómo
    responda el chasis real: cuánto derrapan las orugas, cuánto tarda en
    frenar, qué ángulo gira por segundo. Hay que afinarlas con el robot
    montado, en el suelo definitivo y con la batería cargada.
    """

    start_mode: str = "idle"
    update_hz: float = 10.0

    # --- Patrulla ---
    cruise_speed: float = 0.55
    turn_speed: float = 0.6
    backup_speed: float = 0.45
    # Distancia a la que se deja de avanzar y se gira.
    stop_mm: float = 320.0
    # Tan cerca que girar rozaría: primero hay que retroceder.
    backup_mm: float = 160.0
    # Hay que ver al menos esto de espacio para dar el frente por despejado.
    # Mayor que stop_mm a propósito: si fueran iguales, el robot saldría del
    # giro justo en el límite y volvería a bloquearse de inmediato.
    clear_mm: float = 500.0
    backup_s: float = 0.9
    # Giro mínimo antes de reevaluar. Sin esto el robot vibra contra la pared
    # en vez de rodearla.
    turn_min_s: float = 0.5
    # Girando más de esto sin despejar, se asume encerrado y retrocede.
    turn_timeout_s: float = 3.5

    # --- Seguir a la gata ---
    # Despacio a propósito: el ultrasonido no detecta pelaje, así que el robot
    # no puede "ver" a la gata con los sensores de distancia.
    follow_speed: float = 0.35
    follow_turn_speed: float = 0.42
    # Fracción del encuadre a partir de la cual se considera que ya está
    # bastante cerca y hay que parar.
    follow_stop_area: float = 0.18
    # Desvío tolerable antes de girar sobre el sitio.
    follow_align_tol: float = 0.35
    follow_steer_gain: float = 0.5
    # Cuánto espera quieto tras perderla de vista.
    cat_patience_s: float = 6.0
    patrol_when_no_cat: bool = True
    follow_cat_while_patrolling: bool = True

    # --- Interacción ---
    # Un comando de conducción ajeno silencia a brain este tiempo. Mueves el
    # joystick y el robot obedece sin tener que cambiar de modo a mano.
    manual_override_s: float = 3.0
    announce_cat: bool = True
    cat_greeting: str = "¡Hola, gatita!"


@dataclass(frozen=True)
class NetConfig:
    iface: str = "wlan0"
    ap_ssid: str = "Wally-Setup"
    # WPA2 exige 8 caracteres como mínimo. Con AP abierto, la contraseña de tu
    # wifi viajaría en claro por el aire durante la configuración.
    ap_password: str = "wally1234"
    # Margen para que NetworkManager conecte a una red conocida al arrancar
    # antes de rendirse y levantar el AP.
    boot_timeout_s: float = 30.0
    # Tiempo sin conexión tras el cual se vuelve al AP para poder
    # reconfigurar. Generoso a propósito: un router reiniciándose no debe
    # dejarte sin control. 0 lo desactiva.
    fallback_after_s: float = 120.0
    poll_s: float = 5.0


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
    net: NetConfig = field(default_factory=NetConfig)
    face: FaceConfig = field(default_factory=FaceConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    brain: BrainConfig = field(default_factory=BrainConfig)
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
        "net": NetConfig,
        "face": FaceConfig,
        "voice": VoiceConfig,
        "brain": BrainConfig,
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
