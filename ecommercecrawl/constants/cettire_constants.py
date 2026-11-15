NAME = 'cettire'
MAIN_SITE = 'https://www.cettire.com'
CETTIRE_URLS = 'resources/cettire_urls.csv'
CETTIRE_BRAND_ALLOWLIST = 'resources/cettire_brand_allowlist.csv'
OUTPUT_DIR = 'output'

# Saudi storefront only for now. Country is a URL path prefix (/sa/...).
COUNTRY = 'SA'
REGION_CODE = 'sa'
CURRENCY = 'SAR'

# The listing grid is filled by the site's search service, not by the page
# HTML (notes/2026-11-14-cettire-research.md, section 6).
SEARCH_URL = 'https://search.cettire.com/search-ai/pro-search/api/aiRecommendForProduct'
SEARCH_HEADERS = {
    'content-type': 'application/json',
    'accept': 'application/json',
    'origin': MAIN_SITE,
    'referer': MAIN_SITE + '/',
    'user-agent': (
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/126.0.0.0 Safari/537.36'
    ),
}
# "ar" returns both title and title_ar; "en" returns title only.
SEARCH_LANG = 'ar'
# Paging by page number is unreliable on this service, so each call asks for
# one group of brands that fits in a single response.
SEARCH_PAGE_SIZE = 1000
# Brands are packed into groups whose listed totals stay under this, leaving
# headroom below SEARCH_PAGE_SIZE for products added since the count was read.
BRAND_GROUP_MAX_PRODUCTS = 950
# Small first call per listing: only the brand counts are used from it.
FACET_PAGE_SIZE = 20
# With --limit, each search call asks for this many products (test runs).
LIMITED_PAGE_SIZE = 20
SEARCH_TIMEOUT_SECONDS = 60
SEARCH_DELAY_SECONDS = 1.0

# The search key is published in every page's __NEXT_DATA__ config. Pages are
# behind bot protection, so this page is fetched through the crawler API only
# when the stored key is missing or rejected.
# Any page carries the key, so attempts rotate over a few of them. Zyte's
# plain mode is refused often on this site ("520 Website Ban"): 4 attempts in
# a row all failed in the first live run (2026-11-14), hence the generous
# count and the pause.
API_KEY_PAGE_URLS = (
    MAIN_SITE + '/sa/collections/womens-bags',
    MAIN_SITE + '/sa/collections/womens-bags/shoulder-bags',
    MAIN_SITE + '/sa/collections/womens-bags/tote-bags',
)
API_KEY_CONFIG_FIELD = 'searchAIAPIKey'
API_KEY_FETCH_ATTEMPTS = 12
API_KEY_FETCH_PAUSE_SECONDS = 5.0
ZYTE_EXTRACT_URL = 'https://api.zyte.com/v1/extract'
