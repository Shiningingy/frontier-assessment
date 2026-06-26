"""Helpers that turn raw HTML into compact views for the LLM agents: cleaned
page text, a JSON-LD sample, and structural hints. Keeping pages small controls
token cost on the LLM tiers.
"""
from __future__ import annotations

import json

from bs4 import BeautifulSoup

from .extract import parse_jsonld


def clean_text(html: str, limit: int = 6000) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg", "header", "footer", "nav"]):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    # collapse blank lines
    lines = [ln for ln in (l.strip() for l in text.splitlines()) if ln]
    out = "\n".join(lines)
    return out[:limit]


def jsonld_sample(html: str, limit: int = 3000) -> tuple[list[str], str]:
    soup = BeautifulSoup(html, "lxml")
    nodes = parse_jsonld(soup)
    types = sorted({n.get("@type") for n in nodes if isinstance(n.get("@type"), str)})
    sample = json.dumps(nodes[:3], indent=1, ensure_ascii=False)[:limit] if nodes else "(none)"
    return types, sample


def structure_hints(html: str, limit: int = 2500) -> str:
    """A skeleton of headings + elements carrying class/id, to hint selectors."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    hints: list[str] = []
    for el in soup.find_all(["h1", "h2", "h3", "table", "ul", "dl"]):
        cls = ".".join(el.get("class", [])[:3])
        sel = f"{el.name}" + (f".{cls}" if cls else "")
        txt = el.get_text(" ", strip=True)[:60]
        hints.append(f"{sel} :: {txt}")
        if len("\n".join(hints)) > limit:
            break
    return "\n".join(hints)[:limit]
