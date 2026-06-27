"""Algolia catalog source for Safco (Magento + Algolia).

Safco's category pages show only a curated sample (15 items) and load the full
catalog client-side from Algolia. Rather than fight JS pagination or click "More"
in a browser, we use the **same public, search-only API the site itself uses** —
the app id + search key are embedded in every category page by design. This yields
the complete, structured catalog with true counts in a couple of requests.

This is a "source" tier: it returns already-structured records, so it feeds the
normal validate → store → export pipeline directly (no HTML extraction needed).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Iterator, Optional

import httpx

# Magento-Algolia replica index used for category browsing.
DEFAULT_INDEX = "safco_prod_default_products_name_asc"


@dataclass
class AlgoliaConfig:
    app_id: str
    api_key: str
    index: str = DEFAULT_INDEX


def discover_config(html: str) -> Optional[AlgoliaConfig]:
    """Pull the public Algolia app id + search key from a category page."""
    app = re.search(r'"applicationId":"([^"]+)"', html)
    key = re.search(r'"apiKey":"([^"]+)"', html)
    if not (app and key):
        return None
    idx = DEFAULT_INDEX
    if re.search(r'"' + re.escape(DEFAULT_INDEX) + r'"', html) is None:
        m = re.search(r'"(safco_[a-z0-9_]+_products[a-z0-9_]*)"', html)
        if m:
            idx = m.group(1)
    return AlgoliaConfig(app_id=app.group(1), api_key=key.group(1), index=idx)


def discover_category_id(html: str) -> Optional[str]:
    """The Magento category id the page filters Algolia by (e.g. 385 for gloves)."""
    m = re.search(r'(?:categoryId|category_id|catId|current_category_id)["\' :=]+"?(\d+)', html)
    return m.group(1) if m else None


def _variant_skus(sku_field: Any) -> tuple[Optional[str], list[str]]:
    """A product's `sku` is a list of variant codes (primary first, with numeric
    item numbers in dashed + undashed forms). Return (primary, deduped variants)."""
    if not isinstance(sku_field, list):
        return (sku_field, [])
    if not sku_field:
        return (None, [])
    primary = sku_field[0]
    seen, variants = set(), []
    for code in sku_field[1:]:
        norm = str(code).replace("-", "")
        if norm and norm not in seen:
            seen.add(norm)
            variants.append(code)
    return (primary, variants)


def map_hit(hit: dict, source_category: Optional[str]) -> dict:
    """Map an Algolia product record to our raw-record field names, capturing the
    product's variant SKUs (product variations)."""
    price = None
    p = hit.get("price")
    if isinstance(p, dict):
        usd = p.get("USD") or {}
        price = usd.get("default")
    img = hit.get("image_url") or hit.get("thumbnail_url")
    cats = hit.get("categories_without_path")
    category = " > ".join(cats) if isinstance(cats, list) and cats else source_category
    avail = hit.get("stock_status_label")
    if not avail:
        avail = "InStock" if hit.get("in_stock") else "OutOfStock"
    primary_sku, variant_skus = _variant_skus(hit.get("sku"))
    return {
        "name": hit.get("name"),
        "sku": primary_sku,
        "item_number": hit.get("manufacturer_part_number"),
        "brand": hit.get("manufacturer_name"),
        "price": price,
        "currency": "USD",
        "availability": avail,
        "image_urls": [img] if img else [],
        "category": category,
        "product_url": hit.get("url"),
        "variants": [{"sku": s} for s in variant_skus],
    }


class AlgoliaCatalog:
    def __init__(self, config: AlgoliaConfig, logger: Optional[logging.Logger] = None,
                 hits_per_page: int = 1000, timeout: float = 30.0) -> None:
        self.config = config
        self.logger = logger or logging.getLogger("safco")
        self.hits_per_page = hits_per_page
        self._url = f"https://{config.app_id}-dsn.algolia.net/1/indexes/{config.index}/query"
        self._headers = {
            "X-Algolia-Application-Id": config.app_id,
            "X-Algolia-API-Key": config.api_key,
            "Content-Type": "application/json",
        }

    def _query(self, category_id: str, page: int) -> dict:
        body = {"query": "", "hitsPerPage": self.hits_per_page, "page": page,
                "facetFilters": [[f"categoryIds:{category_id}"]], "attributesToHighlight": []}
        resp = httpx.post(self._url, headers=self._headers, json=body, timeout=30)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _catalog_visible(hit: dict) -> bool:
        # The site shows only catalog-visible products (the rest are variant child
        # rows). visibility_catalog isn't a server-side facet, so we filter here.
        return hit.get("visibility_catalog") in (1, True)

    def products(self, category_id: str, source_category: Optional[str] = None,
                 max_items: Optional[int] = None) -> Iterator[dict]:
        """Yield mapped product records (catalog-visible only) for a category id,
        across all Algolia pages — the complete displayed catalog with variants."""
        page, yielded = 0, 0
        while True:
            d = self._query(category_id, page)
            hits = d.get("hits", [])
            if not hits:
                break
            for hit in hits:
                if not self._catalog_visible(hit):
                    continue
                yield map_hit(hit, source_category)
                yielded += 1
                if max_items and yielded >= max_items:
                    return
            n_pages = d.get("nbPages", page + 1)
            page += 1
            if page >= n_pages:
                break
