"""Per-domain source memory: a cached recipe (profiles/<domain>/_source.json) makes
the orchestrator use the learned source automatically, unless an explicit source is
pinned. This is what makes 'crawl gloves from safco' return the complete catalog.
"""
import logging

from safco_scraper.config import Seed, Settings
from safco_scraper.orchestrator import Orchestrator
from safco_scraper.tools.profiles import ProfileStore

GLOVES = Seed(name="Gloves", url="https://www.safcodental.com/catalog/gloves")


def _settings(tmp_path, backend="html", pinned=False):
    src = {"backend": backend}
    if pinned:
        src["pinned"] = True
    return Settings(site="https://www.safcodental.com", seeds=[],
                    raw={"source": src, "storage": {"db_path": str(tmp_path / "s.db")},
                         "extraction": {}},
                    config_path="x")


def _orch(tmp_path, settings):
    profiles = tmp_path / "profiles"
    ProfileStore(profiles).save_source_recipe("safcodental.com", {"backend": "algolia"})
    return Orchestrator(settings, None, logging.getLogger("t"), profiles_root=str(profiles))


def test_source_recipe_roundtrip_and_not_listed_as_profile(tmp_path):
    store = ProfileStore(tmp_path)
    store.save_source_recipe("safcodental.com",
                             {"backend": "algolia", "algolia": {"category_root": "Dental Supplies"}})
    assert store.get_source_recipe("safcodental.com")["backend"] == "algolia"
    assert store.get_source_recipe("unknown.com") is None
    # _source.json must not be mistaken for an extraction profile
    assert store.list_for_domain("safcodental.com") == []


def test_orchestrator_applies_per_domain_recipe(tmp_path):
    settings = _settings(tmp_path, backend="html")  # config default = html
    orch = _orch(tmp_path, settings)
    orch._apply_source_recipe([GLOVES])
    assert settings.source_backend == "algolia"  # remembered Safco -> Algolia


def test_pinned_source_overrides_recipe(tmp_path):
    settings = _settings(tmp_path, backend="html", pinned=True)  # explicit --source html
    orch = _orch(tmp_path, settings)
    orch._apply_source_recipe([GLOVES])
    assert settings.source_backend == "html"  # explicit choice wins


def test_no_recipe_keeps_config_default(tmp_path):
    settings = _settings(tmp_path, backend="html")
    orch = _orch(tmp_path, settings)
    orch._apply_source_recipe([Seed(name="X", url="https://other-site.com/catalog/x")])
    assert settings.source_backend == "html"  # unknown domain -> config default
