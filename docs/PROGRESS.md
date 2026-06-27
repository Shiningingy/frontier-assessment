# Progress & Findings Log

A running record of what we explored, decided, and built. Newest insights at the bottom.

## Build journey

1. **Deterministic core.** Safco serves clean schema.org JSON-LD in static HTML → extract 30
   products (15+15) at ~0.89 field coverage with **zero LLM**. SQLite + JSON/CSV/XLSX, resumable
   frontier, dedup, retries, metrics.
2. **Agent layer.** Added the conversational **conductor** (`safco chat`), **any-site** profile
   auto-authoring, grounded **reporter** Q&A, and a **Gradio** web UI (`safco ui`).
3. **Pagination.** Found Safco category pages show only ~15 items; `?page=` is client-side JS.
   Built **param-agnostic** next-page detection (rel=next, ?p/?page/?x/?start, path-based;
   same-host filtered — fixed a cross-domain false positive). Proved pagination live on
   **books.toscrape.com** (60 products across pages 1→3, CSS profile, no JSON-LD).
4. **Compliance.** Pointed the tool at **frontierdental.com** → Cloudflare **403** + robots
   disallows AI crawlers (`ai-train=no`). Built anti-bot **detection + refuse-to-evade** and a
   **human-handoff** final tier (`manual_help` table, surfaced in `safco stats` / conductor).

## Key findings (verified)

- **Safco = Magento + Algolia.** Category pages embed public Algolia search creds (appId
  `A5ULKNTM8N`, index `safco_prod_default_products`). The page's own query filters
  `categories.level1` + `numericFilters=visibility_catalog=1` and reports the true total.
- **True displayed counts:** Gloves **100** (matches the browser's "7 pages, 100 products"),
  Sutures **56**. Raw rows incl. variant children: 495 / 415. Each product's `sku` is a list of
  variant codes. Our Algolia source produced **156 products with variants**.
- **frontierdental.com** blocks classic Python scrapers (403) — needs a real browser + permission.

## The completeness insight (today's main learning)

A naïve scraper grabs the 15-item sample and thinks it's done. The fix is a **completeness-critic
agent** (`agents/completeness.py`, `safco check-completeness <url>`): it compares what we captured
to the page's **true total** and flags incompleteness — autonomously reporting *"15 of 100"* on
Safco with **no human hint**.

It learns the true total via **observe-and-replay**: a browser (`tools/browser_probe.py`) captures
the page's own data-API call (Algolia) and reads `nbHits=100` — the captured request already
contains the right filters, so no manual reverse-engineering is needed. This generalizes to any
API-driven catalog.

## Honest framing (how to present this)

- The **Algolia source is an expert-authored recipe** for the known target — hand-built (with the
  AI agents) for this 24h POC. That's transparent, not hidden.
- The **workflow** is what generalizes: agents discover + cache such recipes; the completeness-critic
  guarantees we never silently ship partial data; the **browser/MCP "vision" tier** is the proposed
  general (slower/costlier) solver. As agents meet more sites, coverage trends toward "any site that
  permits automation."

## Status

30 tests passing. Deliverables: README + docs (ARCHITECTURE/SCHEMA/PROFILES/MANUAL/DEMO/PROGRESS),
ROADMAP, sample datasets (Safco + books_demo), and `Frontier_Dental_POC_Presentation.pdf`.
