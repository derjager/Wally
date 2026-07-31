"""Pruebas del bus MQTT.

El caso cubierto aquí es sutil y costó encontrarlo: `connect_async` retorna al
instante, así que un servicio que publicaba su estado retenido nada más
arrancar lo perdía — paho descarta en silencio lo que se publica sin conexión.
El síntoma era que la webapp no sabía que la red estaba en modo hotspot, justo
cuando el hotspot es lo único por lo que puedes llegar al robot.
"""

from __future__ import annotations

import threading

from common.bus import Bus
from common.config import MqttConfig


def _bus() -> Bus:
    return Bus(MqttConfig(host="127.0.0.1", port=1), "test")


def test_arranca_desconectado():
    assert _bus().connected is False


def test_start_no_bloquea_indefinidamente_sin_broker():
    """Sin broker debe devolver el control, no colgar el arranque del servicio."""
    bus = _bus()
    try:
        assert bus.start(wait_s=0.2) is False
        assert bus.connected is False
    finally:
        bus.stop()


def test_la_conexion_marca_el_estado_y_dispara_los_callbacks():
    bus = _bus()
    llamadas: list[str] = []
    bus.on_connected(lambda: llamadas.append("republicar"))

    bus._on_connect(bus._client, None, None, 0)

    assert bus.connected is True
    assert llamadas == ["republicar"]


def test_una_reconexion_vuelve_a_disparar_los_callbacks():
    """Si mosquitto se reinicia pierde los mensajes retenidos; hay que
    republicarlos o la webapp se queda con un estado fantasma."""
    bus = _bus()
    llamadas: list[int] = []
    bus.on_connected(lambda: llamadas.append(1))

    bus._on_connect(bus._client, None, None, 0)
    bus._on_connect(bus._client, None, None, 0)

    assert len(llamadas) == 2


def test_un_callback_que_falla_no_impide_los_demas():
    bus = _bus()
    ok: list[str] = []

    def explota():
        raise RuntimeError("fallo")

    bus.on_connected(explota)
    bus.on_connected(lambda: ok.append("sigo"))

    bus._on_connect(bus._client, None, None, 0)

    assert ok == ["sigo"]
    assert bus.connected is True


def test_conexion_rechazada_no_marca_conectado():
    bus = _bus()
    bus._on_connect(bus._client, None, None, 5)  # 5 = no autorizado
    assert bus.connected is False


def test_start_devuelve_true_si_la_conexion_llega_a_tiempo():
    bus = _bus()
    threading.Timer(0.1, lambda: bus._on_connect(bus._client, None, None, 0)).start()
    try:
        assert bus.start(wait_s=2.0) is True
    finally:
        bus.stop()


def test_un_handler_defectuoso_no_mata_el_hilo_de_red():
    """Sin esto, un fallo en un handler dejaría al servicio sin reconexión ni
    mensajes, en silencio."""
    bus = _bus()
    recibidos: list[str] = []

    def malo(_payload):
        raise ValueError("handler roto")

    bus.subscribe("wally/test/a", malo)
    bus.subscribe("wally/test/b", lambda p: recibidos.append("b"))

    class FakeMsg:
        def __init__(self, topic, payload):
            self.topic = topic
            self.payload = payload

    bus._on_message(bus._client, None, FakeMsg("wally/test/a", b'{"x":1}'))
    bus._on_message(bus._client, None, FakeMsg("wally/test/b", b'{"x":1}'))

    assert recibidos == ["b"]


def test_payload_no_json_se_descarta_sin_romper():
    bus = _bus()
    recibidos: list[dict] = []
    bus.subscribe("wally/test/c", recibidos.append)

    class FakeMsg:
        topic = "wally/test/c"
        payload = b"esto no es json"

    bus._on_message(bus._client, None, FakeMsg())
    assert recibidos == []
