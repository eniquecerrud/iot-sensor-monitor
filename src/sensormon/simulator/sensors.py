"""Generador de una magnitud con ruido de medida, deriva y ciclo lento."""

from __future__ import annotations

import math
import random
from datetime import datetime

from sensormon.config import FaultConfig, SensorConfig
from sensormon.models import Metric, Quality, Reading
from sensormon.util import utcnow


class VirtualSensor:
    def __init__(self, metric: str, spec: SensorConfig, rng: random.Random) -> None:
        self.metric = Metric(metric)
        self.spec = spec
        self.rng = rng
        self.state = spec.baseline

    def sample(
        self,
        *,
        device_id: str,
        elapsed: float,
        dt: float,
        fault: FaultConfig | None,
        now: datetime | None = None,
    ) -> Reading | None:
        spec = self.spec
        step = max(dt, 0.0)
        self.state += spec.drift * step
        self.state += spec.reversion * (spec.baseline - self.state) * step
        if spec.noise > 0 and step > 0:
            self.state += self.rng.gauss(0, spec.noise * 0.2 * math.sqrt(step))

        diurnal = 0.0
        if spec.diurnal_amplitude:
            diurnal = spec.diurnal_amplitude * math.sin(
                2 * math.pi * elapsed / spec.cycle_period_seconds
            )
        measured = self.state + diurnal
        if spec.noise > 0:
            measured += self.rng.gauss(0, spec.noise)

        quality = Quality.good
        if fault is not None:
            if fault.kind == "dropout":
                return None
            if fault.kind == "spike":
                measured += fault.magnitude
                quality = Quality.spike
            elif fault.kind == "bias":
                measured += fault.magnitude
                quality = Quality.fault
            elif fault.kind == "stuck":
                measured = fault.magnitude
                quality = Quality.fault
        elif spec.min_value is not None or spec.max_value is not None:
            if spec.min_value is not None:
                measured = max(spec.min_value, measured)
            if spec.max_value is not None:
                measured = min(spec.max_value, measured)

        return Reading(
            device_id=device_id,
            metric=self.metric,
            value=measured,
            unit=spec.unit,
            timestamp=now or utcnow(),
            quality=quality,
        )
