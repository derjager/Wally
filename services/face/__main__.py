"""wally-face: la cara de Wally en la pantalla táctil de 3.2".

    python -m services.face              # en la Pi, a pantalla completa
    python -m services.face --windowed   # ventana, para desarrollo

En la Pi se dibuja directo al framebuffer, sin escritorio: eso ahorra unos
300 MB de RAM y la CPU que necesita la visión (PLAN.md §5). Es una pantalla
SPI (no HDMI/DRM), así que el framebuffer sale por `fbcon`/`fb_device`
(`FaceConfig`), no por `kmsdrm`. El usuario del servicio debe estar en los
grupos `video` y `render`.

El táctil resistivo no se calibra por posición: los dos gestos que se
reconocen (toque corto y toque largo) solo miden cuánto duró el contacto, así
que no dependen de la orientación ni del mapeo XY del panel (ver PLAN.md §8).
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

from common import log as logsetup
from common import topics
from common.bus import Bus
from common.config import load
from services.face import expressions as ex
from services.face.state import FaceState, Inputs


def _init_display(cfg, windowed: bool):
    """Arranca pygame y devuelve (pantalla, lienzo)."""
    if not windowed:
        # Pantalla SPI (MPI3201, instalada con goodtft/LCD-show): framebuffer
        # clásico, no un dispositivo DRM/KMS. Ver README C10.
        os.environ.setdefault("SDL_VIDEODRIVER", cfg.sdl_video_driver)
        os.environ.setdefault("SDL_FBDEV", cfg.fb_device)

    import pygame

    pygame.init()
    pygame.mouse.set_visible(False)

    if windowed:
        size = (cfg.logical_width * cfg.window_scale, cfg.logical_height * cfg.window_scale)
        screen = pygame.display.set_mode(size)
        pygame.display.set_caption("Wally")
    else:
        screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)

    canvas = pygame.Surface((cfg.logical_width, cfg.logical_height))
    return pygame, screen, canvas


class _TouchGestures:
    """Clasifica toques del táctil resistivo solo por duración.

    Nunca mira coordenadas, así que no necesita calibración: un toque corto
    dispara `on_tap` al soltar; uno sostenido dispara `on_hold` en cuanto
    cruza el umbral, sin esperar a que se levante el dedo (PLAN.md §8).
    """

    def __init__(self, cfg, on_tap, on_hold) -> None:
        self._tap_max_s = cfg.touch_tap_max_s
        self._hold_s = cfg.touch_hold_s
        self._on_tap = on_tap
        self._on_hold = on_hold
        self._started_at: float | None = None
        self._hold_fired = False

    def handle_event(self, event, now: float) -> None:
        import pygame
        # FINGERDOWN/UP si SDL expone multitouch bajo fbcon; si no, cae a
        # MOUSEBUTTONDOWN/UP (así lo suele mapear el táctil resistivo).
        if event.type in (pygame.FINGERDOWN, pygame.MOUSEBUTTONDOWN):
            self._started_at = now
            self._hold_fired = False
        elif event.type in (pygame.FINGERUP, pygame.MOUSEBUTTONUP):
            if self._started_at is not None and not self._hold_fired:
                if now - self._started_at < self._tap_max_s:
                    self._on_tap()
            self._started_at = None

    def poll(self, now: float) -> None:
        if (
            self._started_at is not None
            and not self._hold_fired
            and now - self._started_at >= self._hold_s
        ):
            self._hold_fired = True
            self._on_hold()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wally-face")
    parser.add_argument("--windowed", action="store_true", help="ventana en vez de pantalla completa")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--no-mqtt", action="store_true")
    parser.add_argument("--demo", action="store_true", help="recorre todos los ánimos en bucle")
    args = parser.parse_args(argv)

    cfg = load(args.config)
    logger = logsetup.setup("face", cfg.log_level)

    try:
        pygame, screen, canvas = _init_display(cfg.face, args.windowed)
    except Exception as exc:
        logger.error("no se pudo abrir la pantalla: %s", exc)
        logger.error("en la Pi hace falta pertenecer a los grupos video y render")
        return 1

    from services.face import render

    state = FaceState(cfg.face)
    inputs = Inputs()

    mode_cycle = cfg.face.touch_mode_cycle
    current_mode = mode_cycle[0] if mode_cycle else "idle"

    bus = None
    if not args.no_mqtt:
        bus = Bus(cfg.mqtt, "face")

        def on_mood(payload: dict[str, Any]) -> None:
            mood = str(payload.get("mood", ""))
            state.command_mood(mood, float(payload.get("hold_s", 4.0)), time.monotonic())

        def on_motion(payload: dict[str, Any]) -> None:
            inputs.estop = bool(payload.get("estop", False))
            left = abs(float(payload.get("left", 0.0)))
            right = abs(float(payload.get("right", 0.0)))
            inputs.moving = max(left, right) > 0.05

        def on_sensors(payload: dict[str, Any]) -> None:
            valores = [v for v in payload.values() if isinstance(v, (int, float))]
            inputs.closest_mm = min(valores) if valores else None

        def on_speaking(payload: dict[str, Any]) -> None:
            inputs.speaking = bool(payload.get("speaking", False))

        def on_look(payload: dict[str, Any]) -> None:
            state.look_at(float(payload.get("x", 0.0)), float(payload.get("y", 0.0)))

        def on_cat(payload: dict[str, Any]) -> None:
            inputs.cat_visible = bool(payload.get("present", False))
            # Los ojos siguen a la gata por la pantalla. `offset_x` ya viene
            # normalizado a -1..1 desde wally-vision.
            offset = payload.get("offset_x")
            if inputs.cat_visible and isinstance(offset, (int, float)):
                state.look_at(float(offset), 0.0)

        def on_mode_state(payload: dict[str, Any]) -> None:
            nonlocal current_mode
            mode = payload.get("mode")
            if isinstance(mode, str):
                current_mode = mode

        bus.subscribe(topics.CMD_MOOD, on_mood)
        bus.subscribe(topics.STATE_MOTION, on_motion)
        bus.subscribe(topics.STATE_SENSORS, on_sensors)
        bus.subscribe(topics.STATE_SPEAKING, on_speaking)
        bus.subscribe(topics.CMD_LOOK, on_look)
        bus.subscribe(topics.VISION_CAT, on_cat)
        bus.subscribe(topics.STATE_MODE, on_mode_state)
        bus.start()

    def on_tap() -> None:
        # Toque corto: cicla de modo. Reutiliza CMD_MODE, que ya maneja
        # wally-brain — no hace falta ningún topic nuevo.
        if not mode_cycle or bus is None:
            return
        idx = mode_cycle.index(current_mode) if current_mode in mode_cycle else -1
        next_mode = mode_cycle[(idx + 1) % len(mode_cycle)]
        logger.info("toque: modo %s -> %s", current_mode, next_mode)
        bus.publish(topics.CMD_MODE, {"mode": next_mode})

    def on_hold() -> None:
        # Toque largo: fuerza el hotspot de red. Es el "botón físico" que
        # PLAN.md §9 dejaba pendiente para volver al modo AP.
        if bus is None:
            return
        logger.info("toque largo: forzando hotspot de red")
        bus.publish(topics.CMD_NET_HOTSPOT, {})

    touch = _TouchGestures(cfg.face, on_tap=on_tap, on_hold=on_hold)

    running = True

    def handle_signal(signum, frame):
        nonlocal running
        logger.info("señal %s recibida", signal.Signals(signum).name)
        running = False

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    logger.info(
        "cara a %dx%d lógicos, %d fps%s",
        cfg.face.logical_width, cfg.face.logical_height, cfg.face.fps,
        " (demo)" if args.demo else "",
    )

    clock = pygame.time.Clock()
    demo_moods = list(ex.EXPRESSIONS)
    demo_i = 0
    next_demo = 0.0
    last_mood = None

    try:
        while running:
            now = time.monotonic()
            dt = clock.tick(cfg.face.fps) / 1000.0

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_q):
                    running = False
                else:
                    touch.handle_event(event, now)
            touch.poll(now)

            if args.demo and now >= next_demo:
                mood = demo_moods[demo_i % len(demo_moods)]
                state.command_mood(mood, 2.5, now)
                logger.info("demo: %s", mood)
                demo_i += 1
                next_demo = now + 2.5

            state.set_inputs(inputs, now)
            expr = state.update(dt, now)

            if state.mood != last_mood:
                last_mood = state.mood
                if bus is not None:
                    bus.publish(topics.STATE_MOOD, {"mood": state.mood}, retain=True)

            render.draw(canvas, expr, state.look_x, state.look_y)
            render.present(screen, canvas)
    finally:
        pygame.quit()
        if bus is not None:
            bus.stop()
        logger.info("cara apagada")

    return 0


if __name__ == "__main__":
    sys.exit(main())
