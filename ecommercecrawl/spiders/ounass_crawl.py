import scrapy
from datetime import date
import random
import time
from urllib.parse import urlparse

import requests
from ecommercecrawl.spiders.mastercrawl import MasterCrawl
from ecommercecrawl.rules import ounass_rules as rules
from ecommercecrawl.constants import ounass_constants as constants
from ecommercecrawl.crawler_api import (
    REQUEST_TYPE_HTTP_RESPONSE,
    REQUEST_TYPE_RENDERED_HTML,
    build_crawler_api_request,
)
from scrapy.http import HtmlResponse


FETCH_BACKEND_AUTO = "auto"
FETCH_BACKEND_API = "api"
FETCH_BACKEND_REQUESTS = "requests"


class OunassSpider(MasterCrawl, scrapy.Spider):
    name = constants.NAME
    default_urls_path_setting = 'OUNASS_URLS_PATH'
    default_urls_path_constant = constants.OUNASS_URLS

    def __init__(self, urlpath=None, urls=None, limit=None, category=None, url_categories=None, *args, **kwargs):
        super(OunassSpider, self).__init__(*args, **kwargs)
        self.urlpath = urlpath
        self.start_urls = urls or []
        self.limit = limit
        # Ounass can bypass Scrapy's downloader in requests mode, so keep
        # explicit URL-level dedupe for both fetch backends.
        self._seen_fetch_urls = set()
        # Global category filter (--category), overridable per seed URL via
        # a "category" CSV column. Keyed by base URL (no query string) so
        # pagination pages, which only change the query, keep the same
        # category without needing to thread it through request meta.
        self.category = self._normalize_category(category)
        self.url_categories = {
            self._base_url(url): normalized
            for url, raw_category in (url_categories or {}).items()
            if (normalized := self._normalize_category(raw_category))
        }

    @staticmethod
    def _normalize_category(category):
        if not category:
            return None
        normalized = str(category).strip().lower()
        return normalized or None

    @staticmethod
    def _base_url(url):
        return url.split("?", 1)[0]

    def _get_category_for_url(self, url):
        return self.url_categories.get(self._base_url(url), self.category)

    def _get_setting(self, name, default):
        settings = getattr(self, "settings", None)
        if settings is None:
            return default
        return settings.get(name, default)

    def _get_fetch_backend(self):
        backend = str(
            self._get_setting("OUNASS_FETCH_BACKEND", FETCH_BACKEND_AUTO)
        ).strip().lower()
        if backend not in {FETCH_BACKEND_AUTO, FETCH_BACKEND_API, FETCH_BACKEND_REQUESTS}:
            raise ValueError(f"Unsupported Ounass fetch backend: {backend}")
        return backend

    def _get_requests_tlds(self):
        """
        Hostnames allowed to use normal requests in auto mode.

        `OUNASS_REQUESTS_TLDS` in settings is the source of truth. If it is
        missing or empty, auto mode sends every Ounass hostname to the API.
        """
        configured = self._get_setting("OUNASS_REQUESTS_TLDS", [])
        if configured is None:
            configured = []
        elif isinstance(configured, str):
            configured = configured.split(",")
        return {
            str(hostname).strip().lower()
            for hostname in configured
            if str(hostname).strip()
        }

    def _should_use_requests_for_url(self, url):
        """
        Auto mode is API-first because Ounass crawling is strict.

        Only hostnames explicitly listed in OUNASS_REQUESTS_TLDS stay on
        normal requests; the default empty list means API for every hostname.
        """
        hostname = (urlparse(url).hostname or "").lower()
        return hostname in self._get_requests_tlds()

    def _get_fetch_backend_for_url(self, url):
        backend = self._get_fetch_backend()
        if backend != FETCH_BACKEND_AUTO:
            return backend
        if self._should_use_requests_for_url(url):
            return FETCH_BACKEND_REQUESTS
        return FETCH_BACKEND_API

    def _get_crawler_api_request_type(self, url):
        if url.split("?", 1)[0].endswith(".html"):
            return self._get_setting(
                "OUNASS_CRAWLER_API_PDP_REQUEST_TYPE",
                REQUEST_TYPE_HTTP_RESPONSE,
            )
        return self._get_setting(
            "OUNASS_CRAWLER_API_PLP_REQUEST_TYPE",
            REQUEST_TYPE_HTTP_RESPONSE,
        )

    def _get_pdp_browser_html_fallback_enabled(self):
        """
        Whether a PDP with no inline state should retry once with browserHtml.

        Off by default (OUNASS_PDP_BROWSER_HTML_FALLBACK): browserHtml costs
        more per request than http_response, so retrying is opt-in.
        """
        value = self._get_setting("OUNASS_PDP_BROWSER_HTML_FALLBACK", False)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() == "true"

    def _get_request_tuning(self):
        delay = float(self._get_setting("OUNASS_REQUEST_DELAY_SECONDS", "0.2"))
        jitter = float(self._get_setting("OUNASS_REQUEST_JITTER_SECONDS", "0.1"))
        timeout = int(float(self._get_setting("OUNASS_REQUEST_TIMEOUT_SECONDS", "20")))
        return max(0.0, delay), max(0.0, jitter), max(1, timeout)

    def _handle_seed_url(self, url):
        """
        Schedule an Ounass URL through the configured fetch backend.

        API mode keeps the provider-specific request details in crawler_api;
        requests mode preserves the old synchronous fallback path.
        """
        if url in self._seen_fetch_urls:
            self.logger.info(f"Skipping duplicate Ounass URL: {url}")
            return

        backend = self._get_fetch_backend_for_url(url)
        if backend == FETCH_BACKEND_API:
            self._seen_fetch_urls.add(url)
            yield build_crawler_api_request(
                url=url,
                callback=self.parse,
                settings=getattr(self, "settings", None),
                request_type=self._get_crawler_api_request_type(url),
            )
            return

        yield from self._handle_seed_url_via_requests(url)

    def _handle_seed_url_via_requests(self, url):
        try:
            delay, jitter, timeout = self._get_request_tuning()
            sleep_seconds = delay + (random.uniform(0, jitter) if jitter > 0 else 0.0)
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

            r = requests.get(url, timeout=timeout)
            r.raise_for_status()
            final_url = r.url or url
            if final_url in self._seen_fetch_urls:
                # Redirect aliases can reintroduce the same PDP via a different URL.
                self._seen_fetch_urls.add(url)
                self.logger.info(f"Skipping duplicate Ounass URL after redirect: {final_url}")
                return

            self._seen_fetch_urls.add(url)
            self._seen_fetch_urls.add(final_url)
            scrapy_response = HtmlResponse(
                url=final_url,
                body=r.content,
                encoding='utf-8'
            )
            # parse() may yield Requests and/or Items; just forward them
            for result in self.parse(scrapy_response):
                yield result
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Failed to fetch {url} using requests: {e}")
            return
        
    def get_pages(self, response):
        # get total number of pages from plp api
        try:
            total_pages = rules.get_max_pages(response)
            # If the URL is not sorted, we want to get all pages, even if it's just one
            if constants.PLPSORT not in response.url:
                return [
                    response.url.split("?")[0] + f"?{constants.PLPSORT_KEY}={constants.PLPSORT}&p={p}"
                    for p in range(total_pages)
                ]

            # If already sorted, just get the subsequent pages
            if total_pages <= 1:
                return []
            else:
                # Assuming the first page is p=0, so we get pages 1 to N-1
                return [
                    response.url.split("?")[0] + f"?{constants.PLPSORT_KEY}={constants.PLPSORT}&p={p + 1}"
                    for p in range(total_pages - 1)
                ]

        except (ValueError, AttributeError) as e:
            return []
    
    def parse_plp(self, response):
        """
        This method parses a product listing page, extracts the product URLs,
        and also handles pagination to scrape all pages.
        """
        if rules.is_first_page(response) and constants.PLPSORT not in response.url:
            plp_urls = self.get_pages(response)
            for url in plp_urls:
                yield from self._handle_seed_url(url)
            return  # Stop processing this unsorted page
        
        # Only the first page schedules the other pages 2..N
        if rules.is_first_page(response):
            plp_urls = self.get_pages(response)
            for url in plp_urls:
                yield from self._handle_seed_url(url)

        # Always process the current PLP for products
        category = self._get_category_for_url(response.url)
        pdps = rules.get_pdps(response, category=category)

        for pdp in pdps:
            yield from self._handle_seed_url(pdp)
        
    def parse_pdp(self, response):
        """
        This method parses a product detail page, extracts the product information,
        and returns an Item.

        Ounass PDPs are usually server-rendered, so `state` is present in the
        plain http_response body (cheap). Some pages may not inline it; on a
        miss, retrying once with a forced Zyte browser render is opt-in via
        OUNASS_PDP_BROWSER_HTML_FALLBACK (off by default). When off, or when
        the rendered_html retry also misses, the PDP is dropped.
        """
        try:
            state = rules.get_state(response)
            if state is None:
                meta = getattr(response, "meta", None) or {}
                if meta.get("force_rendered_pdp"):
                    self.logger.error(
                        f"Failed to parse PDP {response.url}: no state found even with rendered_html"
                    )
                    return
                if not self._get_pdp_browser_html_fallback_enabled():
                    self.logger.warning(
                        f"No inline state in http_response for {response.url}; "
                        "browserHtml fallback disabled (OUNASS_PDP_BROWSER_HTML_FALLBACK), skipping."
                    )
                    return
                self.logger.info(
                    f"No inline state in http_response for {response.url}; retrying with rendered_html."
                )
                yield build_crawler_api_request(
                    url=response.url,
                    callback=self.parse_pdp,
                    settings=getattr(self, "settings", None),
                    request_type=REQUEST_TYPE_RENDERED_HTML,
                    meta={"force_rendered_pdp": True},
                )
                return

            data = rules.get_data(state)

            date_string = date.today().strftime("%Y-%m-%d")

            data_dict = {
                'run_id': self.run_id,
                'site': constants.NAME,
                'crawl_date': date_string,
                'url': response.url,
                'language': rules.get_language(response.url)
            }
            merged = data_dict | data
            yield merged
        except Exception as e:
            self.logger.error(f"Failed to parse PDP {response.url}: {e}")
            return
    
    def parse(self, response):
        if rules.is_plp(response):
            yield from self.parse_plp(response)
            return
        elif rules.is_pdp(response):
            yield from self.parse_pdp(response)
            return
