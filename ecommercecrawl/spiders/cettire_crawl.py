import base64
import csv
import os
import secrets
import time
import uuid
from datetime import date

import requests
import scrapy

from ecommercecrawl.constants import cettire_constants as constants
from ecommercecrawl.crawler_api import REQUEST_TYPE_HTTP_RESPONSE, build_crawler_api_request
from ecommercecrawl.rules import cettire_rules as rules
from ecommercecrawl.spiders.mastercrawl import MasterCrawl


class CettireSpider(MasterCrawl, scrapy.Spider):
    """
    Cettire, Saudi storefront (tickets/cettire_crawl.md).

    Listings: the page HTML holds no products, so each seed listing URL is
    turned into calls to the site's search service, one per group of
    allowlisted brands. Those calls are made directly (the search host is not
    behind bot protection).

    Product pages: fetched through the crawler API (plain HTML) to add the
    full gallery and the English copy. A product page that can't be fetched
    does not lose the product: its rows are written from the search data.

    Every product is written as two rows, EN and AR.
    """
    name = constants.NAME
    default_urls_path_setting = 'CETTIRE_URLS_PATH'
    default_urls_path_constant = constants.CETTIRE_URLS

    def __init__(self, urlpath=None, urls=None, limit=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.urlpath = urlpath
        self.start_urls = urls or []
        # --limit N: at most N brand groups per listing, 20 products per call.
        self.limit = limit
        self.date_string = date.today().strftime('%Y-%m-%d')
        self._api_key = None
        self._api_key_refreshed = False
        self._allowlist = None
        self._seen_ids = set()
        # Same session identifiers on every call of a run, as a browser would send.
        self._device_info = {'sessionId': str(uuid.uuid4()), 'deviceId': secrets.token_hex(32)}
        # Per-listing counts for the completeness check, logged at the end.
        self.listing_summaries = []

    # ------------------------------------------------------------ settings

    def _setting(self, name, default=None):
        settings = getattr(self, 'settings', None)
        return settings.get(name, default) if settings is not None else default

    def _load_allowlist(self):
        """Brand names to crawl, one per row. No file or no rows: every brand."""
        if self._allowlist is not None:
            return self._allowlist
        path = self._setting('CETTIRE_BRAND_ALLOWLIST_PATH', constants.CETTIRE_BRAND_ALLOWLIST)
        names = []
        if path and os.path.isfile(path):
            with open(path, newline='', encoding='utf-8-sig') as f:
                for row in csv.reader(f):
                    name = row[0].strip() if row else ''
                    if name and name.lower() != 'brand':
                        names.append(name)
        else:
            self.logger.warning(f'Cettire brand allowlist not found at {path}; crawling every brand.')
        self._allowlist = names
        return names

    # ------------------------------------------------------------ search key

    def _stored_api_key(self):
        return self._setting('CETTIRE_SEARCH_API_KEY') or os.environ.get('CETTIRE_SEARCH_API_KEY')

    def _fetch_page_html_via_zyte(self, url):
        """One plain-HTML fetch through Zyte, retried on its 520 "Website Ban"."""
        zyte_key = self._setting('ZYTE_API_KEY') or os.environ.get('ZYTE_API_KEY')
        if not zyte_key:
            raise RuntimeError('ZYTE_API_KEY is not set; cannot read the Cettire search key from a page.')
        last = None
        for _ in range(constants.API_KEY_FETCH_ATTEMPTS):
            response = requests.post(
                constants.ZYTE_EXTRACT_URL,
                auth=(zyte_key, ''),
                json={'url': url, 'httpResponseBody': True},
                timeout=180,
            )
            if response.status_code == 200:
                return base64.b64decode(response.json().get('httpResponseBody') or '').decode('utf-8', 'replace')
            last = response.status_code
        raise RuntimeError(f'Could not fetch {url} through Zyte (last status {last}).')

    def _refresh_api_key(self):
        """Read the current search key from a Cettire page. Once per run."""
        if self._api_key_refreshed:
            raise RuntimeError('Cettire search service rejected the key read from the site.')
        self._api_key_refreshed = True
        key = rules.extract_search_api_key(self._fetch_page_html_via_zyte(constants.API_KEY_PAGE_URL))
        if not key:
            raise RuntimeError('Cettire page config has no search key; the page layout may have changed.')
        self._api_key = key
        return key

    def _get_api_key(self):
        if self._api_key:
            return self._api_key
        self._api_key = self._stored_api_key()
        if not self._api_key:
            self.logger.info('No stored Cettire search key (CETTIRE_SEARCH_API_KEY); reading it from the site.')
            self._refresh_api_key()
        return self._api_key

    # ------------------------------------------------------------ search calls

    def _post_search(self, body):
        headers = dict(constants.SEARCH_HEADERS, **{'x-api-key': self._get_api_key()})
        return requests.post(constants.SEARCH_URL, json=body, headers=headers,
                             timeout=constants.SEARCH_TIMEOUT_SECONDS)

    def _search(self, query, vendors=None, page_size=constants.SEARCH_PAGE_SIZE):
        """
        One search call. A rejected key (401/403) is not a failed run: the
        current key is read from the site and the call is retried once.
        """
        body = rules.build_search_body(query, vendors, page_size,
                                       request_id=secrets.token_hex(20), device_info=self._device_info)
        response = self._post_search(body)
        if response.status_code in (401, 403):
            self.logger.warning(
                'Cettire search service rejected the stored key; reading the current one from the site. '
                'Update CETTIRE_SEARCH_API_KEY.'
            )
            self._refresh_api_key()
            response = self._post_search(body)
        response.raise_for_status()
        payload = response.json()
        if not payload.get('result', True):
            raise RuntimeError(f"Cettire search returned an error: {payload.get('errorMessage')!r}")
        return payload

    # ------------------------------------------------------------ crawl

    def _handle_seed_url(self, url):
        if rules.is_plp(url):
            yield from self.handle_plp_url(url)
        elif rules.is_pdp(url):
            yield self._pdp_request(url, rows=[])
        else:
            self.logger.warning(f'Skipping URL that is neither a Cettire listing nor a product: {url}')

    def handle_plp_url(self, url):
        query = rules.listing_query(url)
        # First call: only the brand counts are used.
        facets = self._search(query, page_size=constants.FACET_PAGE_SIZE)
        counts = rules.allowed_vendor_counts(rules.vendor_counts(facets), self._load_allowlist())
        groups = rules.pack_brand_groups(counts)
        page_size = constants.SEARCH_PAGE_SIZE
        if self.limit:
            groups = groups[:int(self.limit)]
            page_size = constants.LIMITED_PAGE_SIZE

        expected = sum(counts[name] for group in groups for name in group)
        received = 0
        for group in groups:
            time.sleep(constants.SEARCH_DELAY_SECONDS)
            hits = rules.get_hits(self._search(query, vendors=group, page_size=page_size))
            received += len(hits)
            for hit in hits:
                yield from self._handle_hit(hit)

        summary = {'url': url, 'brands': len(counts), 'groups': len(groups),
                   'expected': expected, 'received': received, 'limited': bool(self.limit)}
        self.listing_summaries.append(summary)
        self.logger.info(f'Cettire listing summary: {summary}')
        if not self.limit and received < expected:
            # The service returns slightly fewer products than its own counts
            # (about 1.5% in the 2026-11-14 probe; cause unknown).
            self.logger.warning(
                f'Cettire listing {url}: received {received} of {expected} listed products '
                f'({expected - received} short).'
            )

    def _handle_hit(self, hit):
        rows = rules.rows_from_hit(hit, self.run_id, self.date_string)
        if not rows:
            self.logger.warning(f"Skipping Cettire hit without a product ID: {hit.get('handle')!r}")
            return
        item_id = rows[0]['portal_itemid']
        if item_id in self._seen_ids:
            return
        self._seen_ids.add(item_id)
        yield self._pdp_request(rows[0]['url'], rows)

    def _pdp_request(self, url, rows):
        return build_crawler_api_request(
            url=url,
            callback=self.parse_pdp,
            errback=self.pdp_failed,
            settings=getattr(self, 'settings', None),
            request_type=REQUEST_TYPE_HTTP_RESPONSE,
            meta={'rows': rows},
        )

    def parse_pdp(self, response):
        rows = response.meta.get('rows') or []
        pdp = rules.extract_product(response.text)
        if pdp is None:
            self.logger.warning(f'No product data on Cettire page {response.url}; writing search data only.')
        if not rows:
            rows = self._rows_from_pdp_only(response.url, pdp)
        for row in rules.merge_pdp_into_rows(rows, pdp):
            yield row

    def pdp_failed(self, failure):
        """A product page we couldn't fetch: keep the product, from search data."""
        rows = failure.request.meta.get('rows') or []
        self.logger.warning(
            f'Cettire product page failed ({failure.type.__name__}): {failure.request.url}; '
            f'writing search data only.'
        )
        for row in rows:
            yield row

    def _rows_from_pdp_only(self, url, pdp):
        """A product URL given directly as a seed: one EN row from the page alone."""
        if not pdp or not pdp.get('portal_itemid'):
            return []
        return [{
            'run_id': self.run_id, 'site': constants.NAME, 'crawl_date': self.date_string,
            'url': url, 'country': rules.get_country(url) or constants.COUNTRY, 'language': 'EN',
            'portal_itemid': pdp['portal_itemid'], 'product_name': pdp.get('product_name'),
            'brand': pdp.get('brand'), 'gender': pdp.get('gender'), 'color': pdp.get('color'),
            'sizes': pdp.get('sizes'), 'category': None, 'subcategory': pdp.get('subcategory'),
            'price': pdp.get('price'), 'currency': pdp.get('currency'),
            'price_discount': pdp.get('price_discount'), 'was_price': pdp.get('was_price'),
            'out_of_stock': pdp.get('out_of_stock', False), 'primary_label': None,
            'image_urls': pdp.get('image_urls'), 'text': None,
            'designer_model_number': pdp.get('designer_model_number'),
            'designer_color': pdp.get('designer_color'),
        }]

    def parse(self, response):
        if rules.is_pdp(response.url):
            yield from self.parse_pdp(response)
