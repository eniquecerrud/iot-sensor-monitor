"""Ensambla bus, almacenamiento, detectores y servicios a partir de la configuración."""

from __future__ import annotations

import os

from sensormon.bus import InMemoryBus, MessageBus, MqttBus
from sensormon.collector.service import Collector
from sensormon.config import IsolationForestConfig, Settings
from sensormon.detection.base import Detector
from sensormon.detection.engine import DetectionEngine
from sensormon.detection.ewma import EwmaDetector
from sensormon.detection.threshold import ThresholdDetector
from sensormon.detection.zscore import ZScoreDetector
from sensormon.hub import EventHub
from sensormon.notify.base import Notifier
from sensormon.notify.console import ConsoleNotifier
from sensormon.notify.webhook import WebhookNotifier
from sensormon.simulator.runner import Simulator
from sensormon.storage.sqlite import SqliteStore


def open_store(settings: Settings) -> SqliteStore:
    store = SqliteStore(settings.storage.path)
    store.init()
    return store


def build_bus(settings: Settings, transport: str, role: str) -> MessageBus:
    if transport == "memory":
        return InMemoryBus()
    if transport != "mqtt":
        raise ValueError(f"Transporte desconocido: {transport}")
    return MqttBus(
        host=settings.mqtt.host,
        port=settings.mqtt.port,
        username=settings.mqtt.username,
        password=settings.mqtt.password,
        client_id=f"{settings.mqtt.client_id}-{role}-{os.getpid()}",
        keepalive=settings.mqtt.keepalive,
    )


def load_isolation_forest(config: IsolationForestConfig) -> Detector:
    try:
        from sensormon.detection.isolation_forest import IsolationForestDetector
    except ImportError as exc:
        raise RuntimeError(
            "IsolationForest está activado pero scikit-learn no está instalado. "
            "Instala el extra: pip install 'sensormon[ml]'"
        ) from exc
    return IsolationForestDetector(
        window=config.window,
        contamination=config.contamination,
        min_samples=config.min_samples,
        refit_every=config.refit_every,
        random_state=config.random_state,
        n_estimators=config.n_estimators,
    )


def build_detectors(settings: Settings) -> list[Detector]:
    detection = settings.detection
    detectors: list[Detector] = []
    if detection.thresholds:
        detectors.append(ThresholdDetector(detection.thresholds))
    if detection.zscore.enabled:
        detectors.append(
            ZScoreDetector(
                window=detection.zscore.window,
                threshold=detection.zscore.threshold,
                min_samples=detection.zscore.min_samples,
            )
        )
    if detection.ewma.enabled:
        detectors.append(
            EwmaDetector(
                alpha=detection.ewma.alpha,
                threshold=detection.ewma.threshold,
                min_samples=detection.ewma.min_samples,
            )
        )
    if detection.isolation_forest.enabled:
        detectors.append(load_isolation_forest(detection.isolation_forest))
    return detectors


def build_engine(settings: Settings) -> DetectionEngine:
    return DetectionEngine(build_detectors(settings), settings.detection.cooldown_seconds)


def build_notifiers(settings: Settings) -> list[Notifier]:
    notifiers: list[Notifier] = []
    for item in settings.notifiers:
        if not item.enabled:
            continue
        if item.type == "console":
            notifiers.append(ConsoleNotifier())
        elif item.type == "webhook":
            if not item.url:
                raise ValueError("El notificador webhook está activo pero no tiene url")
            notifiers.append(WebhookNotifier(item.url, timeout=item.timeout_seconds))
    return notifiers


def build_simulator(settings: Settings, bus: MessageBus) -> Simulator:
    simulator = settings.simulator
    return Simulator(
        simulator.devices,
        list(simulator.faults),
        bus,
        interval=simulator.interval_seconds,
        seed=simulator.seed,
        topic_root=settings.mqtt.topic_root,
    )


def build_collector(
    settings: Settings,
    bus: MessageBus,
    store: SqliteStore,
    hub: EventHub | None = None,
) -> Collector:
    return Collector(
        bus,
        store,
        build_engine(settings),
        build_notifiers(settings),
        hub=hub,
        topic_root=settings.mqtt.topic_root,
    )


def resolve_transport(settings: Settings, explicit: str | None) -> str:
    if explicit:
        if explicit not in {"mqtt", "memory"}:
            raise ValueError("El transporte debe ser mqtt o memory")
        return explicit
    return "mqtt" if settings.mqtt.enabled else "memory"
