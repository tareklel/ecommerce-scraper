import csv
import scrapy
from datetime import date
import re
import logging
from scrapy.utils.log import configure_logging
import pandas as pd
import os
from ecommercecrawl.spiders.mastercrawl import Mastercrawl
from ecommercecrawl import settings
from ecommercecrawl.xpaths.farfetch_xpaths import PAGINATION_XPATH


class FFSpider(scrapy.Spider, Mastercrawl):
    name = "farfetch"

    def __init__(self, urlpath=None, *args, **kwargs):
        super(FFSpider, self).__init__(*args, **kwargs)
        self.urlpath = urlpath
        self.settings = settings

    def start_requests(self):
        # get urls
        urls = []

        try:
            # spider may have a scrapy.settings.Settings set by the crawler in tests or runtime
            settings_get = self.settings.get if hasattr(self, "settings") else None
        except Exception:
            settings_get = None

        if self.urlpath is None:
            if settings_get:
                self.urlpath = settings_get('FARFETCH_URLS_PATH', 'resources/farfetch_urls.csv')
            else:
                self.urlpath = 'resources/farfetch_urls.csv'

        with open(self.urlpath, newline='') as inputfile:
            for row in csv.reader(inputfile):
                if row:
                    urls.append(row[0])
        for url in urls:
            yield scrapy.Request(url=url, callback=self.parse)

    def get_pages(self, response):
        """
        Return urls of all pages in given page.
        If no pagination, return only the current response.url.
        """
        pagination = response.xpath(PAGINATION_XPATH).get()
        if not pagination:
            return [response.url]
        try:
            total_pages = int(pagination.split(' ')[-1])
        except (ValueError, AttributeError):
            return [response.url]
        if total_pages <= 1:
            return [response.url]
        pages = [x + 1 for x in range(total_pages)][1:]
        urls = [response.url + f'?page={str(page)}' for page in pages]
        return [response.url] + urls

    def parse(self, response):
        # check if ending with items.aspx > plp
        if response.url.split('/')[-1].split('?')[0] == 'items.aspx':
            # check if first page, if first get all pages
            if len(response.url.split('?')) > 1:
                pass
            else:
                urls = self.get_no_pages(response)
                for url in urls:
                    yield scrapy.Request(url=url, callback=self.parse)
            # get all pdps from plp
            pdps = response.xpath(
                '//a[@data-component="ProductCardLink"]/@href').getall()
            for pdp in pdps:
                yield scrapy.Request(response.urljoin(pdp), callback=self.parse)
        else:
            #extract product info
            response.url.split('/')[-1].split('?')[0] != 'items.aspx'
            price = response.xpath(
                '//p[@data-component="PriceLarge"]/text()|//p[@data-component="PriceFinalLarge"]/text()').get()
            breadcrumbs = response.xpath(
                '//li[@data-component="BreadcrumbWrapper"]/a/text()').getall()
            product_name = response.xpath(
                '//p[@data-component="LabelPrimary"]/../p/text()').getall()

            today = date.today()
            date_string = today.strftime("%Y-%m-%d")
            filename = f'output/farfetch-{date_string}'

            data = {
                'site': 'Farfetch',
                'crawl_date': date_string,
                'country': response.url.split('/')[3],
                'url': response.url,
                'subfolder': (None if response.url is None else response.url.split("/")[3]),
                'portal_itemid': (None if response.url is None else response.url.split('?')[0].split('/')[-1].split('.')[0].split('-')[-1]),
                'product_name': (None if not product_name else product_name[-1]),
                'gender': (None if response.url is None else response.url.split('/')[5]),
                'brand': response.xpath('//a[@data-ffref="pp_infobrd"]/text()').get(),
                'category': (None if not breadcrumbs else breadcrumbs[2]),
                'subcategory': (None if not breadcrumbs else breadcrumbs[3]),
                'price': (None if price is None else price.split(' ')[-1]),
                'currency': (None if price is None else price.split(' ')[0]),
                'price_discount': response.xpath('//p[@data-component="PriceDiscount"]/text()').get(),
                'sold_out': (True if response.xpath('//p[@data-tstid="soldOut"]/text()').get() else False),
                'primary_label': response.xpath('//p[@data-component="LabelPrimary"]/text()').get(),
                'image_url': response.xpath('//button[@data-is-loaded]/img/@src').get(),
                'text': response.xpath('//div[@data-component="TabPanelContainer"]/div/div/div/div/p/text()').getall(),
            }

            if not os.path.exists('output'):
                # If the directory doesn't exist, create it
                os.makedirs('output')

            # save to JSON
            self.save_to_csv(filename, data)

            # Create a directory for images if it doesn't exist
            image_dir = 'output/images/farfetch/' + date_string + '/' + \
                response.url.split('/')[-1].split('.')[0]
            if not os.path.exists(image_dir):
                os.makedirs(image_dir)

            # Download images
            image_urls = data['image_url']
            yield scrapy.Request(image_urls, callback=self.save_image, meta={'image_dir': image_dir})


if __name__ == "__main__":
    configure_logging(install_root_handler=False)
    logging.basicConfig(
        filename=f'log/{FFSpider.name}-log-{date.today()}.log',
        format='%(asctime)s %(levelname)s: %(message)s',
        level=logging.INFO
    )