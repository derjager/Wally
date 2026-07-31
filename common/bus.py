"""Bus MQTT compartido por los servicios de Wally.

Envuelve paho-mqtt con reconexión automática y payloads JSON. La pérdida del
broker nunca debe tumbar un servicio: los publish se descartan y los handlers
simplemente dejan de recibir, lo que hace saltar el watchdog de motion — que
es exactamente el comportamiento deseado.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Callable

import paho.mqtt.client as mqtt

from common.config import MqttConfig
from common.topics import online_topic

log = logging.getLogger("bus")

Handler = Callable[[dict[str, Any]], None]


class Bus:
    def __init__(self, cfg: MqttConfig, service: str) -> None:
        self._cfg = cfg
        self._service = service
        self._handlers: dict[str, Handler] = {}
        self._on_connected: list[Callable[[], None]] = []
        self._connected = threading.Event()
        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"wally-{service}",
        )
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

        # Si este servicio muere, el broker avisa por él.
        self._client.will_set(online_topic(service), json.dumps({"online": False}), retain=True)

    # -- ciclo de vida ---------------------------------------------------

    def start(self, wait_s: float = 5.0) -> bool:
        """Conecta y espera a que el enlace esté listo.

        La espera importa: `connect_async` retorna de inmediato y un `publish`
        anterior a la conexión se descarta **en silencio**. Sin esto, el estado
        retenido que cada servicio publica nada más arrancar nunca llegaba al
        broker, y la webapp se encontraba sin datos hasta el siguiente cambio.

        Devuelve False si el broker no respondió a tiempo. No es fatal: la
        reconexión sigue en marcha en segundo plano.
        """
        self._client.connect_async(self._cfg.host, self._cfg.port, self._cfg.keepalive)
        self._client.loop_start()

        if wait_s <= 0:
            return False
        if self._connected.wait(wait_s):
            return True
        log.warning("el broker no respondió en %.0fs; se sigue reintentando", wait_s)
        return False

    def on_connected(self, callback: Callable[[], None]) -> None:
        """Registra algo que ejecutar en cada (re)conexión.

        Los mensajes retenidos viven en el broker: si mosquitto se reinicia,
        desaparecen. Republicar aquí es lo que evita que la webapp se quede
        con un estado fantasma tras ese reinicio.
        """
        self._on_connected.append(callback)

    def stop(self) -> None:
        self.publish(online_topic(self._service), {"online": False}, retain=True)
        self._connected.clear()
        self._client.loop_stop()
        self._client.disconnect()

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    # -- uso -------------------------------------------------------------

    def subscribe(self, topic: str, handler: Handler) -> None:
        """Registra un handler. Puede llamarse antes de conectar."""
        self._handlers[topic] = handler
        self._client.subscribe(topic)

    def publish(self, topic: str, payload: dict[str, Any], retain: bool = False) -> None:
        self._client.publish(topic, json.dumps(payload), retain=retain)

    # -- callbacks -------------------------------------------------------

    def _on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        if reason_code != 0:
            log.warning("conexión MQTT rechazada: %s", reason_code)
            return
        log.info("conectado a %s:%s", self._cfg.host, self._cfg.port)
        # Re-suscribir: tras una reconexión el broker no recuerda nada.
        for topic in self._handlers:
            client.subscribe(topic)
        self.publish(online_topic(self._service), {"online": True}, retain=True)
        self._connected.set()

        for callback in self._on_connected:
            try:
                callback()
            except Exception:
                log.exception("callback de reconexión falló")

    def _on_message(self, client, userdata, msg) -> None:
        handler = self._handlers.get(msg.topic)
        if handler is None:
            return
        try:
            payload = json.loads(msg.payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            log.warning("payload no-JSON en %s, descartado", msg.topic)
            return
        if not isinstance(payload, dict):
            log.warning("payload no-objeto en %s, descartado", msg.topic)
            return
        try:
            handler(payload)
        except Exception:
            # Un handler defectuoso no puede matar el hilo de red: sin él no
            # habría reconexión ni más mensajes.
            log.exception("handler de %s falló", msg.topic)
