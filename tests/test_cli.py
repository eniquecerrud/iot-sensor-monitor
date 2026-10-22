from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import httpx
from typer.testing import CliRunner

from sensormon.cli import app
from sensormon.config import load_settings
from sensormon.models import Alert
from sensormon.runtime import run_embedded
from sensormon.simulator.runner import parse_fault_token
from sensormon.storage.sqlite import SqliteStore
from tests.conftest import at, make_reading

runner = CliRunner()


def test_help_and_version() -> None:
    help_result = runner.invoke(app, ["--help"])
    assert help_result.exit_code == 0
    for command in ("simulate", "collect", "serve", "dashboard", "devices", "alerts"):
        assert command in help_result.stdout
    version = runner.invoke(app, ["--version"])
    assert version.exit_code == 0
    assert version.stdout.strip()
    bad_level = runner.invoke(app, ["--log-level", "LOUD", "devices", "--db", "data/unused.db"])
    assert bad_level.exit_code == 2


def test_devices_and_alerts_commands(tmp_path: Path) -> None:
    db = tmp_path / "cli.db"
    empty = runner.invoke(app, ["devices", "--db", str(db), "--json"])
    assert empty.exit_code == 0
    assert empty.stdout.strip() == "[]"

    store = SqliteStore(str(db))
    store.init()
    store.upsert_device("lab-01", location="Laboratorio", sensors=["temperature"], seen=at(0))
    store.insert_reading(make_reading())
    store.insert_alert(
        Alert(
            device_id="lab-01",
            metric="temperature",
            detector="threshold",
            severity="critical",
            message="demasiado calor",
            value=70,
            timestamp=at(2),
        )
    )
    store.insert_alert(
        Alert(
            device_id="pump-03",
            metric="vibration",
            detector="ewma",
            severity="warning",
            message="vibración",
            value=6,
            timestamp=at(3),
        )
    )
    store.close()

    listed = runner.invoke(app, ["devices", "--db", str(db)])
    assert listed.exit_code == 0
    assert "lab-01" in listed.stdout
    assert "Laboratorio" in listed.stdout

    critical = runner.invoke(
        app,
        ["alerts", "--db", str(db), "--severity", "critical", "--json"],
    )
    assert critical.exit_code == 0
    assert "demasiado calor" in critical.stdout
    assert "pump-03" not in critical.stdout
    invalid = runner.invoke(app, ["alerts", "--db", str(db), "--severity", "alta"])
    assert invalid.exit_code == 2


def test_simulate_and_collect_in_memory(tmp_path: Path) -> None:
    simulated = runner.invoke(
        app,
        ["--log-level", "WARNING", "simulate", "--transport", "memory", "--duration", "0.1"],
    )
    assert simulated.exit_code == 0, simulated.stdout + simulated.stderr
    collected = runner.invoke(
        app,
        [
            "--log-level",
            "WARNING",
            "collect",
            "--transport",
            "memory",
            "--duration",
            "0.1",
            "--db",
            str(tmp_path / "empty.db"),
        ],
    )
    assert collected.exit_code == 0, collected.output


def test_invalid_config_and_fault(tmp_path: Path) -> None:
    missing = runner.invoke(
        app,
        ["devices", "--config", str(tmp_path / "missing.yaml"), "--db", str(tmp_path / "a.db")],
    )
    assert missing.exit_code == 2
    bad_fault = runner.invoke(
        app,
        ["simulate", "--transport", "memory", "--duration", "0.05", "--fault", "esto-no-vale"],
    )
    assert bad_fault.exit_code == 2


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_serve_flags_reach_embedded_runtime(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_run(settings, **kwargs):
        captured["port"] = kwargs["port"]
        captured["duration"] = kwargs["duration"]
        captured["faults"] = list(settings.simulator.faults)
        captured["device"] = settings.simulator.devices[0].id

    monkeypatch.setattr("sensormon.cli.run_embedded", fake_run)
    result = runner.invoke(
        app,
        [
            "serve",
            "--embedded",
            "--host",
            "127.0.0.1",
            "--port",
            "8765",
            "--duration",
            "1.5",
            "--db",
            str(tmp_path / "ignored.db"),
            "--fault",
            "lab-01:temperature:spike:5:0:4",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["port"] == 8765
    assert captured["duration"] == 1.5
    assert captured["device"] == "lab-01"
    assert captured["faults"][-1].kind == "spike"


def test_embedded_serve_exposes_live_data(tmp_path: Path) -> None:
    port = _free_port()
    config = tmp_path / "demo.yaml"
    config.write_text(
        """
mqtt:
  enabled: false
simulator:
  interval_seconds: 0.08
  seed: 1
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
detection:
  cooldown_seconds: 30
  thresholds:
    temperature:
      max: 30
      critical_max: 50
  zscore:
    enabled: false
  ewma:
    enabled: false
notifiers:
  - type: console
""",
        encoding="utf-8",
    )
    settings = load_settings(config)
    fault = parse_fault_token("lab-01:temperature:spike:40:0:10")
    settings = settings.model_copy(
        update={"simulator": settings.simulator.model_copy(update={"faults": [fault]})}
    )
    db = tmp_path / "embedded.db"
    errors: list[BaseException] = []

    def run() -> None:
        try:
            run_embedded(
                settings,
                host="127.0.0.1",
                port=port,
                duration=3,
                db_path=str(db),
                log_level="warning",
            )
        except BaseException as exc:  # noqa: BLE001 - el hilo debe devolver el fallo
            errors.append(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 8
    health = None
    while time.monotonic() < deadline:
        try:
            health = httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=0.4)
            if health.status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    assert health is not None and health.status_code == 200

    readings: list[dict] = []
    alerts: list[dict] = []
    while time.monotonic() < deadline:
        readings = httpx.get(f"http://127.0.0.1:{port}/api/readings", timeout=1).json()
        alerts = httpx.get(f"http://127.0.0.1:{port}/api/alerts", timeout=1).json()
        if readings and alerts:
            break
        time.sleep(0.1)
    page = httpx.get(f"http://127.0.0.1:{port}/", timeout=1)
    thread.join(timeout=8)

    assert not errors
    assert readings, "el modo embebido no guardó lecturas"
    assert readings[0]["device_id"] == "lab-01"
    assert any(item["severity"] == "critical" for item in alerts)
    assert "Sensormon" in page.text
