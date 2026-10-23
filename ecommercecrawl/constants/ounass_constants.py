NAME = 'ounass'
MAIN_SITE = 'https://www.ounass.ae/'
OUTPUT_DIR = 'output'
# IMAGE_CDN = 'ounass-ae.atgcdn.a'
# ounass_IMAGE_BASE_DIR = f'{OUTPUT_DIR}/images/ounass'
OUNASS_URLS = 'resources/ounass_urls.csv'
SOLD_OUT_LABEL = 'OUT OF STOCK'
# Listing sort used for pagination: the site's own "Newest" option (listed in
# every listing response's `sortBy`). Must give each product exactly one page.
# The old `fh_sort_by=-newness_ae` (Fredhopper syntax, not a listed option; the
# `_sa` variant behaves the same) sorts on a value many products share, so ties
# resolve differently per page request: on 2026-10-23 saudi shoulder-bags it
# returned 1,860 entries but only 1,517 unique products (~18% never shown, a
# different ~18% each day). `sortBy=onlineDateWithStock-desc` returned 1,854
# unique of 1,860. See docs/ounass_plp_efficient_crawl.md, section 10.
PLPSORT_KEY = 'sortBy'
PLPSORT = 'onlineDateWithStock-desc'
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
# Currency each country's listing prices are in (PLP hit `localeCurrency`).
# PLP-extract rows carry no currency, so the sweep checks this (G7) to avoid
# writing one country's prices onto another country's products.
COUNTRY_CURRENCY = {
    'ae': 'AED',
    'sa': 'SAR',
    'kw': 'KWD',
    'qa': 'QAR',
}
    