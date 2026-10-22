from __future__ import annotations

import pytest

from sensormon.config import NotifierConfig, load_settings
from sensormon.factory import build_detectors, build_notifiers, build_simulator, resolve_transport
from sensormon.notify.console import ConsoleNotifier


def test_default_stack_uses_three_detectors_and_console() -> None:
    settings = load_settings()
    names = [detector.name for detector in build_detectors(settings)]
    assert names == ["threshold", "zscore", "ewma"]
    notifiers = build_notifiers(settings)
    assert len(notifiers) == 1
    assert isinstance(notifiers[0], ConsoleNotifier)
    simulator = build_simulator(settings, bus=type("Bus", (), {"publish": lambda *a, **k: None})())
    assert {device.id for device in simulator.devices} == {"lab-01", "warehouse-02", "pump-03"}


def test_webhook_without_url_fails() -> None:
    settings = load_settings()
    settings.notifiers = [NotifierConfig(type="webhook", enabled=True)]
    with pytest.raises(ValueError, match="url"):
        build_notifiers(settings)


def test_transport_resolution() -> None:
    settings = load_settings()
    assert resolve_transport(settings, None) == "mqtt"
    assert resolve_transport(settings, "memory") == "memory"
    settings.mqtt.enabled = False
    assert resolve_transport(settings, None) == "memory"
    with pytest.raises(ValueError):
        resolve_transport(settings, "kafka")


def test_isolation_forest_can_be_enabled() -> None:
    pytest.importorskip("sklearn")
    settings = load_settings()
    settings.detection.isolation_forest.enabled = True
    names = [detector.name for detector in build_detectors(settings)]
    assert names[-1] == "isolation_forest"
