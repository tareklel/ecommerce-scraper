# Ticket: Bloomingdales.sa Crawler

**Status: done ✓** (bags category, SA only — 2026-07-28)

**Site**: https://bloomingdales.sa (AR) / https://en.bloomingdales.sa (EN)  
**Country**: SA  
**Currency**: SAR  
**Platform**: Salesforce Commerce Cloud (SFCC / Demandware)  
**Probe date**: 2026-07-15  
**Seed URLs**: `resources/bloomingdales_urls.csv`

---

## Scope

**Bags (SA) only for initial launch.** Shoes and clothing not seeded yet.  
Additional GCC countries (KW, AE, QA) are a future expansion — see GCC notes below.

---

## Probe Results Summary (all checks passed)

| Check | Result |
|-------|--------|
| Direct HTTP access | ✓ Cloudflare present but not blocking — 200 OK, no Zyte needed |
| SSR vs CSR | ✓ Full SSR — PLP 1.3MB, PDP 625KB with complete HTML |
| PLP product links | ✓ 48 products embedded in SSR HTML, `Search-UpdateGrid` API for pagination |
| PDP JSON-LD | ✓ `@type: Product` with name, brand, sku, price, currency, availability, images |
| Language mechanism | ✓ Subdomain: `bloomingdales.sa` = AR, `en.bloomingdales.sa` = EN |
| Country | ✓ `.sa` TLD → always SA |
| Currency | ✓ SAR confirmed in JSON-LD `offers.priceCurrency` |
| Images | ✓ 6 images per product, absolute HTTPS CDN URLs |

---

## Language & URL Structure

Bloomingdales operates separate subdomains per language:

| Subdomain | Language | Example PLP |
|-----------|----------|-------------|
| `bloomingdales.sa` | AR | `/womens-bags-cross-body-bags/` |
| `en.bloomingdales.sa` | EN | `/womens-bags-cross-body-bags/` |

PDP URL pattern (same slug, different subdomain):
- AR: `https://bloomingdales.sa/marc-jacobs-حقيبة-مكياج-سين-BAG219542223xBLK.html`
- EN: `https://en.bloomingdales.sa/marc-jacobs-scene-vanity-bag-BAG219542223xBLK.html`

**Key**: URL slug differs per language, but the PID suffix (`BAG219542223xBLK`) is identical. Language is derived purely from the hostname `en.` prefix — this is not SA-specific and will work for any future GCC domain (e.g. `en.bloomingdales.kw`).

```python
def get_language(url: str) -> str:
    hostname = urlparse(url).hostname or ''
    return 'EN' if hostname.startswith('en.') else 'AR'
```

### GCC expansion notes

`get_language` is GCC-ready. Two constants are currently SA-specific and must be updated when adding a new country:

| Constant | Current value | What to change |
|----------|--------------|----------------|
| `LOCALE_MAP` | `{'AR': 'ar_SA', 'EN': 'en_SA'}` | Make country-aware; e.g. KW → `ar_KW`/`en_KW` |
| `SFCC_SITE_ID` | `'BloomingDales_SA-Site'` | Likely `'BloomingDales_KW-Site'` etc. — confirm from probe |

---

## PLP Structure & Pagination

Platform: SFCC `Search-UpdateGrid` endpoint.

**Page 1** (SSR): Load `https://{domain}/{category-slug}/` → 48 products embedded in HTML  
**Pages 2+**: Call `Search-UpdateGrid` API until no products returned.

Category ID (`cgid`) is extracted dynamically from the `js-show-more-btn`'s `data-url`. Stop condition: API response has 0 PDP href matches.

---

## PDP Extraction

Primary source: JSON-LD `@type: Product`. Gender/category/subcategory from HTML microdata BreadcrumbList (position 1–4). Confirmed breadcrumb order: `[0]=brand, [1]=gender, [2]=category, [3]=subcategory, [4]=product_name`.

---

## Full Field Map

| Field | Source | Notes |
|-------|--------|-------|
| `run_id` | spider | Standard |
| `site` | constants | `'bloomingdales'` |
| `crawl_date` | spider | YYYY-MM-DD |
| `url` | response.url | PDP URL including PID |
| `country` | TLD | Always `'SA'` for now |
| `language` | hostname `en.` prefix | `EN` or `AR` |
| `portal_itemid` | URL PID regex | `BAG219542223XBLK` (uppercased) |
| `product_name` | JSON-LD `name` | In crawled language |
| `brand` | JSON-LD `brand.name` | Latin script, language-independent |
| `price` | JSON-LD `offers.price` | Float |
| `currency` | JSON-LD `offers.priceCurrency` | Always `'SAR'` |
| `out_of_stock` | JSON-LD `offers.availability` | `OutOfStock` check |
| `image_urls` | JSON-LD `image[]` | 6 images; ordered list |
| `category` | DOM breadcrumb position 3 | In crawled language |
| `subcategory` | DOM breadcrumb position 4 | In crawled language |
| `gender` | DOM breadcrumb position 2 | `Women`, `Men`, `Kids` |
| `color` | URL PID suffix after `x` | Mapped via `_COLOR_CODES`; raw title-case fallback |
| `sizes` | `<button data-attr="size" data-url=...>` | `onesize` → `One Size`; list |
| `price_discount` | `blm-price__percentage` class element | `"70% OFF"` string; NULL if not on sale |
| `was_price` | `blm-price__standard` content attribute | Float; NULL if not on sale |
| `primary_label` | `blm-pdpmain__badges` container | List; anchored to avoid carousel contamination |
| `text` | JSON-LD `description` + `Details & Care` `<ul>` + `#pdp-sizeandfit` | Struct `{description, details, size_fit}`; None if all null |

---

## Files

| File | Status |
|------|--------|
| `scripts/probe_bloomingdales.py` | ✓ Written and validated |
| `resources/bloomingdales_urls.csv` | ✓ EN + AR bags seeds |
| `tests/fixtures/bloomingdales_plp.html` | ✓ Saved by probe |
| `tests/fixtures/bloomingdales_pdp.html` | ✓ AR PDP (Marc Jacobs Scene Vanity Bag) |
| `ecommercecrawl/constants/bloomingdales_constants.py` | ✓ Done |
| `ecommercecrawl/rules/bloomingdales_rules.py` | ✓ Done |
| `ecommercecrawl/spiders/bloomingdales_crawl.py` | ✓ Done |
| `tests/test_bloomingdales_rules.py` | ✓ Done (36 tests) |
| `run_crawler.py` | ✓ bloomingdales wired in |
| `resources/quality_gate_exclusions.json` | ✓ `color, sizes, price_discount, primary_label` excluded |

---

## Open Questions

- [x] `portal_itemid`: URL PID (`BAG219542223xBLK`) preferred over JSON-LD `sku` — language-independent, variant-level, human-readable.
- [x] Color normalization: raw lowercase code with `_COLOR_CODES` map for common 3-letter codes; multi-word codes title-cased. Full normalization downstream.
- [x] UpdateGrid pagination on `en.bloomingdales.sa`: confirmed working — locale `en_SA` in URL.
- [x] `price_discount` extraction: `blm-price__percentage` class. Validated on `.ae` sale PDP.
- [x] `get_pdp_urls` PID regex: validated against bags PLP — no false positives on nav links.
- [ ] Men's and kids' categories: same SFCC breadcrumb structure assumed but not probed.
- [ ] GCC expansion: probe a KW or AE domain to confirm `SFCC_SITE_ID` and `LOCALE_MAP` values before adding seeds.
