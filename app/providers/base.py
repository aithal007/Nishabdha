"""Shared provider types and a small circuit breaker."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, TypeVar

log = logging.getLogger("unclone.providers")
T = TypeVar("T")


class ProviderError(RuntimeError):
    pass


@dataclass
class SpeakerResult:
    prob: float  # normalized match score in [0,1]; legacy name, not a calibrated probability
    raw: float  # provider's raw score (cosine / API score)
    source: str
    latency_ms: int = 0
    embedding: Any = None  # local only (np.ndarray) - used for swap detection


@dataclass
class SpoofResult:
    synthetic_prob: float  # normalized synthetic score; calibration depends on the provider
    source: str
    latency_ms: int = 0
    detail: dict = field(default_factory=dict)


@dataclass
class EnrollResult:
    source: str
    detectifai_ref: str | None = None
    local_embedding: bytes | None = None
    detail: dict = field(default_factory=dict)


class CircuitBreaker:
    """Skip a failing provider for `cooldown` seconds after `threshold` consecutive failures,
    so one dead API never adds timeout latency to every chunk during the demo."""

    def __init__(self, name: str, threshold: int = 3, cooldown: float = 30.0):
        self.name, self.threshold, self.cooldown = name, threshold, cooldown
        self.failures = 0
        self.open_until = 0.0
        self.last_error = ""

    @property
    def is_open(self) -> bool:
        return time.monotonic() < self.open_until

    def ok(self) -> None:
        self.failures = 0
        self.open_until = 0.0

    def fail(self, err: Exception) -> None:
        self.failures += 1
        self.last_error = f"{type(err).__name__}: {err}"[:300]
        if self.failures >= self.threshold:
            self.open_until = time.monotonic() + self.cooldown
            log.warning("circuit OPEN for %s (%s)", self.name, self.last_error)

    def status(self) -> dict:
        return {"name": self.name, "open": self.is_open, "failures": self.failures, "last_error": self.last_error}


async def with_timeout(coro: Awaitable[T], seconds: float) -> T:
    return await asyncio.wait_for(coro, timeout=seconds)


async def run_sync(fn: Callable[..., T], *args) -> T:
    """Run blocking model inference off the event loop."""
    return await asyncio.to_thread(fn, *args)


def clamp01(x: float) -> float:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return 0.0
    if x != x:  # NaN
        return 0.0
    return 0.0 if x < 0 else 1.0 if x > 1 else x
