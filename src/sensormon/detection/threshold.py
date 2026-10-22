"""Umbrales fijos por magnitud, con nivel de aviso y nivel crítico."""

from __future__ import annotations

from sensormon.config import ThresholdRule
from sensormon.detection.base import describe, make_alert
from sensormon.models import Alert, Reading


class ThresholdDetector:
    name = "threshold"

    def __init__(self, rules: dict[str, ThresholdRule]) -> None:
        self.rules = rules

    def evaluate(self, reading: Reading) -> Alert | None:
        rule = self.rules.get(reading.metric.value)
        if rule is None:
            return None
        value = reading.value
        label = describe(reading)
        unit = reading.unit
        if rule.critical_max is not None and value > rule.critical_max:
            return self._build(
                reading,
                "critical",
                rule.critical_max,
                f"{label} {value:.2f} {unit} supera el umbral crítico ({rule.critical_max:.2f})",
            )
        if rule.critical_min is not None and value < rule.critical_min:
            return self._build(
                reading,
                "critical",
                rule.critical_min,
                f"{label} {value:.2f} {unit} cae bajo el umbral crítico ({rule.critical_min:.2f})",
            )
        if rule.max is not None and value > rule.max:
            return self._build(
                reading,
                "warning",
                rule.max,
                f"{label} {value:.2f} {unit} supera el máximo ({rule.max:.2f})",
            )
        if rule.min is not None and value < rule.min:
            return self._build(
                reading,
                "warning",
                rule.min,
                f"{label} {value:.2f} {unit} cae bajo el mínimo ({rule.min:.2f})",
            )
        return None

    def _build(
        self,
        reading: Reading,
        severity: str,
        limit: float,
        message: str,
    ) -> Alert:
        return make_alert(
            reading,
            detector=self.name,
            severity=severity,  # type: ignore[arg-type]
            message=message,
            score=reading.value - limit,
        )
