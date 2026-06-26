"""Profile-author agent.

Given a page from an unseen template, it inspects the page the system actually
fetched (JSON-LD + HTML structure) and writes a reusable extraction profile, then
VALIDATES that profile by re-running the generic extractor on the same page. Only
a profile that actually produces grounded data is cached. This is how the system
adapts to new sites/templates without hand-written, per-site code — and how it
repairs a profile when a site changes.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from ..llm.base import LLMClient, extract_json
from ..llm.prompts import PROFILE_AUTHOR_SYSTEM, PROFILE_AUTHOR_USER
from ..tools.extract import extract_with_profile
from ..tools.pageview import jsonld_sample, structure_hints
from ..tools.profiles import Profile, ProfileStore, compute_signature, domain_of
from ..tools.validate import normalize_record, record_coverage, ValidationError
from ..utils.logging import log_event


def _infer_template(url: str) -> str:
    path = urlparse(url).path
    if "/product/" in path:
        return "product-detail"
    if "/catalog/" in path:
        return "catalog-listing"
    return "generic"


class ProfileAuthorAgent:
    def __init__(self, client: LLMClient, settings, logger: logging.Logger) -> None:
        self.client = client
        self.settings = settings
        self.logger = logger
        self.store = ProfileStore("profiles")
        self.model = settings.section("llm").get("extract_model")

    def author(self, html: str, url: str, template: Optional[str] = None) -> Profile:
        types, sample = jsonld_sample(html)
        hints = structure_hints(html)
        prompt = PROFILE_AUTHOR_USER.format(
            url=url, jsonld_types=types or "(none)", jsonld_sample=sample, html_hints=hints or "(none)"
        )
        resp = self.client.complete(prompt, system=PROFILE_AUTHOR_SYSTEM, max_tokens=1500, model=self.model)
        spec = extract_json(resp.text)
        if not isinstance(spec, dict) or "fields" not in spec:
            raise ValueError("profile-author did not return a valid profile object")

        domain = domain_of(url)
        profile = Profile(
            site=domain,
            template=template or spec.get("template") or _infer_template(url),
            cardinality=spec.get("cardinality", "one"),
            match=spec.get("match") or {"url_glob": urlparse(url).path},
            fields=spec["fields"],
            authored_by="profile-author-agent",
        )

        # VALIDATE: run the new profile on the same page; only cache if it yields
        # grounded, non-trivial data.
        out = extract_with_profile(html, profile, url)
        coverage = 0.0
        valid_records = 0
        for raw in out.records:
            try:
                p = normalize_record(raw, page_url=url, extraction_tier=out.tier_used)
            except ValidationError:
                continue
            coverage = max(coverage, record_coverage(p))
            valid_records += 1

        profile.touch(compute_signature(html))
        profile.field_confidence = {"_self_validated_coverage": round(coverage, 3)}
        path = self.store.save(profile)
        log_event(self.logger, "profile_author.cached", url=url, template=profile.template,
                  path=str(path), valid_records=valid_records, coverage=round(coverage, 3))
        if valid_records == 0:
            log_event(self.logger, "profile_author.warning", level=logging.WARNING,
                      url=url, msg="authored profile produced no valid records")
        return profile
