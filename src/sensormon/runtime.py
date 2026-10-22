"""Arranque de simulador, colector y panel."""

from __future__ import annotations

import logging
import threading
import time

import uvicorn
from pydantic import ValidationError

from sensormon.api.app import create_app
from sensormon.bus import parse_topic
from sensormon.config import Settings, StorageConfig
from sensormon.factory import (
    build_bus,
    build_collector,
    build_simulator,
    open_store,
    resolve_transport,
)
from sensormon.hub import EventHub
from sensormon.models import Alert, Reading
from sensormon.storage.sqlite import SqliteStore

logger = logging.getLogger(__name__)


def _with_db(settings: Settings, db_path: str | None) -> Settings:
    if db_path is None:
        return settings
    return settings.model_copy(update={"storage": StorageConfig(path=db_path)})


def run_simulator(
    settings: Settings,
    *,
    transport: str,
    duration: float | None = None,
) -> None:
    bus = build_bus(settings, transport, "simulator")
    simulator = build_simulator(settings, bus)
    bus.start()
    logger.info(
        "Simulando %s dispositivos cada %.2fs (%s)",
        len(settings.simulator.devices),
        settings.simulator.interval_seconds,
        transport,
    )
    try:
        simulator.run(duration=duration)
    except KeyboardInterrupt:
        logger.info("Simulador detenido")
    finally:
        logger.info("Lecturas publicadas: %s", simulator.published)
        bus.stop()


def run_collector(
    settings: Settings,
    *,
    transport: str,
    duration: float | None = None,
    db_path: str | None = None,
) -> None:
    settings = _with_db(settings, db_path)
    store = open_store(settings)
    bus = build_bus(settings, transport, "collector")
    collector = build_collector(settings, bus, store)
    try:
        collector.start()
        logger.info("Colector en marcha (%s) → %s", transport, settings.storage.path)
        if duration is None:
            threading.Event().wait()
        else:
            threading.Event().wait(duration)
    except KeyboardInterrupt:
        logger.info("Colector detenido")
    finally:
        collector.stop()
        store.close()


def run_server(
    store: SqliteStore,
    hub: EventHub,
    *,
    host: str,
    port: int,
    duration: float | None = None,
    log_level: str = "info",
) -> None:
    app = create_app(store, hub=hub)
    config = uvicorn.Config(app, host=host, port=port, log_level=log_level)
    server = uvicorn.Server(config)
    if duration is not None or threading.current_thread() is not threading.main_thread():
        server.install_signal_handlers = False

    if duration is not None:

        def _stop() -> None:
            time.sleep(duration)
            server.should_exit = True

        threading.Thread(target=_stop, name="sensormon-stop", daemon=True).start()

        logger.info("Panel en http://%s:%s (datos: %s)", host, port, store.path)
    server.run()


def run_embedded(
    settings: Settings,
    *,
    host: str,
    port: int,
    duration: float | None = None,
    db_path: str | None = None,
    log_level: str = "info",
) -> None:
    settings = _with_db(settings, db_path)
    store = open_store(settings)
    hub = EventHub()
    bus = build_bus(settings, "memory", "embedded")
    stop = threading.Event()
    collector = build_collector(settings, bus, store, hub)
    simulator = build_simulator(settings, bus)
    collector.start()

    def _simulate() -> None:
        simulator.run(duration=duration, stop_event=stop)

    threading.Thread(target=_simulate, name="sensormon-simulator", daemon=True).start()
    logger.info("Modo embebido: simulador y colector comparten un bus en memoria")
    try:
        run_server(
            store,
            hub,
            host=host,
            port=port,
            duration=duration,
            log_level=log_level,
        )
    finally:
        stop.set()
        collector.stop()
        store.close()


def run_dashboard(
    settings: Settings,
    *,
    host: str,
    port: int,
    duration: float | None = None,
    db_path: str | None = None,
    log_level: str = "info",
) -> None:
    """Panel que lee SQLite y se suscribe al broker para el flujo en vivo."""

    settings = _with_db(settings, db_path)
    store = open_store(settings)
    hub = EventHub()
    bus = build_bus(settings, "mqtt", "dashboard")

    def on_sensor(topic: str, payload: dict) -> None:
        parsed = parse_topic(topic, settings.mqtt.topic_root)
        if parsed is None or parsed[1] == "meta":
            return
        try:
            reading = Reading.model_validate(payload)
        except ValidationError:
            logger.debug("Lectura en vivo inválida en %s", topic)
            return
        hub.publish({"type": "reading", "data": reading.model_dump(mode="json")})

    def on_alert(topic: str, payload: dict) -> None:
        try:
            alert = Alert.model_validate(payload)
        except ValidationError:
            logger.debug("Alerta en vivo inválida en %s", topic)
            return
        hub.publish({"type": "alert", "data": alert.model_dump(mode="json")})

    bus.subscribe(f"{settings.mqtt.topic_root}/#", on_sensor)
    bus.subscribe("alerts/#", on_alert)

    def _connect() -> None:
        try:
            bus.start()
        except Exception:
            logger.exception("El panel sigue activo sin flujo MQTT en vivo")

    threading.Thread(target=_connect, name="sensormon-mqtt-tail", daemon=True).start()
    try:
        run_server(
            store,
            hub,
            host=host,
            port=port,
            duration=duration,
            log_level=log_level,
        )
    finally:
        bus.stop()
        store.close()


def transport_or_raise(settings: Settings, explicit: str | None) -> str:
    try:
        return resolve_transport(settings, explicit)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
