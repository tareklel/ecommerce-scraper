import csv
import scrapy
from datetime import date
import re
import logging
from scrapy.utils.log import configure_logging
import pandas as pd
import os
from ecommercecrawl.items import ImgData
from ecommercecrawl.spiders.mastercrawl import Mastercrawl


class FFSpider(scrapy.Spider, Mastercrawl):
    name = "farfetch"
    # choose useragent at random
    # faker = Faker()
    # ualist = [faker.firefox, faker.chrome, faker.safari]
    # user_agent = numpy.random.choice(ualist)()
    # user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/103.0.0.0 Safari/537.36"
    configure_logging(install_root_handler=False)
    logging.basicConfig(
        filename=f'log/farfetch-log-{date.today()}.log',
        format='%(asctime)s %(levelname)s: %(message)s',
        level=logging.INFO
    )

    def start_requests(self):
        # get urls
        urls = []
        with open('resources/farfetch_urls.csv', newline='') as inputfile:
            for row in csv.reader(inputfile):
                urls.append(row[0])
        # check if there is a record of previously scraped files:
        if os.path.isfile('farfetch.jl') and not pd.read_json('farfetch.jl', lines=True).empty:
            self.scraped_urls = pd.read_json('farfetch.jl', lines=True)['url']
        else:
            self.scraped_urls = []
        for url in urls:
            yield scrapy.Request(url=url, callback=self.parse)

    def get_no_pages(self, response):
        """
        get number of pages in given category page and return urls of all pages
        """
        search = re.compile(r'"totalPages\\\\":([0-9]+),\\\\', re.IGNORECASE)\
            .findall(str(response.body))[-1]
        pages = [x + 1 for x in range(int(search))][1:]
        urls = [response.url + f'?page={str(page)}' for page in pages]
        return urls

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
        elif response.url in self.scraped_urls:
            pass
        else:
            response.url.split('/')[-1].split('?')[0] != 'items.aspx'
            price = response.xpath(
                '//p[@data-component="PriceLarge"]/text()|//p[@data-component="PriceFinalLarge"]/text()').get()
            breadcrumbs = response.xpath(
                '//li[@data-component="BreadcrumbWrapper"]/a/text()').getall()
            product_name = response.xpath(
                '//p[@data-component="LabelPrimary"]/../p/text()').getall()

            today = date.today()
            date_string = today.strftime("%Y-%m-%d")
            filename = f'farfetch-{date_string}'

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

            # save to JSON
            self.save_to_csv(filename, data)

            # Create a directory for images if it doesn't exist
            image_dir = 'images/farfetch/' + date_string + '/' + \
                response.url.split('/')[-1].split('.')[0]
            if not os.path.exists(image_dir):
                os.makedirs(image_dir)

            # Download images
            image_urls = data['image_url']
            yield scrapy.Request(image_urls, callback=self.save_image, meta={'image_dir': image_dir})
