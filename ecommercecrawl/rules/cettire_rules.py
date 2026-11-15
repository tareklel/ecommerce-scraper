"""
Extraction rules for Cettire (Saudi storefront).

Two sources (notes/2026-11-14-cettire-research.md):
- the search service response ("hit"): names in both languages, brand,
  category, price, stock, colour, size and 3-4 images per product;
- the product page HTML: a __NEXT_DATA__ script holding an Apollo cache with
  the description, composition, dimensions and the full image gallery
  (English only).
"""
import json
import re
import unicodedata
from urllib.parse import urlparse

from ecommercecrawl.constants import cettire_constants as constants

_COLLECTION_RE = re.compile(r'^/([a-z]{2})/collections/([^/]+)(?:/([^/]+))?/?$')
_PRODUCT_RE = re.compile(r'^/([a-z]{2})/products/([^/]+)')
_HANDLE_ID_RE = re.compile(r'-(\d+)$')
_NEXT_DATA_RE = re.compile(r'__NEXT_DATA__\s*=\s*')
_BR_RE = re.compile(r'<br\s*/?>', re.IGNORECASE)
_TAG_RE = re.compile(r'<[^>]+>')

# Listing image fields in display order; the first is the product card image.
_HIT_IMAGE_FIELDS = ('largeImage', 'image_set2_url', 'media_medium', 'set3_medium')
# Product page image sizes, best first.
_PDP_IMAGE_SIZES = ('original', 'large', 'medium')


# ---------------------------------------------------------------- URLs

def is_plp(url: str) -> bool:
    parsed = urlparse(url)
    return 'cettire.com' in (parsed.netloc or '') and bool(_COLLECTION_RE.match(parsed.path or ''))


def is_pdp(url: str) -> bool:
    parsed = urlparse(url)
    return 'cettire.com' in (parsed.netloc or '') and bool(_PRODUCT_RE.match(parsed.path or ''))


def get_country(url: str) -> str | None:
    """Country from the path prefix: /sa/... -> 'SA'."""
    m = re.match(r'^/([a-z]{2})/', urlparse(url).path or '')
    return m.group(1).upper() if m else None


def listing_query(url: str) -> dict:
    """
    Turn a listing URL into the search service's category filters.

    /sa/collections/womens-bags/shoulder-bags ->
        {'department': 'women', 'catQuery': 'bags', 'subCatQuery': 'shoulder bags'}
    The first path part is "<department>s-<category>"; the optional second
    part is the subcategory.
    """
    m = _COLLECTION_RE.match(urlparse(url).path or '')
    if not m:
        raise ValueError(f'Not a Cettire listing URL: {url}')
    _, first, second = m.groups()
    dept_m = re.match(r'^(women|men|kid)s-(.+)$', first)
    if not dept_m:
        raise ValueError(f'Cannot read department and category from listing URL: {url}')
    department = 'kids' if dept_m.group(1) == 'kid' else dept_m.group(1)
    return {
        'department': department,
        'catQuery': dept_m.group(2).replace('-', ' '),
        'subCatQuery': second.replace('-', ' ') if second else '',
    }


def product_url(handle: str) -> str:
    return f'{constants.MAIN_SITE}/{constants.REGION_CODE}/products/{handle}'


def portal_itemid_from_handle(handle: str | None) -> str | None:
    """The numeric ID that ends every product slug: '...-bag-931787070' -> '931787070'."""
    m = _HANDLE_ID_RE.search(handle or '')
    return m.group(1) if m else None


# ---------------------------------------------------------------- search request

def build_search_body(query: dict, vendors=None, page_size=constants.SEARCH_PAGE_SIZE,
                      request_id: str = '', device_info: dict | None = None) -> dict:
    """The JSON body the site's own listing page sends, with our filters."""
    body = {
        'userVipLevel': 0,
        'countryCode': constants.COUNTRY,
        'regionCode': constants.REGION_CODE,
        'currencyCode': constants.CURRENCY,
        'langCode': constants.SEARCH_LANG,
        'productQueryInfo': {
            'query': '',
            'rankingType': 'rank_score',
            'department': query['department'],
            'catQuery': query['catQuery'],
            'subCatQuery': query.get('subCatQuery', ''),
            'cat3Query': '',
            'designNumberQuery': '',
            'tagQuery': [],
            'seasonQuery': [],
            # Brand names exactly as the "vendor" facet spells them.
            'vendorQuery': list(vendors or []),
            'colorQuery': [],
            'sizeQuery': [],
            'comparePriceQuery': False,
            'pageSize': page_size,
            'rollbackRequest': False,
            'returnCat3Facets': True,
            'returnHMFacet': True,
            'currentPage': 0,
        },
        'blockProductRules': [],
    }
    if request_id:
        body['requestId'] = request_id
    if device_info:
        body['deviceInfo'] = device_info
    return body


def normalize_brand(name: str | None) -> str:
    """Accent-, case- and punctuation-insensitive brand key ('Chloé' == 'CHLOE')."""
    text = unicodedata.normalize('NFKD', name or '').encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', ' ', text.replace('&', ' and ')).strip()


def vendor_counts(payload: dict | None) -> dict:
    """Brand -> product count from a search response's facets."""
    facets = (payload or {}).get('facets') or {}
    vendors = facets.get('vendor')
    return dict(vendors) if isinstance(vendors, dict) else {}


def allowed_vendor_counts(counts: dict, allowlist) -> dict:
    """Keep only brands on the allowlist. An empty allowlist keeps every brand."""
    keys = {normalize_brand(name) for name in (allowlist or []) if normalize_brand(name)}
    if not keys:
        return dict(counts)
    return {name: n for name, n in counts.items() if normalize_brand(name) in keys}


def pack_brand_groups(counts: dict, max_products=constants.BRAND_GROUP_MAX_PRODUCTS) -> list[list[str]]:
    """
    Split brands into groups whose listed totals stay under max_products, so
    each group fits in one search response. Largest brands first; a brand
    bigger than the cap gets a group of its own (its tail will be missed and
    shows up in the completeness check).
    """
    groups, current, total = [], [], 0
    for name, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        if current and total + n > max_products:
            groups.append(current)
            current, total = [], 0
        current.append(name)
        total += n
    if current:
        groups.append(current)
    return groups


def get_hits(payload: dict | None) -> list[dict]:
    """The products of a search response, each as its flat `variantData` dict."""
    hits = []
    for product in (payload or {}).get('products') or []:
        data = product.get('variantData') if isinstance(product, dict) else None
        if isinstance(data, dict):
            hits.append(data)
    return hits


# ---------------------------------------------------------------- search hit -> fields

def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def hit_price(hit: dict) -> float | None:
    return _number(hit.get('sa_sar_price_f'))


def hit_was_price(hit: dict) -> float | None:
    """The pre-sale price, only when it is higher than the selling price."""
    price, before = hit_price(hit), _number(hit.get('sa_sar_compare_at_price_f'))
    if price is None or before is None or before <= price:
        return None
    return before


def discount_percent(price: float | None, was_price: float | None):
    """
    Whole-number discount percentage. Cettire sends no discount label, so it
    is computed. 0 means "known full price"; None means the price itself was
    not observed (silver keeps the previous value on None, so a real 0 is what
    clears an ended sale; same rule as Ounass).
    """
    if price is None:
        return None
    if was_price is None or was_price <= price:
        return 0
    return round((was_price - price) / was_price * 100)


def hit_image_urls(hit: dict) -> list[str] | None:
    urls = []
    for field in _HIT_IMAGE_FIELDS:
        value = hit.get(field)
        if isinstance(value, str) and value.startswith('http') and value not in urls:
            urls.append(value)
    return urls or None


def hit_gender(hit: dict) -> str | None:
    department = hit.get('department')
    if isinstance(department, list):
        department = department[0] if department else None
    return str(department).lower() if department else None


def hit_sizes(hit: dict) -> list[str] | None:
    size = hit.get('Size')
    return [size.strip()] if isinstance(size, str) and size.strip() else None


def hit_out_of_stock(hit: dict) -> bool:
    quantity = _number(hit.get('inventory_quantity'))
    # No stock figure: default to in stock, per the product schema.
    return quantity is not None and quantity <= 0


def rows_from_hit(hit: dict, run_id: str, crawl_date: str) -> list[dict]:
    """
    One search hit -> two rows (EN, AR) in the product schema. Returns [] when
    the hit has no usable ID. Fields the search service doesn't have (`text`,
    `primary_label`) are None; the product page fills `text` for the EN row.
    """
    handle = hit.get('handle')
    item_id = portal_itemid_from_handle(handle)
    if not item_id:
        return []
    price, was_price = hit_price(hit), hit_was_price(hit)
    shared = {
        'run_id': run_id,
        'site': constants.NAME,
        'crawl_date': crawl_date,
        'url': product_url(handle),
        'country': constants.COUNTRY,
        'portal_itemid': item_id,
        'brand': hit.get('vendor'),
        'gender': hit_gender(hit),
        # Colour comes in English only.
        'color': hit.get('Color'),
        'sizes': hit_sizes(hit),
        'price': price,
        'currency': constants.CURRENCY,
        'price_discount': discount_percent(price, was_price),
        'was_price': was_price,
        'out_of_stock': hit_out_of_stock(hit),
        'primary_label': None,
        'image_urls': hit_image_urls(hit),
        'text': None,
        # Kept for matching the same bag across sites.
        'designer_model_number': hit.get('designerModelNumber') or None,
        'designer_color': hit.get('designerColor') or None,
    }
    english = dict(shared, language='EN', product_name=hit.get('title'),
                   category=hit.get('category'), subcategory=hit.get('product_type'))
    arabic = dict(shared, language='AR', product_name=hit.get('title_ar'),
                  category=hit.get('category_ar'), subcategory=hit.get('product_type_ar'))
    return [english, arabic]


# ---------------------------------------------------------------- product page

def parse_next_data(html: str) -> dict | None:
    """The page's __NEXT_DATA__ object, or None when it is missing or broken."""
    m = _NEXT_DATA_RE.search(html or '')
    if not m:
        return None
    try:
        data, _ = json.JSONDecoder().raw_decode(html[m.end():])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def extract_search_api_key(html: str) -> str | None:
    """The search service key the site publishes in its page config."""
    config = (parse_next_data(html) or {}).get('runtimeConfig') or {}
    key = config.get(constants.API_KEY_CONFIG_FIELD)
    return key if isinstance(key, str) and key else None


def _apollo(next_data: dict | None) -> dict:
    state = ((next_data or {}).get('props') or {}).get('apolloState') or {}
    data = state.get('data')
    return data if isinstance(data, dict) else {}


def _deref(cache: dict, ref):
    """Follow an Apollo cache reference ({"id": ...}); other values pass through."""
    if isinstance(ref, dict) and ref.get('type') == 'id' and 'id' in ref:
        return cache.get(ref['id'])
    return ref


def _product_node(cache: dict) -> dict | None:
    for value in cache.values():
        if isinstance(value, dict) and value.get('__typename') == 'CatalogProduct':
            return value
    return None


def _image_url(cache: dict, image_ref) -> str | None:
    image = _deref(cache, image_ref)
    sizes = _deref(cache, image.get('URLs')) if isinstance(image, dict) else None
    if not isinstance(sizes, dict):
        return None
    for size in _PDP_IMAGE_SIZES:
        if isinstance(sizes.get(size), str) and sizes[size].startswith('http'):
            return sizes[size]
    return None


def _gallery(cache: dict, product: dict) -> list[str] | None:
    media = product.get('media')
    if not isinstance(media, list):
        return None
    urls = []
    for ref in media:
        url = _image_url(cache, ref)
        if url and url not in urls:
            urls.append(url)
    return urls


def _variants(cache: dict, product: dict) -> list[dict]:
    out = []
    for ref in product.get('variants') or []:
        variant = _deref(cache, ref)
        if isinstance(variant, dict):
            out.append(variant)
    return out


def _region_price(cache: dict, variant: dict):
    """(price, compareAtPrice) of the variant's Saudi price entry."""
    for ref in variant.get('currencyPrices') or []:
        entry = _deref(cache, ref)
        if isinstance(entry, dict) and entry.get('regionCode') == constants.REGION_CODE:
            return _number(entry.get('price')), _number(entry.get('compareAtPrice'))
    return None, None


def _lines(html_text: str | None) -> list[str]:
    """Split '<br />'-separated copy into clean non-empty lines."""
    parts = _BR_RE.split(html_text or '')
    return [line for line in (_TAG_RE.sub('', p).strip() for p in parts) if line]


def _text(product: dict) -> dict | None:
    """
    Cettire has no prose paragraph: the copy is feature bullets plus
    composition, origin and dimensions. `description` therefore stays None.
    """
    highlights = product.get('highlights')
    bullets = highlights.get('json') if isinstance(highlights, dict) else highlights
    details = [b.strip() for b in bullets if isinstance(b, str) and b.strip()] if isinstance(bullets, list) else []
    if product.get('composition'):
        details.append(str(product['composition']).strip())
    if product.get('madeIn'):
        details.append(f"Made in {str(product['madeIn']).strip()}")
    size_fit = _lines(product.get('dimensions'))
    if not details and not size_fit:
        return None
    return {'description': None, 'details': details or None, 'size_fit': size_fit or None}


def _tag_names(cache: dict, product: dict) -> list[str]:
    connection = _deref(cache, product.get('tags'))
    nodes = connection.get('nodes') if isinstance(connection, dict) else None
    names = []
    for ref in nodes or []:
        tag = _deref(cache, ref)
        if isinstance(tag, dict) and tag.get('name'):
            names.append(tag['name'])
    return names


def extract_product(html: str) -> dict | None:
    """
    Product fields from a product page, or None when the page has no product
    data (blocked page, challenge page, layout change).
    """
    cache = _apollo(parse_next_data(html))
    product = _product_node(cache)
    if not product:
        return None

    variants = _variants(cache, product)
    in_stock = [v for v in variants if not v.get('isSoldOut')]
    # Price of the cheapest in-stock variant (any variant when all are sold out).
    priced = [(p, w) for p, w in (_region_price(cache, v) for v in (in_stock or variants)) if p is not None]
    price, compare = min(priced, key=lambda pw: pw[0]) if priced else (None, None)
    was_price = compare if (price is not None and compare is not None and compare > price) else None

    sizes = [v['size'].strip() for v in in_stock if isinstance(v.get('size'), str) and v['size'].strip()]
    colors = [v['color'] for v in variants if v.get('color')]
    tags = [t.lower() for t in _tag_names(cache, product)]
    gender = next((g for g in ('women', 'men', 'kids') if g in tags), None)
    handle = product.get('slug')

    return {
        'portal_itemid': portal_itemid_from_handle(handle),
        'product_name': product.get('title'),
        'brand': product.get('vendor'),
        'gender': gender,
        'color': colors[0] if colors else None,
        'sizes': sizes or None,
        'subcategory': product.get('productType'),
        'price': price,
        'currency': constants.CURRENCY if price is not None else None,
        'price_discount': discount_percent(price, was_price),
        'was_price': was_price,
        'out_of_stock': bool(product.get('isSoldOut')) or (bool(variants) and not in_stock),
        'image_urls': _gallery(cache, product),
        'text': _text(product),
        'designer_model_number': product.get('designerModelNumber') or None,
        'designer_color': product.get('designerColor') or None,
    }


def merge_pdp_into_rows(rows: list[dict], pdp: dict | None) -> list[dict]:
    """
    Add product-page fields to the rows built from the search hit.

    The search service stays the source for names, category, price, sizes
    and stock (it is read for every product on every run, and for the Saudi
    region). The product page adds the full gallery to every row and the
    English copy to the EN row, and fills anything the hit left blank.

    Stock is deliberately not taken from the page: the server-rendered page
    is built for the site's default region, and in the first live run
    (2026-11-14) it marked 10 of 40 products sold out that the Saudi search
    listed as in stock.
    """
    if not pdp:
        return rows
    merged = []
    for row in rows:
        out = dict(row)
        if pdp.get('image_urls'):
            out['image_urls'] = pdp['image_urls']
        if out.get('language') == 'EN' and pdp.get('text'):
            out['text'] = pdp['text']
        for key in ('brand', 'gender', 'color', 'sizes', 'price', 'currency', 'was_price',
                    'price_discount', 'designer_model_number', 'designer_color'):
            if out.get(key) is None and pdp.get(key) is not None:
                out[key] = pdp[key]
        if out.get('language') == 'EN':
            for key in ('product_name', 'subcategory'):
                if out.get(key) is None and pdp.get(key) is not None:
                    out[key] = pdp[key]
        merged.append(out)
    return merged
