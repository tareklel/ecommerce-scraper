import json
from datetime import date
from urllib.parse import urlencode, urlparse

import scrapy

from ecommercecrawl.spiders.mastercrawl import MasterCrawl
from ecommercecrawl.rules import bloomingdales_rules as rules
from ecommercecrawl.constants import bloomingdales_constants as constants


class BloomingdalesSpider(MasterCrawl, scrapy.Spider):
    name = constants.NAME
    default_urls_path_setting = 'BLOOMINGDALES_URLS_PATH'
    default_urls_path_constant = constants.BLOOMINGDALES_URLS

    def __init__(self, urlpath=None, urls=None, limit=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.urlpath = urlpath
        self.start_urls = urls or []
        self.limit = limit
        self.date_string = date.today().strftime('%Y-%m-%d')
        # Skipped work, written into the manifest (degraded run).
        self.run_degradations = []

    def _handle_seed_url(self, url):
        if rules.is_plp(url):
            yield scrapy.Request(url, callback=self.parse_plp)
        elif rules.is_pdp(url):
            yield scrapy.Request(url, callback=self.parse_pdp)

    def _may_fetch_page(self, page):
        # --limit caps listing pages per seed URL (same meaning as Farfetch);
        # a page is one product search call of SEARCH_PAGE_SIZE products.
        return not self.limit or page <= int(self.limit)

    def _degrade(self, listing_url, message):
        # Reaches the manifest's degradations and the crawl flow's email.
        self.logger.warning(f'{listing_url}: {message}')
        self.run_degradations.append({'kind': 'content', 'scope': listing_url, 'message': message})

    def parse_plp(self, response):
        """
        A listing page renders only its first ~28 products. The rest come from
        the site's product search (Commerce API, through its own proxy) after
        the anonymous guest login every visitor's browser does. The first batch
        is requested here too, so a failed search still crawls it; the
        dupefilter drops it again when the search lists it.
        """
        for url in rules.get_pdp_urls(response):
            yield scrapy.Request(url, callback=self.parse_pdp)

        api = rules.get_commerce_api(response.text)
        cgid = rules.get_listing_cgid(response.text)
        if not api or not cgid:
            self._degrade(response.url, 'listing search settings not found on the page; '
                                        'only its first batch of products was crawled')
            return
        parsed = urlparse(response.url)
        listing = {**api, 'cgid': cgid, 'listing_url': response.url,
                   'base': f"{parsed.scheme}://{parsed.netloc}{api['proxy_path']}"}
        verifier, challenge = rules.pkce_pair()
        redirect_uri = f'{parsed.scheme}://{parsed.netloc}/callback'
        query = urlencode({
            'redirect_uri': redirect_uri, 'response_type': 'code', 'client_id': api['client_id'],
            'hint': 'guest', 'code_challenge': challenge, 'channel_id': api['site_id'],
        })
        path = constants.GUEST_AUTHORIZE_PATH.format(org=api['organization_id'])
        yield scrapy.Request(
            f"{listing['base']}{path}?{query}", callback=self.parse_guest_code, errback=self.listing_failed,
            dont_filter=True,
            meta={'listing': listing, 'verifier': verifier, 'redirect_uri': redirect_uri,
                  'dont_redirect': True, 'handle_httpstatus_list': [301, 302, 303, 307]},
        )

    def parse_guest_code(self, response):
        listing = response.meta['listing']
        code, usid = rules.get_guest_code(response.headers.get('Location', b'').decode())
        if not code or not usid:
            self._degrade(listing['listing_url'], f'guest login gave no code (HTTP {response.status}); '
                                                  'only the first batch of products was crawled')
            return
        yield scrapy.FormRequest(
            f"{listing['base']}{constants.GUEST_TOKEN_PATH.format(org=listing['organization_id'])}",
            formdata={
                'grant_type': 'authorization_code_pkce', 'code': code, 'usid': usid,
                'code_verifier': response.meta['verifier'], 'client_id': listing['client_id'],
                'redirect_uri': response.meta['redirect_uri'], 'channel_id': listing['site_id'],
            },
            callback=self.parse_guest_token, errback=self.listing_failed, dont_filter=True,
            meta={'listing': listing},
        )

    def parse_guest_token(self, response):
        listing = response.meta['listing']
        try:
            token = json.loads(response.text).get('access_token')
        except ValueError:
            token = None
        if not token:
            self._degrade(listing['listing_url'], 'guest login gave no token; '
                                                  'only the first batch of products was crawled')
            return
        # Valid 30 minutes; one listing's search takes seconds.
        yield self._search_request({**listing, 'token': token}, offset=0, page=1)

    def _search_request(self, listing, offset, page):
        query = urlencode({
            'siteId': listing['site_id'], 'refine': f"cgid={listing['cgid']}",
            'offset': offset, 'limit': constants.SEARCH_PAGE_SIZE,
            'locale': rules.get_search_locale(listing['listing_url']),
            'currency': rules.get_currency(listing['listing_url']),
        })
        path = constants.PRODUCT_SEARCH_PATH.format(org=listing['organization_id'])
        return scrapy.Request(
            f"{listing['base']}{path}?{query}", callback=self.parse_search, errback=self.listing_failed,
            headers={'Authorization': f"Bearer {listing['token']}"}, dont_filter=True,
            meta={'listing': listing, 'offset': offset, 'page': page},
        )

    def parse_search(self, response):
        listing = response.meta['listing']
        try:
            data = json.loads(response.text)
        except ValueError:
            self._degrade(listing['listing_url'], f"product search returned no JSON at offset {response.meta['offset']}")
            return
        hits = data.get('hits') or []
        for hit in hits:
            url = rules.build_pdp_url(listing['listing_url'], hit)
            if url:
                yield scrapy.Request(url, callback=self.parse_pdp)
        offset = response.meta['offset'] + len(hits)
        page = response.meta['page'] + 1
        if hits and offset < (data.get('total') or 0) and self._may_fetch_page(page):
            yield self._search_request(listing, offset, page)

    def listing_failed(self, failure):
        listing = failure.request.meta.get('listing') or {}
        self._degrade(listing.get('listing_url', failure.request.url),
                      f'listing search failed ({failure.getErrorMessage()[:200]}); '
                      'only the products found before it were crawled')

    def parse_pdp(self, response):
        try:
            data = rules.extract_product(response)
            data.update({
                'run_id': self.run_id,
                'site': constants.NAME,
                'crawl_date': self.date_string,
                'url': response.url,
                'country': 'SA',
                'language': rules.get_language(response.url),
            })
            yield data
        except Exception as e:
            self.logger.error(f'Failed to parse PDP {response.url}: {e}')

    def parse(self, response):
        if rules.is_plp(response.url):
            yield from self.parse_plp(response)
        elif rules.is_pdp(response.url):
            yield from self.parse_pdp(response)
