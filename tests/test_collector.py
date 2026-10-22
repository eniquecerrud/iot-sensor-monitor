from __future__ import annotations

from pathlib import Path

import pytest

from sensormon.bus import InMemoryBus
from sensormon.collector.service import Collector
from sensormon.config import (
    DeviceConfig,
    FaultConfig,
    SensorConfig,
    load_settings,
)
from sensormon.factory import build_engine, build_simulator
from sensormon.notify.console import ConsoleNotifier
from sensormon.storage.sqlite import SqliteStore
from tests.conftest import at, make_reading


def _settings(tmp_path: Path):
    config = tmp_path / "cfg.yaml"
    config.write_text(
        """
mqtt:
  topic_root: sensors
storage:
  path: ignored.db
simulator:
  interval_seconds: 0.05
  seed: 2
  devices:
    - id: lab-01
      location: Banco de pruebas
      sensors:
        temperature:
          baseline: 22
          noise: 0
          drift: 0
          reversion: 0
          unit: "°C"
  faults:
    - device_id: lab-01
      metric: temperature
      kind: spike
      magnitude: 40
      start_after: 0
      duration: 10
detection:
  cooldown_seconds: 0
  thresholds:
    temperature:
      max: 30
      critical_max: 50
  zscore:
    enabled: false
  ewma:
    enabled: false
notifiers: []
""",
        encoding="utf-8",
    )
    return load_settings(config, storage={"path": str(tmp_path / "live.db")})


def test_pipeline_stores_reading_and_critical_alert(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    settings = _settings(tmp_path)
    store = SqliteStore(settings.storage.path)
    bus = InMemoryBus()
    events: list[dict] = []
    collector = Collector(
        bus,
        store,
        build_engine(settings),
        [ConsoleNotifier()],
        hub=type("Hub", (), {"publish": lambda self, event: events.append(event)})(),
        topic_root="sensors",
    )
    collector.start()
    build_simulator(settings, bus).run(duration=0.12)
    bus.publish(
        "sensors/lab-01/temperature",
        {"device_id": "lab-01", "metric": "temperature", "value": "caliente", "unit": "°C"},
    )
    mismatched = make_reading(device_id="otro").model_dump(mode="json")
    bus.publish("sensors/lab-01/temperature", mismatched)
    bus.publish(
        "sensors/lab-01/meta",
        {"device_id": "otro", "location": "no", "sensors": ["temperature"]},
    )
    bus.publish("sensors/solo", {"value": 1})
    collector.stop()

    readings = store.list_readings()
    assert readings
    assert readings[0].value == pytest.approx(62.0)
    assert readings[0].quality.value == "spike"
    alerts = store.list_alerts()
    assert alerts
    assert alerts[0].severity == "critical"
    assert alerts[0].detector == "threshold"
    devices = store.list_devices()
    assert devices[0].location == "Banco de pruebas"
    assert any(event["type"] == "alert" for event in events)
    assert collector.rejected == 4
    assert "critical" in caplog.text
    store.close()


def test_collector_accepts_a_direct_reading(tmp_path: Path) -> None:
    store = SqliteStore(str(tmp_path / "db.sqlite"))
    bus = InMemoryBus()
    settings = _settings(tmp_path)
    collector = Collector(bus, store, build_engine(settings), topic_root="sensors")
    collector.start()
    bus.publish(
        "sensors/warehouse-02/humidity",
        make_reading(
            device_id="warehouse-02",
            metric="humidity",
            value=55,
            unit="%",
            timestamp=at(3),
        ).model_dump(mode="json"),
    )
    collector.stop()
    assert collector.accepted == 1
    assert store.list_readings(metric="humidity")[0].value == 55
    store.close()


def test_simulator_config_models_are_reusable() -> None:
    device = DeviceConfig(
        id="pump-03",
        sensors={"vibration": SensorConfig(baseline=1, noise=0, unit="mm/s")},
    )
    fault = FaultConfig(device_id="pump-03", metric="vibration", kind="bias", magnitude=2)
    assert device.sensors["vibration"].unit == "mm/s"
    assert fault.kind == "bias"
