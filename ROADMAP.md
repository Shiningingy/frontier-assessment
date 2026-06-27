# Roadmap

The base is a deterministic, agentic catalog scraper for Safco Dental. This roadmap
tracks its evolution into a general, conversational, production-grade data tool.

## Phase 1 — Conversational entry + any-site + Web UI ✅ (this round)

- **Conductor agent** (`safco chat`): a natural-language front door that drives the
  whole workflow via tools — `discover`, `ensure_profile`, `crawl`, `query_catalog`,
  `summary`, `export`. Backend-agnostic tool-use loop (Anthropic API or Claude CLI/Max).
- **Any site**: orchestrator accepts runtime seeds, looks up profiles by each URL's own
  domain, and **auto-authors a profile on a cache miss** — so an unseen site is learned
  once (one LLM pass) then crawled deterministically thereafter.
- **Gradio web UI** (`safco ui`): chat panel + live catalog table + summary.
- Grounding enforced throughout: agents speak only from tool output / DB / fetched page.
- **Pagination following** with a `max_pages` cap — demonstrated live on a multi-page,
  non-JSON-LD site (books.toscrape) via CSS `item_selector` + profile-driven discovery,
  proving the extractor is genuinely site-agnostic.
- **Anti-bot compliance**: detect 403/Cloudflare blocks and refuse to evade.
- **Human-in-the-loop final tier**: queue an actionable human-help request when
  automation can't/shouldn't proceed, instead of failing silently or evading.
- **Completeness-critic agent**: compares what we captured to the page's true total and
  flags incompleteness (autonomously reports "15 of 100" on Safco). `safco check-completeness`.
- **Complete-catalog source (expert recipe)**: Safco's own public Algolia API, used as a
  hand-authored recipe → the full displayed catalog (Gloves 100 + Sutures 56 = 156 products
  with variants). Honest framing: this is what the autonomous workflow below should *discover*.
- **Autonomous API discovery (prototype)**: `browser_probe` captures the page's own data-API
  call via a real browser (observe-and-replay) — proven to read the true `nbHits` with no
  hardcoding.

## Phase 1.5 — Close the autonomous-discovery loop (next)

Turn the prototype into the full automated path, so an unseen API-driven site is handled
without a human reverse-engineering it:
- Completeness-critic detects a gap → **API-discovery agent** selects the captured product
  API, infers pagination, and an LLM maps its JSON fields → our schema (grounded in the real
  response).
- **Cache the discovered recipe** like any profile (endpoint + payload + pagination + field
  map); learned once, deterministic after.
- Fall back to the **browser/MCP "vision" tier** when there's no clean API, and to **human
  handoff** when blocked or uncertain. As the recipe cache grows across sites, coverage trends
  toward "any site that permits automation."

## Phase 2 — Robustness & coverage

- **Discovery beyond a single page**: `sitemap.xml` + full category-tree crawl, deep
  pagination, breadth/depth limits.
- **Automatic tier escalation**: when a page has no JSON-LD and CSS coverage is low,
  auto-escalate to the Playwright fetcher; for anti-scrape/JS-only sites, a
  **vision/MCP tier** (e.g. a browser-using agent) reads the rendered page.
- **Profile lifecycle**: versioning + diffing of authored profiles, human-review queue
  for low-confidence profiles, scheduled revalidation on TTL.
- **Distributed crawl**: swap the SQLite frontier for a durable queue (SQS/Redis/Postgres
  `SKIP LOCKED`) with N stateless workers and a per-domain distributed rate limiter.
- **Data-quality dashboard**: ship `run_summary.json` metrics (coverage, drift,
  dead-letters) to Prometheus/Grafana with alerting on coverage deltas.
- **Supervisor / orchestrator-worker coordination**: today coordination is split correctly
  by uncertainty — a *deterministic* orchestrator runs the known pipeline, an *LLM* conductor
  handles open-ended decisions, and the completeness-critic does QA. At scale (many sites in
  parallel, each needing different escalation), promote the **conductor into a budget-aware
  supervisor**: decompose goals → dispatch to worker agents → monitor completeness/cost →
  **dynamically re-plan** on failure (API blocked → browser → human) and arbitrate when agents
  disagree. Principle kept throughout: reach for an LLM manager only where decisions are
  genuinely uncertain — never just because there are many agents.

## Phase 3 — Real-business integration (data collector / reporter)

Run the tool as a service embedded in business workflows, not just a CLI:

- **Scheduled collection** feeding downstream systems — price/stock monitoring of
  competitor or supplier catalogs on a cron, landing into a data warehouse / Google
  Sheets / BI tool for analysis.
- **Reporting surfaces** — push periodic summaries and **change-alerts** (price drops,
  new SKUs, out-of-stock) to Slack / email / Teams; the grounded reporter answers ad-hoc
  questions directly in those channels.
- **System integrations** — a small **REST / MCP API** so procurement, ERP, CRM or
  pricing engines can query the normalized catalog or trigger a crawl; **webhooks** on
  catalog changes.
- **Decision support** — enrichment for sourcing/pricing decisions (compare brands, track
  unit cost over time), with the natural-language reporter as the analytics layer.

## Phase 4 — Hardening for production

- Secrets via a real secret manager; per-site auth for gated catalogs.
- Containerized scheduled runs (k8s `CronJob` / serverless); incremental, idempotent
  re-crawls.
- Cost controls and observability budgets for the LLM tiers.
- Multi-tenant profile registry shared across deployments.
