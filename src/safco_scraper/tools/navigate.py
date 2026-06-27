"""Navigator: discover product URLs, subcategories and pagination from a category
listing page. Uses the page's schema.org JSON-LD (subcategory ItemList, product
ItemList, BreadcrumbList) with an HTML-anchor fallback, plus a robust,
param-agnostic next-page detector.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

from .extract import _is_type, parse_jsonld

# Words / symbols that mark a "next page" control (case-insensitive).
_NEXT_WORDS = {"next", "next page", "older", "older posts", "more", "load more",
               "show more", "siguiente", "suivant", "weiter", "下一页", "下一頁"}
_NEXT_SYMBOLS = {">", "›", "»", "→", "≫", ">>"}
# Path-based pagination: page-2.html, /page/2, /p/2, _2, -2 at the end.
_PATH_PAGE_RE = re.compile(r"(?:page[-/_]?|/p/)(\d+)", re.I)


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


def find_next_pages(soup: BeautifulSoup, url: str, profile=None) -> list[str]:
    """Find next-page URLs without hardcoding the pagination param name.

    Layered, most-reliable-first: profile selector -> rel=next -> next-labelled
    anchors -> param-agnostic numeric increment (?p / ?page / ?x / ?start ...)
    -> path-based (page-2.html). Restricted to the SAME host + (for query
    pagination) the SAME path, so cross-domain / unrelated links are never followed.
    """
    cur = urlparse(url)
    cur_q = parse_qs(cur.query)
    out: list[str] = []

    def add(href: str | None):
        if not href:
            return
        absu = urljoin(url, href)
        pu = urlparse(absu)
        if pu.scheme not in ("http", "https"):
            return
        if pu.netloc and cur.netloc and pu.netloc != cur.netloc:
            return  # same host only
        if absu.split("#")[0] == url.split("#")[0]:
            return  # not the current page
        out.append(absu)

    # 1) Profile-specified selector (per-site override; cleanest for any-site).
    disc = getattr(profile, "discovery", None) if profile is not None else None
    if disc and disc.get("next_page"):
        for a in soup.select(disc["next_page"]):
            add(a.get("href"))

    # 2) Standard rel="next" on <a> and <link>.
    for el in soup.find_all(["a", "link"]):
        rel = el.get("rel") or []
        rels = rel if isinstance(rel, list) else [rel]
        if any(str(r).lower() == "next" for r in rels):
            add(el.get("href"))

    # 3) Anchors whose visible label / aria-label / title / class signals "next".
    for a in soup.find_all("a", href=True):
        label = (a.get_text(" ", strip=True) or a.get("aria-label") or a.get("title") or "").strip().lower()
        cls = " ".join(a.get("class") or []).lower()
        if label in _NEXT_WORDS or label in _NEXT_SYMBOLS or "next" in cls:
            add(a["href"])

    # 4) Param-agnostic heuristic: same path, one numeric query param == current+1.
    for a in soup.find_all("a", href=True):
        pu = urlparse(urljoin(url, a["href"]))
        if pu.netloc and cur.netloc and pu.netloc != cur.netloc:
            continue
        if pu.path != cur.path or not pu.query:
            continue
        for k, vals in parse_qs(pu.query).items():
            if vals and vals[0].isdigit():
                base = cur_q.get(k, ["1"])[0]
                cur_n = int(base) if base.isdigit() else 1
                if int(vals[0]) == cur_n + 1:
                    add(a["href"])

    # 5) Path-based pagination (page-2.html, /page/2, /p/2) at current+1.
    cm = _PATH_PAGE_RE.search(cur.path)
    cur_pn = int(cm.group(1)) if cm else 1
    for a in soup.find_all("a", href=True):
        pu = urlparse(urljoin(url, a["href"]))
        if pu.netloc and cur.netloc and pu.netloc != cur.netloc:
            continue
        m = _PATH_PAGE_RE.search(pu.path)
        if m and pu.path != cur.path and int(m.group(1)) == cur_pn + 1:
            add(a["href"])

    return _dedup(out)


def discover_listing(html: str, url: str, profile=None) -> DiscoveryResult:
    soup = BeautifulSoup(html, "lxml")
    nodes = parse_jsonld(soup)
    result = DiscoveryResult()

    # Profile-driven CSS product discovery (for sites without JSON-LD navigation).
    disc = getattr(profile, "discovery", None) if profile is not None else None
    if disc and disc.get("product_link"):
        for a in soup.select(disc["product_link"]):
            if a.get("href"):
                result.product_urls.append(urljoin(url, a["href"]))

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

    # HTML fallback for product links if nothing found yet.
    if not result.product_urls:
        for a in soup.select('a[href*="/product/"]'):
            href = a.get("href")
            if href:
                result.product_urls.append(urljoin(url, href))

    result.next_pages = find_next_pages(soup, url, profile)
    result.product_urls = _dedup(result.product_urls)
    result.subcategory_urls = _dedup(result.subcategory_urls)
    return result


def _offer_url(item: dict) -> str | None:
    offers = item.get("offers")
    if isinstance(offers, dict):
        return offers.get("url")
    if isinstance(offers, list) and offers:
        return offers[0].get("url")
    return None
