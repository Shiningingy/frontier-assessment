# User Manual — Safco Catalog Scraper

A practical guide to installing, configuring and operating the tool. For the *why*
behind the design see [ARCHITECTURE.md](ARCHITECTURE.md); for the data shape see
[SCHEMA.md](SCHEMA.md); for the profile format see [PROFILES.md](PROFILES.md).

## Contents
1. [What it is](#1-what-it-is)
2. [Install](#2-install)
3. [The LLM backend & login model](#3-the-llm-backend--login-model) ← read this if anything is confusing
4. [Quick start](#4-quick-start)
5. [Command reference](#5-command-reference)
6. [Configuration reference](#6-configuration-reference)
7. [Using the conductor (chat) & Web UI](#7-using-the-conductor-chat--web-ui)
8. [Scraping a new site](#8-scraping-a-new-site)
9. [Output & where things live](#9-output--where-things-live)
10. [Troubleshooting & FAQ](#10-troubleshooting--faq)
11. [Limitations](#11-limitations)

---

## 1. What it is

A grounded, agent-based catalog scraper. It discovers product categories, extracts
products (schema.org JSON-LD first, CSS/LLM as fallback), normalizes them to a typed
schema, stores them in SQLite, and exports JSON/CSV/Excel. It has two ways to drive it:

- **Deterministic CLI** (`safco crawl`) — fast, reliable, **no API key needed** on sites
  that already have a cached extraction profile (Safco ships with one).
- **Conversational layer** (`safco chat` / `safco ui`) — a natural-language "conductor"
  that can scrape **any** site by auto-authoring a profile, plus answer questions about
  the catalog. This layer needs an LLM backend (see §3).

Everything an agent says is **grounded**: answers come only from fetched pages, tool
output, and the database — never guessed.

## 2. Install

Requires Python 3.10+.

```bash
pip install -e .              # core (deterministic crawl + export + stats)
pip install -e ".[llm]"       # + Anthropic API backend (for chat/report/author with a key)
pip install -e ".[ui]"        # + Gradio web UI
pip install -e ".[browser]"   # + Playwright fetcher for JS/anti-bot sites (optional)
pip install -e ".[dev]"       # + pytest
```
You can combine extras: `pip install -e ".[llm,ui]"`.

## 3. The LLM backend & login model

The scraping engine is plain Python. The **chat/UI/profile-authoring** features need an
LLM "brain" to reason. That brain is a **pluggable backend**, chosen in `config.yaml`
under `llm.backend`. **The app has no login screen** — it inherits auth from whichever
backend you pick. Login happens **once, out-of-band**, never inside the chat window.

| `llm.backend` | What it uses | How you authenticate (once) | Cost |
|---|---|---|---|
| `null` (default) | nothing — deterministic only | — | free, no key |
| `claude_cli` | the `claude` CLI (`claude -p`) | run `claude` once → `/login` with your Max account | free on Max |
| `anthropic` | the Anthropic API | put `ANTHROPIC_API_KEY=...` in `.env` | per-token |

```
You authenticate HERE (once):
  • claude_cli  →  `claude` then /login      ← credential cached by Claude Code
  • anthropic   →  .env: ANTHROPIC_API_KEY    ← just a key
NOT here:
  • the safco chat window / Gradio UI         ← no login; it reuses the above silently
```

- **`claude_cli`**: after you've logged the `claude` CLI in once, every `safco chat` /
  `safco ui` session silently spawns `claude -p` as a subprocess and reuses that login.
  Verify it's ready: `claude -p "say hi" --output-format json` should print a JSON reply.
- **`anthropic`**: copy `.env.example` → `.env`, set `ANTHROPIC_API_KEY`. The `claude`
  binary is never touched.

> ⚠️ Run `safco chat` / `safco ui` in a **normal terminal**, not nested inside a Claude
> Code session — spawning `claude -p` from within Claude Code is slow (Claude launching
> Claude). Standalone, it's a fast ordinary subprocess.

> ⚠️ Because the app inherits machine-level auth, the Gradio UI is a **single-user local
> tool**: anyone who can open its URL uses *your* logged-in LLM. Fine for local/demo use;
> a multi-user deployment needs real per-user auth in front of it (roadmap).

## 4. Quick start

```bash
# 1) Deterministic crawl of the two seed categories — no key required
safco crawl --fresh

# 2) See what you got
safco stats
#    Products: 30  (Dental Exam Gloves: 15, Sutures & surgical products: 15)

# 3) Look at the data
#    data/products.json | products.csv | products.xlsx | REPORT.md
```

To use the AI features, set `llm.backend: claude_cli` (or `anthropic`) in `config.yaml`,
then:
```bash
safco report "which nitrile gloves are under $10? name, sku, price"
safco chat                    # interactive conductor
safco ui                      # web UI at http://127.0.0.1:7860
```

## 5. Command reference

All commands accept a global `--config <path>` (default `config.yaml`).

| Command | What it does | Needs LLM? |
|---|---|---|
| `safco crawl [--fresh]` | Run the full pipeline over `seeds`; store + export. `--fresh` resets the frontier and re-crawls. | No (cached profile) |
| `safco stats` | Print catalog counts + the last `run_summary.json`. | No |
| `safco export [--format json\|csv\|xlsx]` | Re-export the current DB (default: all configured formats). | No |
| `safco report [question]` | Grounded Q&A over the catalog. No arg → interactive REPL (`summary`, `quit`). | Yes |
| `safco chat [message]` | Conversational conductor — scrape any site / ask the catalog. No arg → interactive. | Yes |
| `safco ui [--host --port --share]` | Launch the Gradio web UI (chat + catalog table). | Yes |
| `safco author-profile <url> [--template]` | LLM-author + cache an extraction profile for a page's template. | Yes |

Resumability: `safco crawl` (without `--fresh`) replays only `pending` frontier URLs and
upserts on SKU, so re-runs never duplicate rows. Interrupt any crawl and re-run to resume.

## 6. Configuration reference

Everything is config-driven — no code changes to retarget or retune. Key sections of
[../config.yaml](../config.yaml):

```yaml
seeds:                      # category URLs to crawl
  - {name: "...", url: "https://..."}

crawl:
  follow_product_pages: true   # also visit detail pages for specs/variants
  max_products: null           # cap detail fetches per run (null = no cap)
  follow_subcategories: false  # descend into discovered subcategories

fetcher:
  backend: httpx               # httpx | playwright
  user_agent: "..."
  respect_robots: true

rate_limit: {max_concurrency: 4, per_request_delay_seconds: 0.75, jitter_seconds: 0.5}
retry:      {max_attempts: 4, backoff_base_seconds: 1.0, backoff_max_seconds: 20.0}

extraction:
  min_coverage: 0.55           # below this, a profile is "failed" → LLM/author fallback
  revalidation_sample_rate: 0.05
  profile_ttl_hours: 168

storage: {db_path: "data/runtime/safco.db"}
output:  {dir: "data", formats: ["json", "csv", "xlsx"]}

llm:
  backend: null                # null | anthropic | claude_cli
  classify_model: claude-haiku-4-5
  extract_model:  claude-sonnet-4-6
```

## 7. Using the conductor (chat) & Web UI

The conductor turns natural language into actions by calling tools (`discover`,
`ensure_profile`, `crawl`, `query_catalog`, `summary`, `export`, `list_catalog_sites`).
It keeps calling tools until it can answer, then replies — grounded in their output.

**Terminal:**
```
$ safco chat
you> crawl gloves and sutures from safco and tell me the cheapest nitrile glove
  🔧 crawl({"seed_urls": ["https://www.safcodental.com/catalog/gloves", ...]})
  🔧 query_catalog({"question": "cheapest nitrile glove"})
The cheapest nitrile glove is Halyard Black Nitrile (SKU DRCDL) at $8.29.
```

**Web UI** (`safco ui`):
- **Chat** tab — same conductor, in the browser. Tool steps show as `> 🔧 …` lines above
  each answer.
- **Catalog** tab — click **Refresh** to load the current DB as a table + a summary.

One-shot (no interactive loop): `safco chat "summarize the catalog by brand"`.

## 8. Scraping a new site

The conductor works on any site, not just Safco. On an **unseen** template it auto-runs
the profile-author (one LLM pass) to write + cache an extraction profile, then crawls;
after that the site is cached and future crawls are deterministic.

```
you> discover https://some-store.example/catalog/widgets
you> crawl https://some-store.example/catalog/widgets, listing only
```
Or pre-author a profile explicitly:
```bash
safco author-profile https://some-store.example/product/abc
```
Works on JSON-LD **and** plain-HTML sites: a profile can use CSS `item_selector` +
`discovery` selectors so the generic extractor iterates product cards and follows
pagination on sites with no structured data. (Worked example: a `books.toscrape.com`
profile is bundled; crawling it walks pages 1→N and extracts 20 books/page via CSS.)

**Blocked / anti-bot sites.** If a site returns a 403/Cloudflare challenge, the tool
detects it, records *"blocked — refusing to evade,"* and queues a **human-help request**
(see `safco stats`) rather than trying to bypass the protection. To proceed you must have
permission and supply the page via an authorized browser / the Playwright tier — the tool
will not evade bot-protection for you.

## 9. Output & where things live

| Path | Contents |
|---|---|
| `data/products.json` / `.csv` / `.xlsx` | The normalized catalog (exports). |
| `data/run_summary.json` | Per-run metrics: pages, products, coverage, drifts, dead-letters. |
| `data/REPORT.md` | Human-readable data-quality report. |
| `data/runtime/safco.db` | SQLite: `products`, `frontier` (resume), `dead_letter`. (git-ignored) |
| `profiles/<domain>/<template>.json` | Cached extraction profiles. |
| `logs/run-*.log` | Structured JSON logs, one event per line. (git-ignored) |

## 10. Troubleshooting & FAQ

**`chat`/`report`/`ui` says "requires an LLM backend".** Set `llm.backend` to `claude_cli`
or `anthropic` in `config.yaml` (see §3).

**The chat hangs or is very slow.** You're probably running it nested inside a Claude Code
session. Use a normal terminal. Verify the backend: `claude -p "hi" --output-format json`
(for `claude_cli`) or that `ANTHROPIC_API_KEY` is set (for `anthropic`).

**`claude` CLI not found.** Install Claude Code and run `claude` once to log in, or switch
to the `anthropic` backend.

**Gradio errors / version mismatch.** `pip install -e ".[ui]"`. Built against Gradio ≥ 4.44
(tested on 6.x).

**Crawl found 0 products on a new site.** That template likely lacks JSON-LD; the
deterministic path can't see products. Try `author-profile` (LLM) or the Playwright tier.

**Re-running duplicates data?** No — products upsert on SKU (else URL). Safe to re-run.

**Where's the API key stored?** In `.env` (git-ignored). Never commit it.

## 11. Limitations

- `specifications` appear in static HTML on only some product pages; `alternatives` are
  JS-rendered (empty via httpx); `pack_size`/`variants` are partial — all reflect the
  source, and are the motivating cases for the LLM-fallback / Playwright tiers.
- Both Safco seed categories are single-page; pagination is handled generically but not
  exercised at depth. Auto-discovery beyond a given category page (sitemaps) is roadmap.
- New sites consume LLM calls (one profile-author pass per unseen template), then cached.
- The Gradio UI is single-user/local (inherits machine auth). See [../ROADMAP.md](../ROADMAP.md).
