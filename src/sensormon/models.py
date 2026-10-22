"""Esquemas de telemetría y alertas."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class Metric(StrEnum):
    temperature = "temperature"
    humidity = "humidity"
    pressure = "pressure"
    co2 = "co2"
    vibration = "vibration"


class Quality(StrEnum):
    good = "good"
    fault = "fault"
    spike = "spike"


Severity = Literal["info", "warning", "critical"]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class Reading(BaseModel):
    """Lectura publicada en `sensors/<device_id>/<metric>`."""

    model_config = ConfigDict(extra="forbid")

    device_id: str
    metric: Metric
    value: float
    unit: str = Field(min_length=1, max_length=32)
    timestamp: datetime
    quality: Quality = Quality.good

    @field_validator("device_id")
    @classmethod
    def _device_id(cls, value: str) -> str:
        if not DEVICE_ID_RE.fullmatch(value):
            raise ValueError("device_id contiene caracteres no permitidos")
        return value

    @field_validator("value")
    @classmethod
    def _finite(cls, value: float) -> float:
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("value debe ser finito")
        return float(value)

    @field_validator("timestamp")
    @classmethod
    def _timestamp(cls, value: datetime) -> datetime:
        return _as_utc(value)


class DeviceAnnouncement(BaseModel):
    """Metadatos retenidos en `sensors/<device_id>/meta`."""

    model_config = ConfigDict(extra="forbid")

    device_id: str
    location: str | None = None
    sensors: list[Metric] = Field(default_factory=list)

    @field_validator("device_id")
    @classmethod
    def _device_id(cls, value: str) -> str:
        if not DEVICE_ID_RE.fullmatch(value):
            raise ValueError("device_id contiene caracteres no permitidos")
        return value


class Alert(BaseModel):
    """Alerta generada por un detector y publicada en `alerts/<device_id>`."""

    model_config = ConfigDict(extra="forbid")

    id: int | None = None
    device_id: str
    metric: Metric
    detector: str = Field(min_length=1, max_length=64)
    severity: Severity
    message: str = Field(min_length=1)
    value: float
    score: float | None = None
    timestamp: datetime

    @field_validator("device_id")
    @classmethod
    def _device_id(cls, value: str) -> str:
        if not DEVICE_ID_RE.fullmatch(value):
            raise ValueError("device_id contiene caracteres no permitidos")
        return value

    @field_validator("timestamp")
    @classmethod
    def _timestamp(cls, value: datetime) -> datetime:
        return _as_utc(value)

    @field_validator("score")
    @classmethod
    def _score(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("score debe ser finito")
        return float(value)
