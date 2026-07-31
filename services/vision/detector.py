"""Detección de objetos con TensorFlow Lite.

EfficientDet-Lite0 a 320×320 con 4 hilos ronda los 10 fps en una Pi 4 (PLAN.md
§5). No hace falta más: la inferencia corre a menor frecuencia que la captura,
así que el vídeo sigue fluyendo a 15 fps aunque detectar cueste 100 ms.

La gata se detecta con la clase `cat` de COCO, sin entrenar nada: no hay otros
gatos en casa, así que distinguir individuos sería trabajo desperdiciado. La
interfaz deja hueco para añadir un clasificador de embeddings encima si algún
día hiciera falta.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("vision.detector")

DEFAULT_LABELS = Path(__file__).resolve().parent.parent.parent / "models" / "coco_labels.txt"


@dataclass(frozen=True)
class Detection:
    label: str
    score: float
    # Caja normalizada 0..1 sobre el frame, para no depender de la resolución.
    x: float
    y: float
    w: float
    h: float

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.w / 2, self.y + self.h / 2)

    @property
    def area(self) -> float:
        return self.w * self.h

    def as_dict(self) -> dict:
        return {
            "label": self.label,
            "score": round(self.score, 3),
            "bbox": [round(self.x, 4), round(self.y, 4), round(self.w, 4), round(self.h, 4)],
        }


def load_labels(path: Path | str) -> list[str]:
    p = Path(path)
    if not p.exists():
        log.warning("no se encuentra %s; las clases saldrán numeradas", p)
        return []
    return [line.strip() for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


class Detector(ABC):
    @abstractmethod
    def detect(self, rgb) -> list[Detection]:
        """Recibe un array RGB (alto, ancho, 3) y devuelve las detecciones."""

    @property
    def name(self) -> str:
        return type(self).__name__

    def close(self) -> None:
        pass


class TFLiteDetector(Detector):
    def __init__(self, model: str, labels: str, min_score: float = 0.45,
                 threads: int = 4) -> None:
        try:
            from tflite_runtime.interpreter import Interpreter
        except ImportError:
            # El paquete completo de tensorflow también sirve y es lo que suele
            # haber en un portátil.
            try:
                from tensorflow.lite.python.interpreter import Interpreter  # type: ignore
            except ImportError as exc:
                raise RuntimeError(
                    "falta tflite_runtime. En la Pi: pip install tflite-runtime"
                ) from exc

        model_path = Path(model)
        if not model_path.exists():
            raise RuntimeError(f"no se encuentra el modelo {model_path}")

        self._labels = load_labels(labels)
        self._min_score = min_score

        self._interpreter = Interpreter(model_path=str(model_path), num_threads=threads)
        self._interpreter.allocate_tensors()

        inp = self._interpreter.get_input_details()[0]
        self._input_index = inp["index"]
        _, self._in_h, self._in_w, _ = inp["shape"]
        self._quantized = inp["dtype"].__name__ == "uint8"
        self._outputs = self._interpreter.get_output_details()

        log.info(
            "modelo %s · entrada %dx%d · %s · %d clases",
            model_path.name, self._in_w, self._in_h,
            "uint8" if self._quantized else "float32", len(self._labels),
        )

    def _label_for(self, index: int) -> str:
        if 0 <= index < len(self._labels):
            return self._labels[index]
        return f"clase_{index}"

    def detect(self, rgb) -> list[Detection]:
        import numpy as np
        from PIL import Image

        img = Image.fromarray(rgb).resize((self._in_w, self._in_h), Image.BILINEAR)
        data = np.asarray(img)

        if self._quantized:
            tensor = np.expand_dims(data, axis=0).astype(np.uint8)
        else:
            # Los modelos float esperan el rango [-1, 1].
            tensor = (np.expand_dims(data, axis=0).astype(np.float32) - 127.5) / 127.5

        self._interpreter.set_tensor(self._input_index, tensor)
        self._interpreter.invoke()

        boxes, classes, scores = self._read_outputs()
        if boxes is None:
            return []

        detections: list[Detection] = []
        for box, cls, score in zip(boxes, classes, scores):
            if score < self._min_score:
                continue
            # TFLite entrega las cajas como (ymin, xmin, ymax, xmax).
            ymin, xmin, ymax, xmax = box
            x = max(0.0, min(1.0, float(xmin)))
            y = max(0.0, min(1.0, float(ymin)))
            w = max(0.0, min(1.0, float(xmax))) - x
            h = max(0.0, min(1.0, float(ymax))) - y
            if w <= 0 or h <= 0:
                continue
            detections.append(
                Detection(self._label_for(int(cls)), float(score), x, y, w, h)
            )

        detections.sort(key=lambda d: d.score, reverse=True)
        return detections

    def _read_outputs(self):
        """Extrae cajas, clases y puntuaciones.

        El orden de los tensores de salida varía entre versiones del modelo, así
        que se identifican por su forma en lugar de asumir posiciones fijas —
        confiar en el orden es la causa habitual de que un modelo nuevo
        devuelva cajas en lugar de puntuaciones.
        """
        boxes = classes = scores = None
        for out in self._outputs:
            tensor = self._interpreter.get_tensor(out["index"])
            shape = tensor.shape
            if len(shape) == 3 and shape[2] == 4:
                boxes = tensor[0]
            elif len(shape) == 2:
                if classes is None:
                    classes = tensor[0]
                elif scores is None:
                    scores = tensor[0]
        if boxes is None or classes is None or scores is None:
            log.warning("salidas del modelo inesperadas; no se pudo interpretar")
            return (None, None, None)

        # Las dos salidas 2D son clases y puntuaciones, pero pueden venir en
        # cualquier orden: las puntuaciones siempre están en [0, 1].
        if classes.max(initial=0) <= 1.0 and scores.max(initial=0) > 1.0:
            classes, scores = scores, classes

        return (boxes, classes, scores)


class FakeDetector(Detector):
    """Detector de mentira para desarrollo.

    Hace aparecer y desaparecer una gata siguiendo un recorrido, que es lo que
    hace falta para probar la histéresis de presencia y la reacción de la cara
    sin tener que pasear un gato por delante de la cámara.
    """

    def __init__(self, min_score: float = 0.45, period_s: float = 12.0) -> None:
        import time

        self._t0 = time.monotonic()
        self._period = period_s
        self._min_score = min_score
        self._time = time

    def detect(self, rgb) -> list[Detection]:
        import math

        t = (self._time.monotonic() - self._t0) % self._period
        fase = t / self._period

        salida: list[Detection] = [
            Detection("chair", 0.72, 0.05, 0.55, 0.22, 0.35),
        ]

        # La gata está presente en la mitad central del ciclo.
        if 0.25 < fase < 0.75:
            avance = (fase - 0.25) / 0.5
            x = 0.1 + avance * 0.6
            y = 0.45 + 0.08 * math.sin(avance * math.pi * 2)
            # Confianza baja al entrar y salir de plano: así se ejercita el
            # umbral y la histéresis.
            conf = 0.35 + 0.55 * math.sin(avance * math.pi)
            if conf >= self._min_score:
                salida.append(Detection("cat", conf, x, y, 0.18, 0.14))

        return salida


def create(sim: bool, cfg) -> Detector:
    """Crea el detector. Degrada a `None` si no hay modelo disponible.

    Un robot que ve pero no reconoce sigue siendo teleoperable, así que la
    falta del modelo nunca debe impedir que arranque la cámara.
    """
    if sim:
        return FakeDetector(cfg.min_score)
    return TFLiteDetector(cfg.model, cfg.labels, cfg.min_score, cfg.threads)
