"""Logging uniforme para todos los servicios.

Bajo systemd la salida va a journald, que ya añade su propia marca de tiempo,
así que el formato omite la fecha cuando detecta que corre como servicio.
"""

from __future__ import annotations

import logging
import os
import sys


def setup(service: str, level: str = "INFO") -> logging.Logger:
    under_systemd = "JOURNAL_STREAM" in os.environ
    fmt = "%(levelname)-7s %(name)s: %(message)s"
    if not under_systemd:
        fmt = "%(asctime)s " + fmt

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(fmt, datefmt="%H:%M:%S"))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    return logging.getLogger(service)
