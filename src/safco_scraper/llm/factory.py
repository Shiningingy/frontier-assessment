"""Build an LLM client from config."""
from __future__ import annotations

import logging

from ..config import Settings
from .base import LLMClient


def build_llm_client(settings: Settings, logger: logging.Logger) -> LLMClient:
    backend = settings.llm_backend
    lcfg = settings.section("llm")
    extract_model = lcfg.get("extract_model", "claude-sonnet-4-6")

    if backend == "anthropic":
        from .anthropic_client import AnthropicClient

        logger.info("LLM backend: anthropic")
        return AnthropicClient(default_model=extract_model)
    if backend == "claude_cli":
        from .claude_cli_client import ClaudeCLIClient

        logger.info("LLM backend: claude_cli (Claude Code / Max)")
        # The CLI takes short model aliases; map our config model if it's a full id.
        alias = "sonnet" if "sonnet" in extract_model else ("haiku" if "haiku" in extract_model else "opus")
        return ClaudeCLIClient(default_model=alias)
    from .null_client import NullClient

    logger.info("LLM backend: null (deterministic only)")
    return NullClient()
