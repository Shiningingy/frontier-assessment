"""Command-line entry point.

  safco crawl            run the full deterministic pipeline (no API key needed)
  safco export           re-export the current DB to json/csv/xlsx
  safco author-profile   run the profile-author agent on a URL (needs LLM backend)
  safco report           interactive Q&A over the scraped catalog (needs LLM backend)
  safco stats            print catalog stats + the last run summary
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from .config import load_settings
from .fetcher.factory import build_fetcher
from .orchestrator import Orchestrator
from .utils.logging import setup_logging


def _logger_from(settings):
    lcfg = settings.section("logging")
    return setup_logging(
        level=lcfg.get("level", "INFO"),
        as_json=bool(lcfg.get("json", True)),
        log_dir=lcfg.get("dir", "logs"),
    )


def _build_llm_extractor(settings, logger):
    """Return an LLM-backed extractor callable, or None for deterministic-only."""
    if settings.llm_backend == "null":
        return None
    try:
        from .llm.factory import build_llm_client
        from .agents.extractor import LLMExtractorAgent

        client = build_llm_client(settings, logger)
        return LLMExtractorAgent(client, settings, logger)
    except Exception as exc:  # never block the crawl on optional deps
        logger.warning(f"LLM extractor unavailable, continuing deterministically: {exc}")
        return None


async def _run_crawl(args) -> int:
    settings = load_settings(args.config)
    logger = _logger_from(settings)
    fetcher = build_fetcher(settings, logger)
    llm = _build_llm_extractor(settings, logger)
    orch = Orchestrator(settings, fetcher, logger, llm_extractor=llm)
    try:
        metrics = await orch.run(fresh=args.fresh)
    finally:
        await fetcher.aclose()
    print(json.dumps(metrics.summary(), indent=2))
    print(f"\nStored {metrics.products_stored} products -> {settings.output_dir}/ (json/csv/xlsx) + {settings.db_path}")
    return 0


def _run_export(args) -> int:
    from .tools.export import export_all
    from .tools.store import Store

    settings = load_settings(args.config)
    store = Store(settings.db_path)
    rows = store.all_products()
    fmts = [args.format] if args.format else settings.output_formats
    written = export_all(rows, settings.output_dir, fmts)
    print(f"Exported {len(rows)} products:")
    for p in written:
        print(f"  - {p}")
    return 0


def _run_stats(args) -> int:
    from pathlib import Path

    from .tools.store import Store

    settings = load_settings(args.config)
    store = Store(settings.db_path)
    rows = store.all_products()
    by_cat: dict[str, int] = {}
    for r in rows:
        by_cat[r["source_category"]] = by_cat.get(r["source_category"], 0) + 1
    print(f"Products: {len(rows)}")
    for cat, n in by_cat.items():
        print(f"  {cat}: {n}")
    print(f"Dead-letters: {len(store.dead_letters())}")
    summary = Path(settings.output_dir) / "run_summary.json"
    if summary.exists():
        print("\nLast run summary:")
        print(summary.read_text(encoding="utf-8"))
    return 0


async def _run_author_profile(args) -> int:
    settings = load_settings(args.config)
    logger = _logger_from(settings)
    if settings.llm_backend == "null":
        print("author-profile requires an LLM backend. Set llm.backend to 'anthropic' or 'claude_cli' in config.yaml.")
        return 2
    from .agents.profile_author import ProfileAuthorAgent
    from .fetcher.factory import build_fetcher
    from .llm.factory import build_llm_client

    fetcher = build_fetcher(settings, logger)
    client = build_llm_client(settings, logger)
    agent = ProfileAuthorAgent(client, settings, logger)
    try:
        res = await fetcher.fetch(args.url)
        profile = agent.author(res.html, args.url, template=args.template)
    finally:
        await fetcher.aclose()
    print(f"Authored + cached profile '{profile.template}' for {profile.site}")
    print(json.dumps(profile.to_dict(), indent=2)[:1200])
    return 0


def _run_report(args) -> int:
    settings = load_settings(args.config)
    logger = _logger_from(settings)
    if settings.llm_backend == "null":
        print("report requires an LLM backend. Set llm.backend to 'anthropic' or 'claude_cli' in config.yaml.")
        return 2
    from .agents.reporter import ReporterAgent
    from .llm.factory import build_llm_client

    client = build_llm_client(settings, logger)
    reporter = ReporterAgent(client, settings, logger)
    if args.question:
        print(reporter.answer(args.question))
        return 0
    reporter.repl()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="safco", description="Agentic Safco Dental catalog scraper")
    parser.add_argument("--config", default="config.yaml", help="path to config.yaml")
    sub = parser.add_subparsers(dest="command", required=True)

    p_crawl = sub.add_parser("crawl", help="run the deterministic crawl pipeline")
    p_crawl.add_argument("--fresh", action="store_true", help="reset the frontier and re-crawl from seeds")

    p_export = sub.add_parser("export", help="re-export current DB")
    p_export.add_argument("--format", choices=["json", "csv", "xlsx"], help="single format (default: all configured)")

    sub.add_parser("stats", help="print catalog stats + last run summary")

    p_author = sub.add_parser("author-profile", help="LLM-author an extraction profile for a URL")
    p_author.add_argument("url", help="page URL to author a profile from")
    p_author.add_argument("--template", default=None, help="template name (default: inferred)")

    p_report = sub.add_parser("report", help="interactive Q&A over the catalog")
    p_report.add_argument("question", nargs="?", help="one-shot question (omit for interactive REPL)")

    args = parser.parse_args(argv)

    if args.command == "crawl":
        return asyncio.run(_run_crawl(args))
    if args.command == "export":
        return _run_export(args)
    if args.command == "stats":
        return _run_stats(args)
    if args.command == "author-profile":
        return asyncio.run(_run_author_profile(args))
    if args.command == "report":
        return _run_report(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
