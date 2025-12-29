import json
import re
import logging

def get_products(payload: dict):
    # return products from payload
    v = payload.get('products')
    return v

def get_country(url: str):
    # return counry by analyzing subdomain or subpath
    subdomain = url.split('/')[2].split('.')[0]
    if 'saudi' in subdomain:
        return 'sa'
    elif 'kuwait' in subdomain:
        return 'kw'
    elif 'qatar' in subdomain:
        return 'qa'
    elif 'www' in subdomain:
        return 'ae'
    return None

def get_gender(url: str):
    # return gender from plp subpath
    if '/men/' in url:
        return 'men'
    elif '/women/' in url:
        return 'women'
    elif '/kids/' in url:
        return 'kids'
    return None

def get_language_plp(url: str):
    # return language from plp subpath
    if is_plp(url):
        subdomain = url.split('/')[2].split('.')[0]
        if '/ar/' in url or 'ar-' in subdomain:
            return 'ar'
        return 'en'
    else:
        raise ValueError(f'URL {url} is not a PLP URL')

def get_urlpath(url: str):
    # search plp for url path after gender
    match = re.search(r'/(men|women)/(.+?)(?:\?|$)', url)
    if match:
        return match.group(2)
    return None 

def is_plp(url):
    # check if plp is url
    return '.html' not in url and get_gender(url) is not None

def is_pdp(response):
    # check if response is pdp
    return '.html' in response.url and get_gender(response.url) is None

# extract from item
def get_url_from_item(x):
    if isinstance(x, dict) and x.get('action', {}).get('url'):
        return x['action']['url']
    return None

def get_id_from_item(x):
    if isinstance(x, dict) and x.get('id'):
        return x['id']
    return None

def get_name_from_item(x):
    if isinstance(x, dict) and x.get('name'):
        return x['name']
    return None

def get_brand_from_item(x):
    if isinstance(x, dict) and x.get('brandName'):
        return x['brandName']
    return None

def get_category_from_item(x):
    if isinstance(x, dict) and x.get('analytics'):
        return x['analytics']['category1']
    return None

def get_gender_from_item(x):
    if isinstance(x, dict) and x.get('analytics'):
        return x['analytics']['gender']
    return None

def get_subcategory_from_item(x):
    if isinstance(x, dict) and x.get('analytics'):
        return x['analytics']['category2']
    return None

def get_price_from_item(x):
    if isinstance(x, dict) and x.get('analytics'):
        return x['analytics']['originalPrice']
    return None

def get_currency_from_item(x):
    if isinstance(x, dict) and x.get('originalPrice'):
        return x['originalPrice'].split(' ')[-1]
    return None

def get_price_discount_from_item(x):
    if isinstance(x, dict) and x.get('discountPercentage'):
        return x['discountPercentage']
    return None

def get_image_urls_from_item(x):
    if isinstance(x, dict) and x.get('imagePreviewGallery'):
        return x['imagePreviewGallery'][0]['url']
    return None

def get_primary_label_from_item(x):
    if isinstance(x, dict) and x.get('badges'):
        return [x['text'] for x in x['badges']]
    return None

def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()

def extract_product_details(response):
    accordion_nodes = response.xpath(
        '//div[contains(@class,"accordion-root")]'
        '[.//button//span[normalize-space()="Product Details"]]'
    )
    if not accordion_nodes:
        return ""
    root = accordion_nodes[0]

    detail_fragments = [
        text for text in root.css('div.accordion-details-root > p::text').getall()
        if text is not None
    ]
    details_text = _norm_ws(" ".join(detail_fragments))

    bullets = []
    for li in root.css('ul[data-testid="lineitems"] li::text').getall():
        cleaned = _norm_ws(li)
        if cleaned:
            bullets.append(cleaned)

    if details_text:
        bullets.append(details_text)

    return ' | '.join(bullets)
