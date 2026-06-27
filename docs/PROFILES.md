# Extraction Profiles

A **profile** is a JSON document that tells the generic extractor HOW to pull each
field from one site template. Profiles are *data, not code*: the extractor
(`tools/extract.py`) knows how to apply rules; it never knows what a specific site
looks like. This is what lets one clean function serve many sites — each template is
"learned" once and cached under `profiles/<domain>/<template>.json`.

## Field rule shapes

```jsonc
{ "source": "jsonld", "path": "Product.offers.price" }          // schema.org JSON-LD
{ "source": "css", "selector": "h1.title" }                      // text of first match
{ "source": "css", "selector": "img.main", "attr": "@src" }      // attribute of first match
{ "source": "css", "selector": "li", "label": "strong", "require_colon": true }  // inline label:value -> dict
{ "source": "css", "selector": "table tr", "kv": ["th","td"] }   // key/value table -> dict
{ "source": "css", "selector": ".rel a", "fields": {"name":"@text","url":"@href"} } // list of dicts
{ "source": "regex", "pattern": "Item #\\s*(\\w+)", "group": 1 } // regex over page text
```

`cardinality: "many"` emits one record per JSON-LD `Product` (listing pages);
`"one"` emits a single record (detail pages).

### Non-JSON-LD listing sites (CSS)

For sites with no JSON-LD, a profile can drive both extraction and discovery from CSS:

```jsonc
{
  "cardinality": "many",
  "item_selector": "article.product_pod",        // iterate each product card; css fields resolve relative to it
  "discovery": { "product_link": "h3 a", "next_page": "li.next a" },
  "fields": { "name": {"source":"css","selector":"h3 a","attr":"@title"}, ... }
}
```

(Used by the bundled `books.toscrape.com` profile.) Beyond profiles, an **API recipe** source
can supply already-structured records directly (e.g. `tools/algolia.py`, `extraction_tier: api`).

## Tier memory + self-validation

Each profile records a `template_signature`, per-field `source` (the resolved tier),
`last_validated` and `ttl_hours`. On every page the crawler recomputes the signature
(cheap, structural — JSON-LD `@type` set + chrome landmarks) and:

- **signature matches** → trust the cached rules (fast path);
- **drift / coverage below threshold / TTL expired** → hand the page to the
  **profile-author** agent, which re-derives the profile, **validates it by
  re-running the extractor on that page**, and re-caches with a fresh signature.

So a template that needs the LLM/MCP tier starts there next time, but the cheap
pre-check always runs first — if a site drops its anti-scrape meta and structured
data reappears, the system notices and downgrades. Escalation is cached, never
permanently frozen.

## Authoring a profile for a new site

```bash
safco author-profile https://some-shop.example/product/abc
```

The agent inspects the page's JSON-LD + HTML structure, writes a profile, validates
it, and caches it. Grounding rule: it only authors rules for structures visibly
present — a rule that points at nothing is rejected by validation.
