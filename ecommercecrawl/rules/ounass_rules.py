import json
from ecommercecrawl.constants.ounass_constants import MAIN_SITE

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