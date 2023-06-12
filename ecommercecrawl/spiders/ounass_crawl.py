import csv
import scrapy
from datetime import date
import logging
from scrapy.utils.log import configure_logging


class OunassSpider(scrapy.Spider):
    name = "ounass"
    custom_settings = {
    #    'CLOSESPIDER_PAGECOUNT': 100,
        'FAKEUSERAGENT_PROVIDERS':['scrapy_fake_useragent.providers.FakerProvider'],
        'FAKER_RANDOM_UA_TYPE':"firefox"
    }

    configure_logging(install_root_handler=False)
    logging.basicConfig(
        filename=f'log/ounass-log-{date.today()}.log',
        format='%(asctime)s %(levelname)s: %(message)s',
        level=logging.INFO
        )

    def start_requests(self):
        # get urls
        urls = []
        with open('resources/ounass_urls.csv', newline='') as inputfile:
            for row in csv.reader(inputfile):
                urls.append(row[0])
        # pass subcategory plps to get category and subcategory in crawl
        # only pass apis
        self.urls = urls
        for url in self.urls:
            if '/api/' not in url:
                raise Exception('please pass URLs from api subfolder')
        for url in self.urls:
            yield scrapy.Request(url=url, callback=self.parse)

    def parse(self, response):
        if response.url in self.urls:
            # get total number of pages from plp
            total_pages = response.json()['pagination']['totalPages']
            # scrape all urls
            urls = [response.url + f"?sortBy=popularity-asc&p={p}&facets=0" for p in range(total_pages)]
            for url in urls:
                yield scrapy.Request(url=url, callback=self.parse)
        elif response.url.split('?')[-1].split('=')[0] == 'sortBy':
            # get category and subcategory
            folders = response.url.split('?')[0].split('/')
            cat_dict = {
                'category':folders[-2], 
                'subcategory':folders[-1]
                }

            # get products from plp
            slugs = [x['slug'] for x in response.json()['hits']]
            # get products
            products = [ 'https://' + response.url.split('/')[2] + f'/{slug}.html' for slug in slugs]
            for product in products:
                yield scrapy.Request(url=product, callback=self.parse, meta=cat_dict)
        elif response.url.split('.')[-1] == 'html':
            # check country
            if response.url[8:16] == 'en-saudi':
                country = 'sa'
            elif response.url.split('/')[2].split('.')[2] == 'ae':
                country = 'ae'
            elif 'https://kuwait.ounass.com/' in  response.url:
                country = 'kw'
            elif 'https://www.ounass.qa/' in response.url:
                country = 'qa'
            bread = response.xpath('//ol[@class="BreadcrumbList"]/li/\
                a[@class="BreadcrumbList-breadcrumbLink "]/span/text()').getall()
            sold_out = ('OUT OF STOCK' in response.xpath('//span[@class="Badge"]/text()').getall())
            discount = response.xpath('//span[@class="PriceContainer-discountPercent"]/text()').get()
            image_url = response.xpath('//picture/source/@srcset').getall()
                
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
                'category':response.meta['category'],
                'subcategory':response.meta['subcategory'],
                'price':response.xpath('//span[@class="PriceContainer-price"]/text()').get().split(' ')[0],
                'currency':response.xpath('//span[@class="PriceContainer-price"]/text()').get().split(' ')[-1],
                'price_discount':(None if discount is None else discount.split(" ")[0]),
                'sold_out':sold_out,
                'primary_label':response.xpath('//span[@class="Badge"]/text()').get(),
                'image_url':[x for x in image_url if '//ounass-prod' in x][0],
                'text':response.xpath('//div[@id="content-tab-panel-0"]/p/text()').get()
                }
