"""Politeness controls: a concurrency cap plus a jittered per-request delay.

Async-friendly so the httpx fetcher can run a small pool of concurrent requests
without hammering the origin. Production would shard this per-domain across a
distributed queue; here it is process-local.
"""
from __future__ import annotations

import asyncio
import random


class RateLimiter:
    def __init__(
        self,
        max_concurrency: int = 4,
        per_request_delay: float = 0.75,
        jitter: float = 0.5,
    ) -> None:
        self._sem = asyncio.Semaphore(max(1, max_concurrency))
        self._delay = max(0.0, per_request_delay)
        self._jitter = max(0.0, jitter)
        self._lock = asyncio.Lock()
        self._last_release = 0.0

    async def __aenter__(self) -> "RateLimiter":
        await self._sem.acquire()
        # Serialize the spacing so the effective request rate is bounded even
        # when many coroutines wake at once.
        async with self._lock:
            loop = asyncio.get_event_loop()
            now = loop.time()
            wait = self._last_release + self._delay - now
            if wait > 0:
                await asyncio.sleep(wait)
            extra = random.uniform(0, self._jitter) if self._jitter else 0.0
            if extra:
                await asyncio.sleep(extra)
            self._last_release = loop.time()
        return self

    async def __aexit__(self, *exc: object) -> None:
        self._sem.release()
