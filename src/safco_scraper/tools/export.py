"""Exporters: write the catalog to JSON, CSV and Excel. Nested fields (specs,
images, variants, alternatives) are JSON-encoded in CSV/Excel and kept as native
objects in JSON.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

ROW_COLUMNS = [
    "dedup_key", "name", "sku", "item_number", "brand", "category_path",
    "source_category", "product_url", "price", "currency", "pack_size",
    "availability", "description", "specifications", "image_urls", "rating",
    "variants", "alternatives", "extraction_tier", "scraped_at",
]


def _decode_json_fields(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    for f in ("specifications", "image_urls", "variants", "alternatives"):
        if isinstance(out.get(f), str):
            try:
                out[f] = json.loads(out[f])
            except Exception:
                pass
    return out


def export_json(rows: list[dict[str, Any]], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [_decode_json_fields(r) for r in rows]
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def export_csv(rows: list[dict[str, Any]], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=ROW_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k) for k in ROW_COLUMNS})
    return path


def export_xlsx(rows: list[dict[str, Any]], path: str | Path) -> Path:
    from openpyxl import Workbook

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "products"
    ws.append(ROW_COLUMNS)
    for r in rows:
        ws.append([_stringify(r.get(k)) for k in ROW_COLUMNS])
    wb.save(path)
    return path


def _stringify(v: Any) -> Any:
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return v


def export_all(rows: list[dict[str, Any]], out_dir: str | Path, formats: list[str]) -> list[Path]:
    out_dir = Path(out_dir)
    written = []
    if "json" in formats:
        written.append(export_json(rows, out_dir / "products.json"))
    if "csv" in formats:
        written.append(export_csv(rows, out_dir / "products.csv"))
    if "xlsx" in formats:
        written.append(export_xlsx(rows, out_dir / "products.xlsx"))
    return written
