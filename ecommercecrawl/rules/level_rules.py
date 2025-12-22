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
