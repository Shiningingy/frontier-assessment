"""Param-agnostic next-page detection: works for ?p=, ?page=, ?x=, rel=next,
'Next' text, and path-based pagination, and never follows cross-domain links.
"""
from bs4 import BeautifulSoup

from safco_scraper.tools.navigate import find_next_pages

BASE = "https://shop.test/catalog/x"


def _next(html, url=BASE, profile=None):
    return find_next_pages(BeautifulSoup(html, "lxml"), url, profile)


def test_rel_next():
    assert _next('<a rel="next" href="?p=2">Next</a>') == ["https://shop.test/catalog/x?p=2"]


def test_param_p():
    assert "https://shop.test/catalog/x?p=2" in _next('<a href="?p=2">2</a>')


def test_param_page():
    assert "https://shop.test/catalog/x?page=2" in _next('<a href="?page=2">2</a>')


def test_param_arbitrary_name():
    # an unusual param name must still be detected via the numeric-increment heuristic
    assert "https://shop.test/catalog/x?x=2" in _next('<a href="?x=2">2</a>')
    assert "https://shop.test/catalog/x?start=2" in _next('<a href="?start=2">2</a>')


def test_next_by_text():
    out = _next('<a href="/catalog/x?pg=2">Next ›</a>')
    assert "https://shop.test/catalog/x?pg=2" in out


def test_path_based():
    out = _next('<a href="page-2.html">2</a>', url="https://shop.test/catalogue/page-1.html")
    assert "https://shop.test/catalogue/page-2.html" in out


def test_cross_domain_excluded():
    # a same-param link to ANOTHER host must not be followed (the dentallearning bug)
    html = '<a href="https://www.elsewhere.com/x?page=2">page 2</a>'
    assert _next(html) == []


def test_from_page2_finds_page3():
    out = _next('<a href="?page=3">3</a>', url="https://shop.test/catalog/x?page=2")
    assert "https://shop.test/catalog/x?page=3" in out
