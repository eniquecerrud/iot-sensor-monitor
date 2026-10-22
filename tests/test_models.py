from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from sensormon.catalog import catalog_payload, metric_label
from sensormon.models import Reading


def test_naive_timestamp_is_utc() -> None:
    reading = Reading(
        device_id="lab-01",
        metric="humidity",
        value=40,
        unit="%",
        timestamp=datetime(2026, 1, 1, 0, 0),
    )
    assert reading.timestamp.tzinfo == UTC


def test_rejects_bad_device_and_non_finite_value() -> None:
    with pytest.raises(ValidationError):
        Reading(
            device_id="lab 01",
            metric="temperature",
            value=1,
            unit="°C",
            timestamp=datetime.now(UTC),
        )
    with pytest.raises(ValidationError):
        Reading(
            device_id="lab-01",
            metric="temperature",
            value=float("nan"),
            unit="°C",
            timestamp=datetime.now(UTC),
        )


def test_catalog_covers_every_metric() -> None:
    payload = catalog_payload()
    assert {item["id"] for item in payload} == {
        "temperature",
        "humidity",
        "pressure",
        "co2",
        "vibration",
    }
    assert metric_label("co2") == "CO₂"
