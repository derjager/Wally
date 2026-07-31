"""Pruebas del watchdog: la garantía de seguridad de la que depende todo.

Si estas pruebas fallan, el robot puede quedar en marcha tras perder la red.
"""

from __future__ import annotations

import pytest

from common.config import Config
from services.motion.backend import SimBackend
from services.motion.service import MotionService


@pytest.fixture
def svc():
    io = SimBackend()
    cfg = Config()
    return MotionService(cfg, io, bus=None), io, cfg


def _correr(service, io, cfg, duracion_s: float, t0: float = 1000.0) -> float:
    """Avanza el lazo con un reloj simulado. Devuelve el instante final."""
    dt = 1.0 / cfg.motion.control_hz
    t = t0
    fin = t0 + duracion_s
    while t < fin:
        service.step(dt, t)
        t += dt
    return t


def test_arranca_frenado_sin_comandos(svc):
    """Antes del primer comando el robot no se mueve, pase lo que pase."""
    service, io, cfg = svc
    t = _correr(service, io, cfg, 1.0)
    assert io.duties[cfg.motion.left.pwm] == 0.0


def test_avanza_mientras_llegan_comandos(svc):
    service, io, cfg = svc
    t = 1000.0
    dt = 1.0 / cfg.motion.control_hz
    for _ in range(100):
        service._on_drive({"left": 1.0, "right": 1.0})
        # El handler marca la hora con time.monotonic() real, así que aquí se
        # fuerza el sello para que el reloj simulado sea coherente.
        service._shared.drive_ts = t
        service.step(dt, t)
        t += dt

    assert io.duties[cfg.motion.left.pwm] > 0.0


def test_frena_al_expirar_el_watchdog(svc):
    """Se corta el flujo de comandos y el robot debe detenerse solo."""
    service, io, cfg = svc
    t = 1000.0
    dt = 1.0 / cfg.motion.control_hz

    for _ in range(100):
        service._on_drive({"left": 1.0, "right": 1.0})
        service._shared.drive_ts = t
        service.step(dt, t)
        t += dt
    assert io.duties[cfg.motion.left.pwm] > 0.0

    # Silencio: nadie vuelve a publicar.
    t = _correr(service, io, cfg, 1.0, t0=t)

    assert io.duties[cfg.motion.left.pwm] == 0.0
    assert io.outputs[cfg.motion.left.in1] == 1  # freno corto
    assert io.outputs[cfg.motion.left.in2] == 1


def test_el_frenado_ocurre_dentro_del_plazo_prometido(svc):
    """Detenido en el tiempo del watchdog más el de la rampa de bajada.

    Con watchdog de 500 ms y rampa de 6.0/s, ir de duty completo a cero toma
    ~167 ms más. Se comprueba el margen documentado.
    """
    service, io, cfg = svc
    t = 1000.0
    dt = 1.0 / cfg.motion.control_hz

    for _ in range(100):
        service._on_drive({"left": 1.0, "right": 1.0})
        service._shared.drive_ts = t
        service.step(dt, t)
        t += dt

    ultimo_comando = t
    detenido_en = None
    while t < ultimo_comando + 2.0:
        service.step(dt, t)
        if io.duties[cfg.motion.left.pwm] == 0.0 and detenido_en is None:
            detenido_en = t
            break
        t += dt

    assert detenido_en is not None, "el robot nunca se detuvo"
    transcurrido_ms = (detenido_en - ultimo_comando) * 1000
    presupuesto = cfg.motion.watchdog_ms + (1.0 / cfg.motion.ramp_down_per_s) * 1000 + 50
    assert transcurrido_ms < presupuesto


def test_se_reactiva_al_volver_los_comandos(svc):
    service, io, cfg = svc
    t = 1000.0
    dt = 1.0 / cfg.motion.control_hz

    t = _correr(service, io, cfg, 1.0, t0=t)
    assert io.duties[cfg.motion.left.pwm] == 0.0

    for _ in range(100):
        service._on_drive({"left": 1.0, "right": 1.0})
        service._shared.drive_ts = t
        service.step(dt, t)
        t += dt

    assert io.duties[cfg.motion.left.pwm] > 0.0


def test_comando_malformado_no_refresca_el_watchdog(svc):
    """Un payload basura no debe contar como señal de vida."""
    service, io, cfg = svc
    service._on_drive({"left": "rapido", "right": None})
    assert service._shared.drive_ts == 0.0

    service._on_drive({})
    assert service._shared.drive_ts == 0.0


def test_estop_por_mqtt_corta_el_driver(svc):
    service, io, cfg = svc
    t = 1000.0
    dt = 1.0 / cfg.motion.control_hz

    for _ in range(100):
        service._on_drive({"left": 1.0, "right": 1.0})
        service._shared.drive_ts = t
        service.step(dt, t)
        t += dt

    service._on_estop({"engaged": True})
    service.step(dt, t)

    assert io.outputs[cfg.motion.standby] == 0
    assert io.duties[cfg.motion.left.pwm] == 0.0
