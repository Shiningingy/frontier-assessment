"""Anti-bot blocks are detected and escalated to a human handoff — never evaded.
Driven by a FakeFetcher returning a 403, so it's deterministic and offline.
"""
import asyncio
import logging

from safco_scraper.config import Seed, Settings
from safco_scraper.fetcher.base import FetchResult
from safco_scraper.orchestrator import Orchestrator
from safco_scraper.tools.store import Store

URL = "https://protected.test/catalog/x"


class BlockingFetcher:
    """Simulates a Cloudflare-style 403 challenge."""

    async def fetch(self, url):
        return FetchResult(url=url, status=403, html="<html>Just a moment...</html>", elapsed_ms=1)

    async def aclose(self):
        pass


def _settings(tmp_path):
    return Settings(
        site="https://protected.test", seeds=[],
        raw={"crawl": {"follow_product_pages": False}, "storage": {"db_path": str(tmp_path / "c.db")},
             "output": {"dir": str(tmp_path), "formats": []}, "llm": {}},
        config_path="x",
    )


def test_block_is_detected_and_handed_off(tmp_path):
    settings = _settings(tmp_path)
    orch = Orchestrator(settings, BlockingFetcher(), logging.getLogger("t"),
                        profiles_root=str(tmp_path / "profiles"))
    metrics = asyncio.run(orch.run(seeds=[Seed(name="X", url=URL)]))

    assert metrics.blocked == 1
    assert metrics.products_stored == 0
    assert metrics.manual_help_requests == 1

    store = Store(settings.db_path)
    # The block was dead-lettered with a "refusing to evade" reason ...
    dls = store.dead_letters()
    assert dls and "403" in dls[0]["error"] and "evade" in dls[0]["error"].lower()
    # ... and a human-handoff request was queued with an actionable suggestion.
    help_q = store.help_queue()
    assert len(help_q) == 1
    assert "bot-protected" in help_q[0]["suggested_action"].lower()
