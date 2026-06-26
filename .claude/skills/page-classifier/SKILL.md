---
name: page-classifier
description: Classify a fetched page as category / product-listing / product-detail / unknown. Use to route a page to the right profile.
---

# Page-classifier agent

Decide what kind of page you are looking at so the right extraction profile is used.

## How (rule-first, LLM only if ambiguous)
1. URL pattern: `/catalog/...` -> listing; `/product/...` -> detail.
2. JSON-LD signal: an `ItemList` of `Product`s -> listing; a single top-level
   `Product` -> detail.
3. If rules disagree or are silent, ask the LLM with the page's structure hints —
   but only report a class the evidence supports; answer `unknown` rather than
   guessing.

## Output
`{ "page_type": "category|product-listing|product-detail|unknown", "confidence": 0-1 }`

## Implementation
Rule logic lives in the profile `match` blocks + `tools/profiles.py`. The LLM path
reuses the shared `LLMClient`.
