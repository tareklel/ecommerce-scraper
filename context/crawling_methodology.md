# Site Crawling Methodology

This document defines the process for onboarding a new e-commerce site into the scraper pipeline.
Follow these phases in order. Each phase validates assumptions before you commit to implementation.

See `ecommercecrawl/constants/product_schema.py` for the canonical field contract all spiders must output.

---

## Phase 0: Feasibility Probe

Run a probe script (see `scripts/probe_{site}.py`) or manually check the following before writing any spider code.

### 0.1 WAF / Bot Protection

```bash
curl -sI https://{site}/
```

Look for:
- `cf-ray` header → Cloudflare
- `x-akamai-*` → Akamai WAF (Farfetch: blocked direct + Zyte HTTP)
- `x-sucuri-id` → Sucuri
- HTTP 403/520/503 with <1KB body → bot block

**Decision tree:**
```
Direct curl 200 with content?
├── YES → use direct requests (Scrapy / requests lib)
└── NO  → Zyte httpResponseBody returns content?
          ├── YES → use Zyte HTTP (cheap: ~$1-2 / 1000 requests)
          └── NO  → Zyte browserHtml returns content?
                    ├── YES → proceed but document cost (~$8-10 / 1000 requests); consider raw HTML storage
                    └── NO  → blocked; move to tickets/blocked/
```

### 0.2 SSR vs CSR

Check if HTML response contains product content or just an empty app shell:

```bash
# High token count with product text = SSR
curl -sL https://{site}/some-plp | wc -c

# Common framework signals
curl -sL https://{site}/some-plp | grep -E '__NEXT_DATA__|window\.initialState|data-reactroot|__NUXT__'
```

**SSR** → extraction can happen from raw HTML without JS rendering.
**CSR/SPA** → you need JS rendering (Zyte browserHtml) OR find the underlying JSON API.

### 0.3 PLP API Discovery

Most modern e-commerce PLPs call a JSON API internally. Finding it eliminates the need for HTML parsing on PLPs entirely.

Steps:
1. Open browser DevTools → Network tab → filter by Fetch/XHR
2. Browse a category PLP page
3. Look for responses returning `{"products": [...]}`, `{"items": [...]}`, or similar
4. Check common paths: `/api/products`, `/api/catalog`, `/graphql`, `/api/search`
5. Try `curl -sL "{api_url}" | python3 -m json.tool | head -50`

If a JSON API exists → use it for PLP (stable, no WAF risk, pagination is usually a `page` or `offset` param).

### 0.4 JSON-LD on PDP

```bash
curl -sL https://{site}/some-pdp | grep -A 20 'application/ld+json'
```

Look for `@type: "Product"` or `@type: "ProductGroup"`. This is the most stable extraction path — sites maintain JSON-LD for SEO.

If present, validate the fields against `PRODUCT_SCHEMA`:
- `name` → `product_name`
- `brand.name` → `brand`
- `offers.price` → `price`
- `offers.priceCurrency` → `currency`
- `image` → `image_urls`
- `sku` → `portal_itemid`

### 0.5 Language & Country Signals

Determine how the site encodes language and country:

| Signal | Example | Derivation |
|--------|---------|------------|
| URL path | `/en/`, `/ar/` | Check `'/ar/' in url` |
| Subdomain | `ar.site.com` | Check hostname prefix |
| TLD | `site.sa`, `site.ae` | Map TLD → country |
| URL param | `?lang=ar-AE` | `parse_qs(urlparse(url).query).get('lang')` |
| Cookie/session | stored server-side | Worst case — flag as risk, pass as spider arg |

**Key rule**: language must be derivable from the URL alone. If it requires a cookie or session state, the crawl design needs rethinking (e.g., separate EN and AR seed lists with explicit language arg).

### 0.6 Pagination Type

Browse past page 1 of a PLP and observe what changes:

| Type | Detection | Implementation |
|------|-----------|----------------|
| Page param | `?page=2`, `?p=2` | Generate N URLs from `totalPages` field in API/HTML |
| Offset param | `?offset=48&limit=48` | Increment by `count` until response is empty |
| Cursor | `?after=eyJpZCI6...` | Follow `nextCursor` / `pageInfo.endCursor` |
| Infinite scroll | URL unchanged on scroll | Capture underlying XHR from DevTools; do NOT simulate scroll |

Infinite scroll almost always fires an XHR with an offset or cursor. Find that API call.

---

## Phase 1: PLP Crawling

### 1.1 Seed URLs

Seed URLs live in `resources/{site}_urls.csv`. Include one URL per category per language:

```
https://bloomingdales.sa/en/women/clothing/,plp
https://bloomingdales.sa/ar/women/clothing/,plp
```

The CSV header `url,category` is conventional but only the first column is used by `_iter_seed_urls`.

### 1.2 PLP → PDP Harvesting

Each PLP must yield a list of PDP URLs. Validate:
- At least 1 PDP URL per PLP page
- URLs are absolute
- Language context is preserved in harvested PDP URLs

Language propagation (only needed when language is in a `?lang=` param, not a URL path):
```python
def propagate_language(pdp_url: str, plp_url: str) -> str:
    params = parse_qs(urlparse(plp_url).query)
    lang = params.get('lang', [None])[0]
    if not lang:
        return pdp_url
    sep = '&' if '?' in pdp_url else '?'
    return f'{pdp_url}{sep}lang={lang}'
```

If language is already in the URL path (`/ar/`), harvested PDP URLs will already carry it.

---

## Phase 2: PDP Extraction

### 2.1 Data Source Priority

Use the highest-priority source available on the site:

| Priority | Source | Stability | Notes |
|----------|--------|-----------|-------|
| 1 | Private JSON API | High | Best: structured, no WAF risk on API endpoint |
| 2 | JSON-LD `schema.org/Product` | High | SEO-maintained; parse with `extract_jsonld_blocks()` |
| 3 | Embedded JS blob (`window.initialState`, `__NEXT_DATA__`) | Medium | Site-specific; breaks on JS refactors |
| 4 | OpenGraph / meta tags | Low-Medium | Limited fields; use as fallback for name/price/image |
| 5 | HTML/XPath/CSS selectors | Low | Last resort; brittle on redesign |

### 2.2 Raw HTML vs Extract-on-Crawl

**Extract-on-crawl** (Ounass, Level pattern):
- Parse fields during crawl → write JSONL → S3 bronze
- Smaller storage, Athena-queryable immediately
- Re-crawl required to fix extraction bugs

**Raw HTML first** (use when extraction source is brittle DOM):
- Write full rendered HTML to `bronze/{env}/crawls/{site}/{dt}/{run_id}/raw_html/{itemid}.html.gz`
- Run extraction job separately
- Re-process from stored HTML without re-crawling when extraction logic changes
- 90-day S3 lifecycle rule on `raw_html/` prefix; not Athena-queryable

**Rule**: JSON-LD or private API → extract on crawl. DOM-only → store raw HTML.

---

## Phase 3: Language & Country

### Standard derivation helpers

```python
from urllib.parse import urlparse, parse_qs

def get_language(url: str) -> str:
    """Return 'EN' or 'AR'. Uppercase, no country suffix."""
    parsed = urlparse(url)
    path = parsed.path.lower()
    if '/ar/' in path or path.startswith('/ar'):
        return 'AR'
    if parsed.hostname.split('.')[0] in {'ar', 'arabic'}:
        return 'AR'
    params = parse_qs(parsed.query)
    lang = params.get('lang', [None])[0]
    if lang and lang.lower().startswith('ar'):
        return 'AR'
    return 'EN'


TLD_COUNTRY_MAP = {'ae': 'AE', 'sa': 'SA', 'kw': 'KW', 'qa': 'QA'}

def get_country(url: str) -> str | None:
    hostname = urlparse(url).hostname or ''
    parts = hostname.split('.')
    # Handle subdomain-based country: saudi.ounass.com → SA
    subdomain = parts[0].lower()
    if 'saudi' in subdomain:
        return 'SA'
    if 'kuwait' in subdomain:
        return 'KW'
    if 'qatar' in subdomain:
        return 'QA'
    # TLD-based
    tld = parts[-1].lower()
    return TLD_COUNTRY_MAP.get(tld)
```

Adapt to the specific site's URL structure. Follow the precedent set by `level_rules` and `ounass_rules`.

---

## Phase 4: Images

- `image_urls` must always be a **list**, even for a single image
- Prefer JSON-LD `image[*].contentUrl` or `image[*].url` (all images, ordered)
- Fallback: OpenGraph `og:image` (single image only)
- Must be absolute URLs (`https://...`); fix scheme-relative URLs: `'//' + url` → `'https://' + url`
- No auth tokens in URLs (tokens expire before the image downloader pipeline runs)

---

## Phase 5: Implementation Files

When probe validates the site is crawlable, create:

| File | Content |
|------|---------|
| `ecommercecrawl/constants/{site}_constants.py` | `NAME`, `MAIN_SITE`, `{SITE}_URLS`, API config if applicable |
| `ecommercecrawl/rules/{site}_rules.py` | `is_plp`, `is_pdp`, `get_language`, `get_country`, all field extractors |
| `ecommercecrawl/spiders/{site}_crawl.py` | Spider class extending `MasterCrawl` |
| `resources/{site}_urls.csv` | Seed URL list (one per category × language) |
| `scripts/probe_{site}.py` | Probe script — run before implementation to validate, and after to confirm |
| `tests/test_{site}_rules.py` | Unit tests using saved HTML fixtures |
| `tests/fixtures/{site}_plp.html` | Saved PLP HTML for offline tests |
| `tests/fixtures/{site}_pdp.html` | Saved PDP HTML for offline tests |

Spider skeleton (adapt to site's pagination and extraction source):

```python
class {Site}Spider(MasterCrawl, scrapy.Spider):
    name = constants.NAME
    default_urls_path_setting = '{SITE}_URLS_PATH'
    default_urls_path_constant = constants.{SITE}_URLS

    def parse_plp(self, response):
        # 1. Yield paginated PLP requests (first page only)
        # 2. Yield PDP requests from this page
        ...

    def parse_pdp(self, response):
        # Extract all fields from response
        # Yield dict with all PRODUCT_SCHEMA fields
        ...

    def parse(self, response):
        if rules.is_plp(response.url):
            yield from self.parse_plp(response)
        elif rules.is_pdp(response.url):
            yield from self.parse_pdp(response)
```

---

## Phase 6: Quality Gate

Add the new site's optional-field exclusions to `resources/quality_gate_exclusions.json`:

```json
{
  "{site}": ["price_discount", "sizes", "gender"]
}
```

Fields that are legitimately often NULL should be excluded from blank-rate checks so they don't fail the quality gate.

---

## Probe Script Template

`scripts/probe_{site}.py` should validate:

```
[ ] Direct HTTP returns 200 with content (or WAF block identified)
[ ] HTML size > 50KB (SSR) or < 5KB (CSR shell)
[ ] PLP: at least 1 PDP URL harvested
[ ] PLP: pagination type identified
[ ] PDP: JSON-LD / API source identified
[ ] PDP: all REQUIRED_FIELDS extractable
[ ] Language: derivable from URL
[ ] Country: derivable from URL
[ ] Images: at least 1 absolute URL
```

Print a clear pass/fail verdict per check. Save a fixture from a live PDP for unit tests.
