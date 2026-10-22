"""Media móvil exponencial con varianza en línea.

La lectura se puntúa contra el estado anterior y después actualiza la media,
así un salto no se diluye en el mismo paso que lo detecta.
"""

from __future__ import annotations

import math
from collections import defaultdict

from sensormon.detection.base import describe, make_alert
from sensormon.models import Alert, Reading


class EwmaDetector:
    name = "ewma"

    def __init__(self, alpha: float, threshold: float, min_samples: int) -> None:
        if not 0 < alpha <= 1:
            raise ValueError("alpha debe estar en (0, 1]")
        if threshold <= 0 or min_samples < 2:
            raise ValueError("parámetros EWMA inválidos")
        self.alpha = alpha
        self.threshold = threshold
        self.min_samples = min_samples
        self._mean: dict[tuple[str, str], float] = {}
        self._var: dict[tuple[str, str], float] = {}
        self._count: dict[tuple[str, str], int] = defaultdict(int)

    def evaluate(self, reading: Reading) -> Alert | None:
        key = (reading.device_id, reading.metric.value)
        value = reading.value
        alert: Alert | None = None
        if key in self._mean and self._count[key] >= self.min_samples:
            mean = self._mean[key]
            std = math.sqrt(self._var[key]) if self._var[key] > 0 else 0.0
            z = self._z(value, mean, std)
            if abs(z) >= self.threshold:
                severity = "critical" if abs(z) >= self.threshold * 1.5 else "warning"
                alert = make_alert(
                    reading,
                    detector=self.name,
                    severity=severity,  # type: ignore[arg-type]
                    message=(
                        f"{describe(reading)} se desvía de la media exponencial "
                        f"(z={z:.2f}, ewma={mean:.2f})"
                    ),
                    score=z,
                )
        self._update(key, value)
        return alert

    def _update(self, key: tuple[str, str], value: float) -> None:
        if key not in self._mean:
            self._mean[key] = value
            self._var[key] = 0.0
        else:
            previous = self._mean[key]
            delta = value - previous
            self._mean[key] = previous + self.alpha * delta
            self._var[key] = (1 - self.alpha) * (self._var[key] + self.alpha * delta * delta)
        self._count[key] += 1

    @staticmethod
    def _z(value: float, mean: float, std: float) -> float:
        if std < 1e-9:
            if abs(value - mean) <= 1e-6:
                return 0.0
            return math.inf if value > mean else -math.inf
        return (value - mean) / std
