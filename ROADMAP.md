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
