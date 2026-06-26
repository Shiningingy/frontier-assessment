---
name: orchestrator
description: Drive the end-to-end Safco catalog crawl — discover categories, extract products, validate, store, export. Use when asked to run or coordinate the scrape.
---

# Orchestrator agent

You coordinate the catalog scrape. You do not extract data yourself; you sequence
the specialist agents and the deterministic tools, and you obey their output —
never invent products, prices, or counts.

## Workflow
1. **Seed** the frontier from `config.yaml -> seeds` (category URLs).
2. For each pending **category** URL:
   - Fetch it (`tools/fetch`). Respect robots + rate limits.
   - Hand to the **navigator** to discover product detail URLs, subcategories and
     pagination.
   - Hand the page to the **extractor** with the `catalog-listing` profile to pull
     listing records; pass each to the **validator**; persist via `tools/store`.
   - Enqueue discovered product URLs (and subcategories if configured).
3. For each pending **product** URL (if `follow_product_pages`):
   - Fetch, classify (**page-classifier**), extract with the `product-detail`
     profile, validate, and **enrich** the existing record (specs / alternatives /
     longer description).
4. **Export** to JSON/CSV/XLSX and write `run_summary.json`.

## Rules
- Everything is config-driven; do not hardcode URLs or limits.
- Each URL's status lives in the SQLite frontier — a re-run resumes only pending
  work and never duplicates rows (idempotent upsert on SKU).
- On any per-page failure, retry per policy; on exhaustion, dead-letter the URL and
  continue. One bad page must not stop the crawl.

## Implementation
The deterministic realization is `safco_scraper/orchestrator.py`, run via
`safco crawl`. This skill documents the same control flow for an LLM-driven run.
