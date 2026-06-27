"""The conductor's tool-use loop should dispatch tools and ground its final answer
in their output — driven here by a fake LLM with scripted responses (no network).
"""
import logging
import threading

from safco_scraper.agents.conductor import ConductorAgent
from safco_scraper.agents.reporter import ReporterAgent
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


def test_conductor_injects_configured_seed_urls(tmp_path):
    # The model must be handed the real seed URLs so it never guesses a domain.
    from safco_scraper.config import Seed
    settings = _settings(tmp_path)
    settings.seeds = [Seed(name="Dental Exam Gloves", url="https://www.safcodental.com/catalog/gloves")]
    conductor = ConductorAgent(ScriptedLLM(["{}"]), settings, logging.getLogger("t"))
    assert "https://www.safcodental.com/catalog/gloves" in conductor.system
    assert "do not invent" in conductor.system.lower()


def test_reporter_answer_works_across_threads(tmp_path):
    # Regression: the reporter is built in one thread (e.g. with the conductor at UI
    # startup) but answer() may run in a Gradio worker thread. SQLite is thread-bound,
    # so a per-construction connection would raise "objects created in a thread...".
    settings = _settings(tmp_path)
    _seed_db(settings)
    reporter = ReporterAgent(ScriptedLLM(["The cheapest is Compac Nitrile at $8.49."]),
                             settings, logging.getLogger("t"))
    result = {}

    def run():
        try:
            result["answer"] = reporter.answer("cheapest nitrile?")
        except Exception as exc:  # would be a sqlite ProgrammingError before the fix
            result["error"] = repr(exc)

    t = threading.Thread(target=run)
    t.start()
    t.join()
    assert "error" not in result, result.get("error")
    assert "8.49" in result["answer"]


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
