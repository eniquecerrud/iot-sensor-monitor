"""Escribe cada alerta en el log del proceso."""

from __future__ import annotations

import logging

from sensormon.models import Alert

logger = logging.getLogger("sensormon.alerts")


class ConsoleNotifier:
    def notify(self, alert: Alert) -> None:
        logger.warning(
            "[%s] %s %s %s valor=%.3f %s",
            alert.severity,
            alert.device_id,
            alert.metric.value,
            alert.detector,
            alert.value,
            alert.message,
        )
