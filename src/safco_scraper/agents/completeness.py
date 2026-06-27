"""Completeness-critic agent.

The crucial check the workflow was missing: "did we actually get everything?"
After a category is extracted, the critic determines the *true* product total and
compares it to what we captured. If they differ, the result is incomplete and the
critic recommends an escalation (replay the discovered API → browser/MCP tier →
human help) rather than silently shipping a partial catalog.

It learns the true total the same way a browser does — by observing the page's own
data API via `browser_probe` (no hardcoded site knowledge) — with an HTML-signal
fallback (pagination "N pages" / "N products") when the browser tier isn't available.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class CompletenessVerdict:
    url: str
    extracted: int
    expected: Optional[int]      # true total, if determinable
    complete: bool
    method: str                  # how `expected` was determined
    recommended_action: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "url": self.url, "extracted": self.extracted, "expected": self.expected,
            "complete": self.complete, "method": self.method,
            "recommended_action": self.recommended_action,
        }


_TOTAL_RE = re.compile(r"\b(\d{2,6})\s*(?:products|items|results)\b", re.I)
_PAGES_RE = re.compile(r"\bpage\s*\d+\s*of\s*(\d+)\b", re.I)


class CompletenessCritic:
    def __init__(self, settings, logger: logging.Logger, use_browser: bool = True) -> None:
        self.settings = settings
        self.logger = logger
        self.use_browser = use_browser

    def check(self, url: str, extracted: int, html: Optional[str] = None) -> CompletenessVerdict:
        expected, method = self._expected_total(url, html)
        if expected is None:
            return CompletenessVerdict(url, extracted, None, complete=False, method="unknown",
                                       recommended_action="Could not determine the true total; "
                                       "probe the page's data API (browser tier) or request human review.")
        complete = extracted >= expected
        action = None
        if not complete:
            action = (f"Incomplete: captured {extracted} of {expected}. Escalate — replay the "
                      f"discovered product API to page through all results (the page loads them "
                      f"from its own API), or use the browser/MCP tier, or request human review.")
        return CompletenessVerdict(url, extracted, expected, complete, method, action)

    # ------------------------------------------------------------------ #
    def _expected_total(self, url: str, html: Optional[str]) -> tuple[Optional[int], str]:
        # 1) Authoritative: the page's own data API total (observed via the browser).
        if self.use_browser:
            try:
                from ..tools.browser_probe import probe_category

                probe = probe_category(url, logger=self.logger)
                api = probe.best_product_api()
                if api and api.total:
                    return api.total, f"data-api:{api.endpoint.split('?')[0]}"
            except Exception as exc:
                self.logger.info(f"completeness: browser probe unavailable ({exc})")
        # 2) Fallback: pagination / total text in the (rendered or static) HTML.
        if html:
            m = _TOTAL_RE.search(html)
            if m:
                return int(m.group(1)), "html:total-text"
            p = _PAGES_RE.search(html)
            if p:
                return None, "html:pages-only"  # know it paginates, not the exact total
        return None, "unknown"
