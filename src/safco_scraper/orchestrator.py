"""The orchestrator: the deterministic crawl pipeline that ties the tools together.

Flow:  seed categories -> (navigator) discover products + extract listing records
       -> enqueue product detail pages -> (extractor) enrich from detail pages
       -> (validator) normalize + coverage-gate -> (store) idempotent upsert
       -> export + run summary.

It implements the per-page validation loop from the design: compute a cheap
template signature, compare to the cached profile, extract, validate, and gate on
coverage. When coverage is below threshold (or the signature drifted) and an LLM
backend is configured, it hands off to the profile-author/extractor agent;
otherwise it records the gap in the run metrics (deterministic-only mode).
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from .config import Settings
from .fetcher.base import FetchResult
from .models import Product
from .tools.export import export_all
from .tools.extract import extract_with_profile
from .tools.navigate import discover_listing
from .tools.profiles import Profile, ProfileStore, compute_signature, domain_of
from .tools.store import Store
from .tools.validate import normalize_record, record_coverage, ValidationError
from .utils.logging import log_event


@dataclass
class RunMetrics:
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    pages_fetched: int = 0
    categories_done: int = 0
    products_found: int = 0
    products_stored: int = 0
    validation_failures: int = 0
    low_coverage_records: int = 0
    signature_drifts: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    llm_invocations: int = 0
    dead_letters: int = 0
    coverage_samples: list[float] = field(default_factory=list)
    # Field coverage is computed from the final persisted catalog (post-enrichment)
    # at export time, so it reflects what was actually stored, not in-flight passes.
    field_coverage: dict[str, float] = field(default_factory=dict)

    def record_coverage(self, product: Product, cov: float) -> None:
        self.coverage_samples.append(cov)

    def summary(self) -> dict[str, Any]:
        n = max(1, len(self.coverage_samples))
        avg_cov = sum(self.coverage_samples) / n if self.coverage_samples else 0.0
        return {
            "started_at": self.started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "pages_fetched": self.pages_fetched,
            "categories_done": self.categories_done,
            "products_found": self.products_found,
            "products_stored": self.products_stored,
            "avg_coverage": round(avg_cov, 3),
            "validation_failures": self.validation_failures,
            "low_coverage_records": self.low_coverage_records,
            "signature_drifts": self.signature_drifts,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "llm_invocations": self.llm_invocations,
            "dead_letters": self.dead_letters,
            "field_coverage": self.field_coverage,
        }


class Orchestrator:
    def __init__(
        self,
        settings: Settings,
        fetcher,
        logger: logging.Logger,
        llm_extractor: Optional[Any] = None,
    ) -> None:
        self.settings = settings
        self.fetcher = fetcher
        self.logger = logger
        self.llm_extractor = llm_extractor  # ExtractorAgent-like callable or None
        self.store = Store(settings.db_path)
        self.profiles = ProfileStore("profiles")
        self.metrics = RunMetrics()
        self._min_cov = settings.min_coverage
        self._revalidate_rate = float(settings.section("extraction").get("revalidation_sample_rate", 0.05))

    # ------------------------------------------------------------------ #
    async def run(self, fresh: bool = False) -> RunMetrics:
        if fresh:
            self.store.reset_frontier()
        for seed in self.settings.seeds:
            self.store.enqueue(seed.url, "category", seed.name)

        await self._process_categories()
        if self.settings.follow_product_pages:
            await self._process_products()

        self._export()
        log_event(self.logger, "run.summary", **self.metrics.summary())
        return self.metrics

    # ------------------------------------------------------------------ #
    async def _fetch(self, url: str) -> Optional[FetchResult]:
        try:
            res = await self.fetcher.fetch(url)
            self.metrics.pages_fetched += 1
            return res
        except Exception as exc:  # robots, transport, status after retries
            row = next((r for r in self.store.pending() if r["url"] == url), None)
            attempts = (row["attempts"] if row else 0) + 1
            self.store.dead_letter(url, f"{type(exc).__name__}: {exc}", attempts)
            self.metrics.dead_letters += 1
            log_event(self.logger, "fetch.dead_letter", level=logging.ERROR, url=url, error=str(exc))
            return None

    def _profile_for(self, url: str, template: str) -> Optional[Profile]:
        domain = domain_of(self.settings.site)
        prof = self.profiles.get(domain, template)
        if prof:
            self.metrics.cache_hits += 1
        else:
            self.metrics.cache_misses += 1
        return prof

    def _check_signature(self, profile: Profile, signature: str, url: str) -> None:
        """Drift detection + cache touch. On drift, flag (and, with an LLM, the
        caller will re-author). On first sight, pin the signature."""
        if profile.template_signature is None:
            profile.touch(signature)
            self.profiles.save(profile)
        elif profile.template_signature != signature:
            self.metrics.signature_drifts += 1
            log_event(
                self.logger, "profile.signature_drift", level=logging.WARNING,
                url=url, template=profile.template,
                cached=profile.template_signature, observed=signature,
            )

    # ------------------------------------------------------------------ #
    async def _process_categories(self) -> None:
        pending = self.store.pending("category")
        for row in pending:
            url, source_category = row["url"], row["source_category"]
            res = await self._fetch(url)
            if res is None:
                continue

            profile = self._profile_for(url, "catalog-listing")
            if profile is None:
                log_event(self.logger, "profile.missing", level=logging.ERROR, template="catalog-listing")
                self.store.mark(url, "failed")
                continue

            signature = compute_signature(res.html)
            self._check_signature(profile, signature, url)

            # Extract listing records (full data lives on the listing page).
            products = self._extract_and_validate(res.html, profile, url, source_category)
            for p in products:
                self.store.upsert_product(p)
                self.metrics.products_stored += 1

            # Discover detail pages + subcategories for the next stage.
            disc = discover_listing(res.html, url)
            self.metrics.products_found += len(disc.product_urls)
            for purl in disc.product_urls:
                self.store.enqueue(purl, "product", source_category)
            if self.settings.follow_subcategories:
                for suburl, name in disc.subcategory_urls:
                    self.store.enqueue(suburl, "category", name or source_category)

            self.store.mark(url, "done")
            self.metrics.categories_done += 1
            log_event(self.logger, "category.done", url=url,
                      products=len(products), discovered=len(disc.product_urls))

    async def _process_products(self) -> None:
        pending = self.store.pending("product")
        max_products = self.settings.max_products
        if max_products:
            pending = pending[:max_products]

        for row in pending:
            url, source_category = row["url"], row["source_category"]
            res = await self._fetch(url)
            if res is None:
                continue
            profile = self._profile_for(url, "product-detail")
            if profile is None:
                self.store.mark(url, "done")
                continue
            signature = compute_signature(res.html)
            self._check_signature(profile, signature, url)

            products = self._extract_and_validate(res.html, profile, url, source_category,
                                                  extraction_tier="mixed", count_metrics=False)
            for p in products:
                # Enrich the listing record with detail-only fields.
                self.store.enrich_product(
                    p.dedup_key,
                    specifications=p.specifications,
                    alternatives=[a.model_dump() for a in p.alternatives],
                    description=p.description,
                    image_urls=p.image_urls,
                )
            self.store.mark(url, "done")
            log_event(self.logger, "product.done", url=url)

    # ------------------------------------------------------------------ #
    def _extract_and_validate(
        self, html: str, profile: Profile, url: str,
        source_category: Optional[str], extraction_tier: Optional[str] = None,
        count_metrics: bool = True,
    ) -> list[Product]:
        out = extract_with_profile(html, profile, url)
        tier = extraction_tier or out.tier_used
        products: list[Product] = []
        coverages: list[float] = []
        for raw in out.records:
            try:
                p = normalize_record(raw, source_category=source_category,
                                     page_url=url, extraction_tier=tier)
            except ValidationError as exc:
                self.metrics.validation_failures += 1
                log_event(self.logger, "validate.fail", level=logging.WARNING, url=url, error=str(exc))
                continue
            cov = record_coverage(p)
            coverages.append(cov)
            if count_metrics:
                self.metrics.record_coverage(p, cov)
            products.append(p)

        avg_cov = sum(coverages) / len(coverages) if coverages else 0.0
        revalidate = random.random() < self._revalidate_rate
        if (avg_cov < self._min_cov or revalidate) and self.llm_extractor is not None:
            # Hand off to the LLM-backed extractor/profile-author agent.
            self.metrics.llm_invocations += 1
            log_event(self.logger, "extract.llm_fallback", url=url,
                      avg_coverage=round(avg_cov, 3), reason="low_coverage" if avg_cov < self._min_cov else "sampled")
            try:
                repaired = self.llm_extractor(html=html, url=url, profile=profile,
                                              source_category=source_category, draft=products)
                if repaired:
                    products = repaired
            except Exception as exc:  # never let the agent break the crawl
                log_event(self.logger, "extract.llm_error", level=logging.ERROR, url=url, error=str(exc))
        elif avg_cov < self._min_cov:
            self.metrics.low_coverage_records += len(products)
            log_event(self.logger, "extract.low_coverage", level=logging.WARNING,
                      url=url, avg_coverage=round(avg_cov, 3), threshold=self._min_cov)
        return products

    # ------------------------------------------------------------------ #
    def _compute_field_coverage(self, rows: list[dict[str, Any]]) -> dict[str, float]:
        """Per-field population rate across the final persisted catalog."""
        if not rows:
            return {}
        fields = ["name", "sku", "brand", "price", "availability", "description",
                  "image_urls", "category_path", "specifications", "rating", "alternatives"]
        empty_json = {"[]", "{}", "", None}
        counts = {f: 0 for f in fields}
        for r in rows:
            for f in fields:
                val = r.get(f)
                if isinstance(val, str) and val.strip() in empty_json:
                    continue
                if val in (None, "", "unknown"):
                    continue
                counts[f] += 1
        return {f: round(counts[f] / len(rows), 3) for f in fields}

    def _export(self) -> None:
        rows = self.store.all_products()
        if not rows:
            return
        self.metrics.field_coverage = self._compute_field_coverage(rows)
        out_dir = self.settings.output_dir
        written = export_all(rows, out_dir, self.settings.output_formats)
        # Persist the run summary next to the data for observability.
        (out_dir).mkdir(parents=True, exist_ok=True)
        (out_dir / "run_summary.json").write_text(
            json.dumps(self.metrics.summary(), indent=2), encoding="utf-8"
        )
        log_event(self.logger, "export.done", files=[str(p) for p in written],
                  products=len(rows))
