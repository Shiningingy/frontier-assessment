"""Null backend: no LLM. Present so code paths that optionally use an LLM can be
constructed in deterministic-only mode without special-casing None everywhere.
Any actual call raises, which callers treat as "LLM unavailable".
"""
from __future__ import annotations

from typing import Optional

from .base import LLMResponse


class NullClient:
    default_model = "none"

    def complete(self, prompt: str, *, system: Optional[str] = None,
                 max_tokens: int = 2048, model: Optional[str] = None) -> LLMResponse:
        raise RuntimeError("No LLM backend configured (llm.backend = null).")
