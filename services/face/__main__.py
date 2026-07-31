"""wally-face: la cara de Wally en la pantalla de 3.5".

    python -m services.face              # en la Pi, a pantalla completa
    python -m services.face --windowed   # ventana, para desarrollo

En la Pi se dibuja directo al framebuffer con SDL/KMSDRM, sin escritorio: eso
ahorra unos 300 MB de RAM y la CPU que necesita la visión (PLAN.md §5). El
usuario del servicio debe estar en los grupos `video` y `render` para poder
abrir /dev/dri.
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
        # KMSDRM dibuja sobre el framebuffer sin necesidad de X.
        os.environ.setdefault("SDL_VIDEODRIVER", "kmsdrm")

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

        bus.subscribe(topics.CMD_MOOD, on_mood)
        bus.subscribe(topics.STATE_MOTION, on_motion)
        bus.subscribe(topics.STATE_SENSORS, on_sensors)
        bus.subscribe(topics.STATE_SPEAKING, on_speaking)
        bus.subscribe(topics.CMD_LOOK, on_look)
        bus.subscribe(topics.VISION_CAT, on_cat)
        bus.start()

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
