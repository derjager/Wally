"""wally-vision: captura de cámara.

    python -m services.vision            # en la Pi, con el OV5647
    python -m services.vision --sim      # frames sintéticos

Único proceso con acceso a la cámara (PLAN.md §6). Publica los frames en
memoria compartida para que `wally-web` los sirva sin copias por red.

La detección de objetos entra en la Fase 5; aquí solo se captura.
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

from common import log as logsetup
from common.config import load
from common.framebus import FrameWriter
from services.vision import camera


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wally-vision")
    parser.add_argument("--sim", action="store_true", help="frames sintéticos, sin cámara")
    parser.add_argument("--config", type=Path, default=None)
    args = parser.parse_args(argv)

    cfg = load(args.config)
    logger = logsetup.setup("vision", cfg.log_level)
    vcfg = cfg.vision

    try:
        source = camera.create(
            sim=args.sim,
            width=vcfg.width,
            height=vcfg.height,
            quality=vcfg.jpeg_quality,
            hflip=vcfg.hflip,
            vflip=vcfg.vflip,
        )
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 1

    writer = FrameWriter(name=vcfg.frame_shm)
    running = True

    def handle_signal(signum, frame):
        nonlocal running
        logger.info("señal %s recibida", signal.Signals(signum).name)
        running = False

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    period = 1.0 / vcfg.fps
    frames = 0
    dropped = 0
    last_report = time.monotonic()

    try:
        source.start()
        logger.info("publicando a %.0f fps en shm '%s'", vcfg.fps, vcfg.frame_shm)

        next_tick = time.monotonic()
        while running:
            jpeg = source.capture_jpeg()
            if jpeg is not None:
                if writer.write(jpeg):
                    frames += 1
                else:
                    dropped += 1
                    if dropped == 1:
                        logger.warning(
                            "frame de %d bytes no cabe en el buffer de %d; "
                            "baja jpeg_quality o sube la capacidad",
                            len(jpeg),
                            writer.capacity,
                        )

            now = time.monotonic()
            if now - last_report >= 10.0:
                logger.info("%.1f fps efectivos", frames / (now - last_report))
                frames = 0
                last_report = now

            next_tick += period
            sleep_for = next_tick - time.monotonic()
            if sleep_for > 0:
                time.sleep(sleep_for)
            else:
                next_tick = time.monotonic()
    finally:
        source.close()
        writer.close()
        logger.info("cámara liberada")

    return 0


if __name__ == "__main__":
    sys.exit(main())
