"""Pagination is followed end-to-end: a 2-page synthetic category is crawled via a
FakeFetcher and all products from both pages land in the store. Proves the
orchestrator enqueues `next_pages` and re-polls the frontier within one run.
"""
import asyncio
import json
import logging

from safco_scraper.config import Settings
from safco_scraper.fetcher.base import FetchResult
from safco_scraper.orchestrator import Orchestrator
from safco_scraper.tools.store import Store

DOMAIN = "shop.test"
P1 = "https://shop.test/catalog/x"
P2 = "https://shop.test/catalog/x?p=2"


def _listing_html(skus, next_href=None):
    items = [{
        "@type": "ListItem", "position": i + 1,
        "url": f"https://shop.test/product/{s.lower()}",
        "item": {
            "@type": "Product", "@id": f"https://shop.test/product/{s.lower()}#p",
            "name": f"Widget {s}", "sku": s,
            "offers": {"@type": "Offer", "price": "9.99", "priceCurrency": "USD",
                       "availability": "https://schema.org/InStock",
                       "url": f"https://shop.test/product/{s.lower()}"},
        },
    } for i, s in enumerate(skus)]
    ld = {"@context": "https://schema.org", "@type": "ItemList",
          "name": "Widgets Products", "numberOfItems": len(skus), "itemListElement": items}
    nxt = f'<a rel="next" href="{next_href}">Next</a>' if next_href else ""
    return (f'<html><head><script type="application/ld+json">{json.dumps(ld)}</script></head>'
            f'<body><main>{nxt}</main></body></html>')


class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages
        self.fetched = []

    async def fetch(self, url):
        self.fetched.append(url)
        return FetchResult(url=url, status=200, html=self.pages[url], elapsed_ms=1)

    async def aclose(self):
        pass


def _settings(tmp_path):
    return Settings(
        site="https://shop.test", seeds=[],
        raw={
            "crawl": {"follow_product_pages": False, "follow_pagination": True, "max_pages": 10},
            "extraction": {"min_coverage": 0.0},
            "storage": {"db_path": str(tmp_path / "p.db")},
            "output": {"dir": str(tmp_path), "formats": []},
            "llm": {},
        },
        config_path="x",
    )


def _write_profile(profiles_root):
    d = profiles_root / DOMAIN
    d.mkdir(parents=True, exist_ok=True)
    profile = {
        "site": DOMAIN, "template": "catalog-listing", "cardinality": "many",
        "match": {"url_glob": "/catalog/*"},
        "fields": {
            "name": {"source": "jsonld", "path": "Product.name"},
            "sku": {"source": "jsonld", "path": "Product.sku"},
            "price": {"source": "jsonld", "path": "Product.offers.price"},
            "availability": {"source": "jsonld", "path": "Product.offers.availability"},
            "product_url": {"source": "jsonld", "path": "Product.offers.url"},
        },
        "ttl_hours": 168, "field_confidence": {}, "version": 1, "authored_by": "hand",
    }
    (d / "catalog-listing.json").write_text(json.dumps(profile), encoding="utf-8")


def test_pagination_walks_all_pages(tmp_path):
    profiles_root = tmp_path / "profiles"
    _write_profile(profiles_root)
    settings = _settings(tmp_path)
    pages = {
        P1: _listing_html(["AA", "BB"], next_href="?p=2"),
        P2: _listing_html(["CC", "DD"], next_href=None),
    }
    fetcher = FakeFetcher(pages)
    from safco_scraper.config import Seed

    orch = Orchestrator(settings, fetcher, logging.getLogger("t"), profiles_root=str(profiles_root))
    metrics = asyncio.run(orch.run(seeds=[Seed(name="X", url=P1)]))

    # Both pages fetched, all four products (2 per page) stored.
    assert P1 in fetcher.fetched and P2 in fetcher.fetched
    assert metrics.products_stored == 4
    store = Store(settings.db_path)
    skus = {r["sku"] for r in store.all_products()}
    assert skus == {"AA", "BB", "CC", "DD"}


def test_pagination_respects_max_pages(tmp_path):
    profiles_root = tmp_path / "profiles"
    _write_profile(profiles_root)
    settings = _settings(tmp_path)
    settings.raw["crawl"]["max_pages"] = 1  # stop after the first page
    pages = {
        P1: _listing_html(["AA", "BB"], next_href="?p=2"),
        P2: _listing_html(["CC", "DD"], next_href=None),
    }
    fetcher = FakeFetcher(pages)
    from safco_scraper.config import Seed

    orch = Orchestrator(settings, fetcher, logging.getLogger("t"), profiles_root=str(profiles_root))
    metrics = asyncio.run(orch.run(seeds=[Seed(name="X", url=P1)]))

    # Cap hit after page 1 -> page 2 never fetched.
    assert P2 not in fetcher.fetched
    assert metrics.products_stored == 2
