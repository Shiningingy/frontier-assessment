# Sample Output — read me first

This folder holds two different things. **Only one is the deliverable.**

## ✅ The deliverable — `safco_full/`

The **final, refined output of the agent workflow**: the *complete* displayed catalog for the
**two target categories together** — Dental Exam Gloves (**100**) + Sutures & surgical products
(**56**) = **156 products**, with **variant SKUs** and product descriptions.

| File | Contents |
|---|---|
| `safco_full/products.json` | Full catalog, nested fields as native JSON |
| `safco_full/products.csv` | Flat table (nested fields JSON-encoded) |
| `safco_full/products.xlsx` | Same, as Excel |
| `safco_full/run_summary.json` | Run metrics + per-field coverage |

Produced by the complete-catalog source (the site's own Algolia API, `source.backend: algolia`),
with detail-page enrichment for descriptions. This is the dataset to evaluate / submit.

## ℹ️ Side-product — `products.json` / `products.csv` / `products.xlsx` (this folder root)

A **by-product of the discovery journey, not the final output.** It is what the *deterministic,
no-API-key* path (`safco crawl`, default HTML source) produces: only the **15-item curated sample**
each category exposes in static HTML (15 gloves + 15 sutures = 30). We kept it to demonstrate the
"clone and run with zero setup" path — **but it is intentionally partial and is not the final
catalog.** See `docs/PROGRESS.md` for why (Safco loads the full catalog client-side; we discovered
its API and built the complete source).

`REPORT.md` / `run_summary.json` at this root describe that deterministic demo run.
