"""The LLM extractor's grounding guard must drop hallucinated values — values not
literally present on the page — even if the model returns them.
"""
import logging

from safco_scraper.agents.extractor import LLMExtractorAgent
from safco_scraper.config import Settings
from safco_scraper.llm.base import LLMResponse


class FakeLLM:
    """Returns a product with one grounded field (name present in the page) and one
    hallucinated field (brand absent from the page)."""

    def complete(self, prompt, *, system=None, max_tokens=2048, model=None):
        return LLMResponse(
            text='[{"name": "Real Widget", "brand": "GhostBrand", "sku": "ZZZ-NOPE"}]',
            model="fake", backend="fake",
        )


def _settings():
    return Settings(site="https://x", seeds=[], raw={"llm": {}}, config_path="x")


def test_grounding_guard_drops_absent_values():
    html = "<html><body><h1>Real Widget</h1><p>A real widget for sale.</p></body></html>"
    agent = LLMExtractorAgent(FakeLLM(), _settings(), logging.getLogger("t"))
    products = agent(html=html, url="https://x/p", profile=None,
                     source_category=None, draft=[])
    assert products and len(products) == 1
    p = products[0]
    assert p.name == "Real Widget"      # grounded -> kept
    assert p.brand is None              # "GhostBrand" not on page -> dropped
    assert p.sku is None                # "ZZZ-NOPE" not on page -> dropped
