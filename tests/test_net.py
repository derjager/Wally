"""Pruebas de wally-net: parser de nmcli y máquina de estados."""

from __future__ import annotations

import pytest

from common.config import Config, NetConfig
from services.net.nmcli import (
    FakeBackend,
    Network,
    NetStatus,
    split_terse,
    unescape,
)
from services.net.service import NetService


# -- parser del formato terse ---------------------------------------------


def test_split_terse_basico():
    assert split_terse("MiWifi:82:WPA2") == ["MiWifi", "82", "WPA2"]


def test_split_terse_respeta_los_dos_puntos_escapados():
    """Un SSID puede contener ':', que nmcli escapa. Partir por ':' a secas
    trocearía el nombre de la red y corrompería la lista entera."""
    assert split_terse(r"Vecino\:Raro:44:WPA2") == ["Vecino:Raro", "44", "WPA2"]


def test_split_terse_con_barra_invertida_en_el_ssid():
    assert split_terse(r"Red\\Rara:60:WPA2") == ["Red\\Rara", "60", "WPA2"]


def test_split_terse_campos_vacios():
    """Una red abierta trae el campo de seguridad vacío."""
    assert split_terse("Abierta:30:") == ["Abierta", "30", ""]


def test_unescape():
    assert unescape(r"a\:b") == "a:b"
    assert unescape("sin escapes") == "sin escapes"


def test_red_abierta_se_detecta():
    assert Network("A", 50, "").open
    assert Network("A", 50, "--").open
    assert not Network("A", 50, "WPA2").open


# -- máquina de estados ----------------------------------------------------


def _service(**net_overrides):
    cfg = Config(net=NetConfig(boot_timeout_s=0.1, poll_s=0.01, **net_overrides))
    backend = FakeBackend()
    return NetService(cfg, backend, bus=None), backend


def test_sin_redes_guardadas_arranca_en_hotspot():
    """Robot recién estrenado: no hay wifi configurada, hay que poder llegar a él."""
    svc, backend = _service()
    assert svc.bootstrap() == "hotspot"
    assert backend.status().mode == "hotspot"


def test_con_red_guardada_y_conexion_arranca_como_cliente():
    svc, backend = _service()
    backend.connect("CasaDeClaudio", "correcta")  # deja el perfil guardado
    assert svc.bootstrap() == "client"
    assert svc.snapshot()["online"] is True


def test_red_guardada_que_no_conecta_cae_al_hotspot():
    """Te llevas el robot a otra casa: la wifi guardada no está."""
    svc, backend = _service()
    backend.connect("CasaDeClaudio", "correcta")
    backend._status = NetStatus(mode="disconnected")  # el router ya no existe

    assert svc.bootstrap() == "hotspot"


def test_conectar_con_contrasena_correcta():
    svc, backend = _service()
    svc._do_connect({"ssid": "CasaDeClaudio", "password": "correcta"})

    snap = svc.snapshot()
    assert snap["mode"] == "client"
    assert snap["ssid"] == "CasaDeClaudio"
    assert snap["error"] is None


def test_contrasena_incorrecta_vuelve_al_hotspot():
    """Sin red y sin AP el robot queda inalcanzable y habría que sacarle la SD.
    Ante un fallo de conexión hay que recuperar siempre el modo configuración."""
    svc, backend = _service()
    svc._do_connect({"ssid": "CasaDeClaudio", "password": "mala"})

    snap = svc.snapshot()
    assert snap["mode"] == "hotspot"
    assert snap["error"] is not None


def test_conectar_sin_ssid_no_hace_nada():
    svc, backend = _service()
    svc._do_connect({"password": "x"})
    assert "connect:" not in " ".join(backend.calls)


def test_escaneo_ordena_por_señal():
    svc, backend = _service()
    svc._do_scan()
    señales = [n["signal"] for n in svc._networks]
    assert señales == sorted(señales, reverse=True)


def test_una_caida_breve_no_dispara_el_hotspot():
    """Un router reiniciándose no debe dejarte sin control del robot."""
    svc, backend = _service(fallback_after_s=120.0)
    backend.connect("CasaDeClaudio", "correcta")
    svc.step(1000.0)

    backend._status = NetStatus(mode="disconnected")
    svc.step(1001.0)   # se detecta la caída
    svc.step(1030.0)   # 30 s después, aún esperando

    assert backend.status().mode != "hotspot"


def test_una_caida_larga_devuelve_al_modo_configuracion():
    svc, backend = _service(fallback_after_s=120.0)
    backend.connect("CasaDeClaudio", "correcta")
    svc.step(1000.0)

    backend._status = NetStatus(mode="disconnected")
    svc.step(1001.0)
    svc.step(1200.0)   # 199 s sin red

    assert backend.status().mode == "hotspot"


def test_fallback_desactivable():
    svc, backend = _service(fallback_after_s=0.0)
    backend.connect("CasaDeClaudio", "correcta")
    svc.step(1000.0)

    backend._status = NetStatus(mode="disconnected")
    svc.step(1001.0)
    svc.step(9999.0)

    assert backend.status().mode != "hotspot"


def test_estando_en_hotspot_no_se_cuenta_tiempo_offline():
    svc, backend = _service(fallback_after_s=10.0)
    svc._start_hotspot()
    svc.step(1000.0)
    svc.step(2000.0)

    # No se reinicia el AP una y otra vez.
    assert backend.calls.count("start_hotspot") == 1


def test_recuperar_conexion_limpia_el_contador():
    svc, backend = _service(fallback_after_s=100.0)
    backend.connect("CasaDeClaudio", "correcta")
    svc.step(1000.0)

    backend._status = NetStatus(mode="disconnected")
    svc.step(1001.0)
    backend._status = NetStatus(mode="client", ssid="CasaDeClaudio", ip="192.168.1.55")
    svc.step(1050.0)

    assert svc._offline_since is None


def test_snapshot_expone_lo_que_la_ui_necesita():
    svc, _ = _service()
    snap = svc.snapshot()
    assert set(snap) >= {"mode", "ssid", "ip", "online", "busy", "error", "ap_ssid"}
