"""Default fetcher: async httpx with rate limiting, retries and robots checks.

This is the cheap, fast path. Safco serves full product data in static HTML, so
no browser is needed. The PlaywrightFetcher is the documented escalation tier for
JS-rendered / anti-bot sites.
"""
from __future__ import annotations

import logging
import time

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from ..utils.logging import log_event
from ..utils.ratelimit import RateLimiter
from ..utils.robots import RobotsPolicy
from .base import FetchResult


class RobotsDisallowed(Exception):
    pass


class HttpxFetcher:
    def __init__(
        self,
        user_agent: str,
        timeout: float = 30.0,
        rate_limiter: RateLimiter | None = None,
        robots: RobotsPolicy | None = None,
        max_attempts: int = 4,
        backoff_base: float = 1.0,
        backoff_max: float = 20.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self.user_agent = user_agent
        self.rate_limiter = rate_limiter or RateLimiter()
        self.robots = robots
        self.logger = logger or logging.getLogger("safco")
        self._max_attempts = max_attempts
        self._backoff_base = backoff_base
        self._backoff_max = backoff_max
        self._client = httpx.AsyncClient(
            headers={"User-Agent": user_agent, "Accept-Language": "en-US,en;q=0.9"},
            timeout=timeout,
            follow_redirects=True,
        )

    async def fetch(self, url: str) -> FetchResult:
        if self.robots and not self.robots.allowed(url):
            raise RobotsDisallowed(url)

        # tenacity retry wrapper, configured from instance settings.
        @retry(
            reraise=True,
            stop=stop_after_attempt(self._max_attempts),
            wait=wait_random_exponential(multiplier=self._backoff_base, max=self._backoff_max),
            retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        )
        async def _do() -> FetchResult:
            async with self.rate_limiter:
                start = time.perf_counter()
                resp = await self._client.get(url)
            elapsed = int((time.perf_counter() - start) * 1000)
            # 429 / 5xx are retryable; raise to trigger backoff.
            if resp.status_code == 429 or resp.status_code >= 500:
                log_event(
                    self.logger, "fetch.retryable_status", level=logging.WARNING,
                    url=url, status=resp.status_code,
                )
                resp.raise_for_status()
            return FetchResult(url=str(resp.url), status=resp.status_code, html=resp.text, elapsed_ms=elapsed)

        result = await _do()
        log_event(self.logger, "fetch.ok", url=url, status=result.status, elapsed_ms=result.elapsed_ms)
        return result

    async def aclose(self) -> None:
        await self._client.aclose()
