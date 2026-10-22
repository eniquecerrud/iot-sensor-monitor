"""POST JSON de la alerta a un webhook HTTP."""

from __future__ import annotations

import logging

import httpx

from sensormon.models import Alert

logger = logging.getLogger(__name__)


class WebhookNotifier:
    def __init__(
        self,
        url: str,
        *,
        timeout: float = 3.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not url:
            raise ValueError("el webhook necesita una URL")
        self.url = url
        self.timeout = timeout
        self._client = client
        self._owned: httpx.Client | None = None

    def notify(self, alert: Alert) -> None:
        try:
            response = self._http().post(self.url, json=alert.model_dump(mode="json"))
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Webhook %s falló: %s", self.url, exc)

    def close(self) -> None:
        if self._owned is not None:
            self._owned.close()
            self._owned = None

    def _http(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        if self._owned is None:
            self._owned = httpx.Client(timeout=self.timeout)
        return self._owned
