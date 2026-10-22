from __future__ import annotations

import sys

import pytest

from sensormon.config import IsolationForestConfig, ThresholdRule
from sensormon.detection.engine import DetectionEngine
from sensormon.detection.ewma import EwmaDetector
from sensormon.detection.threshold import ThresholdDetector
from sensormon.detection.zscore import ZScoreDetector
from sensormon.factory import load_isolation_forest
from tests.conftest import at, make_reading

RULES = {
    "temperature": ThresholdRule(min=10, max=30, critical_min=0, critical_max=50),
}


def test_thresholds_cover_warning_and_critical() -> None:
    detector = ThresholdDetector(RULES)
    assert detector.evaluate(make_reading(value=22)) is None
    assert detector.evaluate(make_reading(metric="co2", value=9999, unit="ppm")) is None
    high = detector.evaluate(make_reading(value=36, timestamp=at(1)))
    assert high is not None
    assert high.severity == "warning"
    assert "máximo" in high.message
    critical = detector.evaluate(make_reading(value=61, timestamp=at(2)))
    assert critical is not None
    assert critical.severity == "critical"
    low = detector.evaluate(make_reading(value=5, timestamp=at(3)))
    assert low is not None and low.severity == "warning"
    frozen = detector.evaluate(make_reading(value=-2, timestamp=at(4)))
    assert frozen is not None and frozen.severity == "critical"


def test_zscore_flags_outlier_after_warmup() -> None:
    detector = ZScoreDetector(window=20, threshold=3, min_samples=8)
    for index in range(10):
        assert detector.evaluate(make_reading(value=10, timestamp=at(index))) is None
    alert = detector.evaluate(make_reading(value=80, timestamp=at(11)))
    assert alert is not None
    assert alert.detector == "zscore"
    assert alert.severity == "critical"
    assert alert.score is not None and alert.score > 3


def test_ewma_flags_level_shift() -> None:
    detector = EwmaDetector(alpha=0.2, threshold=3, min_samples=8)
    for index in range(12):
        assert detector.evaluate(make_reading(value=10, timestamp=at(index))) is None
    alert = detector.evaluate(make_reading(value=100, timestamp=at(13)))
    assert alert is not None
    assert alert.detector == "ewma"
    assert "exponencial" in alert.message


def test_engine_cooldown_suppresses_repeats() -> None:
    detector = ZScoreDetector(window=20, threshold=3, min_samples=5)
    quiet = DetectionEngine([detector], cooldown_seconds=60)
    for index in range(6):
        quiet.evaluate(make_reading(value=10, timestamp=at(index)))
    first = quiet.evaluate(make_reading(value=100, timestamp=at(7)))
    second = quiet.evaluate(make_reading(value=120, timestamp=at(8)))
    assert len(first) == 1
    assert second == []

    fresh = ZScoreDetector(window=20, threshold=3, min_samples=5)
    noisy = DetectionEngine([fresh], cooldown_seconds=0)
    for index in range(6):
        noisy.evaluate(make_reading(value=10, timestamp=at(index)))
    assert noisy.evaluate(make_reading(value=100, timestamp=at(7)))
    assert noisy.evaluate(make_reading(value=1000, timestamp=at(8)))


def test_invalid_detector_parameters() -> None:
    with pytest.raises(ValueError):
        ZScoreDetector(window=4, threshold=3, min_samples=8)
    with pytest.raises(ValueError):
        EwmaDetector(alpha=0, threshold=3, min_samples=4)
    with pytest.raises(ValueError):
        DetectionEngine([], cooldown_seconds=-1)


def test_isolation_forest_flags_extreme_point() -> None:
    pytest.importorskip("sklearn")
    from sensormon.detection.isolation_forest import IsolationForestDetector

    detector = IsolationForestDetector(
        window=40,
        contamination=0.05,
        min_samples=30,
        refit_every=1000,
        random_state=0,
        n_estimators=40,
    )
    for index in range(36):
        detector.evaluate(make_reading(value=((index % 4) - 1.5) * 0.2, timestamp=at(index)))
    alert = detector.evaluate(make_reading(value=40, timestamp=at(40)))
    assert alert is not None
    assert alert.detector == "isolation_forest"
    assert alert.score is not None


def test_isolation_forest_requires_sklearn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "sensormon.detection.isolation_forest", None)
    with pytest.raises(RuntimeError, match="scikit-learn"):
        load_isolation_forest(IsolationForestConfig(enabled=True))
