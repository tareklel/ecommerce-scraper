import json
import re
import logging
from ecommercecrawl.constants.ounass_constants import MAIN_SITE, TLD_LANGUAGE_MAP
from html.parser import HTMLParser


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
    return json.loads(response.text)['pagination']['currentPage'] == 0

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
    
    urls = [f'{MAIN_SITE}{slug}.html' for slug in unique_slugs]
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

def get_sold_out(state):
    try:
        return state['pdp']['badge']['value'] == 'OUT OF STOCK'
    except Exception:
        return None
    
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
    

class HTMLCleaner(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []

    def handle_data(self, data):
        self.text.append(data)

    def get_cleaned_text(self):
        return ''.join(self.text).replace('\n', ' ').replace('\xa0', '')

def get_language(url):
    return TLD_LANGUAGE_MAP.get(url.split('https://')[-1].split('/')[0], None)

def extract_product_details(state):
    design_details = [x['html'] for x in state['pdp']['contentTabs'] if x['tabId'] == 'designDetails'][0]
    size_fit = [x['html'] for x in state['pdp']['contentTabs'] if x['tabId'] == 'sizeAndFit'][0]

    cleaner = HTMLCleaner()
    cleaner.feed(design_details)
    design_details_cleaned = cleaner.get_cleaned_text()

    cleaner = HTMLCleaner()
    cleaner.feed(size_fit)
    size_fit_cleaned = cleaner.get_cleaned_text()

    return f"Design Details: {design_details_cleaned}, Size & Fit: {size_fit_cleaned}"


def get_data(state):
    return{
        'country': safe_get(state, ['country']),
        'portal_itemid': safe_get(state, ['pdp', 'visibleSku']),
        'product_name': safe_get(state, ['pdp', 'name']),
        'gender': safe_get(state, ['pdp', 'gender']),
        'brand': safe_get(state, ['pdp', 'designerCategoryName']),
        'category': safe_get(state, ['pdp', 'department']),
        'subcategory': safe_get(state, ['pdp', 'class']),
        'color': safe_get(state, ['pdp', 'color']),
        'price': safe_get(state, ['pdp', 'price']),
        'currency': safe_get(state, ['currency']),
        'price_discount': get_discount(state),
        'primary_label': get_primary_label(state),
        'image_urls': get_image_url(state),
        'out_of_stock': get_sold_out(state),
        'text': extract_product_details(state),     
    }
    