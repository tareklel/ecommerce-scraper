import scrapy
from datetime import date
from ecommercecrawl.spiders.mastercrawl import MasterCrawl
from ecommercecrawl.rules import farfetch_rules as rules
from ecommercecrawl.constants import farfetch_constants as constants


def _slot_delay(url):
    if constants.IMAGE_CDN in url:
        return 2.0
    return 0.5


class FFSpider(MasterCrawl):
    name = constants.NAME
    default_urls_path_setting = 'FARFETCH_URLS_PATH'
    default_urls_path_constant = constants.FARFETCH_URLS

    def __init__(self, urlpath=None, urls=None, limit=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.urlpath = urlpath
        self.start_urls = urls or []
        self.limit = limit

    def _schedule(self, url, **kw):
        req = scrapy.Request(url, **kw)
        req.meta['download_delay'] = _slot_delay(req.url)
        return req

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
        
        if self.limit:
            total_pages = min(total_pages, self.limit)

        # Prefer rules.get_list_page_urls to generate 2..N; if it returns all pages, filter below.
        urls = rules.get_list_page_urls(response.url, total_pages)

        return urls

    # ---------- Router ----------
    def parse(self, response):
        if rules.is_plp(response.url):      # PLP
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
            pdp_url = response.urljoin(pdp)
            yield self._schedule(pdp_url, callback=self.parse)

        # 2) Only the first page schedules the other pages 2..N
        if rules.is_first_page(response.url):
            for url in self.get_pages(response):
                yield self._schedule(url, callback=self.parse)

    # ---------- PDP handler ----------
    def parse_pdp(self, response):
        """
        Orchestrates PDP data extraction, persistence, and image downloading.
        """
        data = self._populate_pdp_data(response)
        #date_string = data['crawl_date']
        #outfile_base = self.build_output_basename(constants.OUTPUT_DIR, date_string, 'pdps')

        # Persist
        #self.save_to_jsonl(outfile_base, data)

        # Images
        # yield from self.download_images(date_string, response.url, data.get('image_url'))

        yield data

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
            'run_id': self.run_id,
            'site': constants.NAME,
            'crawl_date': date_string,
            'url': rules.get_url_drop_param(response.url),
            'country': rules.get_country(response.url),
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