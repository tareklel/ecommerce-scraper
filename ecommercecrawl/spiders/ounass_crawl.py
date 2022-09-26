from unicodedata import category
import scrapy
from datetime import date
import re
from faker import Faker
import numpy
import logging
from scrapy.utils.log import configure_logging


class OunassSpider(scrapy.Spider):
    name = "ounass"
    custom_settings = {
        'CLOSESPIDER_PAGECOUNT': 20,
        'FAKEUSERAGENT_PROVIDERS':['scrapy_fake_useragent.providers.FakerProvider'],
        'FAKER_RANDOM_UA_TYPE':"firefox"
    }

    def start_requests(self):
        configure_logging(install_root_handler=False)
        logging.basicConfig(
        filename=f'ounass-log-{date.today()}.log',
        format='%(asctime)s %(levelname)s: %(message)s',
        level=logging.INFO
    )

        self.urls = [
            'https://www.ounass.ae/api/women/clothing'
        ]
        for url in self.urls:
            yield scrapy.Request(url=url, callback=self.parse)

    def parse(self, response):
        if response.url in self.urls:
            # get total number of pages from plp
            total_pages = response.json()['pagination']['totalPages']
            # scrape all urls
            urls = [response.url + f"?sortBy=popularity-asc&p={p}&facets=0" for p in range(2)]
            for url in urls:
                yield scrapy.Request(url=url, callback=self.parse)
        elif response.url.split('?')[-1].split('=')[0] == 'sortBy':
            # get products from plp
            slugs = [x['slug'] for x in response.json()['hits']]
            # get products
            products = [ 'https://' + response.url.split('/')[2] + f'/{slug}.html' for slug in slugs]
            for product in products:
                yield scrapy.Request(url=product, callback=self.parse)
        elif response.url.split('.')[-1] == 'html':
            # check country
            if response.url[8:16] == 'en-saudi':
                country = 'sa'
            elif response.url.split('/')[2].split('.')[2] == 'ae':
                country = 'ae'
            else:
                country = None
            bread = response.xpath('//ol[@class="BreadcrumbList"]/li/\
                a[@class="BreadcrumbList-breadcrumbLink "]/span/text()').getall()
            sold_out = ('OUT OF STOCK' in response.xpath('//span[@class="Badge"]/text()').getall())
                
            yield {
                'site':'Ounass',
                'crawl_date':date.today(),
                'country':country,
                'url':response.url,
                'portal_itemid':response.xpath('//div[@class="PDPMobile-selectedSku"]/text() \
                    | //span[@class="Help-selectedSku"]/text()').get().split(': ')[-1],
                'product_name':response.xpath('//h1[@class="PDPDesktop-name"]/span/text()').get(),
                'gender':bread[0],
                'brand':response.xpath('//h2[@class="PDPDesktop-designerCategoryName"]/a/text()').get(),
                'category':bread[1],
                'subcategory':bread[2],
                'subsubcategory':bread[3],
                'price':response.xpath('//span[@class="PriceContainer-price"]/text()').get().split(' ')[0],
                'currency':response.xpath('//span[@class="PriceContainer-price"]/text()').get().split(' ')[-1],
                'price_discount':response.xpath('//span[@class="PriceContainer-discountPercent"]/text()').get().split(" ")[0],
                'sold_out':sold_out,
                'primary_label':response.xpath('//span[@class="Badge"]/text()').geta(),
                
                }

            {
            'site':'Farfetch',
            'crawl_date':date.today(),
            'country':response.url.split('/')[3],
            'url':response.url,
            'portal_itemid':response.xpath('div[@class="PDPMobile-selectedSku"]/text()').split(': ')[-1],
            'product_name':(None if not product_name else product_name[-1]),
            'gender':(None if response.url is None else response.url.split('/')[5]),
            'brand':response.xpath('//a[@data-ffref="pp_infobrd"]/text()').get(),
            'category': (None if not breadcrumbs else breadcrumbs[2]),
            'subcategory':(None if not breadcrumbs else breadcrumbs[3]),
            'price':(None if price is None else price.split(' ')[-1]),
            'currency':(None if price is None else price.split(' ')[0]),
            'price_discount':response.xpath('//p[@data-component="PriceDiscount"]/text()').get(),
            'sold_out':(True if response.xpath('//p[@data-tstid="soldOut"]/text()').get() else False),
            'primary_label':response.xpath('//p[@data-component="LabelPrimary"]/text()').get(),
            'image_url':response.xpath('//button[@data-is-loaded]/img/@src').get(),
            'text':response.xpath('//div[@data-component="TabPanelContainer"]/div/div/div/div/p/text()').getall()
            }



