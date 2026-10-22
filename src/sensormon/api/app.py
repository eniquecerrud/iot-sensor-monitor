"""FastAPI: histórico, catálogo y canal en vivo."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from sensormon import __version__
from sensormon.catalog import catalog_payload
from sensormon.hub import EventHub
from sensormon.models import Metric
from sensormon.storage.base import DeviceRecord, ReadingStore

STATIC_DIR = Path(__file__).resolve().parent.parent / "dashboard" / "static"


class ReadingOut(BaseModel):
    device_id: str
    metric: str
    value: float
    unit: str
    timestamp: datetime
    quality: str


class DeviceOut(BaseModel):
    device_id: str
    location: str | None = None
    last_seen: datetime | None = None
    sensors: list[str]
    reading_count: int
    latest: dict[str, ReadingOut] = Field(default_factory=dict)


class AlertOut(BaseModel):
    id: int | None
    device_id: str
    metric: str
    detector: str
    severity: str
    message: str
    value: float
    score: float | None
    timestamp: datetime


def _device_out(record: DeviceRecord) -> DeviceOut:
    latest = {
        metric: ReadingOut(
            device_id=reading.device_id,
            metric=reading.metric.value,
            value=reading.value,
            unit=reading.unit,
            timestamp=reading.timestamp,
            quality=reading.quality.value,
        )
        for metric, reading in record.latest.items()
    }
    return DeviceOut(
        device_id=record.device_id,
        location=record.location,
        last_seen=record.last_seen,
        sensors=list(record.sensors),
        reading_count=record.reading_count,
        latest=latest,
    )


def create_app(store: ReadingStore, hub: EventHub | None = None) -> FastAPI:
    event_hub = hub or EventHub()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        event_hub.bind_loop(asyncio.get_running_loop())
        app.state.hub = event_hub
        app.state.store = store
        yield

    app = FastAPI(
        title="Sensormon",
        version=__version__,
        summary="Lecturas, alertas y flujo en vivo de sensores IoT",
        lifespan=lifespan,
    )
    app.state.hub = event_hub
    app.state.store = store

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index() -> FileResponse:
        page = STATIC_DIR / "index.html"
        if not page.is_file():
            raise HTTPException(status_code=404, detail="El panel no está instalado")
        return FileResponse(page)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "sensormon", "version": __version__}

    @app.get("/api/catalog")
    def catalog() -> list[dict[str, str]]:
        return catalog_payload()

    def device_rows() -> list[DeviceOut]:
        return [_device_out(item) for item in store.list_devices()]

    def reading_rows(
        device_id: str | None = None,
        metric: str | None = None,
        limit: int = 120,
        since: datetime | None = None,
    ) -> list[ReadingOut]:
        if metric is not None:
            try:
                Metric(metric)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="Magnitud desconocida") from exc
        rows = store.list_readings(device_id=device_id, metric=metric, limit=limit, since=since)
        return [
            ReadingOut(
                device_id=row.device_id,
                metric=row.metric.value,
                value=row.value,
                unit=row.unit,
                timestamp=row.timestamp,
                quality=row.quality.value,
            )
            for row in rows
        ]

    def alert_rows(
        device_id: str | None = None,
        severity: str | None = None,
        limit: int = 50,
    ) -> list[AlertOut]:
        if severity is not None and severity not in {"info", "warning", "critical"}:
            raise HTTPException(status_code=422, detail="Severidad desconocida")
        rows = store.list_alerts(device_id=device_id, severity=severity, limit=limit)
        return [
            AlertOut(
                id=row.id,
                device_id=row.device_id,
                metric=row.metric.value,
                detector=row.detector,
                severity=row.severity,
                message=row.message,
                value=row.value,
                score=row.score,
                timestamp=row.timestamp,
            )
            for row in rows
        ]

    @app.get("/api/devices", response_model=list[DeviceOut])
    def devices() -> list[DeviceOut]:
        return device_rows()

    @app.get("/api/readings", response_model=list[ReadingOut])
    def readings(
        device_id: str | None = None,
        metric: str | None = None,
        limit: int = Query(default=120, ge=1, le=1000),
        since: datetime | None = None,
    ) -> list[ReadingOut]:
        return reading_rows(device_id=device_id, metric=metric, limit=limit, since=since)

    @app.get("/api/alerts", response_model=list[AlertOut])
    def alerts(
        device_id: str | None = None,
        severity: str | None = None,
        limit: int = Query(default=50, ge=1, le=500),
    ) -> list[AlertOut]:
        return alert_rows(device_id=device_id, severity=severity, limit=limit)

    @app.websocket("/ws/live")
    async def live(websocket: WebSocket) -> None:
        await websocket.accept()
        queue = event_hub.subscribe()

        async def forward() -> None:
            try:
                while True:
                    event = await queue.get()
                    await websocket.send_json(event)
            except (WebSocketDisconnect, RuntimeError):
                return

        forward_task = asyncio.create_task(forward())
        try:
            await websocket.send_json(
                {
                    "type": "snapshot",
                    "devices": [item.model_dump(mode="json") for item in device_rows()],
                    "alerts": [item.model_dump(mode="json") for item in alert_rows()],
                }
            )
            while True:
                incoming = await websocket.receive()
                if incoming["type"] == "websocket.disconnect":
                    break
        except WebSocketDisconnect:
            pass
        finally:
            forward_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await forward_task
            event_hub.unsubscribe(queue)

    return app
