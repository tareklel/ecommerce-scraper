NAME = 'bloomingdales'
MAIN_SITE_AR = 'https://bloomingdales.sa/'
MAIN_SITE_EN = 'https://en.bloomingdales.sa/'
BLOOMINGDALES_URLS = 'resources/bloomingdales_urls.csv'
OUTPUT_DIR = 'output'

# Listings (since the storefront rebuild, seen 2026-11-16) load products from
# Salesforce's Commerce API through the site's own proxy, after an anonymous
# guest login (the same one every visitor's browser does). The page carries
# the client settings (commerceAPI.parameters). One search page = one
# --limit page.
SEARCH_PAGE_SIZE = 48
GUEST_AUTHORIZE_PATH = '/shopper/auth/v1/organizations/{org}/oauth2/authorize'
GUEST_TOKEN_PATH = '/shopper/auth/v1/organizations/{org}/oauth2/token'
PRODUCT_SEARCH_PATH = '/search/shopper-search/v1/organizations/{org}/product-search'

CURRENCY_BY_COUNTRY = {
    'SA': 'SAR',
    'AE': 'AED',
    'KW': 'KWD',
}
