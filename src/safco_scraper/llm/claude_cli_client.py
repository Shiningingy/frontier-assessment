"""Claude Code CLI backend: shells out to `claude -p`.

This lets the LLM tiers run for free against a Claude Max subscription during
local development (no API key / per-token billing). Requires the `claude` CLI to
be installed and logged in. Selected via config: llm.backend = claude_cli.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Optional

from .base import LLMResponse


class ClaudeCLIClient:
    def __init__(self, default_model: str = "sonnet", binary: str = "claude", timeout: int = 180) -> None:
        if shutil.which(binary) is None:
            raise RuntimeError(
                f"`{binary}` CLI not found on PATH. Install Claude Code and log in, "
                "or set llm.backend to 'anthropic'."
            )
        self.binary = binary
        self.default_model = default_model
        self.timeout = timeout

    def complete(self, prompt: str, *, system: Optional[str] = None,
                 max_tokens: int = 2048, model: Optional[str] = None) -> LLMResponse:
        model = model or self.default_model
        # The prompt is fed via STDIN so no user content (with $, &, quotes, etc.)
        # ever touches the command line — only safe flags do. System instructions
        # are prepended to the stdin prompt.
        full = prompt if not system else f"{system}\n\n---\n\n{prompt}"
        args = [self.binary, "-p", "--output-format", "json", "--model", model]
        kwargs = dict(capture_output=True, text=True, timeout=self.timeout,
                      input=full, encoding="utf-8", errors="replace")
        if os.name == "nt":
            # `claude` is a .cmd shim on Windows; run via the shell. Only safe flags
            # are on the command line (the prompt is on stdin).
            proc = subprocess.run(" ".join(args), shell=True, **kwargs)
        else:
            proc = subprocess.run(args, **kwargs)
        if proc.returncode != 0:
            raise RuntimeError(f"claude CLI failed ({proc.returncode}): {(proc.stderr or '')[:400]}")
        try:
            payload = json.loads(proc.stdout)
            text = payload.get("result", proc.stdout)
            used_model = payload.get("model", model)
        except json.JSONDecodeError:
            text, used_model = proc.stdout, model
        return LLMResponse(text=text, model=used_model, backend="claude_cli")
