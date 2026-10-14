"""In-process pub/sub for WebSocket fan-out: fraud dashboard, per-customer app, per-call listeners."""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

log = logging.getLogger("unclone.events")


class Hub:
    def __init__(self):
        self._subs: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def subscribe(self, topic: str, ws: WebSocket) -> None:
        async with self._lock:
            self._subs[topic].add(ws)

    async def unsubscribe(self, topic: str, ws: WebSocket) -> None:
        async with self._lock:
            self._subs[topic].discard(ws)
            if not self._subs[topic]:
                self._subs.pop(topic, None)

    def count(self, topic: str) -> int:
        return len(self._subs.get(topic, ()))

    async def publish(self, topic: str, event: str, data: Any) -> int:
        msg = json.dumps({"event": event, "topic": topic, "data": data}, default=str, ensure_ascii=False)
        async with self._lock:
            targets = list(self._subs.get(topic, ()))
        dead = []

        async def _send(ws: WebSocket):
            try:
                await asyncio.wait_for(ws.send_text(msg), timeout=2.0)
            except Exception:
                dead.append(ws)

        await asyncio.gather(*(_send(w) for w in targets))
        for ws in dead:
            await self.unsubscribe(topic, ws)
        return len(targets) - len(dead)


hub = Hub()

DASHBOARD = "dashboard"


def customer_topic(customer_id: str) -> str:
    return f"customer:{customer_id}"


def call_topic(call_id: str) -> str:
    return f"call:{call_id}"
