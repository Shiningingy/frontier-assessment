"""Offline extraction tests against captured Safco HTML fixtures."""
from pathlib import Path

from safco_scraper.tools.extract import extract_with_profile
from safco_scraper.tools.navigate import discover_listing
from safco_scraper.tools.profiles import ProfileStore, compute_signature

FIXTURES = Path(__file__).parent / "fixtures"
PROFILES = ProfileStore(Path(__file__).parents[1] / "profiles")


def test_listing_extracts_all_products():
    html = (FIXTURES / "gloves_listing.html").read_text(encoding="utf-8")
    profile = PROFILES.get("safcodental.com", "catalog-listing")
    out = extract_with_profile(html, profile, "https://www.safcodental.com/catalog/gloves")
    assert len(out.records) == 15
    first = out.records[0]
    assert first["name"]
    assert first["sku"]
    assert first["price"] is not None
    assert first["product_url"].startswith("https://www.safcodental.com/product/")


def test_listing_fields_are_grounded_values():
    html = (FIXTURES / "gloves_listing.html").read_text(encoding="utf-8")
    profile = PROFILES.get("safcodental.com", "catalog-listing")
    out = extract_with_profile(html, profile, "https://www.safcodental.com/catalog/gloves")
    skus = {r["sku"] for r in out.records}
    assert "DRCDM" in skus  # Compac Nitrile, verified live


def test_detail_specifications_inline_label():
    html = (FIXTURES / "product_detail.html").read_text(encoding="utf-8")
    profile = PROFILES.get("safcodental.com", "product-detail")
    out = extract_with_profile(html, profile, "https://www.safcodental.com/product/compac-nitrile")
    rec = out.records[0]
    specs = rec["specifications"]
    assert isinstance(specs, dict) and specs
    assert "Brand" in specs and "Material" in specs  # parsed from <li><strong>Label:</strong>


def test_navigator_discovers_products_and_subcategories():
    html = (FIXTURES / "gloves_listing.html").read_text(encoding="utf-8")
    disc = discover_listing(html, "https://www.safcodental.com/catalog/gloves")
    assert len(disc.product_urls) == 15
    assert len(disc.subcategory_urls) >= 1
    assert disc.breadcrumb  # category hierarchy present


def test_signature_stable_across_same_template_pages():
    a = compute_signature((FIXTURES / "gloves_listing.html").read_text(encoding="utf-8"))
    b = compute_signature((FIXTURES / "sutures_listing.html").read_text(encoding="utf-8"))
    # Two pages of the same catalog-listing template hash identically.
    assert a == b
    # A different template (product detail) hashes differently.
    c = compute_signature((FIXTURES / "product_detail.html").read_text(encoding="utf-8"))
    assert c != a
