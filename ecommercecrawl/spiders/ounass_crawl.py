import json
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
from scrapy import signals
from scrapy.exceptions import DontCloseSpider
from scrapy.http import HtmlResponse
from ecommercecrawl import access
from ecommercecrawl import plp_efficient as pe


FETCH_BACKEND_AUTO = "auto"
FETCH_BACKEND_API = "api"
FETCH_BACKEND_REQUESTS = "requests"


class OunassSpider(MasterCrawl, scrapy.Spider):
    name = constants.NAME
    default_urls_path_setting = 'OUNASS_URLS_PATH'
    default_urls_path_constant = constants.OUNASS_URLS

    def __init__(self, urlpath=None, urls=None, limit=None, category=None, url_categories=None,
                 plp_efficient=None, plp_list=None, pdp_list=None, vocabulary=None,
                 plp_manifest=None, *args, **kwargs):
        super(OunassSpider, self).__init__(*args, **kwargs)
        # PLP-efficient mode (docs/ounass_plp_efficient_crawl.md). On via the
        # plp_efficient argument or the OUNASS_PLP_EFFICIENT_CRAWL setting; local
        # input files replace the export invocation (tests, hand-made CSVs).
        self.plp_efficient = plp_efficient
        self.plp_efficient_local_inputs = (plp_list, pdp_list, vocabulary, plp_manifest)
        self.plp_run = None
        self.plp_efficient_inputs = None
        self.plp_efficient_result = None
        self.plp_efficient_startup_error = None
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

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        if spider.plp_efficient_enabled():
            # Phase 2 starts when Scrapy's queue empties after the listing sweep.
            crawler.signals.connect(spider._plp_efficient_on_idle, signal=signals.spider_idle)
        return spider

    def plp_efficient_enabled(self):
        if self.plp_efficient is not None:
            return str(self.plp_efficient).strip().lower() in {"1", "true", "yes", "on"}
        return str(self._get_setting("OUNASS_PLP_EFFICIENT_CRAWL", False)).strip().lower() in {"1", "true", "yes", "on"}

    def start_requests(self):
        if not self.plp_efficient_enabled():
            yield from super().start_requests()
            return
        yield from self._plp_efficient_start_requests()

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
            # /api/ URLs are listing pages (product pages are .html): if one is
            # lost to blocking, the run is degraded with the URL named.
            meta = {access.LISTING_META_KEY: True} if urlparse(url).path.startswith("/api/") else None
            yield build_crawler_api_request(
                url=url,
                callback=self.parse,
                settings=getattr(self, "settings", None),
                request_type=self._get_crawler_api_request_type(url),
                meta=meta,
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
        if self.plp_run is not None and "plp_idx" in getattr(response, "meta", {}):
            yield from self._parse_plp_efficient(response)
            return

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
                'language': rules.get_language(response.url),
                # Every Ounass row carries the flag: 0 = full PDP extraction,
                # 1 = refreshed from a listing (PLP-efficient mode).
                'plp_extract_flag': 0,
            }
            merged = data_dict | data
            yield merged
        except Exception as e:
            self.logger.error(f"Failed to parse PDP {response.url}: {e}")
            return
    
    def parse(self, response):
        if self.plp_run is not None and "plp_idx" in response.meta:
            # PLP-efficient listing page: routed by the request, not the body,
            # so a blocked/garbled page is still accounted for (G3).
            yield from self._parse_plp_efficient(response)
            return
        if rules.is_plp(response):
            yield from self.parse_plp(response)
            return
        elif rules.is_pdp(response):
            yield from self.parse_pdp(response)
            return

    # ------------------------------------------------------------------
    # PLP-efficient mode (docs/ounass_plp_efficient_crawl.md, Part 3)
    # Decisions live in ecommercecrawl/plp_efficient.py (PlpEfficientRun);
    # the spider only feeds it pages and schedules what it asks for.
    # ------------------------------------------------------------------

    def _load_plp_efficient_inputs(self):
        plp_list, pdp_list, vocabulary, manifest_path = self.plp_efficient_local_inputs
        if any((plp_list, pdp_list, vocabulary)):
            manifest = None
            if manifest_path:
                with open(manifest_path, encoding="utf-8") as f:
                    manifest = json.load(f)
            return pe.load_inputs(plp_list, pdp_list, vocabulary, manifest=manifest)
        lambda_name = self._get_setting("OUNASS_PLP_EFFICIENT_EXPORT_LAMBDA", None)
        manifest = pe.invoke_export(lambda_name, site=constants.NAME)
        return pe.load_inputs_from_manifest(manifest)

    def _plp_efficient_start_requests(self):
        """Startup checks first; on any stop, no request is made (no Zyte spend)."""
        try:
            inputs = self._load_plp_efficient_inputs()
        except pe.ExportError as exc:
            self.plp_efficient_startup_error = exc
            self.logger.error(f"PLP-efficient run stopped before any request: {exc}")
            return
        self.plp_efficient_inputs = inputs
        config = pe.Config.from_settings(getattr(self, "settings", None) or {})
        result = pe.validate(inputs, config)
        self.plp_efficient_result = result
        self.logger.info("\n" + pe.format_report(inputs, result))
        for problem in result.by_severity(pe.WARN):
            # One grep-able line per startup warning (e.g. G8 stale gold); the
            # texts also go in the manifest (plp_efficient.startup.warning_messages).
            self.logger.warning(f"PLP-efficient startup warning {problem.check}: {problem.message}")
        if result.stop:
            self.logger.error("PLP-efficient run stopped by startup checks; no request made.")
            return
        self.plp_run = pe.PlpEfficientRun(
            result, config, self.run_id, date.today().strftime("%Y-%m-%d"), site=constants.NAME)
        for idx, plp in enumerate(self.plp_run.plps):
            request = self._plp_efficient_listing_request(idx, plp["url"])
            if request is not None:
                yield request

    def _plp_efficient_listing_request(self, idx, url):
        if url in self._seen_fetch_urls:
            return None
        self._seen_fetch_urls.add(url)
        self.plp_run.page_requested(idx)
        return build_crawler_api_request(
            url=url,
            callback=self.parse,
            settings=getattr(self, "settings", None),
            request_type=self._get_crawler_api_request_type(url),
            # The listing row travels with every page so pagination keeps its scope.
            meta={"plp_idx": idx},
            errback=self._plp_efficient_listing_failed,
        )

    def _plp_efficient_listing_failed(self, failure):
        if isinstance(failure.value, access.AccessDeferred):
            # Set aside for a later access retry round; not a failure yet.
            return
        idx = failure.request.meta.get("plp_idx")
        blocked = access.classify_exception(failure.value) is not None
        if self.plp_run is not None and idx is not None:
            # G3: a partially swept listing's products must not go to Phase 2
            # (they'd falsely look missing).
            self.plp_run.page_failed(idx, access=blocked)
        cause = "blocked (access)" if blocked else "failed"
        self.logger.error(f"PLP-efficient listing page {cause}: {failure.request.url}: {failure.value!r}")

    def _parse_plp_efficient(self, response):
        run = self.plp_run
        idx = response.meta["plp_idx"]
        label = access.classify_response(response)
        if label is not None:
            # A refusal (403/429/5xx) that survived every retry round: the
            # listing page is lost to access, not to its content.
            run.page_failed(idx, access=True)
            self.logger.error(f"PLP-efficient listing page blocked ({label}): {response.url}")
            return
        run.page_parsed(idx)
        if run.is_stopped(idx):
            return
        # Pagination, as in normal mode: the unsorted page 0 schedules every
        # sorted page and is not itself processed; the sorted page 0 schedules
        # pages 1..N-1 and is processed.
        if rules.is_first_page(response):
            for url in self.get_pages(response):
                request = self._plp_efficient_listing_request(idx, url)
                if request is not None:
                    yield request
            if constants.PLPSORT not in response.url:
                return
        for hit in json.loads(response.text).get("hits") or []:
            if not run.check_currency(idx, hit):
                self.logger.error(f"PLP-efficient listing stopped: {run.stats[idx]['stopped']} ({response.url})")
                return
            action, value = run.handle_hit(idx, hit, response.url)
            if action == "emit":
                yield value

    def _plp_efficient_on_idle(self, spider=None):
        """After the sweep: pick Phase 2 PDPs once, schedule them, keep the spider open."""
        run = self.plp_run
        if run is None or run.phase2 is not None:
            return
        access_retry = getattr(getattr(self, "crawler", None), "access_retry", None)
        if access_retry is not None and access_retry.busy():
            # Listing pages still waiting for an access retry round: Phase 2
            # is chosen only once every round is done.
            return
        phase2 = run.select_phase2()
        self.logger.info(f"PLP-efficient Phase 2: {json.dumps({k: v for k, v in phase2.items() if k != 'urls'})}")
        stats = getattr(getattr(self, "crawler", None), "stats", None)
        if stats is not None:
            stats.set_value("plp_efficient/refreshed_from_listing", len(run.crawled))
            stats.set_value("plp_efficient/phase2_candidates", phase2["candidates"])
            stats.set_value("plp_efficient/phase2_ceiling_exceeded", phase2["phase2_ceiling_exceeded"])
        if phase2["phase2_ceiling_exceeded"]:
            self.logger.error(
                f"PLP-efficient Phase 2 skipped: {phase2['candidates']} PDPs exceed the ceiling "
                f"of {run.config.max_phase2_pdps}")
            return
        scheduled = 0
        for url in phase2["urls"]:
            if url in self._seen_fetch_urls:
                continue
            self._seen_fetch_urls.add(url)
            self.crawler.engine.crawl(build_crawler_api_request(
                url=url,
                callback=self.parse_pdp,
                settings=getattr(self, "settings", None),
                request_type=self._get_crawler_api_request_type(url),
            ))
            scheduled += 1
        phase2["scheduled"] = scheduled
        if scheduled:
            raise DontCloseSpider

    def plp_efficient_manifest_block(self):
        """The run manifest's plp_efficient block (PostCrawlPipeline); None in normal mode."""
        if not self.plp_efficient_enabled():
            return None
        return pe.manifest_block(
            inputs=self.plp_efficient_inputs,
            result=self.plp_efficient_result,
            run=self.plp_run,
            startup_error=self.plp_efficient_startup_error,
        )

    def closed(self, reason):
        if self.plp_run is not None:
            self.logger.info(f"PLP-efficient summary: {json.dumps(self.plp_run.summary(), default=str)}")
