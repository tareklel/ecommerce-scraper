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
    data = json.loads(response.text)
    slugs = [x['slug'] for x in data['hits']]
    urls = [f'{MAIN_SITE}{slug}.html' for slug in slugs]
    return urls

def is_pdp(response):
    return response.url.split('.')[-1] == 'html'
