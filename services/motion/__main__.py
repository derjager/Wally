"""Punto de entrada de wally-motion.

    python -m services.motion            # en la Pi, con pigpio
    python -m services.motion --sim      # sin hardware, para desarrollo
"""

from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path

from common import log as logsetup
from common.bus import Bus
from common.config import load
from services.motion import backend as gpio
from services.motion.service import MotionService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wally-motion")
    parser.add_argument("--sim", action="store_true", help="simula el GPIO, sin hardware")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--no-mqtt", action="store_true", help="arranca sin bus (diagnóstico)")
    args = parser.parse_args(argv)

    cfg = load(args.config)
    logger = logsetup.setup("motion", cfg.log_level)

    try:
        io = gpio.create(sim=args.sim)
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 1

    if args.sim:
        logger.warning("MODO SIMULACIÓN: no se toca ningún GPIO")

    bus = None
    if not args.no_mqtt:
        bus = Bus(cfg.mqtt, "motion")
        bus.start()

    service = MotionService(cfg, io, bus)

    def handle_signal(signum, frame):
        logger.info("señal %s recibida", signal.Signals(signum).name)
        service.stop()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    try:
        service.run()
    finally:
        # Pase lo que pase, los motores quedan a cero.
        service.shutdown()
        if bus is not None:
            bus.stop()

    return 0


if __name__ == "__main__":
    sys.exit(main())
