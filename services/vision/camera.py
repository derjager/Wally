"""Fuentes de vídeo: la cámara real y una sintética para desarrollo.

En Bookworm el OV5647 solo se maneja por libcamera/Picamera2 (PLAN.md §5); el
viejo stack de `raspistill` y el driver bcm2835 ya no existen.

La inferencia TFLite entra en la Fase 5. Este módulo solo captura.
"""

from __future__ import annotations

import io
import logging
import math
import time
from abc import ABC, abstractmethod

log = logging.getLogger("vision.camera")


class CameraSource(ABC):
    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def capture_jpeg(self) -> bytes | None: ...

    @abstractmethod
    def close(self) -> None: ...


class PiCameraSource(CameraSource):
    """OV5647 vía Picamera2."""

    def __init__(self, width: int, height: int, quality: int, hflip: bool, vflip: bool) -> None:
        self._size = (width, height)
        self._quality = quality
        self._hflip = hflip
        self._vflip = vflip
        self._cam = None

    def start(self) -> None:
        from picamera2 import Picamera2  # import diferido: no existe fuera de la Pi
        from libcamera import Transform

        self._cam = Picamera2()
        cfg = self._cam.create_video_configuration(
            main={"size": self._size, "format": "RGB888"},
            transform=Transform(hflip=self._hflip, vflip=self._vflip),
        )
        self._cam.configure(cfg)
        self._cam.start()
        # El AE/AWB necesita un momento para estabilizarse; sin esta pausa los
        # primeros frames salen oscuros o con dominante de color.
        time.sleep(1.0)
        log.info("cámara iniciada a %dx%d", *self._size)

    def capture_jpeg(self) -> bytes | None:
        if self._cam is None:
            return None
        from PIL import Image

        array = self._cam.capture_array("main")
        buf = io.BytesIO()
        Image.fromarray(array).save(buf, format="JPEG", quality=self._quality)
        return buf.getvalue()

    def close(self) -> None:
        if self._cam is not None:
            self._cam.stop()
            self._cam.close()
            self._cam = None


class SyntheticSource(CameraSource):
    """Frames generados, para desarrollar la webapp sin cámara.

    Dibuja una escena en movimiento con marca de tiempo y contador, de modo
    que en el navegador se distingue vídeo fluido de una imagen congelada.
    """

    def __init__(self, width: int, height: int, quality: int, **_ignored) -> None:
        self._size = (width, height)
        self._quality = quality
        self._frame = 0
        self._t0 = time.monotonic()

    def start(self) -> None:
        log.warning("FUENTE SINTÉTICA: no se usa cámara real")

    def capture_jpeg(self) -> bytes | None:
        from PIL import Image, ImageDraw

        w, h = self._size
        t = time.monotonic() - self._t0
        img = Image.new("RGB", self._size, (18, 22, 30))
        d = ImageDraw.Draw(img)

        # Rejilla de fondo, para percibir el movimiento.
        for x in range(0, w, 40):
            d.line([(x, 0), (x, h)], fill=(30, 36, 48))
        for y in range(0, h, 40):
            d.line([(0, y), (w, y)], fill=(30, 36, 48))

        # Un objeto orbitando: si se mueve suave, el streaming va bien.
        cx = w / 2 + math.cos(t * 1.2) * (w / 3)
        cy = h / 2 + math.sin(t * 0.9) * (h / 4)
        r = 26
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 138, 61))

        d.text((10, 10), f"WALLY · SIM", fill=(120, 220, 160))
        d.text((10, 26), f"frame {self._frame}  t={t:6.1f}s", fill=(150, 160, 180))

        self._frame += 1
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=self._quality)
        return buf.getvalue()

    def close(self) -> None:
        pass


def create(sim: bool, width: int, height: int, quality: int, hflip: bool, vflip: bool) -> CameraSource:
    if sim:
        return SyntheticSource(width, height, quality)
    try:
        return PiCameraSource(width, height, quality, hflip, vflip)
    except ImportError as exc:
        raise RuntimeError(
            f"Picamera2 no disponible ({exc}). Usa --sim para correr sin cámara."
        ) from exc
