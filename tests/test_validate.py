"""Validation / normalization unit tests."""
from safco_scraper.models import Availability, Product
from safco_scraper.tools.validate import normalize_record, record_coverage


def test_normalize_price_and_availability():
    raw = {
        "name": "  Compac Nitrile ",
        "sku": "DRCDM",
        "brand": "Cranberry",
        "price": "8.49",
        "availability": "https://schema.org/InStock",
        "image_urls": "/media/catalog/x.jpg",
        "product_url": "https://www.safcodental.com/product/compac-nitrile",
        "category": "Dental Exam Gloves",
    }
    p = normalize_record(raw, source_category="Dental Exam Gloves",
                         page_url="https://www.safcodental.com/catalog/gloves")
    assert p.name == "Compac Nitrile"             # stripped
    assert p.price == 8.49                         # parsed to float
    assert p.availability == Availability.IN_STOCK  # enum mapped
    assert p.image_urls == ["https://www.safcodental.com/media/catalog/x.jpg"]  # absolutized
    assert p.category_path == ["Dental Exam Gloves"]


def test_missing_name_raises():
    import pytest
    from safco_scraper.tools.validate import ValidationError

    with pytest.raises(ValidationError):
        normalize_record({"sku": "X"}, page_url="https://x/y")


def test_dedup_key_prefers_sku():
    p = Product(name="A", sku="abc", product_url="https://x/a")
    assert p.dedup_key == "ABC"
    p2 = Product(name="B", product_url="https://x/b")
    assert p2.dedup_key == "https://x/b"


def test_coverage_scoring():
    full = normalize_record(
        {"name": "n", "sku": "s", "brand": "b", "price": "1.0",
         "availability": "InStock", "description": "d",
         "image_urls": ["http://x/i.jpg"], "category": "c"},
        page_url="https://x/p",
    )
    assert record_coverage(full) == 1.0
    sparse = normalize_record({"name": "n"}, page_url="https://x/p")
    assert 0.0 < record_coverage(sparse) < 0.5
