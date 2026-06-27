"""Conductor agent — the conversational entry point.

A backend-agnostic ReAct-style tool-use loop built on the shared `LLMClient`
(text + `extract_json`), so it runs on the Anthropic API OR the Claude CLI / Max
with no SDK lock-in. The conductor interprets natural language and drives the real
workflow tools (discover, ensure_profile, crawl, query_catalog, summary, export).

Grounding: the conductor narrates and answers ONLY from tool outputs (which come
from fetched pages and the database). It never invents products, prices or counts —
the tools are the single source of truth.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from ..config import Seed, Settings
from ..fetcher.factory import build_fetcher
from ..llm.base import LLMClient, extract_json
from ..tools.export import export_all
from ..tools.navigate import discover_listing
from ..tools.profiles import ProfileStore, compute_signature, domain_of
from ..tools.query import deterministic_summary
from ..tools.store import Store
from ..utils.logging import log_event
from .extractor import LLMExtractorAgent
from .profile_author import ProfileAuthorAgent
from .reporter import ReporterAgent

MAX_STEPS = 8

SYSTEM = """\
You are the conductor of a web catalog scraping tool. You turn a user's natural
language into actions by calling tools, then report results.

You can ONLY act through tools. On each turn respond with EXACTLY ONE JSON object,
nothing else, in one of two forms:
  {"tool": "<name>", "args": { ... }}        # to call a tool
  {"final": "<message to the user>"}          # when you are done

Available tools:
- discover {"url"}            -> inspect a page: type, product/subcategory counts, whether a profile is cached.
- ensure_profile {"url"}      -> make sure an extraction profile exists for this template (auto-authors one if new).
- crawl {"seed_urls": [..], "follow_product_pages"?: bool, "max_products"?: int}
                              -> crawl category URLs and store products. Returns a run summary.
- query_catalog {"question"}  -> answer a question strictly from the stored catalog.
- summary {}                  -> deterministic catalog summary (counts, price range, brands).
- export {"format": "json|csv|xlsx"} -> write the catalog to a file.
- list_catalog_sites {}       -> what categories/sites are already stored.

GROUNDING RULES (absolute):
- Base every statement on tool outputs only. Never invent products, prices, SKUs or counts.
- If you need data, call a tool; do not guess. If a tool returns nothing useful, say so.
- For a new site, ensure_profile may spend one LLM call to learn it; that is expected.
- Keep going (call tools) until you can fully answer, then emit {"final": ...}.
"""


class ConductorAgent:
    def __init__(self, client: LLMClient, settings: Settings, logger: logging.Logger) -> None:
        self.client = client
        self.settings = settings
        self.logger = logger
        self.model = settings.section("llm").get("extract_model")
        self.profiles = ProfileStore("profiles")
        self.profile_author = ProfileAuthorAgent(client, settings, logger)
        self.reporter = ReporterAgent(client, settings, logger)
        self._fetcher = None

    # ------------------------------------------------------------------ #
    # Public entry: run one user turn, returning (final_text, step_log).
    # ------------------------------------------------------------------ #
    def run_turn(self, message: str, history: Optional[list] = None) -> tuple[str, list[str]]:
        return asyncio.run(self._arun_turn(message, history or []))

    async def _arun_turn(self, message: str, history: list) -> tuple[str, list[str]]:
        transcript = self._render_history(history)
        transcript.append(f"User: {message}")
        steps: list[str] = []

        for _ in range(MAX_STEPS):
            prompt = "\n".join(transcript) + "\n\nRespond with one JSON object now."
            resp = self.client.complete(prompt, system=SYSTEM, max_tokens=1200, model=self.model)
            try:
                action = extract_json(resp.text)
            except Exception:
                # Treat an unparseable response as a direct final message.
                await self._aclose()
                return resp.text.strip(), steps

            if isinstance(action, dict) and "final" in action:
                await self._aclose()
                return str(action["final"]).strip(), steps

            if not (isinstance(action, dict) and "tool" in action):
                await self._aclose()
                return resp.text.strip(), steps

            tool = action.get("tool")
            args = action.get("args") or {}
            steps.append(f"🔧 {tool}({json.dumps(args, ensure_ascii=False)[:120]})")
            log_event(self.logger, "conductor.tool_call", tool=tool, args=args)
            observation = await self._dispatch(tool, args)
            obs_text = json.dumps(observation, ensure_ascii=False)
            transcript.append(f'Assistant: {{"tool": "{tool}", "args": {json.dumps(args, ensure_ascii=False)}}}')
            transcript.append(f"ToolResult({tool}): {obs_text[:1800]}")

        await self._aclose()
        return ("I reached the step limit before finishing. Here is what I gathered:\n"
                + "\n".join(steps)), steps

    # ------------------------------------------------------------------ #
    @staticmethod
    def _render_history(history: list) -> list[str]:
        out: list[str] = []
        for turn in history[-6:]:
            # Accept (user, assistant) tuples or {role, content} dicts.
            if isinstance(turn, (list, tuple)) and len(turn) == 2:
                out.append(f"User: {turn[0]}")
                out.append(f"Assistant: {{\"final\": {json.dumps(turn[1])}}}")
            elif isinstance(turn, dict):
                role = turn.get("role", "user").capitalize()
                out.append(f"{role}: {turn.get('content','')}")
        return out

    async def _fetcher_get(self):
        if self._fetcher is None:
            self._fetcher = build_fetcher(self.settings, self.logger)
        return self._fetcher

    async def _aclose(self) -> None:
        if self._fetcher is not None:
            try:
                await self._fetcher.aclose()
            finally:
                self._fetcher = None

    # ------------------------------------------------------------------ #
    async def _dispatch(self, tool: str, args: dict) -> Any:
        try:
            if tool == "discover":
                return await self._t_discover(args["url"])
            if tool == "ensure_profile":
                return await self._t_ensure_profile(args["url"])
            if tool == "crawl":
                return await self._t_crawl(args.get("seed_urls", []),
                                           args.get("follow_product_pages", True),
                                           args.get("max_products"))
            if tool == "query_catalog":
                return {"answer": self.reporter.answer(args["question"])}
            if tool == "summary":
                return deterministic_summary(Store(self.settings.db_path))
            if tool == "export":
                return self._t_export(args.get("format", "json"))
            if tool == "list_catalog_sites":
                return self._t_list_sites()
            return {"error": f"unknown tool '{tool}'"}
        except KeyError as exc:
            return {"error": f"missing argument {exc} for tool '{tool}'"}
        except Exception as exc:  # never crash the chat on a tool error
            log_event(self.logger, "conductor.tool_error", level=logging.ERROR, tool=tool, error=str(exc))
            return {"error": f"{type(exc).__name__}: {exc}"}

    # --- individual tools ------------------------------------------------ #
    async def _t_discover(self, url: str) -> dict:
        fetcher = await self._fetcher_get()
        res = await fetcher.fetch(url)
        disc = discover_listing(res.html, url)
        domain = domain_of(url)
        listing = self.profiles.get(domain, "catalog-listing") or self.profiles.find_for_url(url)
        return {
            "url": res.url,
            "status": res.status,
            "products_found": len(disc.product_urls),
            "subcategories_found": len(disc.subcategory_urls),
            "breadcrumb": disc.breadcrumb,
            "has_cached_profile": listing is not None,
            "signature": compute_signature(res.html),
        }

    async def _t_ensure_profile(self, url: str) -> dict:
        domain = domain_of(url)
        template = "catalog-listing" if "/catalog" in url or "/category" in url else "product-detail"
        existing = self.profiles.get(domain, template) or self.profiles.find_for_url(url)
        if existing is not None:
            return {"template": existing.template, "cached": True,
                    "fields": list(existing.fields.keys())}
        fetcher = await self._fetcher_get()
        res = await fetcher.fetch(url)
        profile = self.profile_author.author(res.html, url, template=template)
        return {"template": profile.template, "cached": False, "authored": True,
                "fields": list(profile.fields.keys()),
                "self_validated_coverage": profile.field_confidence.get("_self_validated_coverage")}

    async def _t_crawl(self, seed_urls, follow_product_pages: bool, max_products) -> dict:
        from ..orchestrator import Orchestrator  # local import avoids a cycle

        if isinstance(seed_urls, str):
            seed_urls = [seed_urls]
        seeds = []
        for s in seed_urls:
            if isinstance(s, dict):
                seeds.append(Seed(name=s.get("name") or s.get("url"), url=s["url"]))
            else:
                seeds.append(Seed(name=s, url=s))
        if not seeds:
            return {"error": "no seed_urls provided"}

        # Apply per-call overrides on top of config without mutating shared state.
        self.settings.raw.setdefault("crawl", {})
        self.settings.raw["crawl"]["follow_product_pages"] = bool(follow_product_pages)
        if max_products is not None:
            self.settings.raw["crawl"]["max_products"] = int(max_products)

        fetcher = await self._fetcher_get()
        extractor = LLMExtractorAgent(self.client, self.settings, self.logger)
        orch = Orchestrator(self.settings, fetcher, self.logger,
                            llm_extractor=extractor, profile_author=self.profile_author)
        metrics = await orch.run(seeds=seeds)
        s = metrics.summary()
        return {"products_stored": s["products_stored"], "avg_coverage": s["avg_coverage"],
                "dead_letters": s["dead_letters"], "signature_drifts": s["signature_drifts"],
                "field_coverage": s["field_coverage"], "seeds": [seed.url for seed in seeds]}

    def _t_export(self, fmt: str) -> dict:
        store = Store(self.settings.db_path)
        rows = store.all_products()
        written = export_all(rows, self.settings.output_dir, [fmt])
        return {"exported": [str(p) for p in written], "rows": len(rows)}

    def _t_list_sites(self) -> dict:
        store = Store(self.settings.db_path)
        rows = store.all_products()
        cats: dict[str, int] = {}
        for r in rows:
            cats[r["source_category"]] = cats.get(r["source_category"], 0) + 1
        return {"total_products": len(rows), "by_category": cats}
