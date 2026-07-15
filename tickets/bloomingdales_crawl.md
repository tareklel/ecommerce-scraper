# Ticket: Bloomingdales.sa Crawler

**Status: ready for implementation**

**Site**: https://bloomingdales.sa (AR) / https://en.bloomingdales.sa (EN)  
**Country**: SA  
**Currency**: SAR  
**Platform**: Salesforce Commerce Cloud (SFCC / Demandware)  
**Probe date**: 2026-07-15  
**Seed URLs**: `resources/bloomingdales_urls.csv`

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

**Key**: URL slug is different per language (Arabic vs English product name in path), but the PID suffix (`BAG219542223xBLK`) is identical. Language derivation is purely from hostname.

```python
def get_language(url: str) -> str:
    hostname = urlparse(url).hostname or ''
    return 'EN' if hostname.startswith('en.') else 'AR'
```

---

## PLP Structure & Pagination

Platform: SFCC `Search-UpdateGrid` endpoint.

**Page 1** (SSR): Load `https://{domain}/{category-slug}/` → 48 products embedded in HTML  
**Pages 2+**: Call `Search-UpdateGrid` API in a loop until no more products:

```
GET https://{domain}/on/demandware.store/Sites-BloomingDales_SA-Site/{locale}/Search-UpdateGrid
    ?cgid={category_id}&start={offset}&sz=48
```

Where:
- `{domain}` = `bloomingdales.sa` (AR) or `en.bloomingdales.sa` (EN)
- `{locale}` = `ar_SA` or `en_SA`
- `{category_id}` = from the PLP URL slug, e.g., `women-womens-bags-cross-body-bags`
- `{offset}` = starts at 48, increments by 48

**Stop condition**: API response has 0 `data-pid` attributes (no more products).

**Product link extraction from PLP HTML**:
```python
import re
from urllib.parse import urlparse

def get_pdp_urls(html: str, base_url: str) -> list[str]:
    base = f'{urlparse(base_url).scheme}://{urlparse(base_url).netloc}'
    links = re.findall(r'href="(/[^"]*-[A-Z]{2,}[0-9]{6,}x[^"]+\.html)"', html)
    return [f'{base}{l}' for l in dict.fromkeys(links)]
```

The PID regex (`-[A-Z]{2,}[0-9]{6,}x[^"]+\.html`) distinguishes product PDPs from navigation links (like `/women.html`, `/designer/hermes.html`).

**Category ID extraction** (for the UpdateGrid API):
```python
def get_category_id(url: str) -> str:
    # /womens-bags-cross-body-bags/ → women-womens-bags-cross-body-bags
    slug = urlparse(url).path.strip('/')
    return 'women-' + slug if not slug.startswith('women-') else slug
```

Note: Probe confirmed `cgid=women-womens-bags-cross-body-bags` from the PLP `js-show-more-btn`'s `data-url` attribute. Extract it dynamically from the button rather than hardcoding.

```python
def get_cgid(html: str) -> str | None:
    m = re.search(r'cgid=([^&"]+)', html)
    return m.group(1) if m else None
```

---

## PDP Extraction

### JSON-LD `@type: Product` (primary source — confirmed stable)

```python
import json, re

def extract_jsonld_product(html: str) -> dict | None:
    blocks = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL | re.IGNORECASE,
    )
    for b in blocks:
        try:
            d = json.loads(b.strip())
            if d.get('@type') == 'Product':
                return d
        except Exception:
            pass
    return None
```

**Field map from live probe** (Marc Jacobs Scene Vanity Bag + Khaite Kye Mini Crossbody Bag):

```python
def extract_product(html: str, url: str) -> dict:
    product = extract_jsonld_product(html)
    offers  = product.get('offers') or {}

    images = product.get('image') or []
    if isinstance(images, str):
        images = [images]

    return {
        'portal_itemid': extract_pid(url),              # BAG219542223xBLK (from URL)
        'product_name':  product.get('name', '').strip(),
        'brand':         (product.get('brand') or {}).get('name'),
        'price':         float(offers.get('price') or 0) or None,
        'currency':      offers.get('priceCurrency'),    # SAR
        'out_of_stock':  'OutOfStock' in (offers.get('availability') or ''),
        'image_urls':    [img for img in images if img],
        'description':   product.get('description'),    # HTML in EN, HTML in AR
        'category':      extract_category(html),        # from DOM breadcrumbs
        'subcategory':   extract_subcategory(html),     # from DOM breadcrumbs
        'gender':        extract_gender(html),           # from DOM breadcrumbs
        'color':         extract_color(html),            # from data-attr-value="color"
        'sizes':         extract_sizes(html),            # from data-attr-value size attributes
    }
```

### portal_itemid — from URL

The URL PID (e.g., `BAG219542223xBLK`) is the preferred `portal_itemid`:
- Language-independent (same in EN and AR URLs)
- Includes color code (variant-level)
- Directly extractable without HTML parsing

```python
def extract_pid(url: str) -> str | None:
    m = re.search(r'-([A-Z]{2,}\d{5,}x[^/]+)\.html$', url, re.IGNORECASE)
    return m.group(1).upper() if m else None
```

The JSON-LD also has `sku` (e.g., `219542250`) which is SFCC's internal numeric variant ID. Both are unique per color variant. Use URL PID as `portal_itemid`; store `sku` as a secondary reference if needed.

### Category & Subcategory — from DOM microdata breadcrumbs

No BreadcrumbList in JSON-LD. Use HTML microdata:

```html
<ol itemscope itemtype="http://schema.org/BreadcrumbList">
  <li itemprop="itemListElement" ...>
    <meta itemprop="position" content="1"> → brand (Marc Jacobs)
    <meta itemprop="position" content="2"> → gender (Women)
    <meta itemprop="position" content="3"> → category (Women's Bags)
    <meta itemprop="position" content="4"> → subcategory (Crossbody Bags)
    <meta itemprop="position" content="5"> → product name
  </li>
</ol>
```

Also available in a single JS string: `"category": "Women/Women's Bags/Crossbody Bags/Marc Jacobs"` (parse by splitting on `/`).

```python
def extract_breadcrumbs(html: str) -> list[str]:
    bc_block = re.search(
        r'<ol[^>]+itemtype="http://schema\.org/BreadcrumbList"[^>]*>(.*?)</ol>',
        html, re.DOTALL,
    )
    if not bc_block:
        return []
    return re.findall(r'<span[^>]*itemprop="name"[^>]*>([^<]+)</span>', bc_block.group(1))
    # Returns ['Marc Jacobs', 'Women', "Women's Bags", 'Crossbody Bags', 'Scene Vanity Bag']
    # index 1 = gender, index 2 = category, index 3 = subcategory

def extract_gender(html: str) -> str | None:
    crumbs = extract_breadcrumbs(html)
    return crumbs[1].strip() if len(crumbs) > 1 else None

def extract_category(html: str) -> str | None:
    crumbs = extract_breadcrumbs(html)
    return crumbs[2].strip() if len(crumbs) > 2 else None

def extract_subcategory(html: str) -> str | None:
    crumbs = extract_breadcrumbs(html)
    return crumbs[3].strip() if len(crumbs) > 3 else None
```

### Color — from DOM swatch attribute

```python
def extract_color(html: str) -> str | None:
    # Find color attrs; the selected one matches the URL PID suffix
    colors = re.findall(r'data-attr="color"[^>]*data-attr-value="([^"]+)"', html)
    return colors[0].title() if colors else None  # 'blk' → 'Blk'; 'Burgundy' → 'Burgundy'
    # TODO: add normalization map for common codes (BLK→Black, WHT→White, etc.)
```

Better: extract the currently-active color by matching the URL PID suffix.

```python
def extract_color(html: str, url: str) -> str | None:
    pid = extract_pid(url) or ''
    color_code = pid.split('x', 1)[-1].lower() if 'x' in pid else ''
    # Find the color attr that matches; return its display name if available
    m = re.search(rf'data-attr-value="{re.escape(color_code)}"', html, re.IGNORECASE)
    return color_code.title() if m else None
```

### Sizes — from DOM swatch attribute

```python
def extract_sizes(html: str) -> list[str]:
    sizes = re.findall(r'data-attr="size"[^>]*data-attr-value="([^"]+)"', html)
    return [s for s in dict.fromkeys(sizes) if s and s != 'onesize'] or (['one size'] if sizes else [])
```

---

## Full Field Map

| Field | Source | Notes |
|-------|--------|-------|
| `run_id` | spider | Standard |
| `site` | constants | `'bloomingdales'` |
| `crawl_date` | spider | YYYY-MM-DD |
| `url` | response.url | PDP URL including PID |
| `country` | TLD | Always `'SA'` |
| `language` | hostname | `en.bloomingdales.sa` → `EN`, else `AR` |
| `portal_itemid` | URL PID regex | `BAG219542223xBLK` |
| `product_name` | JSON-LD `name` | In crawled language |
| `brand` | JSON-LD `brand.name` | Latin script, language-independent |
| `price` | JSON-LD `offers.price` | Float |
| `currency` | JSON-LD `offers.priceCurrency` | Always `'SAR'` |
| `out_of_stock` | JSON-LD `offers.availability` | `OutOfStock` check |
| `image_urls` | JSON-LD `image[]` | 6 images per product; list |
| `category` | DOM breadcrumb position 3 | In crawled language |
| `subcategory` | DOM breadcrumb position 4 | In crawled language |
| `gender` | DOM breadcrumb position 2 | `Women`, `Men`, `Kids` |
| `color` | `data-attr-value` (color, matching URL PID) | Lowercase code; title-case |
| `sizes` | `data-attr-value` (size) | List; `onesize` → `one size` |
| `price_discount` | DOM badge or price element | NULL if not on sale |
| `primary_label` | DOM sale badge | `['SALE']` etc. |
| `text` | JSON-LD `description` | HTML string; strip tags for plain text |

---

## Raw HTML vs Extract-on-Crawl Decision

**Extract-on-crawl.** JSON-LD is the primary source (stable, SEO-maintained). DOM breadcrumb extraction is simple regex. No reason to store raw HTML — cost and complexity not justified.

If extraction logic needs updating, the re-crawl is cheap (no Zyte, direct requests).

---

## Files to Create

| File | Status |
|------|--------|
| `scripts/probe_bloomingdales.py` | ✓ Written and validated |
| `resources/bloomingdales_urls.csv` | ✓ Exists — update with EN + AR seeds |
| `tests/fixtures/bloomingdales_plp.html` | ✓ Saved by probe |
| `tests/fixtures/bloomingdales_pdp.html` | ✓ Saved by probe (AR PDP) |
| `ecommercecrawl/constants/bloomingdales_constants.py` | TODO |
| `ecommercecrawl/rules/bloomingdales_rules.py` | TODO |
| `ecommercecrawl/spiders/bloomingdales_crawl.py` | TODO |
| `tests/test_bloomingdales_rules.py` | TODO — after rules |

---

## Constants Sketch

```python
# ecommercecrawl/constants/bloomingdales_constants.py

NAME = 'bloomingdales'
MAIN_SITE_AR = 'https://bloomingdales.sa/'
MAIN_SITE_EN = 'https://en.bloomingdales.sa/'
BLOOMINGDALES_URLS = 'resources/bloomingdales_urls.csv'
OUTPUT_DIR = 'output'

# SFCC site ID for UpdateGrid API
SFCC_SITE_ID = 'BloomingDales_SA-Site'

LOCALE_MAP = {
    'AR': 'ar_SA',
    'EN': 'en_SA',
}

def update_grid_url(domain: str, cgid: str, start: int, sz: int = 48) -> str:
    locale = 'ar_SA' if not domain.startswith('en.') else 'en_SA'
    return (
        f'https://{domain}/on/demandware.store/Sites-{SFCC_SITE_ID}/{locale}'
        f'/Search-UpdateGrid?cgid={cgid}&start={start}&sz={sz}'
    )
```

---

## Spider Sketch

```python
class BloomingdalesSpider(MasterCrawl, scrapy.Spider):
    name = constants.NAME
    default_urls_path_setting = 'BLOOMINGDALES_URLS_PATH'
    default_urls_path_constant = constants.BLOOMINGDALES_URLS

    def parse_plp(self, response):
        # 1. Extract products from this page
        pdp_urls = rules.get_pdp_urls(response.text, response.url)
        for url in pdp_urls:
            yield scrapy.Request(url, callback=self.parse_pdp)

        # 2. If first page, start the UpdateGrid loop for subsequent pages
        if rules.is_first_plp_page(response.url):
            cgid = rules.get_cgid(response.text)
            domain = urlparse(response.url).netloc
            start = 48
            while True:
                api_url = constants.update_grid_url(domain, cgid, start)
                # Fetch synchronously to check stop condition, or use Scrapy recursion
                yield scrapy.Request(api_url, callback=self.parse_plp_page,
                                     meta={'start': start, 'cgid': cgid, 'domain': domain})
                break  # let parse_plp_page recurse

    def parse_plp_page(self, response):
        pdp_urls = rules.get_pdp_urls(response.text, response.url)
        if not pdp_urls:
            return  # no more products
        for url in pdp_urls:
            yield scrapy.Request(url, callback=self.parse_pdp)
        # Request next page
        start = response.meta['start'] + 48
        cgid = response.meta['cgid']
        domain = response.meta['domain']
        yield scrapy.Request(
            constants.update_grid_url(domain, cgid, start),
            callback=self.parse_plp_page,
            meta={'start': start, 'cgid': cgid, 'domain': domain},
        )

    def parse_pdp(self, response):
        data = {
            'run_id': self.run_id,
            'site': constants.NAME,
            'crawl_date': date.today().strftime('%Y-%m-%d'),
            'url': response.url,
            'country': 'SA',
            'language': rules.get_language(response.url),
            **rules.extract_product(response.text, response.url),
        }
        yield data

    def parse(self, response):
        if rules.is_plp(response.url):
            yield from self.parse_plp(response)
        elif rules.is_pdp(response.url):
            yield from self.parse_pdp(response)
```

---

## Seed URLs

Update `resources/bloomingdales_urls.csv` to include EN + AR PLPs:

```csv
url,category
https://bloomingdales.sa/womens-bags-cross-body-bags/,plp
https://en.bloomingdales.sa/womens-bags-cross-body-bags/,plp
https://bloomingdales.sa/womens-shoes/,plp
https://en.bloomingdales.sa/womens-shoes/,plp
https://bloomingdales.sa/womens-clothing/,plp
https://en.bloomingdales.sa/womens-clothing/,plp
```

---

## Quality Gate Exclusions

Add to `resources/quality_gate_exclusions.json`:
```json
{
  "bloomingdales": ["price_discount", "primary_label", "sizes", "color"]
}
```

`price_discount` and `primary_label` are NULL for most products. `color` is a best-effort DOM extraction. `sizes` many products are `one size` (bags) — confirm valid extraction.

---

## Smoke Test

| Type | URL | Validate |
|------|-----|----------|
| PLP (AR) | `bloomingdales.sa/womens-bags-cross-body-bags/` | ≥48 PDP URLs, pagination works (160 total) |
| PLP (EN) | `en.bloomingdales.sa/womens-bags-cross-body-bags/` | Same count, EN URLs |
| PDP (AR) | `...BAG219542223xBLK.html` | `language=AR`, `product_name` in Arabic, 6 images, `currency=SAR` |
| PDP (EN) | `en.bloomingdales.sa/...BAG219542223xBLK.html` | `language=EN`, `product_name` in English, same `portal_itemid` |
| Images | Any PDP | `image_urls` is list of ≥1 absolute HTTPS CDN URLs |
| Out of stock | Find a sold-out PDP | `out_of_stock=True` confirmed |

---

## Open Questions

- [ ] Validate `get_pdp_urls` PID regex against full category — are there product URLs that don't follow the `PID.html` pattern (e.g., gift cards, services)?
- [ ] Should `portal_itemid` use the URL PID (`BAG219542223xBLK`) or the JSON-LD `sku` (`219542250`)? URL PID is human-readable + includes color; JSON-LD sku is numeric SFCC internal. Recommendation: URL PID.
- [ ] Color normalization: `blk` → `Black`, `WHT` → `White` etc. Build a map or use raw lowercase code?
- [ ] Are men's and kids' categories structured the same way (`mens-shoes/`, `kids-bags/`)?
- [ ] How does `price_discount` appear on the page? Check a sale PDP to validate extraction.
- [ ] Does UpdateGrid pagination work the same on `en.bloomingdales.sa`? (Different locale in URL: `en_SA` vs `ar_SA`) — yes, confirmed from probe.
