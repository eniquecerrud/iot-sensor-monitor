from __future__ import annotations

import httpx
import pytest

from sensormon.models import Alert
from sensormon.notify.console import ConsoleNotifier
from sensormon.notify.webhook import WebhookNotifier
from tests.conftest import at


def _alert() -> Alert:
    return Alert(
        id=7,
        device_id="lab-01",
        metric="co2",
        detector="threshold",
        severity="critical",
        message="CO₂ fuera de rango",
        value=2200,
        score=1000,
        timestamp=at(9),
    )


def test_console_notifier_logs(caplog: pytest.LogCaptureFixture) -> None:
    ConsoleNotifier().notify(_alert())
    assert "lab-01" in caplog.text
    assert "critical" in caplog.text


def test_webhook_posts_json() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.append(json.loads(request.content.decode()))
        return httpx.Response(204)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    notifier = WebhookNotifier("http://hooks.test/alerts", client=client)
    notifier.notify(_alert())
    assert seen[0]["device_id"] == "lab-01"
    assert seen[0]["metric"] == "co2"
    assert seen[0]["id"] == 7


def test_webhook_swallows_http_errors() -> None:
    def down(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    def boom(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin red")

    down_client = httpx.Client(transport=httpx.MockTransport(down))
    boom_client = httpx.Client(transport=httpx.MockTransport(boom))
    WebhookNotifier("http://hooks.test/a", client=down_client).notify(_alert())
    WebhookNotifier("http://hooks.test/b", client=boom_client).notify(_alert())


def test_webhook_requires_url() -> None:
    with pytest.raises(ValueError):
        WebhookNotifier("")
