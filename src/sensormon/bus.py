"""Transporte de mensajes: MQTT o bus en memoria para demos y pruebas."""

from __future__ import annotations

import json
import logging
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

Callback = Callable[[str, dict[str, Any]], None]


def topic_matches(pattern: str, topic: str) -> bool:
    """Comodines MQTT: `+` es un nivel y `#` el resto del tema."""

    pattern_parts = pattern.split("/")
    topic_parts = topic.split("/")
    for index, part in enumerate(pattern_parts):
        if part == "#":
            return index == len(pattern_parts) - 1
        if index >= len(topic_parts):
            return False
        if part != "+" and part != topic_parts[index]:
            return False
    return len(pattern_parts) == len(topic_parts)


def parse_topic(topic: str, root: str = "sensors") -> tuple[str, str] | None:
    parts = topic.split("/")
    if len(parts) != 3 or parts[0] != root or not parts[1] or not parts[2]:
        return None
    return parts[1], parts[2]


def decode_payload(raw: bytes | str) -> dict[str, Any]:
    text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("el payload debe ser un objeto JSON")
    return data


class MessageBus(ABC):
    @abstractmethod
    def publish(self, topic: str, payload: dict[str, Any], *, retain: bool = False) -> None:
        """Publica un objeto JSON en `topic`."""

    @abstractmethod
    def subscribe(self, topic: str, callback: Callback) -> None:
        """Registra `callback(topic, payload)` para un filtro MQTT."""

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None


class InMemoryBus(MessageBus):
    """Bus síncrono. `publish` entrega el mensaje antes de volver."""

    def __init__(self) -> None:
        self._subs: list[tuple[str, Callback]] = []
        self._lock = threading.Lock()

    def subscribe(self, topic: str, callback: Callback) -> None:
        with self._lock:
            self._subs.append((topic, callback))

    def publish(self, topic: str, payload: dict[str, Any], *, retain: bool = False) -> None:
        del retain
        with self._lock:
            subs = list(self._subs)
        for pattern, callback in subs:
            if topic_matches(pattern, topic):
                callback(topic, payload)

    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subs)


class MqttBus(MessageBus):
    """Cliente paho-mqtt con reintentos de conexión."""

    def __init__(
        self,
        host: str,
        port: int = 1883,
        *,
        username: str | None = None,
        password: str | None = None,
        client_id: str = "sensormon",
        keepalive: int = 60,
        connect_attempts: int = 12,
    ) -> None:
        import paho.mqtt.client as mqtt

        self._host = host
        self._port = port
        self._keepalive = keepalive
        self._attempts = connect_attempts
        self._subs: list[tuple[str, Callback]] = []
        self._connected = threading.Event()
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        if username:
            self._client.username_pw_set(username, password)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)

    def subscribe(self, topic: str, callback: Callback) -> None:
        self._subs.append((topic, callback))
        if self._connected.is_set():
            self._client.subscribe(topic, qos=0)

    def publish(self, topic: str, payload: dict[str, Any], *, retain: bool = False) -> None:
        if not self._connected.is_set():
            raise RuntimeError("MQTT no está conectado")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._client.publish(topic, body, qos=0, retain=retain)

    def start(self) -> None:
        delay = 0.4
        last_error: Exception | None = None
        for attempt in range(1, self._attempts + 1):
            try:
                self._client.connect(self._host, self._port, self._keepalive)
                last_error = None
                break
            except OSError as exc:
                last_error = exc
                logger.warning(
                    "MQTT %s:%s intento %s/%s falló: %s",
                    self._host,
                    self._port,
                    attempt,
                    self._attempts,
                    exc,
                )
                if attempt < self._attempts:
                    time.sleep(delay)
                    delay = min(delay * 1.6, 5)
        if last_error is not None:
            raise ConnectionError(
                f"No se pudo conectar a MQTT en {self._host}:{self._port}"
            ) from last_error
        self._client.loop_start()
        if not self._connected.wait(timeout=10):
            self._client.loop_stop()
            raise ConnectionError(f"El broker MQTT {self._host}:{self._port} no confirmó la sesión")

    def stop(self) -> None:
        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:
            logger.debug("Error al cerrar MQTT", exc_info=True)
        self._connected.clear()

    def _on_connect(
        self,
        client: Any,
        userdata: Any,
        flags: Any,
        reason_code: Any,
        properties: Any = None,
    ) -> None:
        del userdata, flags, properties
        failed = bool(getattr(reason_code, "is_failure", int(reason_code) != 0))
        if failed:
            logger.error("El broker rechazó la conexión MQTT: %s", reason_code)
            return
        self._connected.set()
        for topic, _callback in self._subs:
            client.subscribe(topic, qos=0)
        logger.info("Conectado a MQTT %s:%s", self._host, self._port)

    def _on_message(self, client: Any, userdata: Any, message: Any) -> None:
        del client, userdata
        self._handle_raw(message.topic, message.payload)

    def _handle_raw(self, topic: str, raw: bytes | str) -> None:
        try:
            payload = decode_payload(raw)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            logger.warning("JSON inválido en %s: %s", topic, exc)
            return
        for pattern, callback in list(self._subs):
            if not topic_matches(pattern, topic):
                continue
            try:
                callback(topic, payload)
            except Exception:
                logger.exception("Error en suscriptor de %s", topic)
