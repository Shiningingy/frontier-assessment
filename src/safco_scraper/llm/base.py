"""LLM client abstraction.

Backends are pluggable so the same agent code runs against:
  - the Anthropic API (tester drops in ANTHROPIC_API_KEY),
  - the Claude Code CLI (`claude -p`, uses a Max subscription for free local tests),
  - a Null client (no LLM; deterministic-only).

All agents depend only on this interface, never on a concrete backend.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Optional, Protocol


@dataclass
class LLMResponse:
    text: str
    model: str
    backend: str


class LLMClient(Protocol):
    def complete(self, prompt: str, *, system: Optional[str] = None,
                 max_tokens: int = 2048, model: Optional[str] = None) -> LLMResponse: ...


_JSON_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def extract_json(text: str) -> Any:
    """Best-effort: pull the first JSON object/array out of an LLM response."""
    text = text.strip()
    m = _JSON_BLOCK.search(text)
    if m:
        text = m.group(1).strip()
    # find first { or [ and balance to the matching close
    start = next((i for i, c in enumerate(text) if c in "{["), None)
    if start is None:
        raise ValueError("no JSON found in LLM response")
    open_c = text[start]
    close_c = "}" if open_c == "{" else "]"
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == open_c:
                depth += 1
            elif c == close_c:
                depth -= 1
                if depth == 0:
                    return json.loads(text[start:i + 1])
    return json.loads(text[start:])  # let json raise a useful error
