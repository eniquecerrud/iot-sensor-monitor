"""Contrato de almacenamiento."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from sensormon.models import Alert, Reading


@dataclass(slots=True)
class DeviceRecord:
    device_id: str
    location: str | None
    last_seen: datetime | None
    sensors: list[str]
    reading_count: int
    latest: dict[str, Reading] = field(default_factory=dict)


class ReadingStore(Protocol):
    def init(self) -> None:
        """Crea el esquema si todavía no existe."""

    def close(self) -> None:
        """Cierra la conexión."""

    def insert_reading(self, reading: Reading) -> None:
        """Guarda una lectura y actualiza el dispositivo."""

    def insert_alert(self, alert: Alert) -> Alert:
        """Guarda una alerta y devuelve la copia con `id`."""

    def upsert_device(
        self,
        device_id: str,
        location: str | None = None,
        sensors: list[str] | None = None,
        seen: datetime | None = None,
    ) -> None:
        """Registra o actualiza la ficha de un dispositivo."""

    def list_readings(
        self,
        *,
        device_id: str | None = None,
        metric: str | None = None,
        limit: int = 200,
        since: datetime | None = None,
    ) -> list[Reading]:
        """Devuelve lecturas en orden cronológico."""

    def list_alerts(
        self,
        *,
        device_id: str | None = None,
        severity: str | None = None,
        limit: int = 100,
    ) -> list[Alert]:
        """Devuelve alertas de la más reciente a la más antigua."""

    def list_devices(self) -> list[DeviceRecord]:
        """Devuelve dispositivos con la última lectura de cada magnitud."""
