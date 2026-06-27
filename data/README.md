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

Produced by the complete-catalog source (the site's own Algolia API), with detail-page enrichment
for descriptions. **This is also what the default `safco crawl` now produces** — the learned
per-domain source recipe (`profiles/safcodental.com/_source.json`) is applied automatically, so
the system uses Algolia for Safco without any config edit. This is the dataset to evaluate / submit.

## ℹ️ Side-product — `products.json` / `products.csv` / `products.xlsx` (this folder root)

A **by-product of the discovery journey, not the final output.** It is the *static-only* sample
that `safco crawl --source html` produces: only the **15-item curated sample** each category exposes
in static HTML (15 gloves + 15 sutures = 30). We kept it (committed at 30) to demonstrate the
zero-API path — **but it is intentionally partial and is not the final catalog.** (Running the
default crawl overwrites these files with the complete 156.) See `docs/PROGRESS.md` for why (Safco
loads the full catalog client-side; we discovered its API and built the complete source).

`REPORT.md` / `run_summary.json` at this root describe that deterministic demo run.
