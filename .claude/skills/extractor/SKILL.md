---
name: extractor
description: Pull structured product fields from a page using its cached profile; fall back to LLM extraction only when coverage is low. Use to extract products from a fetched page.
---

# Extractor agent

Turn a fetched page into structured product records.

## How (tiered)
1. Load the cached profile for the page's template. Run the generic extractor
   (`tools/extract::extract_with_profile`) — deterministic, cheap.
2. Validate the records and compute coverage.
3. If coverage >= threshold: done (fast path, no LLM).
4. If coverage < threshold (or a sampled revalidation fires) and an LLM backend is
   configured: run the **LLM extraction fallback** on the page text, then apply the
   GROUNDING GUARD — drop any value not literally present in the page — and merge to
   FILL GAPS in the deterministic record (never overwrite good data).
5. If the layout looks structurally new, defer to the **profile-author** to repair
   the profile rather than relying on per-page LLM extraction forever.

## Rules — grounding
- Every value must come from the page you fetched. Never guess, infer, or normalize
  from outside knowledge. Missing is better than fabricated.

## Implementation
Deterministic: `tools/extract.py`. LLM fallback + grounding guard:
`agents/extractor.py::LLMExtractorAgent`.
