"""Validation, normalization and coverage scoring.

Turns a raw record (whatever tier produced it) into a clean, typed `Product`.
Also computes per-record *coverage* — the fraction of important fields that were
populated — which is the signal the orchestrator uses to decide whether a profile
succeeded or must be re-authored.
"""
from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import urljoin

from ..models import COVERAGE_FIELDS, Alternative, Availability, Product, Variant


class ValidationError(Exception):
    pass


_PRICE_RE = re.compile(r"[-+]?\d[\d,]*\.?\d*")


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = _PRICE_RE.search(str(value).replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _to_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return [v for v in value if v is not None]
    return [value]


def _abs_url(value: Optional[str], base: str) -> Optional[str]:
    if not value:
        return None
    return urljoin(base, value)


def _category_path(value: Any, fallback: Optional[str]) -> list[str]:
    if isinstance(value, list):
        parts = [str(v).strip() for v in value if str(v).strip()]
    elif isinstance(value, str) and value.strip():
        # category strings can be "A > B > C" or "A/B"
        parts = [p.strip() for p in re.split(r"[>/]", value) if p.strip()]
    else:
        parts = []
    if not parts and fallback:
        parts = [fallback]
    return parts


def normalize_record(
    raw: dict[str, Any],
    *,
    source_category: Optional[str] = None,
    page_url: str = "",
    extraction_tier: str = "jsonld",
) -> Product:
    # Resolve all relative URLs (product link, images, alternatives) against the page
    # the record was found on — works whether product_url is absolute (JSON-LD) or a
    # relative href (CSS extraction).
    base = page_url or raw.get("product_url") or ""

    name = raw.get("name")
    if not name or not str(name).strip():
        raise ValidationError("record has no product name")

    images = [_abs_url(u, base) for u in _to_list(raw.get("image_urls"))]
    images = [u for u in images if u]

    variants = []
    for v in _to_list(raw.get("variants")):
        if isinstance(v, dict):
            variants.append(
                Variant(
                    sku=v.get("sku"),
                    pack_size=v.get("pack") or v.get("pack_size"),
                    price=_to_float(v.get("price")),
                    availability=Availability.from_raw(v.get("availability")),
                )
            )

    alternatives = []
    for a in _to_list(raw.get("alternatives")):
        if isinstance(a, dict):
            alternatives.append(
                Alternative(
                    name=(a.get("name") or "").strip() or None,
                    url=_abs_url(a.get("url"), base),
                    sku=a.get("sku"),
                )
            )

    specs = raw.get("specifications")
    specs = specs if isinstance(specs, dict) else {}

    product = Product(
        name=str(name).strip(),
        sku=raw.get("sku"),
        item_number=raw.get("item_number") or raw.get("sku"),
        brand=raw.get("brand"),
        category_path=_category_path(raw.get("category"), source_category),
        source_category=source_category,
        product_url=_abs_url(raw.get("product_url"), base) or base,
        price=_to_float(raw.get("price")),
        currency=raw.get("currency") or "USD",
        pack_size=raw.get("pack_size"),
        availability=Availability.from_raw(raw.get("availability")),
        description=raw.get("description"),
        specifications={str(k): str(v) for k, v in specs.items()},
        image_urls=images,
        rating=_to_float(raw.get("rating")),
        variants=variants,
        alternatives=alternatives,
        extraction_tier=extraction_tier,
    )
    return product


def record_coverage(product: Product) -> float:
    """Fraction of COVERAGE_FIELDS that are populated (non-empty)."""
    present = 0
    for f in COVERAGE_FIELDS:
        val = getattr(product, f, None)
        if isinstance(val, (list, dict, str)):
            present += 1 if val else 0
        elif isinstance(val, Availability):
            present += 1 if val != Availability.UNKNOWN else 0
        else:
            present += 1 if val is not None else 0
    return present / len(COVERAGE_FIELDS)
