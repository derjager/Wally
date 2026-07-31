"""Pruebas de detección y seguimiento de presencia."""

from __future__ import annotations

import pytest

from services.vision.detector import Detection, FakeDetector, load_labels
from services.vision.tracker import PresenceTracker


def cat(score: float = 0.9) -> Detection:
    return Detection("cat", score, 0.4, 0.4, 0.2, 0.2)


def chair() -> Detection:
    return Detection("chair", 0.8, 0.0, 0.5, 0.3, 0.4)


# -- detecciones -----------------------------------------------------------


def test_geometria_de_la_deteccion():
    d = Detection("cat", 0.9, x=0.2, y=0.3, w=0.4, h=0.2)
    assert d.center == pytest.approx((0.4, 0.4))
    assert d.area == pytest.approx(0.08)


def test_serializacion_para_mqtt():
    d = cat(0.87654)
    payload = d.as_dict()
    assert payload["label"] == "cat"
    assert payload["score"] == 0.877
    assert len(payload["bbox"]) == 4


def test_las_etiquetas_coco_incluyen_gato():
    from services.vision.detector import DEFAULT_LABELS

    labels = load_labels(DEFAULT_LABELS)
    assert "cat" in labels
    # El modelo usa índices sobre esta lista; si se descuadra, detectaría
    # "gato" y reportaría otra cosa.
    assert labels.index("cat") == 16
    assert len(labels) == 90


def test_etiquetas_inexistentes_no_revientan(tmp_path):
    assert load_labels(tmp_path / "no_existe.txt") == []


def test_el_detector_falso_produce_gatos_y_muebles():
    det = FakeDetector(min_score=0.3)
    vistos = set()
    for _ in range(40):
        for d in det.detect(None):
            vistos.add(d.label)
    assert "chair" in vistos


# -- histéresis de presencia -----------------------------------------------


@pytest.fixture
def tracker():
    return PresenceTracker("cat", appear_hits=3, disappear_misses=12)


def test_arranca_sin_presencia(tracker):
    assert tracker.present is False
    assert tracker.snapshot()["present"] is False


def test_hace_falta_evidencia_repetida_para_declarar_presencia(tracker):
    """Un solo fotograma no basta: sería reaccionar a un falso positivo."""
    assert tracker.update([cat()]).present is False
    assert tracker.update([cat()]).present is False
    evento = tracker.update([cat()])
    assert evento.present is True
    assert evento.appeared is True


def test_solo_se_avisa_de_la_aparicion_una_vez(tracker):
    for _ in range(3):
        tracker.update([cat()])
    assert tracker.update([cat()]).appeared is False


def test_una_perdida_breve_no_la_da_por_ida(tracker):
    """Que la gata se tape un momento no significa que se haya ido."""
    for _ in range(3):
        tracker.update([cat()])

    for _ in range(11):
        evento = tracker.update([chair()])
        assert evento.present is True, "se rindió demasiado pronto"


def test_una_ausencia_larga_si_la_da_por_ida(tracker):
    for _ in range(3):
        tracker.update([cat()])
    for _ in range(11):
        tracker.update([])

    evento = tracker.update([])
    assert evento.present is False
    assert evento.disappeared is True


def test_los_umbrales_son_asimetricos(tracker):
    """Aparecer exige poco; desaparecer, mucho más. Perder el rastro un
    instante es menos grave que perseguir un fantasma."""
    assert tracker._appear_hits < tracker._disappear_misses


def test_una_deteccion_intercalada_reinicia_la_cuenta_de_ausencias(tracker):
    for _ in range(3):
        tracker.update([cat()])
    for _ in range(10):
        tracker.update([])

    tracker.update([cat()])          # reaparece un instante
    for _ in range(10):
        assert tracker.update([]).present is True


def test_se_queda_con_la_deteccion_mas_confiada(tracker):
    flojo = Detection("cat", 0.5, 0.1, 0.1, 0.1, 0.1)
    fuerte = Detection("cat", 0.95, 0.6, 0.6, 0.2, 0.2)
    for _ in range(3):
        tracker.update([flojo, fuerte])

    assert tracker.last is not None
    assert tracker.last.score == pytest.approx(0.95)


def test_otras_clases_no_cuentan(tracker):
    for _ in range(10):
        tracker.update([chair()])
    assert tracker.present is False


def test_el_snapshot_da_el_desvio_para_poder_girar(tracker):
    """wally-brain necesita saber a qué lado está para girar hacia ella."""
    izquierda = Detection("cat", 0.9, 0.0, 0.4, 0.2, 0.2)   # centro en x=0.1
    for _ in range(3):
        tracker.update([izquierda])

    snap = tracker.snapshot()
    assert snap["present"] is True
    assert snap["offset_x"] == pytest.approx(-0.8)


def test_el_snapshot_se_vacia_al_desaparecer(tracker):
    for _ in range(3):
        tracker.update([cat()])
    for _ in range(12):
        tracker.update([])

    snap = tracker.snapshot()
    assert snap["present"] is False
    assert snap["bbox"] is None
    assert snap["offset_x"] is None
