"""Orquesta detectores y aplica un tiempo de silencio por serie."""

from __future__ import annotations

import time

from sensormon.detection.base import Detector
from sensormon.models import Alert, Reading


class DetectionEngine:
    def __init__(self, detectors: list[Detector], cooldown_seconds: float = 15.0) -> None:
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds no puede ser negativo")
        self.detectors = detectors
        self.cooldown_seconds = cooldown_seconds
        self._last: dict[tuple[str, str, str], float] = {}

    def evaluate(self, reading: Reading) -> list[Alert]:
        alerts: list[Alert] = []
        now = time.monotonic()
        for detector in self.detectors:
            alert = detector.evaluate(reading)
            if alert is None:
                continue
            key = (alert.device_id, alert.metric.value, alert.detector)
            previous = self._last.get(key)
            if (
                self.cooldown_seconds > 0
                and previous is not None
                and now - previous < self.cooldown_seconds
            ):
                continue
            self._last[key] = now
            alerts.append(alert)
        return alerts
