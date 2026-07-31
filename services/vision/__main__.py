"""wally-vision: cámara y detección de objetos.

    python -m services.vision              # en la Pi, con el OV5647 y TFLite
    python -m services.vision --sim        # frames y detecciones sintéticos
    python -m services.vision --no-detect  # solo vídeo

Único proceso con acceso a la cámara (PLAN.md §6). Publica los frames en
memoria compartida para que `wally-web` los sirva, y las detecciones por MQTT.

**La inferencia va en un hilo aparte.** Detectar cuesta ~100 ms en una Pi 4 y
capturar toca cada 66 ms: hacerlo en el mismo bucle dejaría el vídeo a
trompicones. Así el vídeo mantiene sus 15 fps y la detección va a su ritmo, que
para reaccionar a un gato sobra.
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading
import time
from pathlib import Path

from common import log as logsetup
from common import topics
from common.bus import Bus
from common.config import load
from common.framebus import FrameWriter
from services.vision import camera, overlay
from services.vision.detector import Detection, Detector
from services.vision.tracker import PresenceTracker


class InferenceWorker:
    """Corre el detector sobre el último frame disponible, en su propio hilo."""

    def __init__(self, detector: Detector, fps: float, logger) -> None:
        self._detector = detector
        self._period = 1.0 / fps if fps > 0 else 0.2
        self._log = logger

        self._lock = threading.Lock()
        self._pending = None
        self._detections: list[Detection] = []
        self._running = False
        self._thread: threading.Thread | None = None
        self.last_ms = 0.0
        self.frames = 0

        self.on_detections = None  # callback(list[Detection])

    def submit(self, rgb) -> None:
        """Ofrece un frame. Si el hilo está ocupado, se descarta: siempre
        interesa el más reciente, no acumular una cola de fotogramas viejos."""
        with self._lock:
            self._pending = rgb

    def detections(self) -> list[Detection]:
        with self._lock:
            return list(self._detections)

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="inference", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _loop(self) -> None:
        while self._running:
            with self._lock:
                frame = self._pending
                self._pending = None

            if frame is None:
                time.sleep(0.01)
                continue

            t0 = time.monotonic()
            try:
                found = self._detector.detect(frame)
            except Exception:
                self._log.exception("fallo en la inferencia")
                found = []
            self.last_ms = (time.monotonic() - t0) * 1000.0
            self.frames += 1

            with self._lock:
                self._detections = found

            if self.on_detections is not None:
                try:
                    self.on_detections(found)
                except Exception:
                    self._log.exception("fallo al publicar detecciones")

            # Ritmo objetivo. Si la inferencia ya tardó más, se sigue sin pausa.
            resto = self._period - (time.monotonic() - t0)
            if resto > 0:
                time.sleep(resto)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wally-vision")
    parser.add_argument("--sim", action="store_true", help="cámara y detección sintéticas")
    parser.add_argument("--no-detect", action="store_true", help="solo vídeo, sin inferencia")
    parser.add_argument("--no-mqtt", action="store_true")
    parser.add_argument("--config", type=Path, default=None)
    args = parser.parse_args(argv)

    cfg = load(args.config)
    logger = logsetup.setup("vision", cfg.log_level)
    vcfg = cfg.vision

    try:
        source = camera.create(
            sim=args.sim, width=vcfg.width, height=vcfg.height,
            hflip=vcfg.hflip, vflip=vcfg.vflip,
        )
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 1

    # El detector es opcional: un robot que ve pero no reconoce sigue siendo
    # teleoperable, así que la falta del modelo no puede impedir el arranque.
    worker: InferenceWorker | None = None
    if not args.no_detect:
        from services.vision import detector as det_mod
        try:
            detector = det_mod.create(sim=args.sim, cfg=vcfg)
            worker = InferenceWorker(detector, vcfg.inference_fps, logger)
            logger.info("detector: %s a %.1f fps", detector.name, vcfg.inference_fps)
        except RuntimeError as exc:
            logger.warning("sin detección de objetos (%s)", exc)

    bus = None
    if not args.no_mqtt:
        bus = Bus(cfg.mqtt, "vision")
        bus.start()

    tracker = PresenceTracker(
        vcfg.track_label, vcfg.appear_hits, vcfg.disappear_misses
    )

    def publish_detections(found: list[Detection]) -> None:
        event = tracker.update(found)

        if bus is not None:
            bus.publish(
                topics.VISION_DETECTIONS,
                {"detections": [d.as_dict() for d in found]},
            )
            bus.publish(topics.VISION_CAT, tracker.snapshot(), retain=True)

        if event.appeared:
            logger.info("¡%s a la vista!", vcfg.track_label)
        elif event.disappeared:
            logger.info("%s fuera de vista", vcfg.track_label)

    if worker is not None:
        worker.on_detections = publish_detections
        worker.start()

    writer = FrameWriter(name=vcfg.frame_shm)
    running = True

    def handle_signal(signum, frame):
        nonlocal running
        logger.info("señal %s recibida", signal.Signals(signum).name)
        running = False

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    period = 1.0 / vcfg.fps
    frames = dropped = 0
    last_report = time.monotonic()

    try:
        source.start()
        logger.info("publicando a %.0f fps en shm '%s'", vcfg.fps, vcfg.frame_shm)

        next_tick = time.monotonic()
        while running:
            rgb = source.capture_array()
            if rgb is not None:
                if worker is not None:
                    worker.submit(rgb)
                    if vcfg.draw_overlay:
                        rgb = overlay.draw(rgb, worker.detections(), vcfg.track_label)

                jpeg = camera.encode_jpeg(rgb, vcfg.jpeg_quality)
                if writer.write(jpeg):
                    frames += 1
                else:
                    dropped += 1
                    if dropped == 1:
                        logger.warning(
                            "frame de %d bytes no cabe en el buffer de %d; "
                            "baja jpeg_quality o sube la capacidad",
                            len(jpeg), writer.capacity,
                        )

            now = time.monotonic()
            if now - last_report >= 10.0:
                lapso = now - last_report
                msg = "%.1f fps de vídeo" % (frames / lapso)
                if worker is not None:
                    msg += " · %.1f fps de detección (%.0f ms)" % (
                        worker.frames / lapso, worker.last_ms
                    )
                    worker.frames = 0
                logger.info("%s", msg)
                frames = 0
                last_report = now

            next_tick += period
            sleep_for = next_tick - time.monotonic()
            if sleep_for > 0:
                time.sleep(sleep_for)
            else:
                next_tick = time.monotonic()
    finally:
        if worker is not None:
            worker.stop()
        source.close()
        writer.close()
        if bus is not None:
            bus.stop()
        logger.info("cámara liberada")

    return 0


if __name__ == "__main__":
    sys.exit(main())
