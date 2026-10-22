"""Contrato de un detector y constructor de alertas."""

from __future__ import annotations

import math
from typing import Protocol

from sensormon.catalog import metric_label
from sensormon.models import Alert, Reading, Severity


class Detector(Protocol):
    name: str

    def evaluate(self, reading: Reading) -> Alert | None:
        """Devuelve una alerta o `None` si la lectura es compatible con el modelo."""


def finite_score(value: float) -> float:
    if math.isfinite(value):
        return float(value)
    return math.copysign(1_000_000.0, value)


def make_alert(
    reading: Reading,
    *,
    detector: str,
    severity: Severity,
    message: str,
    score: float | None = None,
) -> Alert:
    return Alert(
        device_id=reading.device_id,
        metric=reading.metric,
        detector=detector,
        severity=severity,
        message=message,
        value=reading.value,
        score=None if score is None else finite_score(score),
        timestamp=reading.timestamp,
    )


def describe(reading: Reading) -> str:
    return metric_label(reading.metric)
