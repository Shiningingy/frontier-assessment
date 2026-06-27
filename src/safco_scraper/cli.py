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
    help_q = store.help_queue()
    if help_q:
        print(f"\n🙋 Human-help requests ({len(help_q)}):")
        for h in help_q:
            print(f"  - {h['url']}\n      {h['reason']}\n      → {h['suggested_action']}")
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


def _run_chat(args) -> int:
    settings = load_settings(args.config)
    logger = _logger_from(settings)
    if settings.llm_backend == "null":
        print("chat requires an LLM backend. Set llm.backend to 'anthropic' or 'claude_cli' in config.yaml.")
        return 2
    from .agents.conductor import ConductorAgent
    from .llm.factory import build_llm_client

    conductor = ConductorAgent(build_llm_client(settings, logger), settings, logger)
    history: list = []
    print("Conductor ready. Tell me what to scrape or ask about the catalog ('quit' to exit).\n")
    if args.message:
        final, _steps = conductor.run_turn(args.message, history)
        print(final)
        return 0
    while True:
        try:
            msg = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not msg:
            continue
        if msg.lower() in {"quit", "exit", "q"}:
            break
        final, steps = conductor.run_turn(msg, history)
        for s in steps:
            print(f"  {s}")
        print("\n" + final + "\n")
        history.append((msg, final))
    return 0


async def _run_check_completeness(args) -> int:
    settings = load_settings(args.config)
    logger = _logger_from(settings)
    from .agents.completeness import CompletenessCritic
    from .tools.extract import extract_with_profile
    from .tools.profiles import ProfileStore, domain_of

    fetcher = build_fetcher(settings, logger)
    try:
        res = await fetcher.fetch(args.url)
    finally:
        await fetcher.aclose()
    profiles = ProfileStore("profiles")
    profile = profiles.get(domain_of(args.url), "catalog-listing") or profiles.find_for_url(args.url)
    extracted = len(extract_with_profile(res.html, profile, args.url).records) if profile else 0

    critic = CompletenessCritic(settings, logger, use_browser=not args.no_browser)
    # The browser probe uses Playwright's sync API, which can't run inside this
    # asyncio loop — run the check in a worker thread.
    verdict = await asyncio.to_thread(critic.check, args.url, extracted, res.html)
    print(json.dumps(verdict.as_dict(), indent=2))
    return 0 if verdict.complete else 1


def _run_ui(args) -> int:
    settings = load_settings(args.config)
    logger = _logger_from(settings)
    if settings.llm_backend == "null":
        print("The UI chat requires an LLM backend. Set llm.backend to 'anthropic' or 'claude_cli' in config.yaml.")
        return 2
    try:
        from .ui.app import launch
    except ImportError:
        print("Gradio not installed. Run: pip install -e .[ui]")
        return 2
    launch(settings, logger, host=args.host, port=args.port, share=args.share)
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

    p_chat = sub.add_parser("chat", help="conversational entry point — scrape any site / ask the catalog")
    p_chat.add_argument("message", nargs="?", help="one-shot message (omit for interactive chat)")

    p_cc = sub.add_parser("check-completeness",
                          help="did we get everything? compare extracted count vs the page's true total")
    p_cc.add_argument("url", help="category URL to check")
    p_cc.add_argument("--no-browser", action="store_true",
                      help="skip the browser probe; use HTML signals only")

    p_ui = sub.add_parser("ui", help="launch the Gradio web UI (chat + catalog view)")
    p_ui.add_argument("--host", default="127.0.0.1")
    p_ui.add_argument("--port", type=int, default=7860)
    p_ui.add_argument("--share", action="store_true", help="create a public Gradio share link")

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
    if args.command == "chat":
        return _run_chat(args)
    if args.command == "check-completeness":
        return asyncio.run(_run_check_completeness(args))
    if args.command == "ui":
        return _run_ui(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
