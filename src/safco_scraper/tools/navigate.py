"""Navigator: discover product URLs, subcategories and pagination from a category
listing page. Uses the page's schema.org JSON-LD (subcategory ItemList, product
ItemList, BreadcrumbList) with an HTML-anchor fallback.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .extract import _is_type, parse_jsonld


@dataclass
class DiscoveryResult:
    product_urls: list[str] = field(default_factory=list)
    subcategory_urls: list[tuple[str, str]] = field(default_factory=list)  # (url, name)
    next_pages: list[str] = field(default_factory=list)
    breadcrumb: list[str] = field(default_factory=list)


def _dedup(seq):
    seen, out = set(), []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def discover_listing(html: str, url: str) -> DiscoveryResult:
    soup = BeautifulSoup(html, "lxml")
    nodes = parse_jsonld(soup)
    result = DiscoveryResult()

    for node in nodes:
        if _is_type(node, "ItemList"):
            for el in node.get("itemListElement", []):
                if not isinstance(el, dict):
                    continue
                item = el.get("item") if isinstance(el.get("item"), dict) else {}
                # Product list element -> product URL (el.url or item.offers.url)
                if _is_type(item, "Product") or "Product" in str(node.get("name", "")):
                    purl = el.get("url") or item.get("url") or _offer_url(item)
                    if purl:
                        result.product_urls.append(urljoin(url, purl))
                # Subcategory list element (CollectionPage)
                elif _is_type(item, "CollectionPage"):
                    name = item.get("name") or ""
                    suburl = item.get("url")
                    if suburl:
                        result.subcategory_urls.append((urljoin(url, suburl), name))
        elif _is_type(node, "BreadcrumbList"):
            crumbs = []
            for el in node.get("itemListElement", []):
                if isinstance(el, dict) and el.get("name"):
                    crumbs.append(el["name"])
            if crumbs:
                result.breadcrumb = crumbs

    # HTML fallback for product links if JSON-LD yielded none.
    if not result.product_urls:
        for a in soup.select('a[href*="/product/"]'):
            href = a.get("href")
            if href:
                result.product_urls.append(urljoin(url, href))

    # Pagination: rel=next or ?p=N / page=N links.
    for a in soup.select('a[rel="next"], a.next, a[href*="?p="], a[href*="page="]'):
        href = a.get("href")
        if href:
            result.next_pages.append(urljoin(url, href))

    result.product_urls = _dedup(result.product_urls)
    result.subcategory_urls = _dedup(result.subcategory_urls)
    result.next_pages = _dedup(p for p in result.next_pages if p != url)
    return result


def _offer_url(item: dict) -> str | None:
    offers = item.get("offers")
    if isinstance(offers, dict):
        return offers.get("url")
    if isinstance(offers, list) and offers:
        return offers[0].get("url")
    return None
