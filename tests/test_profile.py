"""Profile cache + matching tests."""
from safco_scraper.tools.profiles import Profile, ProfileStore


def _profile():
    return Profile(
        site="example.com",
        template="product-detail",
        cardinality="one",
        match={"url_glob": "/product/*"},
        fields={"name": {"source": "jsonld", "path": "Product.name"}},
    )


def test_save_and_get_roundtrip(tmp_path):
    store = ProfileStore(tmp_path)
    store.save(_profile())
    loaded = store.get("example.com", "product-detail")
    assert loaded is not None
    assert loaded.fields["name"]["path"] == "Product.name"


def test_find_for_url_matches_glob(tmp_path):
    store = ProfileStore(tmp_path)
    store.save(_profile())
    found = store.find_for_url("https://example.com/product/widget-123")
    assert found is not None and found.template == "product-detail"
    assert store.find_for_url("https://example.com/catalog/gloves") is None


def test_signature_touch_and_expiry():
    p = _profile()
    assert p.is_expired()  # never validated
    p.touch("sig123")
    assert p.template_signature == "sig123"
    assert not p.is_expired()
