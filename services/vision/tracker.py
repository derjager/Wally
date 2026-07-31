"""Seguimiento de presencia con histéresis.

Un detector de objetos es ruidoso: pierde el objetivo un fotograma suelto
porque se giró, o lo detecta por error una vez. Sin filtrar, el robot anunciaría
"¡la gata!" y se callaría veinte veces en diez segundos.

La histéresis usa umbrales distintos para entrar y salir. Aparecer exige varias
detecciones seguidas —para no reaccionar a un falso positivo— pero desaparecer
exige bastantes más: que la gata se tape un momento no significa que se haya
ido, y perder el rastro es menos grave que perseguir un fantasma.
"""

from __future__ import annotations

from dataclasses import dataclass

from services.vision.detector import Detection


@dataclass(frozen=True)
class PresenceEvent:
    present: bool
    appeared: bool = False
    disappeared: bool = False
    detection: Detection | None = None


class PresenceTracker:
    def __init__(self, label: str, appear_hits: int = 3, disappear_misses: int = 12) -> None:
        self.label = label
        self._appear_hits = appear_hits
        self._disappear_misses = disappear_misses
        self._hits = 0
        self._misses = 0
        self._present = False
        self._last: Detection | None = None

    @property
    def present(self) -> bool:
        return self._present

    @property
    def last(self) -> Detection | None:
        return self._last

    def update(self, detections: list[Detection]) -> PresenceEvent:
        # Si hay varios, el más confiado manda.
        match = max(
            (d for d in detections if d.label == self.label),
            key=lambda d: d.score,
            default=None,
        )

        appeared = disappeared = False

        if match is not None:
            self._hits += 1
            self._misses = 0
            self._last = match
            if not self._present and self._hits >= self._appear_hits:
                self._present = True
                appeared = True
        else:
            self._misses += 1
            self._hits = 0
            if self._present and self._misses >= self._disappear_misses:
                self._present = False
                disappeared = True
                self._last = None

        return PresenceEvent(
            present=self._present,
            appeared=appeared,
            disappeared=disappeared,
            detection=self._last if self._present else None,
        )

    def snapshot(self) -> dict:
        d = self._last if self._present else None
        return {
            "present": self._present,
            "score": round(d.score, 3) if d else None,
            "bbox": [round(d.x, 4), round(d.y, 4), round(d.w, 4), round(d.h, 4)] if d else None,
            # Posición horizontal respecto al centro, en -1..1. Es lo que
            # necesita wally-brain para girar hacia ella en la Fase 6.
            "offset_x": round((d.center[0] - 0.5) * 2, 3) if d else None,
        }
