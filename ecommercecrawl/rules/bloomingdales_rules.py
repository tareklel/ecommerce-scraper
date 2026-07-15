import html as html_module
import json
import re
from urllib.parse import urlparse

from ecommercecrawl.constants import bloomingdales_constants as constants

# Matches the PID suffix: -BAG219542223xBLK.html or -ACC123456xLight___PastelPink.html
_PDP_RE = re.compile(r'-([A-Z]{2,}\d{5,}x[^/]+)\.html$', re.IGNORECASE)

# PLP href pattern: relative URL containing the PID suffix
_PLP_HREF_RE = re.compile(r'href="(/[^"]*-[A-Z]{2,}\d{5,}x[^"]+\.html)"', re.IGNORECASE)

# Common 3-letter SFCC color codes that are not self-describing
_COLOR_CODES = {
    'blk': 'Black', 'wht': 'White', 'bge': 'Beige', 'crm': 'Cream',
    'nvy': 'Navy', 'blu': 'Blue', 'grn': 'Green', 'grg': 'Grey',
    'gry': 'Grey', 'red': 'Red', 'pnk': 'Pink', 'prp': 'Purple',
    'org': 'Orange', 'yel': 'Yellow', 'brn': 'Brown', 'tan': 'Tan',
    'gld': 'Gold', 'slv': 'Silver', 'mlt': 'Multicolor', 'mult': 'Multicolor',
}


def get_language(url: str) -> str:
    """'EN' for en.bloomingdales.sa, 'AR' for bloomingdales.sa."""
    hostname = urlparse(url).hostname or ''
    return 'EN' if hostname.startswith('en.') else 'AR'


def is_plp(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path or ''
    netloc = parsed.netloc or ''
    return (
        'bloomingdales.sa' in netloc
        and not path.endswith('.html')
        and 'demandware.store' not in path
        and len(path.strip('/')) > 0
    )


def is_pdp(url: str) -> bool:
    parsed = urlparse(url)
    return (
        'bloomingdales.sa' in (parsed.netloc or '')
        and parsed.path.endswith('.html')
        and bool(_PDP_RE.search(parsed.path))
    )


def is_first_plp_page(url: str) -> bool:
    """True for category URLs; False for UpdateGrid API responses."""
    return 'demandware.store' not in url


def extract_pid(url: str) -> str | None:
    """
    Extract variant PID from the URL slug.
    /marc-jacobs-scene-vanity-bag-BAG219542223xBLK.html → 'BAG219542223xBLK'
    """
    m = _PDP_RE.search(urlparse(url).path)
    return m.group(1).upper() if m else None


def get_cgid(html: str) -> str | None:
    """Extract SFCC category ID from the show-more button's data-url."""
    m = re.search(r'cgid=([^&"\']+)', html)
    return m.group(1) if m else None


def get_update_grid_url(source_url: str, cgid: str, start: int) -> str:
    """
    Build the SFCC Search-UpdateGrid URL for the next product batch.
    source_url is used only to determine domain and language.
    """
    parsed = urlparse(source_url)
    domain = parsed.netloc
    locale = constants.LOCALE_MAP.get(get_language(source_url), 'ar_SA')
    path = constants.UPDATE_GRID_PATH.format(
        site_id=constants.SFCC_SITE_ID, locale=locale,
    )
    return (
        f'https://{domain}{path}'
        f'?cgid={cgid}&start={start}&sz={constants.UPDATE_GRID_PAGE_SIZE}'
    )


def get_pdp_urls(response) -> list[str]:
    """
    Extract all product-variant PDP URLs from a PLP or UpdateGrid response.
    Each color variant is a separate href in SFCC PLPs, so all variants are captured.
    """
    base = f'{urlparse(response.url).scheme}://{urlparse(response.url).netloc}'
    hrefs = _PLP_HREF_RE.findall(response.text)
    return [f'{base}{h}' for h in dict.fromkeys(hrefs)]


# ---- PDP extraction helpers ----

def _extract_jsonld_product(html: str) -> dict | None:
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


def _extract_breadcrumbs(html: str) -> list[str]:
    """
    Parse HTML microdata BreadcrumbList.
    Returns [brand, gender, category, subcategory, product_name] (by position).
    Bloomingdales uses microdata, not JSON-LD, for breadcrumbs.
    """
    bc = re.search(
        r'<ol[^>]+itemtype="http://schema\.org/BreadcrumbList"[^>]*>(.*?)</ol>',
        html, re.DOTALL,
    )
    if not bc:
        return []
    spans = re.findall(r'<span[^>]*itemprop="name"[^>]*>([^<]+)</span>', bc.group(1))
    return [html_module.unescape(s).strip() for s in spans]


def _strip_html(raw: str | None) -> str | None:
    if not raw:
        return None
    text = re.sub(r'<[^>]+>', ' ', raw)
    text = html_module.unescape(text)
    return re.sub(r'\s+', ' ', text).strip() or None


def extract_color(html: str, url: str) -> str | None:
    pid = extract_pid(url) or ''
    # extract_pid uppercases the whole PID, so separator is 'X'
    if 'X' not in pid:
        return None
    code = pid.split('X', 1)[-1].lower()
    if code in _COLOR_CODES:
        return _COLOR_CODES[code]
    # Multi-word codes use underscores: 'light___pastelpink' → 'Light Pastelpink'
    return re.sub(r'_+', ' ', code).strip().title()


def extract_sizes(html: str) -> list[str] | None:
    raw = re.findall(r'data-attr="size"[^>]*data-attr-value="([^"]+)"', html)
    if not raw:
        return None
    result = []
    for s in dict.fromkeys(raw):
        low = s.lower().replace('_', '')
        result.append('One Size' if low in ('onesize', 'os') else s)
    return result or None


def extract_price_discount(html: str) -> str | None:
    m = re.search(
        r'class="[^"]*(?:percent-off|sale-price|discount-label)[^"]*"[^>]*>\s*([^<]*\d+\s*%[^<]*)<',
        html, re.IGNORECASE,
    )
    return m.group(1).strip() if m else None


def extract_primary_label(html: str) -> list[str] | None:
    labels = re.findall(
        r'class="[^"]*(?:callout|promo-flag|product-badge|badge-label)[^"]*"[^>]*>([^<]+)<',
        html, re.IGNORECASE,
    )
    unique = list(dict.fromkeys(b.strip() for b in labels if b.strip() and len(b.strip()) < 60))
    return unique or None


def extract_product(response) -> dict:
    """
    Extract all product fields from a Bloomingdales PDP response.
    Primary source: JSON-LD schema.org/Product.
    Category/gender: DOM microdata breadcrumbs (position 1-4).
    """
    html = response.text
    url = response.url

    product = _extract_jsonld_product(html)
    if not product:
        raise ValueError(f'No JSON-LD Product block on {url}')

    offers = product.get('offers') or {}
    images = product.get('image') or []
    if isinstance(images, str):
        images = [images]

    crumbs = _extract_breadcrumbs(html)
    # Confirmed order: [0]=brand, [1]=gender, [2]=category, [3]=subcategory, [4]=product_name

    return {
        'portal_itemid': extract_pid(url),
        'product_name':  (product.get('name') or '').strip(),
        'brand':         (product.get('brand') or {}).get('name') if isinstance(product.get('brand'), dict) else product.get('brand'),
        'gender':        crumbs[1] if len(crumbs) > 1 else None,
        'category':      crumbs[2] if len(crumbs) > 2 else None,
        'subcategory':   crumbs[3] if len(crumbs) > 3 else None,
        'price':         float(offers['price']) if offers.get('price') is not None else None,
        'currency':      offers.get('priceCurrency'),
        'out_of_stock':  'OutOfStock' in (offers.get('availability') or ''),
        'image_urls':    [img for img in images if img],
        'text':          _strip_html(product.get('description')),
        'color':         extract_color(html, url),
        'sizes':         extract_sizes(html),
        'price_discount': extract_price_discount(html),
        'primary_label': extract_primary_label(html),
    }
