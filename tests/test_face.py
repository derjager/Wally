"""Pruebas de la cara: reglas de ánimo, transiciones y parpadeo."""

from __future__ import annotations

import random

import pytest

from common.config import FaceConfig
from services.face import expressions as ex
from services.face.state import OBSTACLE_MM, FaceState, Inputs


@pytest.fixture
def face():
    # Semilla fija: el parpadeo y las sacadas usan azar, y una prueba que
    # falla una vez de cada diez no sirve para nada.
    return FaceState(FaceConfig(sleepy_after_s=60.0), rng=random.Random(1234))


# -- expresiones -----------------------------------------------------------


def test_todos_los_animos_existen():
    for mood in ("idle", "happy", "curious", "alert", "sleepy", "teleop", "grumpy", "surprised"):
        assert mood in ex.EXPRESSIONS


def test_un_animo_desconocido_cae_en_idle():
    assert ex.get("no_existe") == ex.EXPRESSIONS["idle"]


def test_blend_en_los_extremos_devuelve_los_originales():
    a, b = ex.get("idle"), ex.get("alert")
    assert ex.blend(a, b, 0.0).eye_height == pytest.approx(a.eye_height)
    assert ex.blend(a, b, 1.0).eye_height == pytest.approx(b.eye_height)


def test_blend_intermedio_queda_entre_ambos():
    a, b = ex.get("sleepy"), ex.get("alert")
    medio = ex.blend(a, b, 0.5)
    assert min(a.eye_height, b.eye_height) < medio.eye_height < max(a.eye_height, b.eye_height)


def test_el_parpadeo_se_compone_sin_perder_la_expresion():
    """Wally debe poder parpadear estando contento sin dejar de estarlo."""
    feliz = ex.get("happy")
    parpadeando = ex.with_blink(feliz, 0.8)
    assert parpadeando.lid == pytest.approx(0.8)
    assert parpadeando.curve == feliz.curve  # sigue sonriendo


def test_la_curva_de_parpadeo_empieza_y_acaba_abierta():
    assert ex.blink_curve(0.0) == 0.0
    assert ex.blink_curve(1.0) == 0.0
    assert ex.blink_curve(0.45) == pytest.approx(1.0)


def test_la_boca_solo_se_anima_al_hablar():
    base = ex.get("idle")
    callado = ex.with_speech(base, 0.5, speaking=False)
    hablando = ex.with_speech(base, 0.5, speaking=True)
    assert callado.mouth_open == base.mouth_open
    assert hablando.mouth_open > 0


# -- reglas de ánimo -------------------------------------------------------


def test_en_reposo_esta_idle(face):
    face.set_inputs(Inputs(), 100.0)
    assert face.resolve_mood(100.0) == "idle"


def test_moverse_pone_cara_de_teleoperado(face):
    face.set_inputs(Inputs(moving=True), 100.0)
    assert face.resolve_mood(100.0) == "teleop"


def test_un_obstaculo_cercano_pone_alerta(face):
    face.set_inputs(Inputs(closest_mm=OBSTACLE_MM - 50), 100.0)
    assert face.resolve_mood(100.0) == "alert"


def test_un_obstaculo_lejano_no_alarma(face):
    face.set_inputs(Inputs(closest_mm=OBSTACLE_MM + 500), 100.0)
    assert face.resolve_mood(100.0) == "idle"


def test_el_estop_manda_sobre_todo_lo_demas(face):
    """Aunque le hayan pedido estar contento, si hay parada de emergencia la
    cara debe reflejarlo: es información de seguridad."""
    face.command_mood("happy", hold_s=60.0, now=100.0)
    face.set_inputs(Inputs(estop=True, moving=True, closest_mm=100.0), 100.0)
    assert face.resolve_mood(101.0) == "grumpy"


def test_un_animo_pedido_gana_a_las_reglas_ambientales(face):
    face.set_inputs(Inputs(), 100.0)
    face.command_mood("surprised", hold_s=5.0, now=100.0)
    assert face.resolve_mood(102.0) == "surprised"


def test_el_animo_pedido_caduca(face):
    face.set_inputs(Inputs(), 100.0)
    face.command_mood("surprised", hold_s=3.0, now=100.0)
    assert face.resolve_mood(101.0) == "surprised"
    assert face.resolve_mood(105.0) == "idle"


def test_un_animo_inventado_se_ignora(face):
    face.set_inputs(Inputs(), 100.0)
    face.command_mood("euforia_cosmica", hold_s=10.0, now=100.0)
    assert face.resolve_mood(101.0) == "idle"


def test_tras_mucha_inactividad_se_adormece(face):
    face.set_inputs(Inputs(), 100.0)
    assert face.resolve_mood(100.0 + 61.0) == "sleepy"


def test_la_actividad_despierta(face):
    face.set_inputs(Inputs(), 100.0)
    assert face.resolve_mood(200.0) == "sleepy"

    face.set_inputs(Inputs(moving=True), 200.0)
    assert face.resolve_mood(201.0) == "teleop"

    face.set_inputs(Inputs(), 201.0)
    assert face.resolve_mood(202.0) == "idle"


def test_hablar_tambien_cuenta_como_actividad(face):
    face.set_inputs(Inputs(), 100.0)
    face.set_inputs(Inputs(speaking=True), 150.0)
    assert face.resolve_mood(160.0) != "sleepy"


def test_ver_a_la_gata_pone_contento(face):
    face.set_inputs(Inputs(cat_visible=True), 100.0)
    assert face.resolve_mood(100.0) == "happy"


def test_la_gata_gana_a_conducir(face):
    """Es lo más interesante que le pasa a este robot."""
    face.set_inputs(Inputs(cat_visible=True, moving=True), 100.0)
    assert face.resolve_mood(100.0) == "happy"


def test_un_obstaculo_gana_a_la_gata(face):
    """Chocar es peor que perderse el saludo."""
    face.set_inputs(Inputs(cat_visible=True, closest_mm=100.0), 100.0)
    assert face.resolve_mood(100.0) == "alert"


def test_ver_a_la_gata_despierta(face):
    face.set_inputs(Inputs(), 100.0)
    assert face.resolve_mood(200.0) == "sleepy"

    face.set_inputs(Inputs(cat_visible=True), 200.0)
    assert face.resolve_mood(201.0) == "happy"


# -- animación -------------------------------------------------------------


def test_la_transicion_entre_animos_es_gradual(face):
    """Un salto seco entre expresiones se ve mecánico."""
    face.set_inputs(Inputs(), 100.0)
    face.update(0.033, 100.0)
    partida = face.update(0.033, 100.033)

    face.command_mood("alert", hold_s=10.0, now=100.1)
    a_medias = face.update(0.1, 100.2)
    destino = ex.get("alert")

    assert a_medias.eye_height != pytest.approx(partida.eye_height)
    assert a_medias.eye_height != pytest.approx(destino.eye_height)


def test_la_transicion_termina_llegando_al_destino(face):
    face.set_inputs(Inputs(), 100.0)
    face.command_mood("alert", hold_s=30.0, now=100.0)

    t = 100.0
    for _ in range(60):
        expr = face.update(0.033, t)
        t += 0.033

    destino = ex.get("alert")
    assert expr.eye_height == pytest.approx(destino.eye_height, abs=0.01)


def test_dormido_no_parpadea(face):
    """Ya tiene los párpados caídos; parpadear encima se ve raro."""
    face.set_inputs(Inputs(), 100.0)
    t = 200.0
    for _ in range(200):
        expr = face.update(0.033, t)
        t += 0.033
    assert face.mood == "sleepy"
    assert expr.lid == pytest.approx(ex.get("sleepy").lid, abs=0.01)


def test_parpadea_alguna_vez(face):
    face.set_inputs(Inputs(), 0.0)
    t = 0.0
    vistos = []
    for _ in range(1200):   # ~40 s
        expr = face.update(0.033, t)
        vistos.append(expr.lid)
        t += 0.033
    assert max(vistos) > 0.5, "nunca parpadeó"


def test_la_mirada_se_mantiene_en_rango(face):
    face.look_at(5.0, -9.0)
    assert face.look_x == 1.0
    assert face.look_y == -1.0


def test_teleoperado_mira_al_frente(face):
    """Conduciendo, unos ojos que vagan distraen; mejor mirada fija."""
    face.set_inputs(Inputs(moving=True), 100.0)
    t = 100.0
    for _ in range(30):
        face.update(0.033, t)
        t += 0.033
    assert face.look_x == 0.0 and face.look_y == 0.0
