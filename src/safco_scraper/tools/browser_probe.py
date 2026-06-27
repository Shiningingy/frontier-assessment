"""Autonomous data-source discovery via browser network capture.

Loads a category page in a real browser, records the XHR/fetch calls it makes, and
finds the one that returns the product list (a JSON array of product-like records).
This is how the system discovers a site's hidden data API (Algolia / GraphQL / REST)
*without any hardcoded site knowledge* — it observes what the page itself does, then
the API can be replayed with pagination to get the complete catalog.

Requires the browser extra: pip install -e .[browser] && playwright install chromium.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

# Keys that hint a JSON object is a product record.
_PRODUCTISH = ("name", "title", "price", "sku", "image", "url", "brand", "manufacturer")


@dataclass
class ApiCall:
    endpoint: str
    method: str
    headers: dict
    post_data: Optional[str]
    hits_path: list            # path tokens to the records array, e.g. ["results",0,"hits"]
    total: Optional[int]       # nbHits / total count reported by the API
    n_records: int
    sample: dict
    record_keys: list
    category_scoped: bool = False  # request filters by this page's category


@dataclass
class ProbeResult:
    url: str
    rendered_card_count: int = 0
    api_calls: list[ApiCall] = field(default_factory=list)

    def best_product_api(self) -> Optional[ApiCall]:
        """The product-list API for THIS category: prefer a request that is scoped to
        the page's category (has a category facet filter) over generic widgets like
        'best sellers' or search autocomplete; then by reported total."""
        if not self.api_calls:
            return None
        return sorted(
            self.api_calls,
            key=lambda c: (c.category_scoped, c.total or c.n_records, len(c.record_keys)),
            reverse=True,
        )[0]


def _score_record(keys) -> int:
    kl = [str(k).lower() for k in keys]
    return sum(1 for p in _PRODUCTISH if any(p in k for k in kl))


def _find_record_arrays(obj: Any, path=None, out=None):
    """Yield (path_tokens, list, total_guess) for product-ish arrays of dicts."""
    if path is None:
        path, out = [], []
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        keys = set().union(*[set(d.keys()) for d in obj[:3] if isinstance(d, dict)])
        if _score_record(keys) >= 2:
            out.append((list(path), obj, keys))
    if isinstance(obj, dict):
        for k, v in obj.items():
            _find_record_arrays(v, path + [k], out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:2]):
            _find_record_arrays(v, path + [i], out)
    return out


def _total_near(container: Any) -> Optional[int]:
    """A total/count field sitting beside a hits array (nbHits, total, count...)."""
    if not isinstance(container, dict):
        return None
    for k in ("nbHits", "total", "totalHits", "count", "found", "total_count", "totalResults"):
        v = container.get(k)
        if isinstance(v, int):
            return v
    return None


def probe_category(url: str, wait_ms: int = 6000, user_agent: Optional[str] = None,
                   logger: Optional[logging.Logger] = None) -> ProbeResult:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - optional dep
        raise RuntimeError("Playwright not installed. Run: pip install -e .[browser] "
                           "&& playwright install chromium") from exc
    logger = logger or logging.getLogger("safco")
    ua = user_agent or ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
    result = ProbeResult(url=url)
    seen_endpoints: set[str] = set()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(user_agent=ua)

        def on_response(resp):
            try:
                if "json" not in resp.headers.get("content-type", ""):
                    return
                body = resp.json()
            except Exception:
                return
            for path, arr, keys in _find_record_arrays(body):
                # the container holding the array (for a sibling total)
                container = body
                for tok in path[:-1]:
                    container = container[tok]
                total = _total_near(container)
                ep = resp.url.split("?")[0]
                dedup = f"{ep}|{'.'.join(map(str, path))}|{total}"
                if dedup in seen_endpoints:
                    continue
                seen_endpoints.add(dedup)
                req = resp.request
                pd = (req.post_data or "").lower()
                # category-scoped if the request actually FILTERS by a category
                # (facetFilters on categories.*, or a magento-category rule context).
                category_scoped = (("facetfilter" in pd and "categories.level" in pd)
                                   or "magento-category" in pd)
                result.api_calls.append(ApiCall(
                    endpoint=resp.url, method=req.method, headers=dict(req.headers),
                    post_data=req.post_data, hits_path=path, total=total,
                    n_records=len(arr), sample=arr[0], record_keys=sorted(keys),
                    category_scoped=category_scoped,
                ))

        page.on("response", on_response)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(wait_ms)
            result.rendered_card_count = page.locator("a[href*='/product/']").count()
        finally:
            browser.close()
    logger.info(f"browser_probe: {len(result.api_calls)} product-API candidate(s) on {url}")
    return result
