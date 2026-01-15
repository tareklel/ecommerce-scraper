import scrapy
from datetime import date
from ecommercecrawl.spiders.mastercrawl import MasterCrawl
from ecommercecrawl.rules import ounass_rules as rules
from ecommercecrawl.constants import ounass_constants as constants
from scrapy.http import HtmlResponse
import requests
import os

class OunassSpider(MasterCrawl, scrapy.Spider):
    name = constants.NAME
    default_urls_path_setting = 'OUNASS_URLS_PATH'
    default_urls_path_constant = constants.OUNASS_URLS

    def __init__(self, urlpath=None, urls=None, limit=None, *args, **kwargs):
        super(OunassSpider, self).__init__(*args, **kwargs)
        self.urlpath = urlpath
        self.start_urls = urls or []
        self.limit = limit
    
    def _handle_seed_url(self, url):
        """
        Override MasterCrawl._handle_seed_url so that the initial responses
        are fetched via `requests` instead of Scrapy's downloader.
        """
        try:
            r = requests.get(url)
            r.raise_for_status()
            scrapy_response = HtmlResponse(
                url=r.url,
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
                    response.url.split("?")[0] + f"?sortBy={constants.PLPSORT}&p={p}"
                    for p in range(total_pages)
                ]

            # If already sorted, just get the subsequent pages
            if total_pages <= 1:
                return []
            else:
                # Assuming the first page is p=0, so we get pages 1 to N-1
                return [
                    response.url.split("?")[0] + f"?sortBy={constants.PLPSORT}&p={p + 1}"
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
        pdps = rules.get_pdps(response)
        
        for pdp in pdps:
            yield from self._handle_seed_url(pdp)
        
    def parse_pdp(self, response):
        """
        This method parses a product detail page, extracts the product information,
        and returns an Item.
        """
        try:
            state = rules.get_state(response)
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
