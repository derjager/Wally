"""Punto de entrada de wally-web.

    python -m services.web              # http://<ip>:8080
    python -m services.web --no-mqtt    # solo UI y vídeo, sin publicar comandos
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import uvicorn

from common import log as logsetup
from common.bus import Bus
from common.config import load
from services.web.app import create_app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wally-web")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--no-mqtt", action="store_true")
    args = parser.parse_args(argv)

    cfg = load(args.config)
    logger = logsetup.setup("web", cfg.log_level)

    bus = None
    if not args.no_mqtt:
        bus = Bus(cfg.mqtt, "web")
        bus.start()
    else:
        logger.warning("sin MQTT: los controles no llegarán a los motores")

    app = create_app(cfg, bus)

    host = args.host or cfg.web.host
    port = args.port or cfg.web.port
    logger.info("sirviendo en http://%s:%d", host, port)

    try:
        uvicorn.run(app, host=host, port=port, log_level=cfg.log_level.lower(), access_log=False)
    finally:
        if bus is not None:
            bus.stop()

    return 0


if __name__ == "__main__":
    sys.exit(main())
