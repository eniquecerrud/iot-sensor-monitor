"""Fan-out de eventos hacia los WebSocket del panel."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)


class EventHub:
    """Puente entre hilos del colector y el bucle asyncio de FastAPI."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subs: list[asyncio.Queue[dict[str, Any]]] = []
        self._lock = threading.Lock()

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        with self._lock:
            self._subs.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        with self._lock:
            if queue in self._subs:
                self._subs.remove(queue)

    def publish(self, event: dict[str, Any]) -> None:
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        with self._lock:
            subs = list(self._subs)
        for queue in subs:
            try:
                loop.call_soon_threadsafe(self._enqueue, queue, event)
            except RuntimeError:
                logger.debug("El bucle del panel ya no acepta eventos", exc_info=True)

    @staticmethod
    def _enqueue(queue: asyncio.Queue[dict[str, Any]], event: dict[str, Any]) -> None:
        if queue.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                queue.get_nowait()
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            return
