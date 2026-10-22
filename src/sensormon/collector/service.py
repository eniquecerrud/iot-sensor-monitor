"""Suscriptor que valida, guarda, detecta y republica alertas."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from sensormon.bus import MessageBus, parse_topic
from sensormon.detection.engine import DetectionEngine
from sensormon.hub import EventHub
from sensormon.models import Alert, DeviceAnnouncement, Reading
from sensormon.notify.base import Notifier
from sensormon.storage.base import ReadingStore
from sensormon.util import utcnow

logger = logging.getLogger(__name__)


class Collector:
    def __init__(
        self,
        bus: MessageBus,
        store: ReadingStore,
        engine: DetectionEngine,
        notifiers: list[Notifier] | None = None,
        *,
        hub: EventHub | None = None,
        topic_root: str = "sensors",
    ) -> None:
        self.bus = bus
        self.store = store
        self.engine = engine
        self.notifiers = list(notifiers or [])
        self.hub = hub
        self.topic_root = topic_root
        self.accepted = 0
        self.rejected = 0
        self._started = False

    def start(self) -> None:
        self.store.init()
        self.bus.subscribe(f"{self.topic_root}/#", self._on_message)
        self.bus.start()
        self._started = True
        logger.info("Colector escuchando %s/#", self.topic_root)

    def stop(self) -> None:
        if self._started:
            self.bus.stop()
            self._started = False
        for notifier in self.notifiers:
            close = getattr(notifier, "close", None)
            if callable(close):
                close()

    def _on_message(self, topic: str, payload: dict[str, Any]) -> None:
        parsed = parse_topic(topic, self.topic_root)
        if parsed is None:
            self.rejected += 1
            logger.warning("Tema ignorado: %s", topic)
            return
        device_id, kind = parsed
        try:
            if kind == "meta":
                self._handle_meta(device_id, payload)
                return
            reading = self._handle_reading(device_id, kind, payload)
        except (ValidationError, ValueError) as exc:
            self.rejected += 1
            logger.warning("Payload inválido en %s: %s", topic, exc)
            return
        self.accepted += 1
        self.store.insert_reading(reading)
        self._emit({"type": "reading", "data": reading.model_dump(mode="json")})
        for alert in self.engine.evaluate(reading):
            self._publish_alert(alert)

    def _handle_meta(self, device_id: str, payload: dict[str, Any]) -> None:
        meta = DeviceAnnouncement.model_validate(payload)
        if meta.device_id != device_id:
            raise ValueError("device_id no coincide con el tema")
        self.store.upsert_device(
            meta.device_id,
            location=meta.location,
            sensors=[item.value for item in meta.sensors],
            seen=utcnow(),
        )

    def _handle_reading(self, device_id: str, kind: str, payload: dict[str, Any]) -> Reading:
        reading = Reading.model_validate(payload)
        if reading.device_id != device_id or reading.metric.value != kind:
            raise ValueError("el payload no coincide con el tema")
        return reading

    def _publish_alert(self, alert: Alert) -> None:
        saved = self.store.insert_alert(alert)
        body = saved.model_dump(mode="json")
        self.bus.publish(f"alerts/{saved.device_id}", body)
        self._emit({"type": "alert", "data": body})
        for notifier in self.notifiers:
            try:
                notifier.notify(saved)
            except Exception:
                logger.exception("El notificador falló para la alerta %s", saved.id)

    def _emit(self, event: dict[str, Any]) -> None:
        if self.hub is not None:
            self.hub.publish(event)
