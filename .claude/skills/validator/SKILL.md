---
name: validator
description: Normalize, validate and de-duplicate extracted product records into the documented schema. Use after extraction, before storage.
---

# Validator / deduplicator agent

Make raw extracted records clean, typed and unique.

## How
1. Coerce types: price -> number, availability -> enum, images/category -> lists,
   resolve relative URLs to absolute.
2. Validate against the `Product` schema (`models.py`). Drop records with no name;
   count validation failures.
3. Compute **coverage** (fraction of key fields populated) — the signal that gates
   whether the profile succeeded.
4. De-duplicate / upsert on `dedup_key` = SKU (else product URL) for idempotency.

## Rules
- Normalize formatting only; never substitute or invent missing values.
- Flag low-coverage or invalid records for the orchestrator's metrics rather than
  silently fixing them.

## Implementation
`safco_scraper/tools/validate.py` + `tools/store.py` (idempotent upsert).
