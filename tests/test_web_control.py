"""Pruebas de la traducción joystick → tracción y de la webapp."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from common.config import Config
from services.web.app import create_app
from services.web.control import parse_joystick


# -- traducción del joystick ----------------------------------------------


def test_avanzar_recto():
    cmd = parse_joystick({"throttle": 1.0, "steer": 0.0})
    assert cmd is not None
    assert cmd.left == pytest.approx(1.0)
    assert cmd.right == pytest.approx(1.0)


def test_giro_en_el_sitio():
    cmd = parse_joystick({"throttle": 0.0, "steer": 1.0})
    assert cmd is not None
    assert cmd.left == pytest.approx(1.0)
    assert cmd.right == pytest.approx(-1.0)


def test_entradas_fuera_de_rango_se_recortan():
    """Un cliente manipulado no puede pedir más del máximo."""
    cmd = parse_joystick({"throttle": 99.0, "steer": 0.0})
    assert cmd is not None
    assert cmd.left <= 1.0
    assert cmd.right <= 1.0


def test_formato_directo_left_right():
    cmd = parse_joystick({"left": 0.5, "right": -0.5})
    assert cmd is not None
    assert cmd.left == pytest.approx(0.5)
    assert cmd.right == pytest.approx(-0.5)


@pytest.mark.parametrize(
    "msg",
    [
        {},
        {"throttle": "rápido"},
        {"left": None, "right": 1.0},
        {"otra_cosa": 1},
    ],
)
def test_mensajes_invalidos_no_producen_comando(msg):
    """None significa "no publiques": un mensaje corrupto no es señal de vida."""
    assert parse_joystick(msg) is None


# -- webapp ----------------------------------------------------------------


class FakeBus:
    """Bus de mentira que solo registra lo publicado."""

    def __init__(self) -> None:
        self.published: list[tuple[str, dict]] = []
        self.subscriptions: dict[str, object] = {}

    def subscribe(self, topic, handler):
        self.subscriptions[topic] = handler

    def publish(self, topic, payload, retain=False):
        self.published.append((topic, payload))


@pytest.fixture
def client_and_bus():
    bus = FakeBus()
    app = create_app(Config(), bus)
    with TestClient(app) as client:
        yield client, bus


def test_health(client_and_bus):
    client, _ = client_and_bus
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["watchdog_ms"] == 500


def test_el_websocket_de_control_publica_a_mqtt(client_and_bus):
    client, bus = client_and_bus
    with client.websocket_connect("/ws/control") as ws:
        ws.send_json({"throttle": 1.0, "steer": 0.0})
        ws.send_json({"throttle": 0.0, "steer": 0.0})

    drives = [p for t, p in bus.published if t.endswith("cmd/drive")]
    assert len(drives) == 2
    assert drives[0]["left"] == pytest.approx(1.0)
    assert drives[1]["left"] == pytest.approx(0.0)


def test_un_mensaje_corrupto_no_publica_nada(client_and_bus):
    """Clave para el watchdog: basura recibida no debe contar como vida."""
    client, bus = client_and_bus
    with client.websocket_connect("/ws/control") as ws:
        ws.send_text("esto no es json")
        ws.send_json({"throttle": "mucho"})
        ws.send_json({})

    assert [p for t, p in bus.published if t.endswith("cmd/drive")] == []


def test_estop_por_websocket(client_and_bus):
    client, bus = client_and_bus
    with client.websocket_connect("/ws/control") as ws:
        ws.send_json({"type": "estop", "engaged": True})

    estops = [p for t, p in bus.published if t.endswith("cmd/estop")]
    assert estops == [{"engaged": True}]


def test_comando_de_servo(client_and_bus):
    client, bus = client_and_bus
    with client.websocket_connect("/ws/control") as ws:
        ws.send_json({"type": "servo", "arm_left": 90})

    servos = [p for t, p in bus.published if t.endswith("cmd/servo")]
    assert servos == [{"arm_left": 90}]


def test_al_cerrarse_el_socket_no_se_publica_una_parada(client_and_bus):
    """El robot se detiene por watchdog, no por un mensaje final.

    Publicar una parada al desconectar parece prudente pero es peor: podría
    llegar después de que otro cliente tomara el control y frenarlo a media
    maniobra.
    """
    client, bus = client_and_bus
    with client.websocket_connect("/ws/control") as ws:
        ws.send_json({"throttle": 1.0, "steer": 0.0})

    drives = [p for t, p in bus.published if t.endswith("cmd/drive")]
    assert len(drives) == 1
    assert drives[0]["left"] == pytest.approx(1.0)


def test_la_telemetria_refleja_lo_que_llega_por_mqtt(client_and_bus):
    client, bus = client_and_bus
    from common import topics

    bus.subscriptions[topics.STATE_MOTION]({"left": 0.4, "right": 0.4, "watchdog": False})
    bus.subscriptions[topics.STATE_SENSORS]({"front": 320.0})

    body = client.get("/api/state").json()
    assert body["motion"]["left"] == 0.4
    assert body["sensors"]["front"] == 320.0


# -- red -------------------------------------------------------------------


def test_estado_de_red_llega_desde_wally_net(client_and_bus):
    client, bus = client_and_bus
    from common import topics

    bus.subscriptions[topics.NET_STATUS](
        {"mode": "hotspot", "ssid": None, "ip": "192.168.4.1", "online": False}
    )
    bus.subscriptions[topics.NET_NETWORKS](
        {"networks": [{"ssid": "CasaDeClaudio", "signal": 80, "security": "WPA2"}]}
    )

    assert client.get("/api/net/status").json()["mode"] == "hotspot"
    nets = client.get("/api/net/networks").json()["networks"]
    assert nets[0]["ssid"] == "CasaDeClaudio"


def test_conectar_publica_el_comando(client_and_bus):
    client, bus = client_and_bus
    r = client.post("/api/net/connect", json={"ssid": "MiRed", "password": "secreta"})

    assert r.json()["pending"] is True
    cmds = [p for t, p in bus.published if t.endswith("cmd/net/connect")]
    assert cmds == [{"ssid": "MiRed", "password": "secreta"}]


def test_conectar_sin_ssid_se_rechaza(client_and_bus):
    client, bus = client_and_bus
    r = client.post("/api/net/connect", json={"password": "x"})

    assert r.json()["ok"] is False
    assert [p for t, p in bus.published if t.endswith("cmd/net/connect")] == []


def test_scan_y_hotspot_publican_comandos(client_and_bus):
    client, bus = client_and_bus
    client.post("/api/net/scan")
    client.post("/api/net/hotspot")

    temas = [t for t, _ in bus.published]
    assert any(t.endswith("cmd/net/scan") for t in temas)
    assert any(t.endswith("cmd/net/hotspot") for t in temas)


def test_la_webapp_nunca_ejecuta_nmcli(client_and_bus):
    """wally-web está expuesto a la red y corre sin privilegios: solo publica
    mensajes. Quien toca NetworkManager es wally-net, como root."""
    import services.web.app as webapp

    fuente = Path(webapp.__file__).read_text()
    assert "nmcli" not in fuente
    assert "subprocess" not in fuente
