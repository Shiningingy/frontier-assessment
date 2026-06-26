"""Build a fetcher from config (httpx default, playwright escalation)."""
from __future__ import annotations

import logging

from ..config import Settings
from ..utils.ratelimit import RateLimiter
from ..utils.robots import RobotsPolicy
from .httpx_fetcher import HttpxFetcher


def build_fetcher(settings: Settings, logger: logging.Logger):
    fcfg = settings.section("fetcher")
    rcfg = settings.section("rate_limit")
    retry = settings.section("retry")
    ua = fcfg.get("user_agent", "SafcoScraperPOC/0.1")

    limiter = RateLimiter(
        max_concurrency=int(rcfg.get("max_concurrency", 4)),
        per_request_delay=float(rcfg.get("per_request_delay_seconds", 0.75)),
        jitter=float(rcfg.get("jitter_seconds", 0.5)),
    )
    robots = RobotsPolicy(user_agent=ua, respect=bool(fcfg.get("respect_robots", True)))

    backend = fcfg.get("backend", "httpx")
    if backend == "playwright":
        from .playwright_fetcher import PlaywrightFetcher

        return PlaywrightFetcher(
            user_agent=ua,
            timeout=float(fcfg.get("timeout_seconds", 30)),
            rate_limiter=limiter,
            robots=robots,
            logger=logger,
        )
    return HttpxFetcher(
        user_agent=ua,
        timeout=float(fcfg.get("timeout_seconds", 30)),
        rate_limiter=limiter,
        robots=robots,
        max_attempts=int(retry.get("max_attempts", 4)),
        backoff_base=float(retry.get("backoff_base_seconds", 1.0)),
        backoff_max=float(retry.get("backoff_max_seconds", 20.0)),
        logger=logger,
    )
