"""The generic, site-agnostic extractor.

`extract_with_profile(html, profile, url)` applies a profile's field rules to a
page and returns raw records. It knows how to apply rules (jsonld path / css
selector / regex / attr), never what a specific site looks like — so the same
function serves every site once a profile exists for its template.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from bs4 import BeautifulSoup

from .profiles import Profile, _iter_nodes, compute_signature


@dataclass
class ExtractionOutput:
    records: list[dict[str, Any]]
    signature: str
    tier_used: str = "jsonld"
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# JSON-LD helpers
# --------------------------------------------------------------------------- #
def parse_jsonld(soup: BeautifulSoup) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text() or ""
        try:
            data = json.loads(raw)
        except Exception:
            continue
        nodes.extend(_iter_nodes(data))
    return nodes


def _is_type(node: dict[str, Any], wanted: str) -> bool:
    t = node.get("@type")
    if isinstance(t, str):
        return t == wanted
    if isinstance(t, list):
        return wanted in t
    return False


def find_product_nodes(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """All Product nodes (de-duplicated by @id), order preserved."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for node in parse_jsonld(soup):
        if not _is_type(node, "Product"):
            continue
        key = str(node.get("@id") or node.get("sku") or node.get("name") or id(node))
        if key in seen:
            continue
        seen.add(key)
        out.append(node)
    return out


def resolve_jsonld_path(node: dict[str, Any], path: str) -> Any:
    """Resolve a dotted path like 'Product.offers.price' against a Product node.

    A leading 'Product' token is namespace sugar and is dropped. Lists are
    transparently indexed at [0] when a further key is requested, so
    `offers.price` works whether offers is a dict or a list of offers.
    """
    tokens = path.split(".")
    if tokens and tokens[0].lower() == "product":
        tokens = tokens[1:]
    cur: Any = node
    for tok in tokens:
        if isinstance(cur, list):
            cur = cur[0] if cur else None
        if not isinstance(cur, dict):
            return None
        cur = cur.get(tok)
    return cur


# --------------------------------------------------------------------------- #
# CSS / regex helpers
# --------------------------------------------------------------------------- #
def _element_value(el, attr: str | None) -> Optional[str]:
    if attr in (None, "@text", "text"):
        return el.get_text(" ", strip=True) or None
    name = attr[1:] if attr.startswith("@") else attr
    val = el.get(name)
    if isinstance(val, list):
        val = " ".join(val)
    return val


def apply_css_rule(soup: BeautifulSoup, rule: dict[str, Any]) -> Any:
    selector = rule.get("selector")
    if not selector:
        return None
    elements = soup.select(selector)
    if not elements:
        return None

    # inline-label list -> dict (e.g. <li><strong>Brand:</strong> Cranberry</li>).
    # Generic: each matched element holds a label sub-element; the remaining text
    # is the value. `require_colon` keeps only true "Label:" rows.
    if "label" in rule:
        out: dict[str, str] = {}
        label_sel = rule["label"]
        require_colon = rule.get("require_colon", False)
        for el in elements:
            lab = el.select_one(label_sel)
            if not lab:
                continue
            key = lab.get_text(" ", strip=True)
            if require_colon and not key.rstrip().endswith(":"):
                continue
            key = key.rstrip(":").strip()
            full = el.get_text(" ", strip=True)
            value = full[len(lab.get_text(" ", strip=True)):].strip(" :–-")
            if key and value:
                out[key] = value
        return out or None

    # key/value table -> dict (e.g. specifications)
    if "kv" in rule:
        key_sel, val_sel = rule["kv"]
        out: dict[str, str] = {}
        for row in elements:
            k_el = row.select_one(key_sel)
            v_el = row.select_one(val_sel)
            if k_el and v_el:
                k = k_el.get_text(" ", strip=True).rstrip(":")
                v = v_el.get_text(" ", strip=True)
                if k:
                    out[k] = v
        return out or None

    # list of sub-records (e.g. variants, alternatives)
    if "fields" in rule:
        rows = []
        for el in elements:
            rec: dict[str, Any] = {}
            for fname, fsel in rule["fields"].items():
                if fsel.startswith("@"):  # attribute of the matched element itself
                    rec[fname] = _element_value(el, fsel)
                else:
                    sub = el.select_one(fsel)
                    rec[fname] = _element_value(sub, rule.get("attr")) if sub else None
            if any(rec.values()):
                rows.append(rec)
        return rows or None

    # single scalar (text or attribute of first match)
    if rule.get("all"):
        return [_element_value(el, rule.get("attr")) for el in elements]
    return _element_value(elements[0], rule.get("attr"))


def apply_regex_rule(text: str, rule: dict[str, Any]) -> Optional[str]:
    pattern = rule.get("pattern")
    if not pattern:
        return None
    m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    group = rule.get("group", 1)
    try:
        return m.group(group).strip()
    except (IndexError, Exception):
        return None


# --------------------------------------------------------------------------- #
# Main entry point
# --------------------------------------------------------------------------- #
def _resolve_field(rule: dict[str, Any], product_node: dict[str, Any] | None,
                   soup: BeautifulSoup, page_text: str) -> Any:
    source = rule.get("source", "jsonld")
    if source == "jsonld":
        if product_node is None:
            return None
        return resolve_jsonld_path(product_node, rule.get("path", ""))
    if source in ("css", "attr"):
        return apply_css_rule(soup, rule)
    if source == "regex":
        return apply_regex_rule(page_text, rule)
    return None


def extract_with_profile(html: str, profile: Profile, url: str) -> ExtractionOutput:
    soup = BeautifulSoup(html, "lxml")
    signature = compute_signature(html)
    page_text = soup.get_text(" ", strip=True)
    notes: list[str] = []

    product_nodes = find_product_nodes(soup)
    records: list[dict[str, Any]] = []

    if profile.cardinality == "many":
        if product_nodes:
            # Listing page with JSON-LD: one record per Product node in the ItemList.
            for node in product_nodes:
                rec = {"product_url": url}
                for fname, rule in profile.fields.items():
                    rec[fname] = _resolve_field(rule, node, soup, page_text)
                records.append(rec)
        elif profile.item_selector:
            # Non-JSON-LD listing: iterate CSS item containers, resolve css/regex
            # fields RELATIVE TO EACH item (so the extractor stays site-agnostic).
            items = soup.select(profile.item_selector)
            if not items:
                notes.append(f"item_selector '{profile.item_selector}' matched nothing")
            for el in items:
                rec = {"product_url": url}
                item_text = el.get_text(" ", strip=True)
                for fname, rule in profile.fields.items():
                    src = rule.get("source", "css")
                    if src in ("css", "attr"):
                        rec[fname] = apply_css_rule(el, rule)
                    elif src == "regex":
                        rec[fname] = apply_regex_rule(item_text, rule)
                    # jsonld fields are skipped on non-JSON-LD pages
                records.append(rec)
        else:
            notes.append("no Product nodes and no item_selector for 'many' profile")
    else:
        # Detail page: a single record. jsonld fields read from the primary
        # Product node; css/regex fields read from the whole document.
        primary = product_nodes[0] if product_nodes else None
        rec = {"product_url": url}
        for fname, rule in profile.fields.items():
            rec[fname] = _resolve_field(rule, primary, soup, page_text)
        records.append(rec)

    tiers = {r.get("source", "jsonld") for r in profile.fields.values()}
    tier_used = "mixed" if len(tiers) > 1 else (next(iter(tiers)) if tiers else "jsonld")
    return ExtractionOutput(records=records, signature=signature, tier_used=tier_used, notes=notes)
