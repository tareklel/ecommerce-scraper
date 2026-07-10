# Ticket: Farfetch Crawler — JSON-LD Extraction

**Status: blocked — not possible now**

**Blocker**: Farfetch uses Akamai WAF. Only Zyte `browserHtml: True` gets through — `httpResponseBody` returns 520 even via Zyte's proxy. `browserHtml` is prohibitively expensive at crawl scale. Revisit if Zyte session reuse or a cheaper anti-bot bypass becomes viable.

## Goal

Replace the XPath/CSS PDP extractor with a JSON-LD-based extractor using the
`schema.org/ProductGroup` block Farfetch embeds on every PDP. Validated live
against item-32020644 (TOTEME boots, AE).

---

## What the Probe Confirmed

Farfetch is **not** Next.js. The HTML head has `data-reactroot` (custom React SSR).
`__NEXT_DATA__` does not exist. `window.universal_variable` only has page-level
metadata (currency, locale, pageId) — no product fields.

Every live PDP embeds two JSON-LD blocks:
```
<script type="application/ld+json">{"@type": "ProductGroup", ...}</script>
<script type="application/ld+json">{"@type": "BreadcrumbList", ...}</script>
```

ProductGroup is the extraction target. It is a declared `schema.org` standard
interface that Farfetch actively maintains for SEO — more stable than CSS
selectors or internal JS variables.

---

## Why JSON-LD Instead of XPath

| | XPath/CSS selectors | JSON-LD ProductGroup |
|---|---|---|
| Breaks on | Designer moves a div | Farfetch stops following schema.org |
| Failure mode | Silent NULL | Missing key → detectable error |
| Recovery | Re-crawl after fixing selectors | Re-parse stored raw HTML |
| Fields available | Visible DOM only | Structured object incl. all variants |
| Price | Usually visible price only | Per-variant price + currency |

---

## Field Map (from live probe)

```python
# JSON-LD path → field
pg["productGroupID"]                     → portal_itemid
pg["name"].strip()                       → product_name
pg["brand"]["name"]                      → brand
pg["color"]                              → colour
pg["description"]                        → description  (pipe-delimited: name|color|materials|categories)
pg["url"]                                → canonical_url
pg["image"][*]["contentUrl"]             → image_urls (list)

# Price: min across in-stock variants
pg["hasVariant"][i]["offers"]["priceSpecification"][0]["price"]    → price
pg["hasVariant"][i]["offers"]["priceSpecification"][0]["priceCurrency"] → currency
pg["hasVariant"][i]["offers"]["availability"]  → "InStock" / "OutOfStock"
pg["hasVariant"][i]["size"]              → sizes (list)

# Category from BreadcrumbList (1-indexed position)
breadcrumbs[position=3]["item"]["name"]  → category
breadcrumbs[position=4]["item"]["name"]  → subcategory

# Language — derived from URL, not injected externally
parse_qs(urlparse(url).query).get("lang", ["en-US"])[0].split("-")[0].upper()  → language
# "?lang=ar-AE" → "AR" | no param → "EN"
```

Live example (item-32020644):
```json
{
  "portal_itemid": "32020644",
  "product_name":  "nappa over-the-knee boots",
  "brand":         "TOTEME",
  "colour":        "Black",
  "price":         5109.07,
  "currency":      "AED",
  "out_of_stock":  false,
  "sizes":         ["40", "37", "41"],
  "n_images":      4,
  "category":      "Shoes",
  "subcategory":   "Over-The-Knee Boots"
}
```

---

## Schema

```python
@dataclass
class FarfetchProduct:
    run_id:         str
    site:           str          # "farfetch"
    crawl_date:     str          # YYYY-MM-DD
    country:        str          # from URL path segment (/ae/, /sa/)
    language:       str          # "EN" or "AR" — derived from ?lang= param (see get_language())
    portal_itemid:  str          # pg["productGroupID"]
    product_name:   str          # pg["name"] — in the request language
    brand:          str          # pg["brand"]["name"] — language-independent
    colour:         str | None   # pg["color"]
    price:          float | None # min price across in-stock variants
    currency:       str | None   # pg["hasVariant"][i]["offers"]["priceSpecification"][0]["priceCurrency"]
    out_of_stock:   bool         # True if all variants OutOfStock
    sizes:          list[str]    # available sizes — language-independent
    image_urls:     list[str]    # pg["image"][*]["contentUrl"] — language-independent
    category:       str | None   # BreadcrumbList position 3 — in the request language
    subcategory:    str | None   # BreadcrumbList position 4 — in the request language
    canonical_url:  str | None   # pg["url"]
    description:    str | None   # pg["description"] — in the request language
```

---

## Field Contract

```python
REQUIRED = {"portal_itemid", "product_name", "brand", "price", "currency", "language"}
OPTIONAL = {"colour", "out_of_stock", "sizes", "image_urls", "category", "subcategory"}
```

- Required field missing → log ERROR with `run_id` + item URL; skip row
- Optional field missing → emit row with NULL/empty list; log WARNING

---

## Raw HTML Capture

On every PDP fetch, write the full rendered HTML to S3:
```
bronze/{env}/crawls/farfetch/{dt}/{run_id}/raw_html/{portal_itemid}.html.gz
```

Enables re-parsing if the JSON-LD schema changes without re-crawling.
Not Athena-queryable — recovery artifact only. 90-day retention.

---

## PLP Discovery

The existing `farfetch_rules.get_pdp_urls()` already parses `@type=ItemList`
JSON-LD from PLPs — keep this. Confirmed working.

PLP seed URL format (from breadcrumb data):
- Brand listing: `/ae/shopping/women/{brand-slug}/items.aspx`
- Category: `/ae/shopping/women/{brand-slug}/{category-slug}-{id}/items.aspx`

---

## Language Handling

Farfetch has no separate language pages. Language is a URL parameter (`?lang=ar-AE`).
JSON-LD content (product name, category/subcategory from breadcrumbs, description)
reflects the active language. `brand`, `price`, `portal_itemid`, `image_urls`, and
`sizes` are language-independent.

### Derivation — `farfetch_rules.get_language(url)`

Follows `level_rules.get_language` convention: parse URL, extract language, drop
country suffix, return uppercase.

```python
from urllib.parse import urlparse, parse_qs

def get_language(url: str) -> str:
    """Parse ?lang=ar-AE → 'AR'. No param → 'EN'."""
    params = parse_qs(urlparse(url).query)
    lang_param = params.get("lang", ["en-US"])[0]
    return lang_param.split("-")[0].upper()
    # "ar-AE" → "AR" | "en-US" → "EN"
```

### PLP → PDP propagation

When harvesting PDP URLs from a PLP, append the same `?lang=` so the PDP is
fetched in the same language as the seed:

```python
def append_lang(pdp_url: str, plp_url: str) -> str:
    params = parse_qs(urlparse(plp_url).query)
    lang = params.get("lang", [None])[0]
    if not lang:
        return pdp_url
    sep = "&" if "?" in pdp_url else "?"
    return f"{pdp_url}{sep}lang={lang}"

# In spider PLP callback:
for pdp_url in rules.get_pdp_urls(response):
    yield response.follow(append_lang(pdp_url, response.url))
```

### Scope of this ticket

This ticket ships **`EN` only** (`lang=en-US`, the default). A follow-on
exploration ticket covers: which languages per country (AE: EN + AR, SA: TBD),
canonical mapping of Arabic names, and whether Arabic is a separate run or a
`language` dimension in the bronze schema.

---

## Zyte Configuration

### `browserHtml: True` is required — confirmed

Farfetch uses Akamai WAF. Tested 2026-07-10:
- Direct curl → 478 bytes, "Access Denied" (Akamai hard block)
- `httpResponseBody` via Zyte → HTTP 520 (Akamai blocked the plain HTTP request even through Zyte's proxy)
- `browserHtml: True` via Zyte → 304K chars, full PDP with JSON-LD ✓

There is no cheaper path. `browserHtml` is the only Zyte mode that carries enough
browser fingerprinting to get past Akamai on Farfetch.

**Cost mitigation options to explore separately:**
- Zyte `actions` + session reuse (one browser session across multiple PDPs)
- Batch/async API calls to parallelise and reduce wall-clock cost
- Cache raw HTML S3 blobs and skip re-crawl when price/stock hasn't changed

```python
# PDP and PLP — both require browserHtml
"zyte_api": {"browserHtml": True, "geolocation": "AE"}
```

---

## Files Changed / Added

| File | Action |
|------|--------|
| `ecommercecrawl/spiders/farfetch_crawl.py` | Rewrite `_populate_pdp_data` to use JSON-LD extractor |
| `ecommercecrawl/rules/farfetch_rules.py` | Delete PDP XPath functions; add `extract_product_group()`, `extract_product()` |
| `ecommercecrawl/xpaths/farfetch_xpaths.py` | Delete |
| `ecommercecrawl/constants/farfetch_constants.py` | Add JSON-LD type constants, raw HTML S3 path |
| `scripts/zyte_farfetch_probe.py` | Probe script (written and validated) |
| `tests/test_farfetch_extractor.py` | Unit tests using saved fixture JSON-LD |

---

## Testing Strategy

**Unit tests** — `tests/test_farfetch_extractor.py`:
- Fixture: `tests/fixtures/farfetch_product_group.json` — real ProductGroup block from probe
- Test: `extract_product(fixture, breadcrumbs)` → all required fields populated
- Test: all variants OutOfStock → `out_of_stock=True`, price is `None`
- Test: `brand` key missing → raises / logs error, row skipped
- Test: `color` missing (optional) → row emitted with `colour=None`

**Probe script** (run before implementation to re-validate field paths):
```bash
export ZYTE_API_KEY=$(aws secretsmanager get-secret-value \
  --secret-id ecommerce-scraper/env --query SecretString --output text \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['ZYTE_API_KEY'])")

# Validate PDP extraction
poetry run python scripts/zyte_farfetch_probe.py

# Dump raw JSON-LD for fixture capture
poetry run python scripts/zyte_farfetch_probe.py --dump-jsonld

# Validate PLP ItemList extraction
poetry run python scripts/zyte_farfetch_probe.py --probe-plp
```

---

## Out of Scope

- Multi-country seeds (AE + SA) — separate ticket
- Re-parse job from raw HTML blobs
- Observability / missing-field alerting
- Image downloading (existing pipeline handles once `image_urls` populated)

---

## Smoke Test

Before signing off, run the spider against `resources/farfetch_urls.csv` and
inspect the extracted output manually:

| Type | URL | Validate |
|------|-----|----------|
| PLP  | `/ae/shopping/women/tops-1/items.aspx` | ItemList yields ≥1 PDP URL, pagination works |
| PLP (AR) | same `?lang=ar-AE` | harvested PDP URLs carry `?lang=ar-AE` |
| PDP  | `/ae/…/toteme--item-16824594.aspx` | All 5 required fields extracted, price in AED, `language=EN` |
| PDP (AR) | same `?lang=ar-AE` | `product_name` / `category` in Arabic, `language=AR` |

Note: validate `tops-1` PLP is still live — it uses the old category-N format that
may 404. Update the CSV with a confirmed live brand PLP if stale.

---

## Open Questions

- [ ] Does PLP return `ItemList` JSON-LD via `httpResponseBody` (SSR) or only after JS?
      Run `--probe-plp` and compare `httpResponseBody` vs `browserHtml` response size.
- [ ] Is `tops-1` PLP in `resources/farfetch_urls.csv` still live, or does it 404 like `bags-1`?
      Validate before running smoke test; replace with a confirmed brand PLP if stale.
- [x] Raw HTML 90-day retention: confirmed — add S3 lifecycle rule on `raw_html/` prefix in same PR.
