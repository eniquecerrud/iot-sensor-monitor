"""Utilidades compartidas por la suite."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sensormon.models import Reading

UTC = UTC


def make_reading(**overrides: object) -> Reading:
    data: dict[str, object] = {
        "device_id": "lab-01",
        "metric": "temperature",
        "value": 22.0,
        "unit": "°C",
        "timestamp": datetime(2026, 10, 22, 12, 0, tzinfo=UTC),
    }
    data.update(overrides)
    return Reading(**data)


def at(seconds: int) -> datetime:
    return datetime(2026, 10, 22, 12, 0, tzinfo=UTC) + timedelta(seconds=seconds)
