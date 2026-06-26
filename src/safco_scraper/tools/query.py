"""Catalog query helpers for the reporter agent. The reporter answers strictly
from these rows (the database) — never from outside knowledge.
"""
from __future__ import annotations

import json
from typing import Any

from .store import Store

# Compact projection sent to the reporter LLM as ground truth.
REPORT_FIELDS = [
    "name", "sku", "brand", "category_path", "source_category",
    "price", "currency", "availability", "pack_size", "product_url",
]


def load_catalog(store: Store) -> list[dict[str, Any]]:
    rows = store.all_products()
    out = []
    for r in rows:
        out.append({k: r.get(k) for k in REPORT_FIELDS})
    return out


def catalog_json(store: Store) -> tuple[int, str]:
    cat = load_catalog(store)
    return len(cat), json.dumps(cat, ensure_ascii=False, indent=0)


def deterministic_summary(store: Store) -> dict[str, Any]:
    """Pure-Python catalog summary (no LLM) for the stats/report header."""
    rows = store.all_products()
    by_cat: dict[str, int] = {}
    by_brand: dict[str, int] = {}
    prices = []
    in_stock = 0
    for r in rows:
        by_cat[r["source_category"]] = by_cat.get(r["source_category"], 0) + 1
        if r.get("brand"):
            by_brand[r["brand"]] = by_brand.get(r["brand"], 0) + 1
        if r.get("price") is not None:
            prices.append(r["price"])
        if r.get("availability") == "in_stock":
            in_stock += 1
    return {
        "total_products": len(rows),
        "by_category": by_cat,
        "top_brands": dict(sorted(by_brand.items(), key=lambda kv: kv[1], reverse=True)[:10]),
        "price_min": min(prices) if prices else None,
        "price_max": max(prices) if prices else None,
        "price_avg": round(sum(prices) / len(prices), 2) if prices else None,
        "in_stock": in_stock,
    }
