"""wally-voice: la voz de Wally.

    python -m services.voice           # Piper en la Pi
    python -m services.voice --sim     # `say` en macOS, o solo texto

Publica `wally/state/speaking` para que la cara anime la boca mientras habla.
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any

from common import log as logsetup
from common import topics
from common.bus import Bus
from common.config import load
from services.voice import tts
from services.voice.queue import SpeechQueue


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wally-voice")
    parser.add_argument("--sim", action="store_true")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--no-mqtt", action="store_true")
    parser.add_argument("--say", help="dice una frase y termina (para probar el audio)")
    args = parser.parse_args(argv)

    cfg = load(args.config)
    logger = logsetup.setup("voice", cfg.log_level)

    backend = tts.create(cfg.voice, sim=args.sim)
    logger.info("backend de voz: %s", backend.name)

    if args.say:
        backend.say(args.say)
        return 0

    queue = SpeechQueue(cfg.voice.max_queue, cfg.voice.dedupe_window_s)
    lock = threading.Lock()

    bus = None
    if not args.no_mqtt:
        bus = Bus(cfg.mqtt, "voice")

        def on_say(payload: dict[str, Any]) -> None:
            text = str(payload.get("text", ""))
            urgent = str(payload.get("priority", "normal")) == "urgent"
            with lock:
                if not queue.push(text, time.monotonic(), urgent):
                    logger.debug("descartada (repetida o cola llena): %r", text)

        bus.subscribe(topics.CMD_SAY, on_say)
        bus.start()

    running = True

    def handle_signal(signum, frame):
        nonlocal running
        logger.info("señal %s recibida", signal.Signals(signum).name)
        running = False
        backend.stop()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    def set_speaking(value: bool) -> None:
        if bus is not None:
            bus.publish(topics.STATE_SPEAKING, {"speaking": value})

    set_speaking(False)
    logger.info("esperando frases en %s", topics.CMD_SAY)

    try:
        while running:
            with lock:
                item = queue.pop()

            if item is None:
                time.sleep(0.05)
                continue

            logger.info("diciendo: %s", item.text)
            set_speaking(True)
            try:
                backend.say(item.text)
            finally:
                # Pase lo que pase, la cara no puede quedarse moviendo la boca
                # de un discurso que ya terminó.
                set_speaking(False)
    finally:
        backend.stop()
        set_speaking(False)
        if bus is not None:
            bus.stop()

    return 0


if __name__ == "__main__":
    sys.exit(main())
