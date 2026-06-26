"""Normalized data model for the product catalog.

This is the documented output schema (see docs/SCHEMA.md). Every scraped record
is validated and normalized into a `Product` before it is persisted, regardless
of which extraction tier produced the raw data.
"""
from __future__ import annotations

import enum
import json
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class Availability(str, enum.Enum):
    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"
    PREORDER = "preorder"
    DISCONTINUED = "discontinued"
    UNKNOWN = "unknown"

    @classmethod
    def from_raw(cls, value: Any) -> "Availability":
        if value is None:
            return cls.UNKNOWN
        text = str(value).strip().lower().rsplit("/", 1)[-1]  # schema.org/InStock -> instock
        mapping = {
            "instock": cls.IN_STOCK,
            "in_stock": cls.IN_STOCK,
            "in stock": cls.IN_STOCK,
            "outofstock": cls.OUT_OF_STOCK,
            "out_of_stock": cls.OUT_OF_STOCK,
            "soldout": cls.OUT_OF_STOCK,
            "preorder": cls.PREORDER,
            "backorder": cls.PREORDER,
            "discontinued": cls.DISCONTINUED,
        }
        return mapping.get(text.replace(" ", ""), cls.UNKNOWN)


class Variant(BaseModel):
    """A purchasable variation of a product (e.g. a pack size / size option)."""

    sku: Optional[str] = None
    pack_size: Optional[str] = None
    price: Optional[float] = None
    availability: Availability = Availability.UNKNOWN


class Alternative(BaseModel):
    """A related / alternative product surfaced on the detail page."""

    name: Optional[str] = None
    url: Optional[str] = None
    sku: Optional[str] = None


class Product(BaseModel):
    """One normalized catalog product."""

    # Identity
    name: str
    sku: Optional[str] = None
    item_number: Optional[str] = None
    brand: Optional[str] = None

    # Placement
    category_path: list[str] = Field(default_factory=list)
    source_category: Optional[str] = None
    product_url: str

    # Commercial
    price: Optional[float] = None
    currency: Optional[str] = "USD"
    pack_size: Optional[str] = None
    availability: Availability = Availability.UNKNOWN

    # Descriptive
    description: Optional[str] = None
    specifications: dict[str, str] = Field(default_factory=dict)
    image_urls: list[str] = Field(default_factory=list)
    rating: Optional[float] = None

    # Relations
    variants: list[Variant] = Field(default_factory=list)
    alternatives: list[Alternative] = Field(default_factory=list)

    # Provenance / observability
    extraction_tier: str = "jsonld"  # jsonld | css | regex | llm | mixed
    scraped_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @field_validator("name", "description", "brand", "sku", mode="before")
    @classmethod
    def _strip(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v

    @property
    def dedup_key(self) -> str:
        """Idempotency key. SKU is authoritative; fall back to the canonical URL."""
        return (self.sku or "").strip().upper() or self.product_url.strip().lower()

    def to_row(self) -> dict[str, Any]:
        """Flatten to a single row for CSV / Excel / SQLite (nested fields JSON-encoded)."""
        return {
            "dedup_key": self.dedup_key,
            "name": self.name,
            "sku": self.sku,
            "item_number": self.item_number,
            "brand": self.brand,
            "category_path": " > ".join(self.category_path),
            "source_category": self.source_category,
            "product_url": self.product_url,
            "price": self.price,
            "currency": self.currency,
            "pack_size": self.pack_size,
            "availability": self.availability.value,
            "description": self.description,
            "specifications": json.dumps(self.specifications, ensure_ascii=False),
            "image_urls": json.dumps(self.image_urls, ensure_ascii=False),
            "rating": self.rating,
            "variants": json.dumps([v.model_dump() for v in self.variants], ensure_ascii=False),
            "alternatives": json.dumps([a.model_dump() for a in self.alternatives], ensure_ascii=False),
            "extraction_tier": self.extraction_tier,
            "scraped_at": self.scraped_at,
        }


# The set of fields used to compute extraction "coverage" (how complete a record
# is). Drives the min_coverage gate that decides whether a profile succeeded.
COVERAGE_FIELDS = [
    "name",
    "sku",
    "brand",
    "price",
    "availability",
    "description",
    "image_urls",
    "category_path",
]
