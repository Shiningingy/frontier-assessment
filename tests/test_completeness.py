"""Completeness-critic verdict logic (offline; HTML-signal path, no browser)."""
import logging

from safco_scraper.agents.completeness import CompletenessCritic
from safco_scraper.config import Settings


def _critic():
    s = Settings(site="x", seeds=[], raw={}, config_path="x")
    return CompletenessCritic(s, logging.getLogger("t"), use_browser=False)


def test_incomplete_when_extracted_below_total():
    v = _critic().check("https://x/cat", extracted=15, html="<p>100 products</p>")
    assert v.expected == 100
    assert v.complete is False
    assert v.recommended_action and "Escalate" in v.recommended_action


def test_complete_when_extracted_meets_total():
    v = _critic().check("https://x/cat", extracted=100, html="<p>100 products found</p>")
    assert v.expected == 100
    assert v.complete is True
    assert v.recommended_action is None


def test_unknown_total_is_flagged_not_assumed_complete():
    v = _critic().check("https://x/cat", extracted=15, html="<p>no count here</p>")
    assert v.expected is None
    assert v.complete is False          # unknown != complete
    assert v.method == "unknown"
