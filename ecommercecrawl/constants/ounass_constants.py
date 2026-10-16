NAME = 'ounass'
MAIN_SITE = 'https://www.ounass.ae/'
OUTPUT_DIR = 'output'
# IMAGE_CDN = 'ounass-ae.atgcdn.a'
# ounass_IMAGE_BASE_DIR = f'{OUTPUT_DIR}/images/ounass'
OUNASS_URLS = 'resources/ounass_urls.csv'
SOLD_OUT_LABEL = 'OUT OF STOCK'
PLPSORT_KEY = 'fh_sort_by'
PLPSORT = '-newness_ae'
TLD_LANGUAGE_MAP = {
    'www.ounass.ae': 'EN',
    'saudi.ounass.com': 'AR',
    'kuwait.ounass.com': 'EN',
    'www.ounass.qa': 'EN',
    'ar.ounass.ae': 'AR',
    'ar-kuwait.ounass.com': 'AR',
    'ar.ounass.qa': 'AR',
    'ar.ounass.sa': 'AR',
    'en-saudi.ounass.com': 'EN'
}
# Country each Ounass hostname serves (lowercase, as in scraper-pipeline's
# canonical keys). Used by the PLP-efficient startup check G7 together with
# TLD_LANGUAGE_MAP; mirrored in scraper-pipeline's
# dbt/tests/test_crawl_plp_registry_ounass_url.sql, so keep the two in sync.
TLD_COUNTRY_MAP = {
    'www.ounass.ae': 'ae',
    'ar.ounass.ae': 'ae',
    'saudi.ounass.com': 'sa',
    'en-saudi.ounass.com': 'sa',
    'ar.ounass.sa': 'sa',
    'kuwait.ounass.com': 'kw',
    'ar-kuwait.ounass.com': 'kw',
    'www.ounass.qa': 'qa',
    'ar.ounass.qa': 'qa',
}
    