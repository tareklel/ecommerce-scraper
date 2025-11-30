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
    
    def parse(self, response):
        # Only the first page schedules the other pages 2..N
        if rules.is_plp(response):
            yield from self.parse_plp(response)
        elif rules.is_pdp(response):
            # check country
            if response.url[8:16] == 'en-saudi':
                country = 'sa'
            elif response.url.split('/')[2].split('.')[2] == 'ae':
                country = 'ae'
            elif 'https://kuwait.ounass.com/' in response.url:
                country = 'kw'
            elif 'https://www.ounass.qa/' in response.url:
                country = 'qa'

            try:
                bread = response.xpath('//ol[@class="BreadcrumbList hide-scrollbar"]/li/\
                    a[@class="BreadcrumbList-breadcrumbLink "]/span/text()').getall()
            except IndexError:
                bread = response.xpath('//ol[@class="BreadcrumbList"]/li/\
                    a[@class="BreadcrumbList-breadcrumbLink "]/span/text()').getall()

            sold_out = ('OUT OF STOCK' in response.xpath(
                '//span[@class="Badge"]/text()').getall())
            discount = response.xpath(
                '//span[@class="PriceContainer-discountPercent"]/text()').get()
            image_url = response.xpath('//picture/source/@srcset').getall()

            today = date.today()
            date_string = today.strftime("%Y-%m-%d")
            filename = f'output/ounass-{date_string}'

            image = response.xpath(
                '//button[@id="stylecolor-media-gallery-image-button-0"]/picture/source/@srcset').getall()[0].split('?')[0]
            image = 'https:' + image

            data = {
                'site': 'Ounass',
                'crawl_date': date.today(),
                'country': country,
                'url': response.url,
                'portal_itemid': response.xpath('//div[@class="PDPMobile-selectedSku"]/text() \
                    | //span[@class="Help-selectedSku"]/text()').get().split(': ')[-1],
                'product_name': response.xpath('//h1[@class="PDPDesktop-name"]/span/text()').get(),
                'gender': bread[0],
                'brand': response.xpath('//h2[@class="PDPDesktop-designerCategoryName"]/a/text()').get(),
                #'category': response.meta['category'],
                #'subcategory': response.meta['subcategory'],
                'price': response.xpath('//span[@class="PriceContainer-price"]/text()').get().split(' ')[0],
                'currency': response.xpath('//span[@class="PriceContainer-price"]/text()').get().split(' ')[-1],
                'price_discount': (None if discount is None else discount.split(" ")[0]),
                'sold_out': sold_out,
                'primary_label': response.xpath('//span[@class="Badge"]/text()').get(),
                'image_url': image,
                'text': response.xpath('//div[@id="content-tab-panel-0"]/p/text()').get()
            }

            if not os.path.exists('output'):
                # If the directory doesn't exist, create it
                os.makedirs('output')

            # save to CSV
            self.save_to_csv(filename, data)

            # Create a directory for images if it doesn't exist
            image_dir = 'output/images/ounass/' + date_string + '/' + \
                response.url.split('/')[-1].split('.')[0]
            if not os.path.exists(image_dir):
                os.makedirs(image_dir)

            # Download images
            image_urls = data['image_url']
            yield scrapy.Request(image_urls, callback=self.save_image, meta={'image_dir': image_dir})