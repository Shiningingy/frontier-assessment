---
name: navigator
description: Discover product detail URLs, subcategories and pagination from a Safco category listing page. Use when given a category page and asked what to crawl next.
---

# Navigator agent

Given a fetched category page, return the URLs to crawl next. Work only from what
the page actually contains.

## How
1. Parse the page's schema.org JSON-LD:
   - product `ItemList` -> each element's URL is a product detail page.
   - subcategory `ItemList` (`CollectionPage` items) -> subcategory URLs.
   - `BreadcrumbList` -> the category hierarchy.
2. Detect pagination: `rel="next"`, `?p=N`, `page=N` links.
3. If JSON-LD has no product list, fall back to anchors matching `/product/`.

## Output
`{ product_urls: [...], subcategory_urls: [(url,name)...], next_pages: [...], breadcrumb: [...] }`

## Rules
- Only emit URLs that appear on the page. Never construct or guess product URLs.
- De-duplicate; resolve relative URLs against the page URL.

## Implementation
`safco_scraper/tools/navigate.py::discover_listing`.
