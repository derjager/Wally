"""Punto de entrada de wally-net.

    sudo python -m services.net          # en la Pi: modificar red pide privilegios
    python -m services.net --sim         # backend de mentira, para desarrollo
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
from pathlib import Path

from common import log as logsetup
from common.bus import Bus
from common.config import load
from services.net import nmcli
from services.net.service import NetService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wally-net")
    parser.add_argument("--sim", action="store_true", help="no toca la red real")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--no-mqtt", action="store_true")
    args = parser.parse_args(argv)

    cfg = load(args.config)
    logger = logsetup.setup("net", cfg.log_level)

    if args.sim:
        logger.warning("MODO SIMULACIÓN: no se toca la configuración de red")
    elif os.geteuid() != 0:
        logger.error(
            "hace falta root para modificar la red. Usa sudo, o --sim para desarrollo."
        )
        return 1

    backend = nmcli.create(sim=args.sim, iface=cfg.net.iface)

    bus = None
    if not args.no_mqtt:
        bus = Bus(cfg.mqtt, "net")
        bus.start()

    service = NetService(cfg, backend, bus)

    def handle_signal(signum, frame):
        logger.info("señal %s recibida", signal.Signals(signum).name)
        service.stop()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    try:
        service.run()
    finally:
        if bus is not None:
            bus.stop()

    return 0


if __name__ == "__main__":
    sys.exit(main())
