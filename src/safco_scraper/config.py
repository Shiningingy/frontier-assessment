"""Config-driven execution: load config.yaml + .env into typed settings objects.

No behaviour is hardcoded in the pipeline; everything tunable lives in config.yaml
so the system can be pointed at new categories / sites and retuned without code
changes.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml
from dotenv import load_dotenv


@dataclass
class Seed:
    name: str
    url: str


@dataclass
class Settings:
    site: str
    seeds: list[Seed]
    raw: dict[str, Any]  # full parsed config for sections accessed ad hoc
    config_path: Path

    # --- convenience accessors over self.raw -------------------------------
    def section(self, name: str) -> dict[str, Any]:
        return self.raw.get(name, {}) or {}

    @property
    def follow_product_pages(self) -> bool:
        return bool(self.section("crawl").get("follow_product_pages", True))

    @property
    def follow_subcategories(self) -> bool:
        return bool(self.section("crawl").get("follow_subcategories", False))

    @property
    def follow_pagination(self) -> bool:
        return bool(self.section("crawl").get("follow_pagination", True))

    @property
    def max_pages(self) -> Optional[int]:
        return self.section("crawl").get("max_pages")

    @property
    def max_products(self) -> Optional[int]:
        return self.section("crawl").get("max_products")

    @property
    def db_path(self) -> Path:
        return Path(self.section("storage").get("db_path", "data/runtime/safco.db"))

    @property
    def output_dir(self) -> Path:
        return Path(self.section("output").get("dir", "data"))

    @property
    def output_formats(self) -> list[str]:
        return list(self.section("output").get("formats", ["json", "csv"]))

    @property
    def llm_backend(self) -> str:
        return str(self.section("llm").get("backend", "null"))

    @property
    def min_coverage(self) -> float:
        return float(self.section("extraction").get("min_coverage", 0.55))


def load_settings(config_path: str | os.PathLike = "config.yaml") -> Settings:
    """Load config.yaml and .env. Environment variables win for secrets."""
    load_dotenv()  # pull .env into os.environ if present
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path.resolve()}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    seeds = [Seed(**s) for s in data.get("seeds", [])]
    return Settings(
        site=data.get("site", ""),
        seeds=seeds,
        raw=data,
        config_path=path,
    )
