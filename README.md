# Safco Dental — Agentic Catalog Scraper (POC)

A runnable, agent-based scraping system that discovers product categories on
[safcodental.com](https://www.safcodental.com), extracts structured product data,
normalizes it, stores it (SQLite + JSON/CSV/Excel), and is designed to harden into a
production crawler. Built for the Frontier Dental AI take-home.

**It runs on clone with no API key.** The deterministic core crawls and exports by
itself; the LLM/agent tiers are optional and only kick in where they add value
(authoring extraction rules for new templates, fallback on irregular pages, and
catalog Q&A).

```
$ safco crawl
... 32 pages fetched, 30 products, avg field-coverage 0.89, 0 failures, 0 dead-letters
Stored 30 products -> data/ (json/csv/xlsx) + data/runtime/safco.db
```

---

## 1. Architecture overview

The key finding that shapes everything: **Safco serves clean `schema.org` JSON-LD in
static HTML**, so the core fields need no browser and no LLM. The system is therefore
**deterministic-first, AI-where-it-pays**, with one twist that keeps it general:

> A **generic, site-agnostic extractor** runs an **extraction profile**
> (field → rule). Per-site knowledge lives entirely in cached JSON profiles, not in
> code. A **profile-author agent** writes the profile for any unseen template and
> caches it, so one clean function serves many sites.

Two runtimes share one set of Python tools:

| | Deterministic core (`safco crawl`) | Agent layer |
|---|---|---|
| Needs a key? | **No** (cached profiles) | Yes (`ANTHROPIC_API_KEY`) or Claude CLI (Max) |
| Role | Fast, reliable bulk crawl | Profile authoring/repair, extraction fallback, Q&A |

```
seeds → fetch → navigator (discover) → extractor (profile) → validator → store → export
                                   ↑ low coverage / drift ↓
                         profile-author / LLM extraction fallback (grounded)
```

Full diagrams in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md);
profile format in [docs/PROFILES.md](docs/PROFILES.md);
schema in [docs/SCHEMA.md](docs/SCHEMA.md).

## 2. Why this approach

- **JSON-LD-first is fast, cheap, and reliable.** The catalog already exposes
  structured product data; extracting it deterministically beats throwing an LLM at
  every page. We measured ~0.89 average field coverage with zero LLM calls.
- **Profiles, not per-site code.** Hardcoding selectors per site doesn't scale. A
  generic extractor + cached, agent-authored profiles means new sites are *learned*,
  not coded, and the extractor stays clean.
- **AI only where it earns it.** The brief explicitly warns against AI as
  decoration. We use it for exactly the hard parts: authoring/repairing profiles,
  irregular-layout extraction fallback, and natural-language reporting.
- **Always runnable.** A reviewer can clone and get a real dataset with no
  credentials; the AI tiers layer on top when a key/CLI is present.

## 3. Agent responsibilities

| Agent | Responsibility | Where |
|---|---|---|
| **conductor** ⭐ | Conversational front door: natural language → tool calls (discover/ensure_profile/crawl/query/export) over **any** site | `agents/conductor.py` |
| **orchestrator** | Sequence discover → extract → validate → store → export; checkpointing, retries, metrics | `orchestrator.py` |
| **navigator** | Discover product URLs, subcategories, pagination from listing JSON-LD | `tools/navigate.py` |
| **page-classifier** | Page type (rule-first; LLM only if ambiguous) | profile `match` + LLM |
| **profile-author** ⭐ | Inspect an unseen template, write + **self-validate** + cache a profile; repair drift | `agents/profile_author.py` |
| **extractor** | Apply cached profile; LLM fallback + grounding guard on low coverage | `tools/extract.py` + `agents/extractor.py` |
| **validator/deduplicator** | Normalize, validate to schema, dedup on SKU, coverage scoring | `tools/validate.py` |
| **reporter** ⭐ | Grounded natural-language Q&A over the catalog | `agents/reporter.py` |

Each role is also a `.claude/skills/<name>/SKILL.md`, so the workflow is runnable
inside Claude Code, not only as Python.

**Grounding (anti-hallucination):** agents obey only what they actually see — script
output, DB rows, the fetched page. Enforced in code: the LLM extractor drops any
value not literally present on the page; the profile-author's output is validated by
re-running it; the reporter answers only from DB rows.

## 4. Setup & execution

Requires Python 3.10+.

```bash
# 1. Install (deterministic core only — no key needed)
pip install -e .

# 2. Crawl the two seed categories -> SQLite + JSON/CSV/XLSX + run summary
safco crawl                      # use --fresh to reset the frontier and re-crawl

# 3. Inspect
safco stats                      # catalog counts + last run summary
cat data/products.json           # the normalized catalog
```

Optional **AI tiers** — enable one backend in `config.yaml` (`llm.backend`):

```bash
pip install -e .[llm]            # for the Anthropic backend
# config.yaml: llm.backend = anthropic   (set ANTHROPIC_API_KEY in .env)
#          or: llm.backend = claude_cli  (uses a logged-in Claude Code / Max — no key)

safco author-profile https://www.safcodental.com/product/compac-nitrile   # write+cache a profile
safco report "which nitrile gloves are under $10? list name, sku, price"  # grounded Q&A
safco report                     # interactive REPL (try: summary)
```

**Conversational entry point + any-site (`safco chat` / `safco ui`).** The conductor
agent is a natural-language front door that drives the whole workflow — and works on
**any site**, not just Safco: given an unseen URL it auto-authors an extraction profile
(one LLM pass), caches it, then crawls.

```bash
pip install -e .[ui]             # adds the Gradio web UI
safco chat                       # terminal chat; e.g. "crawl gloves from safco and
                                 #   tell me the cheapest nitrile glove"
safco chat "summarize the catalog by brand"
safco ui                         # browser chat + live catalog table (http://127.0.0.1:7860)
```

Any-site crawling and the chat need an LLM backend (`anthropic` or `claude_cli`); the
plain `safco crawl` on cached sites still needs no key. See [ROADMAP.md](ROADMAP.md) for
where this is heading (scheduled collection, change-alerts, REST/MCP API, BI integration).

Optional **browser tier** for JS/anti-bot sites (not needed for Safco):
`pip install -e .[browser] && playwright install chromium`, then
`config.yaml: fetcher.backend = playwright`.

Everything is config-driven (`config.yaml`): seeds, rate limits, concurrency,
fetcher/LLM backend, output formats, coverage thresholds.

## 5. Sample output

`safco crawl` produces `data/products.{json,csv,xlsx}`, `data/run_summary.json`, and
`data/runtime/safco.db` (30 products across both seed categories). One record:

```json
{
  "dedup_key": "DRCDM", "name": "Compac Nitrile", "sku": "DRCDM",
  "brand": "Cranberry", "category_path": ["Dental Exam Gloves"],
  "product_url": "https://www.safcodental.com/product/compac-nitrile",
  "price": 8.49, "currency": "USD", "availability": "in_stock",
  "description": "Compac™ By The Cuff® Nitrile Powder Free Exam Gloves ...",
  "specifications": {"Brand": "Cranberry® Compac", "Material": "Powder-free nitrile",
                     "Thickness": "Approximately 2.2–2.5 mil", "Color": "Black"},
  "image_urls": ["https://www.safcodental.com/media/catalog/product/c/r/...jpg"],
  "extraction_tier": "mixed", "scraped_at": "2026-06-26T21:42:..."
}
```

Full field reference: [docs/SCHEMA.md](docs/SCHEMA.md).

## 6. Limitations (current)

- **Scope:** crawls the 2 seed categories; both happen to be single-page (15 items
  each). Pagination is detected and handled generically but is untested at depth.
- **Specifications** appear in static HTML on only some product pages (~1/30); most
  Safco detail pages have no spec list. This is the real state of the source, and the
  motivating case for the LLM extraction fallback (infer specs from the description).
- **Alternatives / related products** are JS-rendered (empty in static HTML), so they
  are not captured by the httpx path — a job for the Playwright tier.
- **Reporter** loads the whole catalog into context (fine for a POC); at scale it
  should generate SQL against the DB (see below).
- The `null` LLM backend means `author-profile` and `report` require enabling a
  backend; the crawl itself does not.

## 7. Failure handling

- **Retries:** `tenacity` exponential backoff + jitter on network errors, 429s, and
  5xx (`fetcher/httpx_fetcher.py`).
- **Per-URL isolation:** one bad page never stops the crawl; after retries it is
  written to the `dead_letter` table with the error and attempt count.
- **Resumability / idempotency:** the SQLite `frontier` tracks each URL's status; a
  re-run replays only `pending` work and upserts on SKU, so re-runs never duplicate
  rows. (Verified: a resume run fetches 0 pages and the catalog stays at 30.)
- **Robots & rate limits:** `robots.txt` is honored (fail-open with logging); a
  concurrency cap + jittered per-request delay keep the crawl polite.
- **Profile drift:** a changed template signature or sub-threshold coverage routes
  the page to the profile-author instead of silently emitting nulls.
- **Agent safety:** LLM-tier exceptions are caught and never break the crawl; the
  grounding guard prevents hallucinated values from entering the catalog.

## 8. Scaling to full-site crawling in production

- **Distributed frontier:** replace the SQLite frontier with a durable queue
  (SQS/Redis/Postgres `SKIP LOCKED`); the `(url, status, attempts)` model already
  fits a work-queue. Run N stateless workers; politeness becomes a per-domain
  distributed rate limiter.
- **Full discovery:** seed from `sitemap.xml` + the top-level `/catalog` tree
  (already discoverable via the subcategory `ItemList`); enable
  `follow_subcategories` and pagination to fan out across the whole catalog.
- **Profile cache as a service:** store profiles in a shared store keyed by
  `domain+template`; the profile-author runs on cache-miss/drift only, so per-page
  LLM cost stays near zero at steady state. TTL + sampled revalidation catch silent
  site changes (and sites that *drop* anti-scrape, letting us downgrade tiers).
- **Scheduling:** containerized (`Dockerfile`) and run on cron / k8s `CronJob` /
  serverless for incremental re-crawls; idempotent upserts make re-runs safe.
- **Secrets:** keys via env / secret manager (`.env` for local, never committed).
- **Backpressure & cost controls:** concurrency, `max_products`, and coverage
  thresholds are all config knobs.

## 9. Monitoring data quality

- **Per-run observability** (`data/run_summary.json`): pages fetched, products
  stored, **average + per-field coverage %**, validation failures, low-coverage
  records, **signature drifts**, profile cache hit/miss, LLM invocations,
  dead-letters.
- **Field coverage as the primary signal.** A sudden drop in coverage for a known
  template is the earliest indication the site changed under us — the same threshold
  that triggers profile repair is the data-quality alarm. Wire `run_summary.json`
  into Prometheus/Grafana/CloudWatch and alert on coverage deltas, dead-letter rate,
  and drift counts.
- **Structured JSON logs** (one event per line) make per-URL failures and drift
  events greppable and dashboardable.
- **Schema validation** rejects malformed records at the boundary; counts are
  surfaced, not hidden.
- **Sampled re-validation** re-checks even passing templates, catching slow drift.

## Project layout

```
src/safco_scraper/
  cli.py  config.py  orchestrator.py  models.py
  fetcher/   httpx_fetcher.py  playwright_fetcher.py  factory.py
  tools/     fetch via fetcher, extract.py (generic), profiles.py (cache),
             navigate.py, validate.py, store.py, export.py, query.py, pageview.py
  agents/    extractor.py  profile_author.py  reporter.py
  llm/       base.py  anthropic_client.py  claude_cli_client.py  null_client.py  prompts.py
  utils/     ratelimit.py  retry (tenacity)  robots.py  logging.py
.claude/skills/<agent>/SKILL.md     # agent definitions (runnable in Claude Code)
profiles/safcodental.com/*.json     # cached extraction profiles
tests/                              # offline tests against captured HTML fixtures
docs/  config.yaml  Dockerfile
```

## Tests

```bash
pip install -e .[dev] && pytest        # 13 offline tests, no network/LLM needed
```

They exercise extraction on captured Safco HTML, normalization/coverage, the profile
cache + signature stability, and the LLM grounding guard.
