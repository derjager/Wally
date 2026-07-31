"""Punto de entrada de wally-brain.

    python -m services.brain                 # arranca en el modo de config
    python -m services.brain --mode patrol   # fuerza un modo al arrancar

No necesita `--sim`: brain no toca hardware, solo publica comandos. Se prueba
levantando `wally-motion --sim` al lado y mirando el bus.
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

from common import log as logsetup
from common import topics
from common.bus import Bus
from common.config import load
from services.brain.service import MODES, BrainService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wally-brain")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--mode", choices=MODES, default=None)
    parser.add_argument("--no-mqtt", action="store_true")
    args = parser.parse_args(argv)

    cfg = load(args.config)
    logger = logsetup.setup("brain", cfg.log_level)

    bus = None
    if not args.no_mqtt:
        bus = Bus(cfg.mqtt, "brain")
        bus.start()

    service = BrainService(cfg, bus)
    if args.mode:
        service.set_mode(args.mode, time.monotonic())

    if bus is not None:
        bus.publish(topics.STATE_MODE, {"mode": service.mode}, retain=True)
        bus.on_connected(
            lambda: bus.publish(topics.STATE_MODE, {"mode": service.mode}, retain=True)
        )

    running = True

    def handle_signal(signum, frame):
        nonlocal running
        logger.info("señal %s recibida", signal.Signals(signum).name)
        running = False

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    period = 1.0 / cfg.brain.update_hz
    logger.info("modo inicial: %s · %.0f Hz", service.mode, cfg.brain.update_hz)
    logger.warning(
        "las constantes de navegación son estimaciones: hay que afinarlas con "
        "el robot montado (ver [brain] en config/wally.toml)"
    )

    next_tick = time.monotonic()
    last_log = ""

    try:
        while running:
            now = time.monotonic()
            service.step(now)

            estado = f"{service.mode}/{service.snapshot()['patrol_phase']}"
            if service.manual_override:
                estado += " (mando manual)"
            if estado != last_log:
                logger.info("%s", estado)
                last_log = estado

            next_tick += period
            sleep_for = next_tick - time.monotonic()
            if sleep_for > 0:
                time.sleep(sleep_for)
            else:
                next_tick = time.monotonic()
    finally:
        # Al salir no se publica una parada: dejar de hablar ya frena el robot
        # vía watchdog, y un último mensaje podría pisar a quien tome el
        # control después.
        if bus is not None:
            bus.stop()
        logger.info("brain apagado")

    return 0


if __name__ == "__main__":
    sys.exit(main())
