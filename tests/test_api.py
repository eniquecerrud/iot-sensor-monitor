from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from sensormon.api.app import create_app
from sensormon.hub import EventHub
from sensormon.models import Alert
from sensormon.storage.sqlite import SqliteStore
from tests.conftest import at, make_reading


def _client(tmp_path: Path) -> tuple[TestClient, SqliteStore, EventHub]:
    store = SqliteStore(str(tmp_path / "api.db"))
    store.init()
    hub = EventHub()
    app = create_app(store, hub=hub)
    return TestClient(app), store, hub


def test_health_catalog_and_dashboard(tmp_path: Path) -> None:
    client, store, _hub = _client(tmp_path)
    with client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"
        catalog = client.get("/api/catalog").json()
        assert len(catalog) == 5
        page = client.get("/")
        assert page.status_code == 200
        assert "Sensormon" in page.text
        assert client.get("/static/app.js").status_code == 200
        assert client.get("/static/styles.css").status_code == 200
        assert client.get("/api/devices").json() == []
        assert client.get("/api/alerts").json() == []
    store.close()


def test_readings_alerts_and_validation(tmp_path: Path) -> None:
    client, store, _hub = _client(tmp_path)
    store.insert_reading(make_reading(value=21, timestamp=at(1)))
    store.insert_reading(
        make_reading(device_id="pump-03", metric="vibration", value=2, unit="mm/s", timestamp=at(2))
    )
    store.insert_alert(
        Alert(
            device_id="lab-01",
            metric="temperature",
            detector="threshold",
            severity="warning",
            message="calor",
            value=40,
            timestamp=at(3),
        )
    )
    with client:
        readings = client.get(
            "/api/readings",
            params={"device_id": "lab-01", "metric": "temperature"},
        )
        assert readings.status_code == 200
        assert readings.json()[0]["value"] == 21
        assert client.get("/api/readings", params={"metric": "nope"}).status_code == 422
        alerts = client.get("/api/alerts", params={"severity": "warning"}).json()
        assert alerts[0]["message"] == "calor"
        assert client.get("/api/alerts", params={"severity": "alta"}).status_code == 422
        devices = client.get("/api/devices").json()
        assert {item["device_id"] for item in devices} == {"lab-01", "pump-03"}
    store.close()


def test_websocket_forwards_live_events(tmp_path: Path) -> None:
    client, store, hub = _client(tmp_path)
    with client, client.websocket_connect("/ws/live") as websocket:
        snapshot = websocket.receive_json()
        assert snapshot["type"] == "snapshot"
        hub.publish({"type": "reading", "data": make_reading().model_dump(mode="json")})
        event = websocket.receive_json()
        assert event["type"] == "reading"
        assert event["data"]["device_id"] == "lab-01"
    store.close()
