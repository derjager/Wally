"""Clasificación de gestos táctiles: solo por duración, sin coordenadas."""

from __future__ import annotations

from types import SimpleNamespace

import pygame
import pytest

from common.config import FaceConfig
from services.face.__main__ import _TouchGestures


def _event(kind: int) -> SimpleNamespace:
    return SimpleNamespace(type=kind)


@pytest.fixture
def gestures():
    calls = {"tap": 0, "hold": 0}
    cfg = FaceConfig(touch_tap_max_s=0.6, touch_hold_s=3.0)
    touch = _TouchGestures(
        cfg,
        on_tap=lambda: calls.__setitem__("tap", calls["tap"] + 1),
        on_hold=lambda: calls.__setitem__("hold", calls["hold"] + 1),
    )
    return touch, calls


def test_toque_corto_dispara_tap_al_soltar(gestures):
    touch, calls = gestures
    touch.handle_event(_event(pygame.MOUSEBUTTONDOWN), now=100.0)
    touch.handle_event(_event(pygame.MOUSEBUTTONUP), now=100.3)
    assert calls == {"tap": 1, "hold": 0}


def test_toque_sostenido_dispara_hold_sin_esperar_a_soltar(gestures):
    touch, calls = gestures
    touch.handle_event(_event(pygame.FINGERDOWN), now=100.0)
    touch.poll(now=100.5)
    assert calls == {"tap": 0, "hold": 0}
    touch.poll(now=103.0)
    assert calls == {"tap": 0, "hold": 1}
    # Soltar después de un hold ya disparado no debe además contar como tap.
    touch.handle_event(_event(pygame.FINGERUP), now=103.5)
    assert calls == {"tap": 0, "hold": 1}


def test_toque_a_medio_camino_no_dispara_nada(gestures):
    """Ni tan corto como para ser tap ni tan largo como para ser hold."""
    touch, calls = gestures
    touch.handle_event(_event(pygame.MOUSEBUTTONDOWN), now=100.0)
    touch.handle_event(_event(pygame.MOUSEBUTTONUP), now=101.5)
    assert calls == {"tap": 0, "hold": 0}


def test_eventos_no_tactiles_se_ignoran(gestures):
    touch, calls = gestures
    touch.handle_event(_event(pygame.KEYDOWN), now=100.0)
    touch.poll(now=200.0)
    assert calls == {"tap": 0, "hold": 0}
