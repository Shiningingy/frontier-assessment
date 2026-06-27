# Output Schema

Every scraped record is normalized into a `Product` (see `src/safco_scraper/models.py`)
before storage. Nested fields are JSON-encoded in CSV/Excel and native objects in JSON.

## Product

| Field | Type | Notes |
|---|---|---|
| `dedup_key` | string | Idempotency key: SKU (upper-cased) else product URL. Primary key in SQLite. |
| `name` | string | **Required.** Product name. |
| `sku` | string? | SKU / item number / product code. |
| `item_number` | string? | Defaults to SKU when no separate item number. |
| `brand` | string? | Brand / manufacturer. |
| `category_path` | string[] | Category hierarchy (breadcrumb), e.g. `["Dental Supplies","Dental Exam Gloves"]`. CSV/Excel join with ` > `. |
| `source_category` | string? | The seed category this product was discovered under. |
| `product_url` | string | Canonical product detail URL. |
| `price` | number? | Numeric price (currency stripped). |
| `currency` | string? | ISO currency, default `USD`. |
| `pack_size` | string? | Unit / pack size when available. |
| `availability` | enum | `in_stock` \| `out_of_stock` \| `preorder` \| `discontinued` \| `unknown`. |
| `description` | string? | Product description. |
| `specifications` | object | Key→value attributes (e.g. `{"Material":"Powder-free nitrile"}`). |
| `image_urls` | string[] | Absolute image URLs. |
| `rating` | number? | Aggregate rating value when present. |
| `variants` | object[] | `{sku, pack_size, price, availability}` purchasable variations. |
| `alternatives` | object[] | `{name, url, sku}` related/alternative products. |
| `extraction_tier` | string | Provenance: `jsonld` \| `css` \| `regex` \| `llm` \| `api` \| `mixed`. |
| `scraped_at` | string | ISO-8601 UTC timestamp. |

## Storage layout (SQLite)

- `products` — one row per `dedup_key` (idempotent upsert).
- `frontier` — `(url, kind, status, source_category, attempts)` for resumable crawling.
- `dead_letter` — `(url, error, attempts, failed_at)` for permanently failed URLs.

## Exports

`data/products.json`, `data/products.csv`, `data/products.xlsx`, and the run
observability artifact `data/run_summary.json`.
