"""SQLite persistence: the product catalog, the crawl frontier (for resumability)
and a dead-letter table for permanently failed URLs.

- Products are upserted on `dedup_key` (SKU, else URL) -> idempotent re-runs.
- The frontier records each URL's status (pending/done/failed) so an interrupted
  run resumes by replaying only what is still pending.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ..models import Product

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    dedup_key       TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    sku             TEXT,
    item_number     TEXT,
    brand           TEXT,
    category_path   TEXT,
    source_category TEXT,
    product_url     TEXT,
    price           REAL,
    currency        TEXT,
    pack_size       TEXT,
    availability    TEXT,
    description     TEXT,
    specifications  TEXT,
    image_urls      TEXT,
    rating          REAL,
    variants        TEXT,
    alternatives    TEXT,
    extraction_tier TEXT,
    scraped_at      TEXT,
    updated_at      TEXT
);

CREATE TABLE IF NOT EXISTS frontier (
    url        TEXT PRIMARY KEY,
    kind       TEXT,           -- category | product | subcategory
    status     TEXT,           -- pending | done | failed
    source_category TEXT,
    attempts   INTEGER DEFAULT 0,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS dead_letter (
    url        TEXT PRIMARY KEY,
    error      TEXT,
    attempts   INTEGER,
    failed_at  TEXT
);

-- Human-in-the-loop handoff: the final escalation tier. When automation can't (or
-- shouldn't) proceed, a clear, actionable request is queued for a human instead of
-- evading or failing silently.
CREATE TABLE IF NOT EXISTS manual_help (
    url         TEXT PRIMARY KEY,
    reason      TEXT,
    suggested_action TEXT,
    requested_at TEXT,
    resolved    INTEGER DEFAULT 0
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # --- products --------------------------------------------------------- #
    def upsert_product(self, product: Product) -> None:
        row = product.to_row()
        row["updated_at"] = _now()
        cols = list(row.keys())
        placeholders = ",".join(["?"] * len(cols))
        updates = ",".join(f"{c}=excluded.{c}" for c in cols if c != "dedup_key")
        sql = (
            f"INSERT INTO products ({','.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT(dedup_key) DO UPDATE SET {updates}"
        )
        self.conn.execute(sql, [row[c] for c in cols])
        self.conn.commit()

    def enrich_product(
        self,
        dedup_key: str,
        *,
        specifications: dict | None = None,
        alternatives: list | None = None,
        description: str | None = None,
        image_urls: list | None = None,
    ) -> None:
        """Merge detail-page-only fields into an existing listing record.

        Only overwrites a column when the detail page provides richer data
        (non-empty specs/alts, or a longer description / more images), so the
        listing record is never degraded. Marks the row's tier as 'mixed'.
        """
        row = self.conn.execute(
            "SELECT description, image_urls FROM products WHERE dedup_key=?", (dedup_key,)
        ).fetchone()
        if row is None:
            return
        sets, params = [], []
        if specifications:
            sets.append("specifications=?")
            params.append(json.dumps(specifications, ensure_ascii=False))
        if alternatives:
            sets.append("alternatives=?")
            params.append(json.dumps(alternatives, ensure_ascii=False))
        if description and len(description) > len(row["description"] or ""):
            sets.append("description=?")
            params.append(description)
        if image_urls:
            existing = json.loads(row["image_urls"] or "[]")
            if len(image_urls) > len(existing):
                sets.append("image_urls=?")
                params.append(json.dumps(image_urls, ensure_ascii=False))
        if not sets:
            return
        sets.append("extraction_tier='mixed'")
        sets.append("updated_at=?")
        params.append(_now())
        params.append(dedup_key)
        self.conn.execute(f"UPDATE products SET {','.join(sets)} WHERE dedup_key=?", params)
        self.conn.commit()

    def product_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]

    def all_products(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM products ORDER BY source_category, name")]

    # --- frontier (checkpointing) ----------------------------------------- #
    def enqueue(self, url: str, kind: str, source_category: str | None = None) -> None:
        self.conn.execute(
            "INSERT INTO frontier (url, kind, status, source_category, attempts, updated_at) "
            "VALUES (?, ?, 'pending', ?, 0, ?) ON CONFLICT(url) DO NOTHING",
            (url, kind, source_category, _now()),
        )
        self.conn.commit()

    def pending(self, kind: str | None = None) -> list[sqlite3.Row]:
        if kind:
            cur = self.conn.execute(
                "SELECT * FROM frontier WHERE status='pending' AND kind=?", (kind,)
            )
        else:
            cur = self.conn.execute("SELECT * FROM frontier WHERE status='pending'")
        return cur.fetchall()

    def mark(self, url: str, status: str) -> None:
        self.conn.execute(
            "UPDATE frontier SET status=?, attempts=attempts+1, updated_at=? WHERE url=?",
            (status, _now(), url),
        )
        self.conn.commit()

    def dead_letter(self, url: str, error: str, attempts: int) -> None:
        self.conn.execute(
            "INSERT INTO dead_letter (url, error, attempts, failed_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(url) DO UPDATE SET error=excluded.error, attempts=excluded.attempts, failed_at=excluded.failed_at",
            (url, error, attempts, _now()),
        )
        self.mark(url, "failed")
        self.conn.commit()

    def dead_letters(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM dead_letter")]

    # --- human handoff (final escalation tier) ---------------------------- #
    def request_human_help(self, url: str, reason: str, suggested_action: str) -> None:
        self.conn.execute(
            "INSERT INTO manual_help (url, reason, suggested_action, requested_at, resolved) "
            "VALUES (?, ?, ?, ?, 0) ON CONFLICT(url) DO UPDATE SET "
            "reason=excluded.reason, suggested_action=excluded.suggested_action, requested_at=excluded.requested_at",
            (url, reason, suggested_action, _now()),
        )
        self.conn.commit()

    def help_queue(self, include_resolved: bool = False) -> list[dict[str, Any]]:
        q = "SELECT * FROM manual_help"
        if not include_resolved:
            q += " WHERE resolved=0"
        return [dict(r) for r in self.conn.execute(q)]

    def reset_frontier(self) -> None:
        self.conn.execute("DELETE FROM frontier")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
