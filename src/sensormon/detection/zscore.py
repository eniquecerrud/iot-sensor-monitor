"""Z-score sobre una ventana móvil, calculado sin incluir el punto actual."""

from __future__ import annotations

import math
import statistics
from collections import defaultdict, deque

from sensormon.detection.base import describe, make_alert
from sensormon.models import Alert, Reading


class ZScoreDetector:
    name = "zscore"

    def __init__(self, window: int, threshold: float, min_samples: int) -> None:
        if window < 2 or min_samples < 2 or min_samples > window:
            raise ValueError("ventana z-score inválida")
        if threshold <= 0:
            raise ValueError("el umbral z-score debe ser positivo")
        self.window = window
        self.threshold = threshold
        self.min_samples = min_samples
        self._history: dict[tuple[str, str], deque[float]] = defaultdict(
            lambda: deque(maxlen=window)
        )

    def evaluate(self, reading: Reading) -> Alert | None:
        key = (reading.device_id, reading.metric.value)
        history = self._history[key]
        alert: Alert | None = None
        if len(history) >= self.min_samples:
            mean = statistics.fmean(history)
            std = statistics.stdev(history)
            z = self._z(reading.value, mean, std)
            if abs(z) >= self.threshold:
                severity = "critical" if abs(z) >= self.threshold * 1.5 else "warning"
                alert = make_alert(
                    reading,
                    detector=self.name,
                    severity=severity,  # type: ignore[arg-type]
                    message=(
                        f"{describe(reading)} anómala respecto a la ventana "
                        f"(z={z:.2f}, media={mean:.2f})"
                    ),
                    score=z,
                )
        history.append(reading.value)
        return alert

    @staticmethod
    def _z(value: float, mean: float, std: float) -> float:
        if std < 1e-9:
            if abs(value - mean) <= 1e-6:
                return 0.0
            return math.inf if value > mean else -math.inf
        return (value - mean) / std
