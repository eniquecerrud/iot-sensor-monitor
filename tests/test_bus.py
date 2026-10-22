from __future__ import annotations

import json

import pytest

from sensormon.bus import InMemoryBus, MqttBus, decode_payload, parse_topic, topic_matches


@pytest.mark.parametrize(
    ("pattern", "topic", "expected"),
    [
        ("sensors/#", "sensors/lab-01/temperature", True),
        ("sensors/#", "sensors", True),
        ("sensors/+/temperature", "sensors/lab-01/temperature", True),
        ("sensors/+/temperature", "sensors/lab-01/humidity", False),
        ("sensors/+", "sensors/lab-01/temperature", False),
        ("#", "alerts/lab-01", True),
        ("alerts/+", "alerts/lab-01", True),
        ("a/#/b", "a/x/b", False),
        ("sensors/lab-01/co2", "sensors/lab-01/co2", True),
    ],
)
def test_topic_matches(pattern: str, topic: str, expected: bool) -> None:
    assert topic_matches(pattern, topic) is expected


def test_parse_topic() -> None:
    assert parse_topic("sensors/lab-01/temperature") == ("lab-01", "temperature")
    assert parse_topic("sensors/lab-01/meta") == ("lab-01", "meta")
    assert parse_topic("alerts/lab-01") is None
    assert parse_topic("sensors/lab-01/temperature", root="other") is None


def test_decode_payload() -> None:
    assert decode_payload(b'{"value": 1}') == {"value": 1}
    assert decode_payload('{"value": 2}') == {"value": 2}
    with pytest.raises(ValueError):
        decode_payload(b"[1, 2]")
    with pytest.raises(json.JSONDecodeError):
        decode_payload(b"{")


def test_memory_bus_delivers_and_isolates_wildcards() -> None:
    bus = InMemoryBus()
    seen: list[str] = []
    bus.subscribe("sensors/+/temperature", lambda topic, _payload: seen.append(topic))
    bus.subscribe("alerts/#", lambda topic, _payload: seen.append(topic))
    bus.publish("sensors/lab-01/temperature", {"value": 1})
    bus.publish("sensors/lab-01/humidity", {"value": 2})
    bus.publish("alerts/lab-01", {"id": 3}, retain=True)
    assert seen == ["sensors/lab-01/temperature", "alerts/lab-01"]
    assert bus.subscriber_count() == 2


def test_memory_bus_propagates_subscriber_errors() -> None:
    bus = InMemoryBus()

    def boom(_topic: str, _payload: dict) -> None:
        raise RuntimeError("fallo")

    bus.subscribe("a", boom)
    with pytest.raises(RuntimeError, match="fallo"):
        bus.publish("a", {})


def test_mqtt_bus_rejects_bad_payloads_and_routes_good_ones() -> None:
    bus = MqttBus("127.0.0.1", 1, client_id="test", connect_attempts=1)
    seen: list[dict] = []

    def fail(_topic: str, _payload: dict) -> None:
        raise RuntimeError("suscriptor")

    bus.subscribe("sensors/#", fail)
    bus.subscribe("sensors/+/temperature", lambda _topic, payload: seen.append(payload))
    bus._handle_raw("sensors/lab-01/temperature", b'{"value": 21}')
    bus._handle_raw("sensors/lab-01/temperature", b"no-json")
    bus._handle_raw("sensors/lab-01/temperature", b"[]")
    assert seen == [{"value": 21}]
    with pytest.raises(RuntimeError, match="conectado"):
        bus.publish("sensors/x/y", {"value": 1})
    bus.stop()


def test_mqtt_connect_failure_is_fast() -> None:
    bus = MqttBus("127.0.0.1", 1, client_id="refused", connect_attempts=1)
    with pytest.raises(ConnectionError):
        bus.start()
