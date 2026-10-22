from __future__ import annotations

import random

import pytest

from sensormon.bus import InMemoryBus
from sensormon.config import DeviceConfig, FaultConfig, SensorConfig
from sensormon.simulator.runner import Simulator, parse_fault_token
from sensormon.simulator.sensors import VirtualSensor
from tests.conftest import at


def _spec(**overrides: object) -> SensorConfig:
    data: dict[str, object] = {
        "baseline": 20.0,
        "noise": 0.0,
        "drift": 0.0,
        "reversion": 0.0,
        "unit": "°C",
        "diurnal_amplitude": 0.0,
    }
    data.update(overrides)
    return SensorConfig(**data)


def test_sample_is_deterministic_without_noise() -> None:
    sensor = VirtualSensor("temperature", _spec(), random.Random(1))
    reading = sensor.sample(device_id="lab-01", elapsed=0, dt=1, fault=None, now=at(0))
    assert reading is not None
    assert reading.value == pytest.approx(20.0)
    assert reading.quality.value == "good"


def test_drift_reversion_and_diurnal_cycle() -> None:
    drifting = VirtualSensor("temperature", _spec(drift=0.5), random.Random(1))
    drifted = drifting.sample(device_id="lab-01", elapsed=0, dt=2, fault=None, now=at(0))
    assert drifted is not None
    assert drifted.value == pytest.approx(21.0)

    pulled = VirtualSensor("temperature", _spec(baseline=10, reversion=1), random.Random(1))
    pulled.state = 30
    reverted = pulled.sample(device_id="lab-01", elapsed=0, dt=1, fault=None, now=at(0))
    assert reverted is not None
    assert reverted.value == pytest.approx(10.0)

    cyclic = VirtualSensor(
        "temperature",
        _spec(baseline=0, diurnal_amplitude=2, cycle_period_seconds=4),
        random.Random(1),
    )
    wave = cyclic.sample(device_id="lab-01", elapsed=1, dt=0, fault=None, now=at(1))
    assert wave is not None
    assert wave.value == pytest.approx(2.0)


def test_noise_changes_the_series() -> None:
    sensor = VirtualSensor("humidity", _spec(noise=1.0, unit="%"), random.Random(3))
    values = [
        sensor.sample(device_id="lab-01", elapsed=index, dt=1, fault=None, now=at(index)).value
        for index in range(12)
    ]
    assert len(set(round(value, 5) for value in values)) > 1


def test_faults_and_physical_clamp() -> None:
    sensor = VirtualSensor("temperature", _spec(min_value=10, max_value=25), random.Random(1))
    clamped = sensor.sample(device_id="lab-01", elapsed=0, dt=1, fault=None, now=at(0))
    assert clamped is not None
    assert clamped.value == pytest.approx(20.0)

    low = VirtualSensor("temperature", _spec(baseline=0, min_value=10), random.Random(1))
    clamped_low = low.sample(device_id="lab-01", elapsed=0, dt=1, fault=None, now=at(0))
    assert clamped_low is not None
    assert clamped_low.value == pytest.approx(10.0)

    spiked = sensor.sample(
        device_id="lab-01",
        elapsed=1,
        dt=1,
        fault=FaultConfig(device_id="lab-01", metric="temperature", kind="spike", magnitude=30),
        now=at(1),
    )
    assert spiked is not None
    assert spiked.quality.value == "spike"
    assert spiked.value == pytest.approx(50.0)

    stuck = sensor.sample(
        device_id="lab-01",
        elapsed=2,
        dt=1,
        fault=FaultConfig(device_id="lab-01", metric="temperature", kind="stuck", magnitude=21.5),
        now=at(2),
    )
    assert stuck is not None
    assert stuck.value == pytest.approx(21.5)
    assert stuck.quality.value == "fault"

    biased = sensor.sample(
        device_id="lab-01",
        elapsed=3,
        dt=1,
        fault=FaultConfig(device_id="lab-01", metric="temperature", kind="bias", magnitude=-3),
        now=at(3),
    )
    assert biased is not None
    assert biased.value == pytest.approx(17.0)

    dropped = sensor.sample(
        device_id="lab-01",
        elapsed=4,
        dt=1,
        fault=FaultConfig(device_id="lab-01", metric="temperature", kind="dropout"),
        now=at(4),
    )
    assert dropped is None


def test_parse_fault_token() -> None:
    fault = parse_fault_token("pump-03:*:bias:1.5:2:9")
    assert fault.device_id == "pump-03"
    assert fault.metric is None
    assert fault.kind == "bias"
    assert fault.magnitude == pytest.approx(1.5)
    assert fault.start_after == pytest.approx(2)
    assert fault.duration == pytest.approx(9)
    with pytest.raises(ValueError):
        parse_fault_token("solo-dos:partes")
    with pytest.raises(ValueError):
        parse_fault_token("lab-01:temperature:nope:1")


def test_simulator_publishes_meta_and_spike() -> None:
    device = DeviceConfig(
        id="lab-01",
        location="Banco",
        sensors={"temperature": _spec(), "humidity": _spec(baseline=40, unit="%")},
    )
    fault = FaultConfig(
        device_id="lab-01",
        metric="temperature",
        kind="spike",
        magnitude=8,
        start_after=0,
        duration=5,
    )
    bus = InMemoryBus()
    seen: list[tuple[str, dict]] = []
    bus.subscribe("sensors/#", lambda topic, payload: seen.append((topic, payload)))
    simulator = Simulator([device], [fault], bus, interval=0.05, seed=1)
    simulator.run(duration=0.12)
    topics = [topic for topic, _payload in seen]
    assert "sensors/lab-01/meta" in topics
    temps = [payload for topic, payload in seen if topic.endswith("/temperature")]
    assert temps
    assert temps[0]["quality"] == "spike"
    assert temps[0]["value"] == pytest.approx(28.0)
    assert simulator.published == len(temps) + sum(topic.endswith("/humidity") for topic in topics)
