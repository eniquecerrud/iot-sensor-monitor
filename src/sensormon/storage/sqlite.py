"""Almacén SQLite con un único escritor y lecturas concurrentes (WAL)."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from sensormon.models import Alert, Metric, Quality, Reading
from sensormon.storage.base import DeviceRecord

_SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY,
    location TEXT,
    sensors TEXT NOT NULL DEFAULT '[]',
    last_seen TEXT
);

CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    quality TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    metric TEXT NOT NULL,
    detector TEXT NOT NULL,
    severity TEXT NOT NULL,
    message TEXT NOT NULL,
    value REAL NOT NULL,
    score REAL,
    timestamp TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_readings_lookup
    ON readings (device_id, metric, id);
CREATE INDEX IF NOT EXISTS idx_alerts_device
    ON alerts (device_id, id);
"""


def _iso(value: datetime) -> str:
    return value.isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


class SqliteStore:
    def __init__(self, path: str) -> None:
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()

    def init(self) -> None:
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def insert_reading(self, reading: Reading) -> None:
        timestamp = _iso(reading.timestamp)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO readings (device_id, metric, value, unit, timestamp, quality)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    reading.device_id,
                    reading.metric.value,
                    reading.value,
                    reading.unit,
                    timestamp,
                    reading.quality.value,
                ),
            )
            self._upsert_device(
                reading.device_id,
                location=None,
                sensors=[reading.metric.value],
                seen=timestamp,
            )
            self._conn.commit()

    def insert_alert(self, alert: Alert) -> Alert:
        timestamp = _iso(alert.timestamp)
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO alerts
                    (device_id, metric, detector, severity, message, value, score, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alert.device_id,
                    alert.metric.value,
                    alert.detector,
                    alert.severity,
                    alert.message,
                    alert.value,
                    alert.score,
                    timestamp,
                ),
            )
            self._conn.commit()
            new_id = int(cursor.lastrowid or 0)
        return alert.model_copy(update={"id": new_id})

    def upsert_device(
        self,
        device_id: str,
        location: str | None = None,
        sensors: list[str] | None = None,
        seen: datetime | None = None,
    ) -> None:
        with self._lock:
            self._upsert_device(
                device_id,
                location=location,
                sensors=sensors,
                seen=_iso(seen) if seen else None,
            )
            self._conn.commit()

    def _upsert_device(
        self,
        device_id: str,
        *,
        location: str | None,
        sensors: list[str] | None,
        seen: str | None,
    ) -> None:
        row = self._conn.execute(
            "SELECT location, sensors, last_seen FROM devices WHERE device_id = ?",
            (device_id,),
        ).fetchone()
        merged = list(sensors or [])
        if row is None:
            self._conn.execute(
                """
                INSERT INTO devices (device_id, location, sensors, last_seen)
                VALUES (?, ?, ?, ?)
                """,
                (device_id, location, json.dumps(merged), seen),
            )
            return
        previous = json.loads(row["sensors"] or "[]")
        combined = list(dict.fromkeys([*previous, *merged]))
        self._conn.execute(
            """
            UPDATE devices
            SET location = ?, sensors = ?, last_seen = ?
            WHERE device_id = ?
            """,
            (
                location if location is not None else row["location"],
                json.dumps(combined),
                seen or row["last_seen"],
                device_id,
            ),
        )

    def list_readings(
        self,
        *,
        device_id: str | None = None,
        metric: str | None = None,
        limit: int = 200,
        since: datetime | None = None,
    ) -> list[Reading]:
        clauses = ["1 = 1"]
        params: list[object] = []
        if device_id is not None:
            clauses.append("device_id = ?")
            params.append(device_id)
        if metric is not None:
            clauses.append("metric = ?")
            params.append(metric)
        if since is not None:
            clauses.append("timestamp >= ?")
            params.append(_iso(since))
        params.append(limit)
        query = f"""
            SELECT device_id, metric, value, unit, timestamp, quality
            FROM readings
            WHERE {" AND ".join(clauses)}
            ORDER BY id DESC
            LIMIT ?
        """
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        readings = [
            Reading(
                device_id=row["device_id"],
                metric=Metric(row["metric"]),
                value=row["value"],
                unit=row["unit"],
                timestamp=_parse_dt(row["timestamp"]),
                quality=Quality(row["quality"]),
            )
            for row in rows
        ]
        readings.reverse()
        return readings

    def list_alerts(
        self,
        *,
        device_id: str | None = None,
        severity: str | None = None,
        limit: int = 100,
    ) -> list[Alert]:
        clauses = ["1 = 1"]
        params: list[object] = []
        if device_id is not None:
            clauses.append("device_id = ?")
            params.append(device_id)
        if severity is not None:
            clauses.append("severity = ?")
            params.append(severity)
        params.append(limit)
        query = f"""
            SELECT id, device_id, metric, detector, severity, message, value, score, timestamp
            FROM alerts
            WHERE {" AND ".join(clauses)}
            ORDER BY id DESC
            LIMIT ?
        """
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [
            Alert(
                id=row["id"],
                device_id=row["device_id"],
                metric=Metric(row["metric"]),
                detector=row["detector"],
                severity=row["severity"],
                message=row["message"],
                value=row["value"],
                score=row["score"],
                timestamp=_parse_dt(row["timestamp"]),
            )
            for row in rows
        ]

    def list_devices(self) -> list[DeviceRecord]:
        with self._lock:
            devices = self._conn.execute(
                "SELECT device_id, location, sensors, last_seen FROM devices ORDER BY device_id"
            ).fetchall()
            counts = {
                row["device_id"]: int(row["n"])
                for row in self._conn.execute(
                    "SELECT device_id, COUNT(*) AS n FROM readings GROUP BY device_id"
                )
            }
            latest_rows = self._conn.execute(
                """
                SELECT r.device_id, r.metric, r.value, r.unit, r.timestamp, r.quality
                FROM readings r
                JOIN (
                    SELECT device_id, metric, MAX(id) AS id
                    FROM readings
                    GROUP BY device_id, metric
                ) m ON r.id = m.id
                """
            ).fetchall()
        latest: dict[str, dict[str, Reading]] = {}
        for row in latest_rows:
            reading = Reading(
                device_id=row["device_id"],
                metric=Metric(row["metric"]),
                value=row["value"],
                unit=row["unit"],
                timestamp=_parse_dt(row["timestamp"]),
                quality=Quality(row["quality"]),
            )
            latest.setdefault(row["device_id"], {})[row["metric"]] = reading
        return [
            DeviceRecord(
                device_id=row["device_id"],
                location=row["location"],
                last_seen=_parse_dt(row["last_seen"]),
                sensors=json.loads(row["sensors"] or "[]"),
                reading_count=counts.get(row["device_id"], 0),
                latest=latest.get(row["device_id"], {}),
            )
            for row in devices
        ]
