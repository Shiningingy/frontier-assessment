"""Extraction profiles + the profile cache.

A *profile* is a JSON document that tells the generic extractor HOW to pull each
field from a given site template (field -> rule). Profiles are site-agnostic data,
not code: the extractor knows how to apply rules, never what a specific site looks
like. The profile-author agent writes profiles for unseen templates; the cache
persists them so future runs are deterministic and cheap.

Each profile records a `template_signature` (a cheap structural fingerprint) plus
`last_validated`/`ttl_hours`, which together drive cache invalidation: on every
page we recompute the signature in microseconds and decide whether to trust the
cached tiers or re-enter authoring. See docs/PROFILES.md.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup

# Rule sources, cheapest -> most expensive. The extractor starts a field at the
# tier recorded in its rule; this ordering also defines "downgrade/upgrade".
TIER_ORDER = ["jsonld", "css", "regex", "attr", "llm"]


def domain_of(url: str) -> str:
    host = (urlparse(url).netloc or url).lower()
    return host[4:] if host.startswith("www.") else host


# Page-chrome landmarks that are template-invariant (same across all pages of a
# site), used as a coarse structural fingerprint alongside the JSON-LD @type set.
_LANDMARK_TAGS = ["html", "head", "body", "header", "nav", "main", "footer", "form"]


def compute_signature(html: str) -> str:
    """Cheap *structural* fingerprint of a page template.

    Built from features that depend on the template, not the content:
      - the set of schema.org @types present in JSON-LD,
      - the number of JSON-LD blocks,
      - which page-chrome landmark tags are present.
    Two pages of the same template hash equal regardless of how much product copy
    they contain; the hash flips when the structure changes (e.g. a site drops its
    anti-scrape meta and JSON-LD appears, or a layout redesign) -> revalidation.
    """
    soup = BeautifulSoup(html, "lxml")

    # Only the TOP-LEVEL entity @types of each block (Product, BreadcrumbList,
    # ItemList...). Nested/optional types (Offer, Brand, AggregateRating, Review)
    # are content-dependent and would make the signature wobble, so we skip them.
    jsonld_types: set[str] = set()
    blocks = soup.find_all("script", attrs={"type": "application/ld+json"})
    for tag in blocks:
        try:
            data = json.loads(tag.string or tag.get_text() or "")
        except Exception:
            continue
        top_nodes = data if isinstance(data, list) else [data]
        for node in top_nodes:
            if not isinstance(node, dict):
                continue
            t = node.get("@type")
            if isinstance(t, str):
                jsonld_types.add(t)
            elif isinstance(t, list):
                jsonld_types.update(x for x in t if isinstance(x, str))

    landmarks = [t for t in _LANDMARK_TAGS if soup.find(t) is not None]

    basis = json.dumps(
        {"types": sorted(jsonld_types), "blocks": len(blocks), "landmarks": landmarks},
        sort_keys=True,
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def _iter_nodes(data: Any):
    """Yield every dict node in an arbitrarily nested JSON-LD structure."""
    if isinstance(data, dict):
        yield data
        for v in data.values():
            yield from _iter_nodes(v)
    elif isinstance(data, list):
        for v in data:
            yield from _iter_nodes(v)


@dataclass
class Profile:
    site: str
    template: str
    fields: dict[str, dict[str, Any]]
    cardinality: str = "one"  # "one" detail page | "many" listing page
    match: dict[str, Any] = field(default_factory=dict)
    template_signature: Optional[str] = None
    last_validated: Optional[str] = None
    ttl_hours: int = 168
    field_confidence: dict[str, float] = field(default_factory=dict)
    version: int = 1
    authored_by: str = "hand"  # hand | profile-author-agent

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Profile":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})

    def to_dict(self) -> dict[str, Any]:
        return {
            "site": self.site,
            "template": self.template,
            "cardinality": self.cardinality,
            "match": self.match,
            "fields": self.fields,
            "template_signature": self.template_signature,
            "last_validated": self.last_validated,
            "ttl_hours": self.ttl_hours,
            "field_confidence": self.field_confidence,
            "version": self.version,
            "authored_by": self.authored_by,
        }

    def matches_url(self, url: str) -> bool:
        glob = self.match.get("url_glob")
        if not glob:
            return True
        path = urlparse(url).path
        return fnmatch.fnmatch(path, glob)

    def is_expired(self) -> bool:
        if not self.last_validated:
            return True
        try:
            ts = datetime.fromisoformat(self.last_validated)
        except ValueError:
            return True
        return datetime.now(timezone.utc) - ts > timedelta(hours=self.ttl_hours)

    def touch(self, signature: str | None = None) -> None:
        self.last_validated = datetime.now(timezone.utc).isoformat()
        if signature:
            self.template_signature = signature


class ProfileStore:
    """Filesystem-backed cache of profiles, keyed by domain + template."""

    def __init__(self, root: str | Path = "profiles") -> None:
        self.root = Path(root)

    def _path(self, domain: str, template: str) -> Path:
        return self.root / domain / f"{template}.json"

    def get(self, domain: str, template: str) -> Optional[Profile]:
        p = self._path(domain, template)
        if not p.exists():
            return None
        return Profile.from_dict(json.loads(p.read_text(encoding="utf-8")))

    def list_for_domain(self, domain: str) -> list[Profile]:
        d = self.root / domain
        if not d.exists():
            return []
        return [Profile.from_dict(json.loads(f.read_text(encoding="utf-8"))) for f in d.glob("*.json")]

    def find_for_url(self, url: str) -> Optional[Profile]:
        """Best-effort match by URL glob among cached profiles for the host."""
        domain = domain_of(url)
        candidates = [p for p in self.list_for_domain(domain) if p.matches_url(url)]
        if not candidates:
            return None
        # Prefer the most specific glob (longest pattern).
        candidates.sort(key=lambda p: len(p.match.get("url_glob", "")), reverse=True)
        return candidates[0]

    def save(self, profile: Profile) -> Path:
        domain = domain_of(profile.site) if "//" in profile.site or "." in profile.site else profile.site
        path = self._path(domain, profile.template)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(profile.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return path
