"""Anthropic API backend. Uses ANTHROPIC_API_KEY from the environment / .env."""
from __future__ import annotations

import os
from typing import Optional

from .base import LLMResponse


class AnthropicClient:
    def __init__(self, default_model: str = "claude-sonnet-4-6", api_key: Optional[str] = None) -> None:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("anthropic not installed. Run: pip install -e .[llm]") from exc
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY not set (put it in .env or the environment).")
        self._client = anthropic.Anthropic(api_key=key)
        self.default_model = default_model

    def complete(self, prompt: str, *, system: Optional[str] = None,
                 max_tokens: int = 2048, model: Optional[str] = None) -> LLMResponse:
        model = model or self.default_model
        kwargs = {"model": model, "max_tokens": max_tokens,
                  "messages": [{"role": "user", "content": prompt}]}
        if system:
            kwargs["system"] = system
        msg = self._client.messages.create(**kwargs)
        text = "".join(block.text for block in msg.content if getattr(block, "type", None) == "text")
        return LLMResponse(text=text, model=model, backend="anthropic")
