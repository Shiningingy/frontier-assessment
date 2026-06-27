"""The conductor's tool-use loop should dispatch tools and ground its final answer
in their output — driven here by a fake LLM with scripted responses (no network).
"""
import logging

from safco_scraper.agents.conductor import ConductorAgent
from safco_scraper.config import Settings
from safco_scraper.llm.base import LLMResponse
from safco_scraper.models import Product
from safco_scraper.tools.store import Store


class ScriptedLLM:
    """Returns queued responses in order, one per complete() call."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def complete(self, prompt, *, system=None, max_tokens=2048, model=None):
        self.calls.append(prompt)
        text = self._responses.pop(0)
        return LLMResponse(text=text, model="fake", backend="fake")


def _settings(tmp_path):
    db = tmp_path / "safco.db"
    return Settings(
        site="https://www.safcodental.com",
        seeds=[],
        raw={"llm": {}, "storage": {"db_path": str(db)}, "output": {"dir": str(tmp_path)}},
        config_path="x",
    )


def _seed_db(settings):
    store = Store(settings.db_path)
    store.upsert_product(Product(name="Compac Nitrile", sku="DRCDM", brand="Cranberry",
                                 product_url="https://x/a", price=8.49, source_category="Dental Exam Gloves"))
    store.upsert_product(Product(name="Crave", sku="DRCCA", brand="Cranberry",
                                 product_url="https://x/b", price=24.49, source_category="Dental Exam Gloves"))
    store.close()


def test_conductor_dispatches_tool_then_finalizes(tmp_path):
    settings = _settings(tmp_path)
    _seed_db(settings)
    llm = ScriptedLLM([
        '{"tool": "list_catalog_sites", "args": {}}',
        '{"final": "There are 2 products stored, both in Dental Exam Gloves."}',
    ])
    conductor = ConductorAgent(llm, settings, logging.getLogger("t"))
    final, steps = conductor.run_turn("what is stored?", [])

    assert "2 products" in final
    assert any("list_catalog_sites" in s for s in steps)
    assert len(llm.calls) == 2  # one tool call, one finalize


def test_conductor_handles_unknown_tool_gracefully(tmp_path):
    settings = _settings(tmp_path)
    _seed_db(settings)
    llm = ScriptedLLM([
        '{"tool": "nonexistent", "args": {}}',
        '{"final": "Sorry, I could not do that."}',
    ])
    conductor = ConductorAgent(llm, settings, logging.getLogger("t"))
    final, steps = conductor.run_turn("do something weird", [])
    assert "Sorry" in final  # the loop recovered from the unknown-tool observation
