import base64
import hashlib
import html as html_module
import json
import re
import secrets
from urllib.parse import parse_qs, unquote, urlparse

from ecommercecrawl.constants import bloomingdales_constants as constants

# Matches variant PID suffix: -BAG219542223xBLK.html or -ACC123456xLight___PastelPink.html
# Also matches numeric master-product URLs: -219019583.html (single-variant products like shoes)
_PDP_RE = re.compile(
    r'-([A-Z]{2,}\d{5,}x[^/\s.]+|\d{7,})\.html$',
    re.IGNORECASE,
)

# PLP href pattern: relative URL containing the PID suffix (variant or numeric master)
_PLP_HREF_RE = re.compile(
    r'href="(/[^"]*-(?:[A-Z]{2,}\d{5,}x[^"]+|\d{7,})\.html)"',
    re.IGNORECASE,
)

# Common 3-letter SFCC color codes that are not self-describing
_COLOR_CODES = {
    'blk': 'Black', 'wht': 'White', 'bge': 'Beige', 'crm': 'Cream',
    'nvy': 'Navy', 'blu': 'Blue', 'grn': 'Green', 'grg': 'Grey',
    'gry': 'Grey', 'red': 'Red', 'pnk': 'Pink', 'prp': 'Purple',
    'org': 'Orange', 'yel': 'Yellow', 'brn': 'Brown', 'tan': 'Tan',
    'gld': 'Gold', 'slv': 'Silver', 'mlt': 'Multicolor', 'mult': 'Multicolor',
}


def get_language(url: str) -> str:
    """'EN' for en.bloomingdales.*, 'AR' for bloomingdales.* (no en. prefix)."""
    hostname = urlparse(url).hostname or ''
    return 'EN' if hostname.startswith('en.') else 'AR'


def is_plp(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path or ''
    netloc = parsed.netloc or ''
    return (
        'bloomingdales.' in netloc
        and not path.endswith('.html')
        and 'demandware.store' not in path
        and len(path.strip('/')) > 0
    )


def is_pdp(url: str) -> bool:
    parsed = urlparse(url)
    return (
        'bloomingdales.' in (parsed.netloc or '')
        and parsed.path.endswith('.html')
        and bool(_PDP_RE.search(parsed.path))
    )


def extract_pid(url: str, html: str = '') -> str | None:
    """
    Extract variant PID from the URL slug.
    /marc-jacobs-scene-vanity-bag-BAG219542223xBLK.html → 'BAG219542223XBLK'
    For numeric-only master URLs (e.g. -219019583.html), falls back to the
    js-product-id-vg DOM element which holds the selected variant PID.
    """
    m = _PDP_RE.search(urlparse(url).path)
    if not m:
        return None
    raw = m.group(1)
    # If URL has a variant PID (contains 'x'), return it uppercased
    if re.search(r'[A-Za-z]', raw):
        return raw.upper()
    # Numeric master ID — try to get the actual selected variant PID from DOM
    if html:
        dom_m = re.search(r'class="js-product-id-vg">([^<]+)<', html)
        if dom_m:
            return dom_m.group(1).strip().upper()
    return raw.upper()


_COMMERCE_API_RE = re.compile(r'"commerceAPI":\{"proxyPath":"([^"]*)","parameters":(\{[^}]*\})')


def get_commerce_api(html: str) -> dict | None:
    """
    The listing page's Commerce API settings: the site's proxy path and the
    public client settings its own browser code uses. None if the page has
    none (an older page layout).
    """
    m = _COMMERCE_API_RE.search(html or '')
    if not m:
        return None
    try:
        params = json.loads(m.group(2))
        proxy_path = json.loads(f'"{m.group(1)}"')   # undoes \u002F escapes
    except ValueError:
        return None
    keys = {'client_id': 'clientId', 'organization_id': 'organizationId', 'site_id': 'siteId'}
    api = {k: params.get(v) for k, v in keys.items()}
    if not all(api.values()) or not proxy_path.startswith('/'):
        return None
    api['proxy_path'] = proxy_path
    return api


def get_listing_cgid(html: str) -> str | None:
    """The listing's category ID, from the product search the page itself ran."""
    m = re.search(r'refine_1=cgid%3D([^&"\'\\]+)', html or '')
    if m:
        return unquote(m.group(1))
    m = re.search(r'"refine"\s*:\s*\[\s*"cgid=([^"\\]+)"', html or '')
    return m.group(1) if m else None


def get_country(url: str) -> str:
    """'SA' for bloomingdales.sa / en.bloomingdales.sa."""
    return (urlparse(url).hostname or '').rsplit('.', 1)[-1].upper()


def get_search_locale(url: str) -> str:
    """'en-SA' / 'ar-SA': the product search's locale for this listing."""
    return f'{get_language(url).lower()}-{get_country(url)}'


def get_currency(url: str) -> str:
    return constants.CURRENCY_BY_COUNTRY.get(get_country(url), 'SAR')


def pkce_pair() -> tuple[str, str]:
    """(verifier, challenge) for the guest login, as the browser makes them."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b'=').decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    return verifier, challenge


def get_guest_code(location: str) -> tuple[str | None, str | None]:
    """(code, usid) from the guest login's redirect Location."""
    query = parse_qs(urlparse(location or '').query)
    return (query.get('code') or [None])[0], (query.get('usid') or [None])[0]


def _slug(text: str) -> str:
    return re.sub(r'[^A-Za-z0-9]+', '-', (text or '').strip()).strip('-')


def build_pdp_url(listing_url: str, hit: dict) -> str | None:
    """
    The product page URL for a product search hit, in the site's own form:
    <brand, lower case>-<English product name>-<product ID>.html, on the
    listing's host (both languages use the English slug). Matches the
    listing's own links (checked on 25 of 25, both languages, 2026-11-18).
    """
    pid = (hit or {}).get('productId')
    brand = _slug(hit.get('c_brand_en') or hit.get('c_brand') or '').lower() if pid else ''
    name = _slug(hit.get('c_name_en') or hit.get('productName') or '') if pid else ''
    if not (pid and brand and name):
        return None
    parsed = urlparse(listing_url)
    return f'{parsed.scheme}://{parsed.netloc}/{brand}-{name}-{pid}.html'


def get_pdp_urls(response) -> list[str]:
    """
    Extract all product-variant PDP URLs from a listing page (its first,
    server-rendered batch).
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


def _extract_jsonld_breadcrumbs(html: str) -> list[str]:
    blocks = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL | re.IGNORECASE,
    )
    for b in blocks:
        try:
            d = json.loads(b.strip())
        except Exception:
            continue
        if not isinstance(d, dict) or d.get('@type') != 'BreadcrumbList':
            continue
        elements = sorted(
            (e for e in d.get('itemListElement') or [] if isinstance(e, dict)),
            key=lambda e: e.get('position') or 0,
        )
        names = []
        for e in elements:
            item = e.get('item')
            name = (item.get('name') if isinstance(item, dict) else None) or e.get('name')
            names.append(html_module.unescape(name).strip() if isinstance(name, str) else None)
        return names
    return []


def _extract_breadcrumbs(html: str) -> list[str]:
    """
    Parse the BreadcrumbList.
    Returns [brand, gender, category, subcategory, product_name] (by position).
    Bloomingdales moved from HTML microdata to JSON-LD (seen 2026-11-10);
    JSON-LD is read first and microdata is kept as a fallback.
    """
    crumbs = _extract_jsonld_breadcrumbs(html)
    if crumbs:
        return crumbs
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


def _li_texts(ul_html: str) -> list[str]:
    items = re.findall(r'<li[^>]*>(.*?)</li>', ul_html, re.DOTALL | re.IGNORECASE)
    result = []
    for li in items:
        text = re.sub(r'<[^>]+>', ' ', li)
        text = html_module.unescape(re.sub(r'\s+', ' ', text).strip())
        if text:
            result.append(text)
    return result


_DETAILS_LABEL_RE = re.compile(
    r'<b>(?:Details\s*(?:&amp;|&)\s*Care|التفاصيل[^<]*)</b>',
    re.IGNORECASE,
)

def _extract_details_and_care(html: str) -> list[str] | None:
    # EN: <b>Details & Care</b>  |  AR: <b>التفاصيل وإرشادات العناية:</b>
    # SFCC may omit </ul>, so use a character window rather than relying on </ul>.
    m = _DETAILS_LABEL_RE.search(html)
    if not m:
        return None
    chunk = html[m.end():m.end() + 800]
    result = _li_texts(chunk)
    return result or None


def _extract_size_fit(html: str) -> list[str] | None:
    # Locate #pdp-sizeandfit, then grab <li> items within a tight window.
    # SFCC renders the <ul> without a closing </ul> on some products, so we
    # must not rely on </ul> as a terminator — a character window is safer.
    m = re.search(r'id=["\']pdp-sizeandfit["\']', html, re.IGNORECASE)
    if not m:
        return None
    # 800 chars is enough for ~15 dimension lines but stops well before any nav.
    chunk = html[m.start():m.start() + 800]
    result = _li_texts(chunk)
    return result or None


def extract_color(html: str, url: str) -> str | None:
    pid = extract_pid(url, html) or ''
    # extract_pid uppercases the whole PID, so separator is 'X'
    if 'X' not in pid:
        return None
    code = pid.split('X', 1)[-1].lower()
    if code in _COLOR_CODES:
        return _COLOR_CODES[code]
    # Multi-word codes use underscores: 'light___pastelpink' → 'Light Pastelpink'
    return re.sub(r'_+', ' ', code).strip().title()


def extract_sizes(html: str) -> list[str] | None:
    # Cross-sell carousels on the PDP also render size swatches for other products.
    # Main product size buttons always have data-url; carousel tiles don't.
    raw = []
    for btn in re.findall(r'<button\b[^>]*>', html, re.IGNORECASE):
        if 'data-url=' in btn and 'data-attr="size"' in btn:
            m = re.search(r'data-attr-value="([^"]+)"', btn)
            if m:
                raw.append(m.group(1))
    if not raw:
        return None
    result = []
    for s in dict.fromkeys(raw):
        low = s.lower().replace('_', '')
        result.append('One Size' if low in ('onesize', 'os') else s)
    return result or None


def extract_price_discount(html: str) -> str | None:
    m = re.search(
        r'class="[^"]*(?:blm-price__percentage|percent-off|sale-price|discount-label)[^"]*"[^>]*>\s*([^<]*\d+\s*%[^<]*)<',
        html, re.IGNORECASE,
    )
    return m.group(1).strip() if m else None


def extract_was_price(html: str) -> float | None:
    # Original/slashed price lives in blm-price__standard — only present when on sale
    m = re.search(
        r'class="[^"]*blm-price__standard[^"]*"[^>]*>.*?content="(\d+(?:\.\d+)?)"',
        html, re.DOTALL | re.IGNORECASE,
    )
    return float(m.group(1)) if m else None


def extract_primary_label(html: str) -> list[str] | None:
    # Anchor to blm-pdpmain__badges to avoid carousel tile badges (same class, different container)
    m = re.search(r'class="[^"]*blm-pdpmain__badges[^"]*"', html, re.IGNORECASE)
    if not m:
        return None
    chunk = html[m.start():m.start() + 600]
    labels = re.findall(
        r'class="[^"]*blm-badge[^"]*"[^>]*>\s*([^\s<][^<]{0,58}?)\s*<',
        chunk, re.IGNORECASE,
    )
    unique = list(dict.fromkeys(b.strip() for b in labels if b.strip()))
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
        'portal_itemid': extract_pid(url, html),
        'product_name':  (product.get('name') or '').strip(),
        'brand':         (product.get('brand') or {}).get('name') if isinstance(product.get('brand'), dict) else product.get('brand'),
        'gender':        crumbs[1] if len(crumbs) > 1 else None,
        'category':      crumbs[2] if len(crumbs) > 2 else None,
        'subcategory':   crumbs[3] if len(crumbs) > 3 else None,
        'price':         float(offers['price']) if offers.get('price') is not None else None,
        'currency':      offers.get('priceCurrency'),
        'out_of_stock':  'OutOfStock' in (offers.get('availability') or ''),
        'image_urls':    [img for img in images if img],
        'text': (lambda t: t if any(v is not None for v in t.values()) else None)({
            'description': _strip_html(product.get('description')),
            'details':     _extract_details_and_care(html),
            'size_fit':    _extract_size_fit(html),
        }),
        'color':         extract_color(html, url),
        'sizes':         extract_sizes(html),
        'price_discount': extract_price_discount(html),
        'was_price':      extract_was_price(html),
        'primary_label': extract_primary_label(html),
    }
