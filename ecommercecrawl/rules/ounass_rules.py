import html as html_mod
import json
import re
import logging
from ecommercecrawl.constants.ounass_constants import TLD_LANGUAGE_MAP
from urllib.parse import urlparse

SOLD_OUT_LABELS_NORMALIZED = {
    "out of stock",
    "sold out",
    "نفدت الكمية",
}


def is_plp(response):
    try:
        data = json.loads(response.text)
    except Exception:
        return False

    return data.get("routeType") == "plp"

def get_max_pages(response):
    data = json.loads(response.text)
    return data['pagination']['totalPages']


def is_first_page(response):
    return json.loads(response.text)['page'] == 0

def get_pdps(response):
    """
    Extracts all unique product detail page (PDP) URLs from a PLP response.
    This includes both the main product slugs and slugs for configurable variations.
    """
    data = json.loads(response.text)
    hits = data.get('hits', [])

    # Extract primary slugs
    slugs = [hit.get('slug') for hit in hits]

    # Extract additional slugs for product variations
    additional_slugs = []
    for hit in hits:
        for attr in hit.get('configurableAttributes', []):
            for option in attr.get('options', []):
                try:
                    # Navigate through the nested structure to find the variation slug
                    slug = option['attributeSpecificProperties']['slug']
                    additional_slugs.append(slug)
                except (KeyError, TypeError):
                    # This will catch cases where keys are missing or a value is not a dictionary
                    pass

    # Combine, filter out None/empty values, deduplicate, and create full URLs
    all_slugs = slugs + additional_slugs
    unique_slugs = {slug for slug in all_slugs if slug}
    
    parsed_url = urlparse(response.url)
    base_address = f"{parsed_url.scheme}://{parsed_url.netloc}"
    urls = [f'{base_address}/{slug}.html' for slug in unique_slugs]
    return sorted(urls)


def is_pdp(response):
    return response.url.split('.')[-1] == 'html'


def get_state(response):
    """
    Extracts the window.state JSON object from a PDP response.

    This function is designed to be resilient to changes in the page structure.
    It includes robust error handling and logging to avoid scraper failures.
    """
    logger = logging.getLogger(__name__)

    # 1. Extract the script content
    try:
        script = response.xpath(
            "//script[contains(., '\"routeType\":\"new-pdp\"')]/text()"
        ).get()
        if not script:
            logger.warning(f"Could not find state script on page: {response.url}")
            return 
    except Exception as e:
        logger.error(f"Failed to extract script from {response.url}: {e}")
        return 

    # 2. Find the JSON object within the script
    try:
        state_match = re.search(r'window\.initialState\s*=\s*({.*?});', script, re.DOTALL)
        if not state_match:
            logger.warning(f"Could not find state JSON in script on page: {response.url}")
            return 
        state_json = state_match.group(1)
    except Exception as e:
        logger.error(f"Regex failed to find state JSON in {response.url}: {e}")
        return

    # 3. Parse the JSON
    try:
        return json.loads(state_json)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse state JSON from {response.url}: {e}")
        return

def safe_get(data, keys, default=None):
    """
    Safely retrieve a value from a nested dictionary.

    Args:
        data (dict): The dictionary to search.
        keys (list): A list of keys representing the path to the value.
        default: The value to return if the path is not found.

    Returns:
        The retrieved value or the default.
    """
    if not isinstance(data, dict):
        return default

    for key in keys:
        if not isinstance(data, dict):
            return default
        data = data.get(key)
        if data is None:
            return default
    return data

def _normalize_text(value):
    if not isinstance(value, str):
        return None
    # Collapse whitespace and normalize casing for label comparisons.
    return " ".join(value.split()).strip().casefold()


def _parse_stock_status_value(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = _normalize_text(value)
        if normalized is None:
            return None
        if normalized in {"in stock", "available", "instock"}:
            return False
        if normalized in SOLD_OUT_LABELS_NORMALIZED | {"outofstock"}:
            return True
    return None


def get_sold_out(state):
    # Prefer explicit stock flags/status fields if Ounass provides them.
    for path in (
        ['pdp', 'isOutOfStock'],
        ['pdp', 'outOfStock'],
        ['pdp', 'isSoldOut'],
        ['pdp', 'stockStatus'],
        ['pdp', 'stock_status'],
        ['pdp', 'availability'],
    ):
        parsed = _parse_stock_status_value(safe_get(state, path))
        if parsed is not None:
            return parsed

    # Fallback to badge text. Missing badge means "not sold out" by default.
    badge_value = safe_get(state, ['pdp', 'badge', 'value'])
    normalized_badge = _normalize_text(badge_value)
    if normalized_badge is None:
        return False
    return normalized_badge in SOLD_OUT_LABELS_NORMALIZED
    
def get_discount(state):
    try:
        return state['pdp']['discountPercent']
    except KeyError:
        return None

def get_primary_label(state):
    try:
        return state['pdp']['badge']['value']
    except Exception:
        return None
    
def get_image_url(state):
    try:
        return state['pdp']['images'][0]['oneX'].split('//')[1]
    except Exception:
        return None
    

def get_language(url):
    return TLD_LANGUAGE_MAP.get(url.split('https://')[-1].split('/')[0], None)


def _parse_tab_html(raw_html: str) -> tuple[str | None, list[str] | None]:
    """Return (prose, bullets) from an HTML tab blob."""
    def clean(s: str) -> str:
        s = re.sub(r'<[^>]+>', ' ', s)
        s = html_mod.unescape(re.sub(r'\s+', ' ', s).strip())
        s = s.replace('\xa0', '').replace('\u200f', '').strip()
        # Ounass inlines bullet glyphs as text (e.g. "\u2022 \u0627\u0644\u0644\u0648\u0646: \u0623\u0632\u0631\u0642")
        return re.sub(r'^[\u2022\u00b7\-]\s*', '', s).strip()

    paras = re.findall(r'<p[^>]*>(.*?)</p>', raw_html, re.DOTALL | re.IGNORECASE)
    prose_parts = [clean(p) for p in paras]
    prose = ' '.join(t for t in prose_parts if t) or None

    lis = re.findall(r'<li[^>]*>(.*?)</li>', raw_html, re.DOTALL | re.IGNORECASE)
    bullets = [clean(li) for li in lis]
    bullets = [b for b in bullets if b] or None

    return prose, bullets


def extract_product_details(state) -> dict:
    tabs = {x['tabId']: x['html'] for x in state['pdp']['contentTabs']}

    design_html = tabs.get('designDetails', '')
    size_html = tabs.get('sizeAndFit', '')

    desc, detail_bullets = _parse_tab_html(design_html)
    size_prose, size_bullets = _parse_tab_html(size_html)

    # size_fit: prefer bullets; fall back to wrapping prose as single-item list
    size_fit: list[str] | None = size_bullets
    if not size_fit and size_prose:
        size_fit = [size_prose]

    return {'description': desc, 'details': detail_bullets, 'size_fit': size_fit}


def get_data(state):
    return{
        'country': safe_get(state, ['country']),
        'portal_itemid': safe_get(state, ['pdp', 'visibleSku']),
        'product_name': safe_get(state, ['pdp', 'name']),
        'gender': safe_get(state, ['pdp', 'gender']),
        'brand': safe_get(state, ['pdp', 'designerCategoryName']),
        'brand_id': safe_get(state, ['pdp', 'designerId']),
        'category': safe_get(state, ['pdp', 'department']),
        'subcategory': safe_get(state, ['pdp', 'class']),
        'color': safe_get(state, ['pdp', 'colorInEnglish']),
        'price': safe_get(state, ['pdp', 'price']),
        'currency': safe_get(state, ['currency']),
        'price_discount': get_discount(state),
        'primary_label': get_primary_label(state),
        'image_urls': get_image_url(state),
        'out_of_stock': get_sold_out(state),
        'text': extract_product_details(state),     
    }
    
