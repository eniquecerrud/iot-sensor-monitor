from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from sensormon.config import MqttConfig, Settings, ThresholdRule, load_settings


def test_default_yaml_loads_sample_devices() -> None:
    settings = load_settings()
    ids = [device.id for device in settings.simulator.devices]
    assert ids == ["lab-01", "warehouse-02", "pump-03"]
    assert settings.mqtt.host == "127.0.0.1"
    assert settings.detection.isolation_forest.enabled is False
    assert "temperature" in settings.detection.thresholds


def test_env_overrides_yaml(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SENSOR_MQTT__HOST", "broker.internal")
    monkeypatch.setenv("SENSOR_MQTT__PORT", "1884")
    monkeypatch.setenv("SENSOR_SIMULATOR__INTERVAL_SECONDS", "0.25")
    monkeypatch.setenv("SENSOR_DETECTION__ISOLATION_FOREST__ENABLED", "true")
    settings = load_settings()
    assert settings.mqtt.host == "broker.internal"
    assert settings.mqtt.port == 1884
    assert settings.simulator.interval_seconds == 0.25
    assert settings.detection.isolation_forest.enabled is True


def test_init_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SENSOR_MQTT__HOST", "from-env")
    settings = load_settings(mqtt=MqttConfig(host="from-init"))
    assert settings.mqtt.host == "from-init"


def test_explicit_config_and_missing_file(tmp_path: Path) -> None:
    path = tmp_path / "custom.yaml"
    path.write_text("mqtt:\n  host: cola\n", encoding="utf-8")
    settings = load_settings(path)
    assert settings.mqtt.host == "cola"
    assert settings.simulator.devices == []
    with pytest.raises(FileNotFoundError):
        load_settings(tmp_path / "no-existe.yaml")


def test_yaml_must_be_a_mapping(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("- uno\n- dos\n", encoding="utf-8")
    with pytest.raises(ValueError, match="mapa YAML"):
        load_settings(path)


def test_threshold_order_is_validated() -> None:
    with pytest.raises(ValidationError):
        ThresholdRule(min=10, max=5)


def test_empty_yaml_uses_defaults(tmp_path: Path) -> None:
    path = tmp_path / "empty.yaml"
    path.write_text("", encoding="utf-8")
    settings = load_settings(path)
    assert isinstance(settings, Settings)
    assert settings.api.port == 8000
    assert settings.notifiers[0].type == "console"
