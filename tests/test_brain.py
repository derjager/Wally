"""Pruebas de comportamiento autónomo.

Lo que se puede validar sin robot son las **decisiones**: que ante un obstáculo
gire en vez de seguir, que no se quede vibrando contra una pared, que ceda el
control al mando manual. Lo que NO se valida aquí es si las velocidades y
tiempos concretos funcionan sobre el suelo real: eso depende del chasis y hay
que afinarlo con el robot montado.
"""

from __future__ import annotations

import pytest

from common.config import BrainConfig, Config
from services.brain.behaviors import (
    Drive,
    PatrolBehavior,
    PatrolPhase,
    Perception,
    follow_cat,
)
from services.brain.service import BrainService


@pytest.fixture
def cfg():
    return BrainConfig()


@pytest.fixture
def patrol(cfg):
    return PatrolBehavior(cfg)


# -- primitivas ------------------------------------------------------------


def test_giro_sobre_el_sitio_mueve_las_orugas_en_sentidos_opuestos():
    d = Drive.spin(0.6, direction=1)
    assert d.left == pytest.approx(0.6)
    assert d.right == pytest.approx(-0.6)


def test_el_lado_mas_libre_es_el_que_tiene_mas_espacio():
    assert Perception(left_mm=200, right_mm=900).freest_side() == 1
    assert Perception(left_mm=900, right_mm=200).freest_side() == -1


def test_sin_lecturas_laterales_elige_un_lado_estable():
    """Alternar al azar produciría bailes en las esquinas."""
    p = Perception()
    assert p.freest_side() == p.freest_side()


def test_un_sensor_sin_eco_no_cuenta_como_obstaculo():
    """`None` es "sin eco", que casi siempre significa nada delante."""
    assert Perception(front_mm=None).blocked(300) is False


# -- patrulla --------------------------------------------------------------


def test_con_el_camino_libre_avanza(patrol, cfg):
    d = patrol.update(Perception(front_mm=2000), now=0.0)
    assert d.left > 0 and d.left == pytest.approx(d.right)
    assert patrol.phase == PatrolPhase.CRUISE


def test_ante_un_obstaculo_gira(patrol, cfg):
    d = patrol.update(Perception(front_mm=cfg.stop_mm - 50, left_mm=200, right_mm=900), 0.0)
    assert patrol.phase == PatrolPhase.TURN
    assert d.left * d.right < 0, "debería girar sobre el sitio"
    assert d.left > 0, "hacia el lado más libre, que es la derecha"


def test_muy_pegado_retrocede_antes_de_girar(patrol, cfg):
    """Girar rozando la pared engancharía las orugas."""
    d = patrol.update(Perception(front_mm=cfg.backup_mm - 20), 0.0)
    assert patrol.phase == PatrolPhase.BACKUP
    assert d.left < 0 and d.right < 0


def test_el_retroceso_dura_un_tiempo_minimo(patrol, cfg):
    patrol.update(Perception(front_mm=cfg.backup_mm - 20), 0.0)
    d = patrol.update(Perception(front_mm=cfg.backup_mm - 20), cfg.backup_s / 2)
    assert d.left < 0, "no debería haber salido aún del retroceso"


def test_tras_retroceder_pasa_a_girar(patrol, cfg):
    patrol.update(Perception(front_mm=100), 0.0)
    d = patrol.update(Perception(front_mm=200, left_mm=900, right_mm=100), cfg.backup_s + 0.1)
    assert patrol.phase == PatrolPhase.TURN
    assert d.left * d.right < 0


def test_el_giro_no_se_abandona_al_primer_hueco(patrol, cfg):
    """Sin un tiempo mínimo, el robot vibra contra la pared en vez de rodearla."""
    patrol.update(Perception(front_mm=cfg.stop_mm - 50), 0.0)
    assert patrol.phase == PatrolPhase.TURN

    d = patrol.update(Perception(front_mm=5000), cfg.turn_min_s / 2)
    assert patrol.phase == PatrolPhase.TURN
    assert d.left * d.right < 0


def test_el_giro_termina_cuando_hay_espacio_de_sobra(patrol, cfg):
    patrol.update(Perception(front_mm=cfg.stop_mm - 50), 0.0)
    d = patrol.update(Perception(front_mm=cfg.clear_mm + 200), cfg.turn_min_s + 0.1)
    assert patrol.phase == PatrolPhase.CRUISE
    assert d.left == pytest.approx(d.right)


def test_no_sale_del_giro_en_el_limite_justo(patrol, cfg):
    """clear_mm > stop_mm a propósito: salir justo en el umbral haría que se
    bloquease otra vez al instante."""
    assert cfg.clear_mm > cfg.stop_mm

    patrol.update(Perception(front_mm=cfg.stop_mm - 50), 0.0)
    patrol.update(Perception(front_mm=cfg.stop_mm + 10), cfg.turn_min_s + 0.1)
    assert patrol.phase == PatrolPhase.TURN


def test_acercarse_mientras_gira_interrumpe_el_giro(patrol, cfg):
    """Al girar junto a una pared, una esquina puede acercarse por debajo del
    umbral. Seguir girando raspa las orugas contra el obstáculo, y esperar al
    turn_timeout serían varios segundos rozando."""
    patrol.update(Perception(front_mm=cfg.stop_mm - 50, left_mm=300, right_mm=1200), 0.0)
    assert patrol.phase == PatrolPhase.TURN

    d = patrol.update(Perception(front_mm=cfg.backup_mm - 40), 0.2)

    assert patrol.phase == PatrolPhase.BACKUP
    assert d.left < 0 and d.right < 0


def test_girar_sin_salida_acaba_retrocediendo(patrol, cfg):
    """Metido en un rincón, girar eternamente no lo saca."""
    patrol.update(Perception(front_mm=cfg.stop_mm - 50), 0.0)

    t = cfg.turn_min_s
    for _ in range(200):
        t += 0.1
        d = patrol.update(Perception(front_mm=200), t)
        if patrol.phase == PatrolPhase.BACKUP:
            break

    assert patrol.phase == PatrolPhase.BACKUP
    assert d.left < 0


def test_reset_vuelve_a_crucero(patrol, cfg):
    patrol.update(Perception(front_mm=100), 0.0)
    patrol.reset()
    assert patrol.phase == PatrolPhase.CRUISE


# -- seguir a la gata ------------------------------------------------------


def test_sin_gata_no_se_mueve(cfg):
    d = follow_cat(Perception(cat_present=False), cfg)
    assert d == Drive.stop()


def test_gata_descentrada_gira_hacia_ella(cfg):
    d = follow_cat(Perception(cat_present=True, cat_offset_x=-0.8, cat_area=0.02), cfg)
    assert d.left * d.right < 0
    assert d.left < 0, "la gata está a la izquierda"


def test_gata_encarada_avanza(cfg):
    d = follow_cat(Perception(cat_present=True, cat_offset_x=0.05, cat_area=0.02), cfg)
    assert d.left > 0 and d.right > 0


def test_se_para_cuando_ya_esta_cerca(cfg):
    """Frena por tamaño en la imagen: el ultrasonido no detecta pelaje, así que
    fiarse de los sensores sería justo el error que no se puede cometer."""
    d = follow_cat(
        Perception(cat_present=True, cat_offset_x=0.0, cat_area=cfg.follow_stop_area + 0.05),
        cfg,
    )
    assert d == Drive.stop()


def test_persigue_despacio(cfg):
    """Va más lento que patrullando: no se puede confiar en los sensores para
    no atropellarla."""
    assert cfg.follow_speed < cfg.cruise_speed

    d = follow_cat(Perception(cat_present=True, cat_offset_x=0.0, cat_area=0.02), cfg)
    assert max(abs(d.left), abs(d.right)) <= cfg.follow_speed + 0.01


def test_un_obstaculo_detiene_la_persecucion(cfg):
    """La gata no es lo único que puede haber delante."""
    d = follow_cat(
        Perception(cat_present=True, cat_offset_x=0.0, cat_area=0.02,
                   front_mm=cfg.stop_mm - 50),
        cfg,
    )
    assert d == Drive.stop()


def test_las_velocidades_nunca_se_salen_de_rango(cfg):
    for offset in (-1.0, -0.3, 0.0, 0.3, 1.0):
        d = follow_cat(
            Perception(cat_present=True, cat_offset_x=offset, cat_area=0.02), cfg
        )
        assert -1.0 <= d.left <= 1.0
        assert -1.0 <= d.right <= 1.0


# -- servicio y arbitraje --------------------------------------------------


class FakeBus:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict]] = []
        self.subscriptions: dict = {}

    def subscribe(self, topic, handler):
        self.subscriptions[topic] = handler

    def publish(self, topic, payload, retain=False):
        self.published.append((topic, payload))


@pytest.fixture
def brain():
    bus = FakeBus()
    return BrainService(Config(), bus), bus


def test_parado_no_publica_nada(brain):
    """Sin publicar, el watchdog de motion frena. Es el comportamiento correcto."""
    service, bus = brain
    service.set_mode("idle", 0.0)
    assert service.step(1.0) is None


def test_teleoperado_no_estorba(brain):
    """En manual, brain debe callarse por completo."""
    service, bus = brain
    service.set_mode("teleop", 0.0)
    assert service.step(1.0) is None

    drives = [p for t, p in bus.published if t.endswith("cmd/drive")]
    assert drives == []


def test_patrullando_publica_aunque_decida_pararse(brain):
    """Publicar ceros explícitos mantiene viva la cadena del watchdog y
    distingue "quieto a propósito" de "murió el que mandaba"."""
    service, bus = brain
    service.set_mode("patrol", 0.0)
    service._on_sensors({"front": 2000.0})

    d = service.step(1.0)
    assert d is not None
    drives = [p for t, p in bus.published if t.endswith("cmd/drive")]
    assert len(drives) == 1


def test_los_comandos_llevan_marca_de_origen(brain):
    """Sin `src`, brain no distinguiría sus propios comandos de los del
    joystick y se cedería el paso a sí mismo eternamente."""
    service, bus = brain
    service.set_mode("patrol", 0.0)
    service._on_sensors({"front": 2000.0})
    service.step(1.0)

    drive = next(p for t, p in bus.published if t.endswith("cmd/drive"))
    assert drive["src"] == "brain"


def test_el_mando_manual_silencia_a_brain(brain):
    service, bus = brain
    service.set_mode("patrol", 0.0)
    service._on_sensors({"front": 2000.0})
    assert service.decide(1.0) is not None

    service._on_drive({"left": 1.0, "right": 1.0, "src": "web"})
    assert service.manual_override is True
    assert service.decide(1.0) is None


def test_brain_no_se_cede_el_paso_a_si_mismo(brain):
    service, bus = brain
    service.set_mode("patrol", 0.0)
    service._on_drive({"left": 0.5, "right": 0.5, "src": "brain"})
    assert service.manual_override is False


def test_el_control_manual_caduca(brain):
    service, bus = brain
    cfg = Config().brain
    service.set_mode("patrol", 0.0)
    service._on_sensors({"front": 2000.0})
    service._on_drive({"left": 1.0, "right": 1.0, "src": "web"})

    import time
    service._manual_until = time.monotonic() - 0.1   # como si ya hubiera pasado
    assert service.decide(time.monotonic()) is not None


def test_cambiar_de_modo_reinicia_la_patrulla(brain):
    service, bus = brain
    service.set_mode("patrol", 0.0)
    service._on_sensors({"front": 100.0})
    service.step(1.0)
    assert service._patrol.phase != PatrolPhase.CRUISE

    service.set_mode("follow_cat", 2.0)
    assert service._patrol.phase == PatrolPhase.CRUISE


def test_un_modo_invalido_se_ignora(brain):
    service, bus = brain
    service.set_mode("patrol", 0.0)
    service._on_mode({"mode": "bailar_salsa"})
    assert service.mode == "patrol"


def test_patrullando_la_gata_tiene_prioridad(brain):
    service, bus = brain
    service.set_mode("patrol", 0.0)
    service._on_sensors({"front": 2000.0})
    service._on_cat({"present": True, "offset_x": 0.9, "bbox": [0.4, 0.4, 0.1, 0.1]})

    d = service.decide(1.0)
    assert d is not None and d.left * d.right < 0, "debería girar hacia ella"


def test_saluda_a_la_gata_una_sola_vez(brain):
    service, bus = brain
    service.set_mode("follow_cat", 0.0)
    service._on_cat({"present": True, "offset_x": 0.0, "bbox": [0.4, 0.4, 0.1, 0.1]})

    for t in range(5):
        service.step(float(t))

    saludos = [p for t, p in bus.published if t.endswith("cmd/say")]
    assert len(saludos) == 1


def test_vuelve_a_saludar_tras_perderla_y_reencontrarla(brain):
    service, bus = brain
    service.set_mode("follow_cat", 0.0)
    service._on_cat({"present": True, "offset_x": 0.0, "bbox": [0.4, 0.4, 0.1, 0.1]})
    service.step(1.0)
    service._on_cat({"present": False})
    service.step(2.0)
    service._on_cat({"present": True, "offset_x": 0.0, "bbox": [0.4, 0.4, 0.1, 0.1]})
    service.step(3.0)

    saludos = [p for t, p in bus.published if t.endswith("cmd/say")]
    assert len(saludos) == 2
