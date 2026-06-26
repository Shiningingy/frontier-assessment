"""Escalation fetcher for JS-rendered / anti-bot pages.

Not needed for Safco (static HTML), but wired and selectable via
`fetcher.backend: playwright` so the system can handle sites that only expose
data after client-side rendering. Playwright is an optional dependency
(`pip install -e .[browser]` then `playwright install chromium`); we import it
lazily so the deterministic httpx path has zero browser dependency.
"""
from __future__ import annotations

import logging
import time

from ..utils.logging import log_event
from ..utils.ratelimit import RateLimiter
from ..utils.robots import RobotsPolicy
from .base import FetchResult


class PlaywrightFetcher:
    def __init__(
        self,
        user_agent: str,
        timeout: float = 30.0,
        rate_limiter: RateLimiter | None = None,
        robots: RobotsPolicy | None = None,
        wait_until: str = "networkidle",
        logger: logging.Logger | None = None,
    ) -> None:
        self.user_agent = user_agent
        self.timeout = timeout
        self.rate_limiter = rate_limiter or RateLimiter()
        self.robots = robots
        self.wait_until = wait_until
        self.logger = logger or logging.getLogger("safco")
        self._pw = None
        self._browser = None

    async def _ensure_browser(self):
        if self._browser is not None:
            return
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover - optional dep
            raise RuntimeError(
                "Playwright backend selected but not installed. "
                "Run: pip install -e .[browser] && playwright install chromium"
            ) from exc
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=True)

    async def fetch(self, url: str) -> FetchResult:
        if self.robots and not self.robots.allowed(url):
            from .httpx_fetcher import RobotsDisallowed

            raise RobotsDisallowed(url)
        await self._ensure_browser()
        async with self.rate_limiter:
            start = time.perf_counter()
            page = await self._browser.new_page(user_agent=self.user_agent)
            try:
                resp = await page.goto(url, wait_until=self.wait_until, timeout=self.timeout * 1000)
                html = await page.content()
                status = resp.status if resp else 0
                final_url = page.url
            finally:
                await page.close()
        elapsed = int((time.perf_counter() - start) * 1000)
        log_event(self.logger, "fetch.ok", url=url, status=status, elapsed_ms=elapsed, backend="playwright")
        return FetchResult(url=final_url, status=status, html=html, elapsed_ms=elapsed)

    async def aclose(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()
