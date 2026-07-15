import scrapy
from datetime import date

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

    def _handle_seed_url(self, url):
        if rules.is_plp(url):
            yield scrapy.Request(url, callback=self.parse_plp)
        elif rules.is_pdp(url):
            yield scrapy.Request(url, callback=self.parse_pdp)

    def parse_plp(self, response):
        """
        Harvest PDP URLs from a category PLP page.
        On the first page, kicks off UpdateGrid pagination for subsequent batches.
        """
        for url in rules.get_pdp_urls(response):
            yield scrapy.Request(url, callback=self.parse_pdp)

        if rules.is_first_plp_page(response.url):
            cgid = rules.get_cgid(response.text)
            if cgid:
                yield scrapy.Request(
                    rules.get_update_grid_url(response.url, cgid, start=48),
                    callback=self.parse_plp_page,
                    meta={'cgid': cgid, 'start': 48, 'base_url': response.url},
                )
            else:
                self.logger.warning(f'No cgid found on PLP: {response.url}')

    def parse_plp_page(self, response):
        """
        Handle SFCC Search-UpdateGrid API responses (pages 2+).
        Recurses until the response contains no product URLs.
        """
        pdp_urls = rules.get_pdp_urls(response)
        if not pdp_urls:
            return

        for url in pdp_urls:
            yield scrapy.Request(url, callback=self.parse_pdp)

        start = response.meta['start'] + constants.UPDATE_GRID_PAGE_SIZE
        yield scrapy.Request(
            rules.get_update_grid_url(response.meta['base_url'], response.meta['cgid'], start),
            callback=self.parse_plp_page,
            meta={**response.meta, 'start': start},
        )

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
