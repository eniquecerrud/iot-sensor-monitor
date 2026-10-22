from __future__ import annotations

import threading

from sensormon.models import Alert
from sensormon.storage.sqlite import SqliteStore
from tests.conftest import at, make_reading


def test_roundtrip_filters_and_latest(tmp_path) -> None:
    store = SqliteStore(str(tmp_path / "s.db"))
    store.init()
    store.upsert_device("lab-01", location="Laboratorio", sensors=["temperature"], seen=at(0))
    store.insert_reading(make_reading(value=21, timestamp=at(1)))
    store.insert_reading(make_reading(metric="humidity", value=40, unit="%", timestamp=at(2)))
    store.insert_reading(
        make_reading(
            device_id="pump-03",
            metric="vibration",
            value=1.2,
            unit="mm/s",
            timestamp=at(3),
        )
    )
    saved = store.insert_alert(
        Alert(
            device_id="lab-01",
            metric="temperature",
            detector="threshold",
            severity="warning",
            message="supera el máximo",
            value=48,
            score=3,
            timestamp=at(4),
        )
    )
    store.insert_alert(
        Alert(
            device_id="pump-03",
            metric="vibration",
            detector="zscore",
            severity="critical",
            message="vibración anómala",
            value=9,
            timestamp=at(5),
        )
    )

    assert saved.id == 1
    temps = store.list_readings(device_id="lab-01", metric="temperature")
    assert [item.value for item in temps] == [21]
    assert store.list_readings(since=at(3))[0].device_id == "pump-03"
    warnings = store.list_alerts(severity="warning")
    assert len(warnings) == 1
    assert warnings[0].message == "supera el máximo"
    devices = {item.device_id: item for item in store.list_devices()}
    assert devices["lab-01"].location == "Laboratorio"
    assert devices["lab-01"].latest["humidity"].value == 40
    assert set(devices["lab-01"].sensors) == {"temperature", "humidity"}
    assert devices["lab-01"].reading_count == 2
    assert devices["pump-03"].latest["vibration"].unit == "mm/s"
    store.close()


def test_concurrent_inserts(tmp_path) -> None:
    store = SqliteStore(str(tmp_path / "c.db"))
    store.init()

    def write(offset: int) -> None:
        for index in range(20):
            stamp = at(offset * 100 + index)
            store.insert_reading(make_reading(value=offset + index, timestamp=stamp))

    threads = [threading.Thread(target=write, args=(seed,)) for seed in (1, 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(store.list_readings(limit=100)) == 40
    store.close()


def test_memory_database() -> None:
    store = SqliteStore(":memory:")
    store.init()
    store.insert_reading(make_reading())
    assert len(store.list_devices()) == 1
    store.close()
