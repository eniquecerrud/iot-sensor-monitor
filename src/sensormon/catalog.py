"""Catálogo visible de magnitudes.

El panel consume `GET /api/catalog`. Para añadir un sensor nuevo, extiende
`Metric` y registra aquí etiqueta, unidad por defecto y color.
"""

from __future__ import annotations

from dataclasses import dataclass

from sensormon.models import Metric


@dataclass(frozen=True, slots=True)
class MetricSpec:
    id: str
    label: str
    unit: str
    color: str
    description: str


CATALOG: dict[Metric, MetricSpec] = {
    Metric.temperature: MetricSpec(
        "temperature",
        "Temperatura",
        "°C",
        "#e07a3d",
        "Temperatura ambiente o de proceso",
    ),
    Metric.humidity: MetricSpec(
        "humidity",
        "Humedad",
        "%",
        "#3d9ec9",
        "Humedad relativa",
    ),
    Metric.pressure: MetricSpec(
        "pressure",
        "Presión",
        "hPa",
        "#8b7fd6",
        "Presión barométrica",
    ),
    Metric.co2: MetricSpec(
        "co2",
        "CO₂",
        "ppm",
        "#3fbf7f",
        "Concentración de dióxido de carbono",
    ),
    Metric.vibration: MetricSpec(
        "vibration",
        "Vibración",
        "mm/s",
        "#d6a441",
        "Velocidad de vibración",
    ),
}


def metric_label(metric: Metric | str) -> str:
    return CATALOG[Metric(metric)].label


def catalog_payload() -> list[dict[str, str]]:
    return [
        {
            "id": spec.id,
            "label": spec.label,
            "unit": spec.unit,
            "color": spec.color,
            "description": spec.description,
        }
        for spec in CATALOG.values()
    ]
