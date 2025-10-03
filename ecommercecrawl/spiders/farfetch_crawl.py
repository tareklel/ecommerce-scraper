import csv
import scrapy
from datetime import date
import logging
from scrapy.utils.log import configure_logging
import os
from ecommercecrawl.spiders.mastercrawl import Mastercrawl
from ecommercecrawl import settings
from ecommercecrawl.rules import farfetch_rules as rules
from ecommercecrawl.constants import farfetch_constants as constants


class FFSpider(scrapy.Spider, Mastercrawl):
    name = constants.NAME

    def __init__(self, urlpath=None, *args, **kwargs):
        super(FFSpider, self).__init__(*args, **kwargs)
        self.urlpath = urlpath
        self.settings = settings

    def start_requests(self):
        urls = []
        try:
            settings_get = self.settings.get if hasattr(self, "settings") else None
        except Exception:
            settings_get = None

        if self.urlpath is None:
            if settings_get:
                self.urlpath = settings_get('FARFETCH_URLS_PATH', constants.FARFETCH_URLS)
            else:
                self.urlpath = constants.FARFETCH_URLS

        with open(self.urlpath, newline='') as inputfile:
            for row in csv.reader(inputfile):
                if row:
                    urls.append(row[0])
        for url in urls:
            yield scrapy.Request(url=url, callback=self.parse)

    # ---------- Pagination helper (returns ONLY pages 2..N) ----------
    def get_pages(self, response):
        """
        Return URLs for remaining pages (2..N) of the current PLP.
        If no pagination or total_pages <= 1, return [].
        """
        pagination = rules.get_pagination(response)
        if not pagination:
            return []
        try:
            total_pages = rules.get_max_page(pagination)  # e.g., "1 of 51" -> 51
        except (ValueError, AttributeError):
            return []
        if total_pages <= 1:
            return []

        # Prefer rules.get_list_page_urls to generate 2..N; if it returns all pages, filter below.
        urls = rules.get_list_page_urls(response.url, total_pages)

        return urls

    # ---------- Router ----------
    def parse(self, response):
        if rules.is_items_page(response.url):      # PLP
            yield from self.parse_plp(response)
            return

        if rules.is_pdp_url(response.url):         # PDP
            yield from self.parse_pdp(response)
            return
        # else: ignore non-product URLs

    # ---------- PLP handler ----------
    def parse_plp(self, response):
        # 1) Always process the current PLP (including page 1)
        pdps = rules.get_pdp_urls(response)
        for pdp in pdps:
            yield response.follow(pdp, callback=self.parse)

        # 2) Only the first page schedules the other pages 2..N
        if rules.is_first_page(response.url):
            for url in self.get_pages(response):
                yield scrapy.Request(url=url, callback=self.parse)

    # ---------- PDP handler ----------
    def parse_pdp(self, response):
        """
        Orchestrates PDP data extraction, persistence, and image downloading.
        """
        data = self._populate_pdp_data(response)
        date_string = data['crawl_date']
        outfile_base = self.build_output_basename(constants.OUTPUT_DIR, constants.NAME, date_string)

        # Persist
        self.ensure_dir(constants.OUTPUT_DIR)
        self.save_to_csv(outfile_base, data)

        # Images
        yield from self.download_images(date_string, response.url, data.get('image_url'))

    def _populate_pdp_data(self, response):
        """
        Extracts all data from a PDP response and returns it as a dictionary.
        """
        today = date.today()
        primary_label = rules.get_primary_label(response)
        breadcrumbs = rules.get_breadcrumbs(response)
        date_string = today.strftime("%Y-%m-%d")
        sold_out = rules.is_sold_out(primary_label)
        
        if not sold_out:    
            price_raw = rules.get_price(response)
            price, currency = rules.get_price_and_currency(price_raw)
            discount = rules.get_discount(response)
            image_url = rules.get_image_url(response)
        else:
            price_raw = None
            price = None
            currency = None
            discount = None
            image_url = None

        return {
            'site': constants.NAME,
            'crawl_date': date_string,
            'country': rules.get_country(response.url),
            'url': rules.get_url_drop_param(response.url),
            'portal_itemid': rules.get_portal_itemid(response.url),
            'product_name': rules.get_product_name(response),
            'gender': rules.get_gender(response.url),
            'brand': rules.get_brand(response),
            'category': rules.get_category_from_breadcrumbs(breadcrumbs),
            'subcategory': rules.get_subcategory_from_breadcrumbs(breadcrumbs),
            'price': price,
            'currency': currency,
            'price_discount': discount,
            'sold_out': sold_out,
            'primary_label': primary_label,
            'image_url': image_url,
            'text': rules.get_text(response),
        }

    # ---------- Image downloader ----------
    def download_images(self, date_string: str, pdp_url: str, image_field):
            """
            Create target image directory and schedule image downloads.
            Accepts a single URL (str) or list of URLs.
            """
            image_dir = f'{constants.FARFETCH_IMAGE_BASE_DIR}/{date_string}/{rules.get_pdp_subfolder(pdp_url)}'
            self.ensure_dir(image_dir)

            # Normalize to iterable
            if not image_field:
                return
            urls = image_field if isinstance(image_field, (list, tuple)) else [image_field]

            for img_url in urls:
                if img_url:
                    yield scrapy.Request(img_url, callback=self.save_image, meta={'image_dir': image_dir})

if __name__ == "__main__":
    configure_logging(install_root_handler=False)
    os.makedirs('log', exist_ok=True)
    logging.basicConfig(
        filename=f'log/{FFSpider.name}-log-{date.today()}.log',
        format='%(asctime)s %(levelname)s: %(message)s',
        level=logging.INFO
    )