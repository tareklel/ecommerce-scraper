import scrapy
from datetime import date
from ecommercecrawl.spiders.mastercrawl import MasterCrawl
from ecommercecrawl.rules import level_rules as rules
from ecommercecrawl.constants import level_constants as constants
import requests
import re


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
            yield from self.handle_plp_url(url)
            return
        yield scrapy.Request(url, callback=self.parse_pdp, meta={"item": {}})

    def get_api_params(self, url, page_number=0):
        if rules.is_plp(url):
            country = rules.get_country(url)
            gender = rules.get_gender(url)
            headers = constants.API_HEADERS
            language = rules.get_language_plp(url)
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
            items = rules.get_products(payload) or []
            if not items:
                break
            for item in items:
                yield from self._handle_plp_item(item)
            page +=1
        
    def _handle_plp_item(self, item):
        date_string = date.today().strftime("%Y-%m-%d")
        url = rules.get_url_from_item(item)


        data_dict = {
                'run_id': self.run_id,
                'site': constants.NAME,
                'crawl_date': date_string,
                'url': url,
                'portal_itemid': rules.get_id_from_item(item),
                'product_name': rules.get_name_from_item(item),
                'gender': rules.get_gender_from_item(item),
                'brand': rules.get_brand_from_item(item),
                'category':rules.get_category_from_item(item),
                'subcategory': rules.get_subcategory_from_item(item),
                'price': rules.get_price_from_item(item),
                'currency': rules.get_currency_from_item(item),
                # percentage discounted
                'price_discount': rules.get_price_discount_from_item(item),
                'primary_label': rules.get_primary_label_from_item(item),
                'image_urls': rules.get_image_urls_from_item(item)
                # add sold out https://www.levelshoes.com/off-white-out-of-office-ooo-sneakers-white-calf-leather-men-low-tops-a8vplk.html
                # 'is_sold_out': rules.is_sold_out_from_item(item),
            }
        yield scrapy.Request(
            url, 
            callback=self.parse_pdp, 
            meta={"item": data_dict}
            )

    def parse(self, response):
        yield from self.parse_pdp(response)

    def parse_pdp(self, response):
        item = response.meta.get('item', {})
        # add logic here to handle fillng data dict for blanks in response
        item['text'] = rules.extract_product_details(response)
        yield item
