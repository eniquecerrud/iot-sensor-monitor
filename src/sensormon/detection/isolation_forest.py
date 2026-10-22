"""Isolation Forest univariante. Requiere el extra `sensormon[ml]`.

En una serie muy estrecha el bosque asigna la misma puntuación a cualquier
punto fuera del rango observado y puede no cruzar el umbral. Si eso ocurre,
un z-score robusto (mediana y MAD) de la misma ventana actúa de respaldo.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict, deque

import numpy as np
from sklearn.ensemble import IsolationForest

from sensormon.detection.base import describe, make_alert
from sensormon.models import Alert, Reading


class IsolationForestDetector:
    name = "isolation_forest"

    def __init__(
        self,
        *,
        window: int = 40,
        contamination: float = 0.05,
        min_samples: int = 30,
        refit_every: int = 10,
        random_state: int = 0,
        n_estimators: int = 80,
    ) -> None:
        self.window = window
        self.contamination = contamination
        self.min_samples = min_samples
        self.refit_every = refit_every
        self.random_state = random_state
        self.n_estimators = n_estimators
        self.robust_z = 8.0
        self._history: dict[tuple[str, str], deque[float]] = defaultdict(
            lambda: deque(maxlen=window)
        )
        self._models: dict[tuple[str, str], IsolationForest] = {}
        self._seen: dict[tuple[str, str], int] = defaultdict(int)

    def evaluate(self, reading: Reading) -> Alert | None:
        key = (reading.device_id, reading.metric.value)
        history = self._history[key]
        model = self._models.get(key)
        alert: Alert | None = None
        if model is not None and len(history) >= self.min_samples:
            point = np.array([[reading.value]], dtype=float)
            prediction = int(model.predict(point)[0])
            score = float(model.decision_function(point)[0])
            robust = self._robust_z(reading.value, history)
            # El bosque univariante satura fuera de un rango diminuto (score ~ 0
            # y predicción normal). El z robusto cubre ese pico evidente.
            if prediction == -1 or abs(robust) >= self.robust_z:
                alert = make_alert(
                    reading,
                    detector=self.name,
                    severity="warning",
                    message=(
                        f"{describe(reading)} aislada por Isolation Forest (score={score:.3f})"
                    ),
                    score=score,
                )
        history.append(reading.value)
        self._seen[key] += 1
        if len(history) >= self.min_samples and (
            model is None or self._seen[key] % self.refit_every == 0
        ):
            self._models[key] = self._fit(history)
        return alert

    def _fit(self, history: deque[float]) -> IsolationForest:
        samples = np.fromiter(history, dtype=float).reshape(-1, 1)
        model = IsolationForest(
            n_estimators=self.n_estimators,
            contamination=self.contamination,
            random_state=self.random_state,
            n_jobs=1,
        )
        model.fit(samples)
        return model

    @staticmethod
    def _robust_z(value: float, history: deque[float]) -> float:
        median = statistics.median(history)
        mad = statistics.median(abs(item - median) for item in history)
        if mad < 1e-9:
            if abs(value - median) <= 1e-6:
                return 0.0
            return math.inf if value > median else -math.inf
        return 0.6745 * (value - median) / mad
