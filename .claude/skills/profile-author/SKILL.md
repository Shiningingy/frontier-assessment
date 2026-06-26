---
name: profile-author
description: Inspect an unseen page template and write+cache a reusable extraction profile (field -> rule); repair a stale profile when coverage drops. Use for new sites or when extraction quality falls.
---

# Profile-author agent

You make the scraper work on a template it has never seen, by writing a JSON
**extraction profile** the generic extractor can run. You never write Python — the
site-specific knowledge lives entirely in the profile (data), keeping the extractor
clean and reusable.

## When to run
- A page has no cached profile (new site/template).
- An existing profile's coverage dropped below threshold or its `template_signature`
  drifted (the site changed) — repair it.

## How
1. Look at what the page ACTUALLY contains: its JSON-LD sample, detected @types, and
   HTML structure hints.
2. Author a profile: prefer `jsonld` rules; use `css`/`regex` only for fields not in
   JSON-LD. Target name, sku, brand, price, currency, availability, image_urls,
   description, category, product_url, specifications, variants, alternatives, rating.
3. **Validate**: re-run the generic extractor with your profile on the same page and
   check coverage. Only cache a profile that produces grounded, non-empty records.
4. Cache it under `profiles/<domain>/<template>.json` with a fresh `template_signature`.

## Rules — grounding
- Author rules only for structures visibly present. Do not invent selectors/paths.
- A profile that omits an absent field is correct; a rule pointing at nothing is
  rejected by validation.

## Implementation
`safco_scraper/agents/profile_author.py`, CLI: `safco author-profile <url>`.
