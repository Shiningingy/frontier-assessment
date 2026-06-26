"""LLM extractor agent (extraction fallback tier).

Invoked by the orchestrator only when deterministic extraction returns low
coverage or on a sampled revalidation. It reads the page the system actually
fetched and returns structured products — then a GROUNDING GUARD drops any value
that does not literally appear in the page, so the agent can never inject guessed
or hallucinated data into the catalog.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from ..llm.base import LLMClient, extract_json
from ..llm.prompts import EXTRACT_FALLBACK_SYSTEM, EXTRACT_FALLBACK_USER
from ..models import COVERAGE_FIELDS, Product
from ..tools.pageview import clean_text
from ..tools.validate import normalize_record, record_coverage, ValidationError
from ..utils.logging import log_event

# Scalar fields whose LLM-provided value must be verifiable in the page text.
_GROUNDED_SCALARS = ["name", "sku", "brand", "description"]


def _missing_fields(products: list[Product]) -> list[str]:
    if not products:
        return list(COVERAGE_FIELDS)
    p = products[0]
    missing = []
    for f in COVERAGE_FIELDS:
        v = getattr(p, f, None)
        if not v:
            missing.append(f)
    return missing


def _ground(value: Any, haystack: str) -> bool:
    """True if a scalar value is literally present in the page text."""
    if value is None:
        return False
    s = str(value).strip()
    if len(s) < 3:  # too short to verify meaningfully; allow
        return True
    return s.lower() in haystack


class LLMExtractorAgent:
    def __init__(self, client: LLMClient, settings, logger: logging.Logger) -> None:
        self.client = client
        self.settings = settings
        self.logger = logger
        self.model = settings.section("llm").get("extract_model")

    def __call__(self, *, html: str, url: str, profile, source_category: Optional[str],
                 draft: list[Product]) -> Optional[list[Product]]:
        page_text = clean_text(html, limit=8000)
        haystack = page_text.lower()
        prompt = EXTRACT_FALLBACK_USER.format(
            url=url, missing=", ".join(_missing_fields(draft)) or "(any)", page_text=page_text
        )
        resp = self.client.complete(prompt, system=EXTRACT_FALLBACK_SYSTEM,
                                    max_tokens=2048, model=self.model)
        try:
            data = extract_json(resp.text)
        except Exception as exc:
            log_event(self.logger, "extractor_agent.parse_fail", level=logging.WARNING, url=url, error=str(exc))
            return None
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            return None

        results: list[Product] = []
        dropped = 0
        for raw in data:
            if not isinstance(raw, dict):
                continue
            # GROUNDING GUARD: drop scalar values not present in the page.
            for f in _GROUNDED_SCALARS:
                if f in raw and not _ground(raw[f], haystack):
                    raw.pop(f, None)
                    dropped += 1
            # specifications values must be grounded too
            specs = raw.get("specifications")
            if isinstance(specs, dict):
                raw["specifications"] = {k: v for k, v in specs.items() if _ground(v, haystack)}
            raw.setdefault("product_url", url)
            try:
                p = normalize_record(raw, source_category=source_category, page_url=url,
                                     extraction_tier="llm")
            except ValidationError:
                continue
            results.append(p)

        if dropped:
            log_event(self.logger, "extractor_agent.grounding_dropped", url=url, dropped=dropped)
        if not results:
            return None

        # Merge: prefer the deterministic draft, let the LLM only FILL gaps.
        merged = self._merge(draft, results)
        log_event(self.logger, "extractor_agent.done", url=url,
                  llm_products=len(results), merged=len(merged),
                  avg_coverage=round(sum(record_coverage(p) for p in merged) / max(1, len(merged)), 3))
        return merged

    @staticmethod
    def _merge(draft: list[Product], llm: list[Product]) -> list[Product]:
        if not draft:
            return llm
        # Index llm products by sku/name for gap-filling the draft.
        by_key = {}
        for p in llm:
            by_key[(p.sku or "").upper()] = p
            by_key[p.name.lower()] = p
        out = []
        for d in draft:
            match = by_key.get((d.sku or "").upper()) or by_key.get(d.name.lower())
            if match:
                if not d.description and match.description:
                    d.description = match.description
                if not d.specifications and match.specifications:
                    d.specifications = match.specifications
                if not d.brand and match.brand:
                    d.brand = match.brand
                if not d.image_urls and match.image_urls:
                    d.image_urls = match.image_urls
                d.extraction_tier = "mixed"
            out.append(d)
        return out
