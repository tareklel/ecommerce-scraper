import scrapy
from datetime import date
from ecommercecrawl.spiders.mastercrawl import MasterCrawl
from ecommercecrawl.rules import level_rules as rules
from ecommercecrawl.constants import level_constants as constants
from scrapy.http import HtmlResponse, TextResponse
import requests
import os

class LevelSpider(MasterCrawl, scrapy.Spider):
    name = constants.NAME
    default_urls_path_setting = 'LEVEL_URLS_PATH'
    default_urls_path_constant = constants.LEVEL_URLS

    def __init__(self, urlpath=None, urls=None, limit=None, *args, **kwargs):
        super(LevelSpider, self).__init__(*args, **kwargs)
        self.urlpath = urlpath
        self.start_urls = urls or []
        self.limit = limit

    def _fetch_plp_via_api(self, url, page_number=0):
        """
        Fetch a PLP payload directly from the Level API using requests.
        """
        api, params, headers = self.get_api_params(url, page_number)
        try:
            response = requests.get(api, params=params, headers=headers)
            response.raise_for_status()
            payload = response.json()
        except requests.exceptions.RequestException as exc:
            self.logger.error(f"Failed to fetch PLP {url} via API: {exc}")
            return None

        return payload

    def _handle_seed_url(self, url):
        """
        Override to fetch PLP data via the API before parsing.
        """
        if rules.is_plp(url):
            self.handle_plp_url(url)
                

        # Non-PLP URLs fall back to the default Scrapy downloader.
        yield from super()._handle_seed_url(url)
        
    def get_api_params(self, url, page_number=0):
        if rules.is_plp(url):
            country = rules.get_country(url)
            gender = rules.get_gender(url)
            headers = constants.API_HEADERS
            language = rules.get_language(url)
            urlpath = rules.get_urlpath(url)

            api = f'{constants.API_BASE_URL}/{country}/{language}/{constants.API_ENDPOINT}'

            params_base = {
                "urlPath":urlpath,
                "groupID":constants.GROUPID,
                "museTier": constants.MUSETIER,
                "count": constants.API_COUNT,
                "genderType": gender,
                "mediaGender": gender,
                "page": page_number
            }
            return api, dict(params_base), headers
        else:
            raise ValueError(f'URL {url} is not a PLP URL')
    
    def handle_plp_url(self, url):
        page = 0
        while True:
            payload = self._fetch_plp_via_api(url, page)
            items = rules.get_products(payload)
            if not items:
                break
            for item in items:
                self.handle_plp_item(item)
            page +=1
    
    def handle_plp_item(self, item):
        return

    def parse(self, response):
        """
        This method parses a product detail page, extracts the product information,
        and returns an Item.
        """
        if rules.is_pdp(response):
            yield from self.parse_pdp(response)
            return
        
    def parse_pdp(self, response):
        return
        