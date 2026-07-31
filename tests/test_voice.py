"""Pruebas de la cola de voz."""

from __future__ import annotations

import pytest

from services.voice.queue import SpeechQueue
from services.voice.tts import LogBackend


@pytest.fixture
def cola():
    return SpeechQueue(max_size=5, dedupe_window_s=8.0)


def test_ida_y_vuelta(cola):
    cola.push("hola", now=0.0)
    assert len(cola) == 1
    assert cola.pop().text == "hola"
    assert cola.pop() is None


def test_orden_de_llegada(cola):
    cola.push("uno", 0.0)
    cola.push("dos", 1.0)
    assert [cola.pop().text, cola.pop().text] == ["uno", "dos"]


def test_las_frases_vacias_se_ignoran(cola):
    assert cola.push("", 0.0) is False
    assert cola.push("   ", 0.0) is False
    assert len(cola) == 0


def test_no_repite_lo_mismo_seguido(cola):
    """Acercándose a una pared, el aviso llegaría muchas veces por segundo."""
    assert cola.push("obstáculo", 0.0) is True
    assert cola.push("obstáculo", 1.0) is False
    assert cola.push("obstáculo", 3.0) is False
    assert len(cola) == 1
    assert cola.dropped_duplicates == 2


def test_pasada_la_ventana_puede_repetirse(cola):
    cola.push("obstáculo", 0.0)
    assert cola.push("obstáculo", 9.0) is True


def test_lo_urgente_ignora_el_filtro_de_repeticion(cola):
    cola.push("cuidado", 0.0)
    assert cola.push("cuidado", 1.0, urgent=True) is True


def test_lo_urgente_se_dice_antes(cola):
    cola.push("una cosa sin importancia", 0.0)
    cola.push("otra cosa cualquiera", 0.1)
    cola.push("batería baja", 0.2, urgent=True)

    assert cola.pop().text == "batería baja"


def test_los_urgentes_conservan_su_orden_entre_si(cola):
    cola.push("normal", 0.0)
    cola.push("urgente primero", 0.1, urgent=True)
    cola.push("urgente segundo", 0.2, urgent=True)

    assert cola.pop().text == "urgente primero"
    assert cola.pop().text == "urgente segundo"
    assert cola.pop().text == "normal"


def test_al_desbordar_se_tira_lo_viejo(cola):
    """Lo reciente es lo relevante: comentar algo de hace un minuto es peor
    que perderlo."""
    for i in range(8):
        cola.push(f"frase {i}", float(i))

    assert len(cola) == 5
    assert cola.dropped_overflow == 3
    # Sobreviven las últimas, no las primeras.
    assert cola.pop().text == "frase 3"


def test_al_desbordar_se_protege_lo_urgente(cola):
    cola.push("aviso importante", 0.0, urgent=True)
    for i in range(10):
        cola.push(f"charla {i}", float(i + 1))

    textos = []
    while (item := cola.pop()) is not None:
        textos.append(item.text)

    assert "aviso importante" in textos


def test_clear_vacia_la_cola(cola):
    cola.push("a", 0.0)
    cola.push("b", 1.0)
    cola.clear()
    assert len(cola) == 0


# -- backend ---------------------------------------------------------------


def test_el_backend_de_log_registra_lo_dicho():
    b = LogBackend()
    assert b.say("hola gatita") is True
    assert b.spoken == ["hola gatita"]
