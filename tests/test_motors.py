"""Pruebas de la lógica de tracción: rampa, tope de duty y mezcla de joystick."""

from __future__ import annotations

import pytest

from common.config import MotionConfig
from services.motion.backend import SimBackend
from services.motion.motors import (
    DifferentialDrive,
    approach,
    clamp,
    mix_arcade,
    ramp_step,
)


# -- funciones puras -------------------------------------------------------


def test_approach_no_sobrepasa_el_objetivo():
    assert approach(0.0, 1.0, 0.3) == pytest.approx(0.3)
    assert approach(0.9, 1.0, 0.3) == pytest.approx(1.0)
    assert approach(0.0, -1.0, 0.3) == pytest.approx(-0.3)


def test_clamp_limita_entradas_fuera_de_rango():
    assert clamp(5.0) == 1.0
    assert clamp(-5.0) == -1.0
    assert clamp(0.5) == 0.5


def test_frenar_es_mas_rapido_que_acelerar():
    """La rampa es asimétrica a propósito: es lo que hace útil al watchdog."""
    acelerando = ramp_step(0.0, 1.0, dt=0.1, up_per_s=2.0, down_per_s=6.0)
    frenando = ramp_step(1.0, 0.0, dt=0.1, up_per_s=2.0, down_per_s=6.0)
    assert acelerando == pytest.approx(0.2)
    assert 1.0 - frenando == pytest.approx(0.6)


def test_invertir_marcha_pasa_por_cero():
    """Nunca se salta de adelante a atrás de golpe: destrozaría el driver."""
    v = 1.0
    cruces = []
    for _ in range(40):
        v = ramp_step(v, -1.0, dt=0.02, up_per_s=2.0, down_per_s=6.0)
        cruces.append(v)
    # Alcanza el objetivo, y ningún paso individual salta de un signo a otro
    # con magnitud alta.
    assert v == pytest.approx(-1.0, abs=0.01)
    for a, b in zip(cruces, cruces[1:]):
        assert abs(b - a) < 0.2


def test_mix_arcade_normaliza_en_lugar_de_saturar():
    left, right = mix_arcade(throttle=1.0, steer=1.0)
    assert max(abs(left), abs(right)) == pytest.approx(1.0)
    # La proporción entre orugas se conserva tras normalizar.
    assert left == pytest.approx(1.0)
    assert right == pytest.approx(0.0)


def test_mix_arcade_giro_en_el_sitio():
    left, right = mix_arcade(throttle=0.0, steer=1.0)
    assert left == pytest.approx(1.0)
    assert right == pytest.approx(-1.0)


# -- driver ----------------------------------------------------------------


@pytest.fixture
def drive():
    io = SimBackend()
    cfg = MotionConfig()
    return DifferentialDrive(io, cfg), io, cfg


def test_el_tope_de_duty_se_respeta_a_fondo(drive):
    """A pleno comando la salida física no supera duty_cap.

    Es la protección de los motores de 3V frente al riel de 4.8V.
    """
    d, io, cfg = drive
    d.set_target(1.0, 1.0)
    for _ in range(200):
        d.update(0.02)

    assert io.duties[cfg.left.pwm] == pytest.approx(cfg.duty_cap)
    assert io.duties[cfg.right.pwm] == pytest.approx(cfg.duty_cap)
    assert io.duties[cfg.left.pwm] <= 0.60


def test_detenerse_aplica_freno_corto(drive):
    d, io, cfg = drive
    d.set_target(0.0, 0.0)
    d.update(0.02)
    # IN1 e IN2 ambos en alto = short brake en el TB6612.
    assert io.outputs[cfg.left.in1] == 1
    assert io.outputs[cfg.left.in2] == 1
    assert io.duties[cfg.left.pwm] == 0.0


def test_marcha_atras_invierte_los_pines_de_direccion(drive):
    d, io, cfg = drive
    d.set_target(-1.0, -1.0)
    for _ in range(100):
        d.update(0.02)
    assert io.outputs[cfg.left.in1] == 0
    assert io.outputs[cfg.left.in2] == 1


def test_estop_corta_por_hardware_sin_rampa(drive):
    d, io, cfg = drive
    d.set_target(1.0, 1.0)
    for _ in range(100):
        d.update(0.02)
    assert io.duties[cfg.left.pwm] > 0

    d.estop()

    # STBY a nivel bajo deshabilita el driver de inmediato.
    assert io.outputs[cfg.standby] == 0
    assert io.duties[cfg.left.pwm] == 0.0
    assert d.estop_engaged


def test_estop_ignora_comandos_hasta_ser_liberado(drive):
    d, io, cfg = drive
    d.estop()
    d.set_target(1.0, 1.0)
    for _ in range(100):
        d.update(0.02)
    assert io.duties[cfg.left.pwm] == 0.0

    d.clear_estop()
    assert io.outputs[cfg.standby] == 1
    d.set_target(1.0, 1.0)
    for _ in range(100):
        d.update(0.02)
    assert io.duties[cfg.left.pwm] == pytest.approx(cfg.duty_cap)


def test_invert_corrige_una_oruga_al_reves():
    io = SimBackend()
    cfg = MotionConfig()
    d = DifferentialDrive(io, cfg)
    d.set_target(1.0, 1.0)
    for _ in range(100):
        d.update(0.02)
    sin_invertir = io.outputs[cfg.left.in1]

    io2 = SimBackend()
    cfg2 = MotionConfig()
    object.__setattr__(cfg2.left, "invert", True)
    d2 = DifferentialDrive(io2, cfg2)
    d2.set_target(1.0, 1.0)
    for _ in range(100):
        d2.update(0.02)

    assert io2.outputs[cfg2.left.in1] != sin_invertir


def test_shutdown_deja_todo_a_cero(drive):
    d, io, cfg = drive
    d.set_target(1.0, 1.0)
    for _ in range(100):
        d.update(0.02)

    d.shutdown()

    assert io.duties[cfg.left.pwm] == 0.0
    assert io.duties[cfg.right.pwm] == 0.0
    assert io.outputs[cfg.standby] == 0
