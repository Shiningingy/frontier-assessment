"""Minimal robots.txt awareness. Fetched once per host and cached. Honours
Disallow rules for our user-agent (falling back to '*'). Fail-open: if robots
cannot be fetched, we allow but log it.
"""
from __future__ import annotations

import urllib.robotparser
from urllib.parse import urljoin, urlparse

import httpx


class RobotsPolicy:
    def __init__(self, user_agent: str, respect: bool = True) -> None:
        self.user_agent = user_agent
        self.respect = respect
        self._parsers: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def _parser_for(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        parsed = urlparse(url)
        host = f"{parsed.scheme}://{parsed.netloc}"
        if host in self._parsers:
            return self._parsers[host]
        robots_url = urljoin(host, "/robots.txt")
        rp: urllib.robotparser.RobotFileParser | None = urllib.robotparser.RobotFileParser()
        try:
            resp = httpx.get(robots_url, timeout=15, headers={"User-Agent": self.user_agent})
            if resp.status_code == 200:
                rp.parse(resp.text.splitlines())
            else:
                rp = None  # no robots -> allow all
        except Exception:
            rp = None  # fail-open
        self._parsers[host] = rp
        return rp

    def allowed(self, url: str) -> bool:
        if not self.respect:
            return True
        rp = self._parser_for(url)
        if rp is None:
            return True
        return rp.can_fetch(self.user_agent, url)

    def crawl_delay(self, url: str) -> float | None:
        if not self.respect:
            return None
        rp = self._parser_for(url)
        if rp is None:
            return None
        try:
            return rp.crawl_delay(self.user_agent)
        except Exception:
            return None
