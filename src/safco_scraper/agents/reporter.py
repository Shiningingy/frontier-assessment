"""Reporter agent: interactive Q&A over the scraped catalog.

Strictly grounded: it loads the catalog rows from the database and answers ONLY
from those rows (the system prompt forbids outside knowledge / guessing). For
small catalogs the rows are passed as context; the same agent in production would
generate SQL against the DB instead (documented in the README).
"""
from __future__ import annotations

import json
import logging

from ..llm.base import LLMClient
from ..llm.prompts import REPORTER_SYSTEM, REPORTER_USER
from ..tools.query import catalog_json, deterministic_summary
from ..tools.store import Store


class ReporterAgent:
    def __init__(self, client: LLMClient, settings, logger: logging.Logger) -> None:
        self.client = client
        self.settings = settings
        self.logger = logger
        self.model = settings.section("llm").get("classify_model") or settings.section("llm").get("extract_model")

    def answer(self, question: str) -> str:
        # Open the DB in the calling thread — SQLite connections are thread-bound, and
        # this agent may be constructed once (e.g. the conductor) but called from a
        # different worker thread (e.g. the Gradio UI).
        store = Store(self.settings.db_path)
        try:
            n, catalog = catalog_json(store)
            if n == 0:
                return "The catalog is empty. Run `safco crawl` first."
            prompt = REPORTER_USER.format(n=n, catalog=catalog, question=question)
            resp = self.client.complete(prompt, system=REPORTER_SYSTEM, max_tokens=1024, model=self.model)
            return resp.text.strip()
        finally:
            store.close()

    def repl(self) -> None:
        store = Store(self.settings.db_path)
        n = store.product_count()
        print(f"Reporter ready — {n} products in the catalog. Ask a question (or 'summary', 'quit').\n")
        while True:
            try:
                q = input("catalog> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not q:
                continue
            if q.lower() in {"quit", "exit", "q"}:
                break
            if q.lower() in {"summary", "stats"}:
                print(json.dumps(deterministic_summary(store), indent=2))
                continue
            try:
                print("\n" + self.answer(q) + "\n")
            except Exception as exc:
                print(f"[error] {exc}\n")
        store.close()
