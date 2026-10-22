"""Contrato de un notificador."""

from __future__ import annotations

from typing import Protocol

from sensormon.models import Alert


class Notifier(Protocol):
    def notify(self, alert: Alert) -> None:
        """Entrega una alerta. No debe interrumpir el colector si el destino falla."""
