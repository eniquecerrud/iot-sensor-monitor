"""Bucle del simulador. Publica telemetría y un anuncio por dispositivo."""

from __future__ import annotations

import random
import threading
import time

from sensormon.bus import MessageBus
from sensormon.config import DeviceConfig, FaultConfig
from sensormon.models import DeviceAnnouncement, Metric
from sensormon.simulator.sensors import VirtualSensor
from sensormon.util import utcnow


def parse_fault_token(token: str) -> FaultConfig:
    """Formato: `dispositivo:metrica:tipo:magnitud[:inicio[:duracion]]`.

    `metrica` puede ser `*` para aplicar la avería a todos los sensores.
    """

    parts = token.split(":")
    if len(parts) < 4 or len(parts) > 6:
        raise ValueError(
            "Avería inválida. Usa dispositivo:metrica:tipo:magnitud[:inicio[:duracion]]"
        )
    metric = parts[1]
    try:
        magnitude = float(parts[3])
        start_after = float(parts[4]) if len(parts) > 4 else 0.0
        duration = float(parts[5]) if len(parts) > 5 else 30.0
    except ValueError as exc:
        raise ValueError(f"No se pudieron leer los números de la avería: {token}") from exc
    return FaultConfig(
        device_id=parts[0],
        metric=None if metric == "*" else metric,
        kind=parts[2],  # type: ignore[arg-type]
        magnitude=magnitude,
        start_after=start_after,
        duration=duration,
    )


class Simulator:
    def __init__(
        self,
        devices: list[DeviceConfig],
        faults: list[FaultConfig],
        bus: MessageBus,
        *,
        interval: float,
        seed: int | None = 7,
        topic_root: str = "sensors",
    ) -> None:
        if interval <= 0:
            raise ValueError("interval debe ser positivo")
        self.devices = devices
        self.faults = faults
        self.bus = bus
        self.interval = interval
        self.topic_root = topic_root
        master = random.Random(seed)
        self._series: list[tuple[DeviceConfig, VirtualSensor]] = []
        for device in devices:
            for metric, spec in device.sensors.items():
                rng = random.Random(master.randrange(1, 2**31 - 1))
                self._series.append((device, VirtualSensor(metric, spec, rng)))
        self.published = 0

    def announce(self) -> None:
        for device in self.devices:
            payload = DeviceAnnouncement(
                device_id=device.id,
                location=device.location,
                sensors=[Metric(name) for name in device.sensors],
            ).model_dump(mode="json")
            self.bus.publish(f"{self.topic_root}/{device.id}/meta", payload, retain=True)

    def active_fault(self, device_id: str, metric: str, elapsed: float) -> FaultConfig | None:
        for fault in self.faults:
            if fault.device_id != device_id:
                continue
            if fault.metric not in (None, metric):
                continue
            if fault.start_after <= elapsed < fault.start_after + fault.duration:
                return fault
        return None

    def tick(self, elapsed: float, dt: float) -> int:
        now = utcnow()
        sent = 0
        for device, sensor in self._series:
            fault = self.active_fault(device.id, sensor.metric.value, elapsed)
            reading = sensor.sample(
                device_id=device.id,
                elapsed=elapsed,
                dt=dt,
                fault=fault,
                now=now,
            )
            if reading is None:
                continue
            topic = f"{self.topic_root}/{device.id}/{sensor.metric.value}"
            self.bus.publish(topic, reading.model_dump(mode="json"))
            sent += 1
        self.published += sent
        return sent

    def run(
        self,
        *,
        duration: float | None = None,
        stop_event: threading.Event | None = None,
    ) -> None:
        self.announce()
        started = time.monotonic()
        next_tick = started
        while stop_event is None or not stop_event.is_set():
            elapsed = time.monotonic() - started
            if duration is not None and elapsed >= duration:
                break
            self.tick(elapsed, self.interval)
            next_tick += self.interval
            pause = next_tick - time.monotonic()
            if duration is not None:
                pause = min(pause, duration - (time.monotonic() - started))
            if pause > 0:
                if stop_event is not None:
                    if stop_event.wait(pause):
                        break
                else:
                    time.sleep(pause)
