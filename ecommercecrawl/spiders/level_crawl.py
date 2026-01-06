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
        self.date_string = date.today().strftime("%Y-%m-%d")

    def _get_payload(self, api, params, headers):
        try:
            response = requests.get(api, params=params, headers=headers)
            response.raise_for_status()
            payload = response.json()
        except requests.exceptions.RequestException as exc:
            self.logger.error(f"Failed to fetch PLP via API: {exc}")
            return None

        return payload
    
    def _fetch_plp_via_api(self, url, page_number=0):
        """
        Fetch a PLP payload directly from the Level API using requests.
        """
        api, params, headers = self.get_api_params_plp(url, page_number)
        return self._get_payload(api, params, headers)
    
    def _fetch_pdp_via_api(self, sku, language, gender):
        api, params, headers = self.get_api_params_pdp(sku, language, gender)
        return self._get_payload(api, params, headers)

    def _handle_seed_url(self, url):
        """
        Override to fetch PLP data via the API before parsing.
        """
        if rules.is_plp(url):
            yield from self.handle_plp_url(url)
            return
        elif rules.is_pdp(url):
            yield scrapy.Request(url, callback=self.parse)
            return
        return None

    def get_api_params_plp(self, url, page_number=0):
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
                yield from self._handle_item(item)
            page +=1
        
    def _handle_item(self, item):
        url = rules.get_url_from_item(item)


        data_dict = {
                'run_id': self.run_id,
                'site': constants.NAME,
                'crawl_date': self.date_string,
                'url': url,
                'country': rules.get_country(url),
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
                # add stock_info https://www.levelshoes.com/off-white-out-of-office-ooo-sneakers-white-calf-leather-men-low-tops-a8vplk.html
                # 'stock': rules.get_stock_from_item(item),
            }
        yield scrapy.Request(
            url, 
            callback=self.parse_pdp, 
            meta={"data_dict": data_dict}
            )

    def parse(self, response):
        if rules.is_pdp(response.url):
            yield from self.parse_pdp(response)

    def parse_pdp(self, response):
            # Fill in any missing fields from meta with lightweight placeholders without overwriting provided values.
            data_dict = dict(response.meta.get('data_dict', {}))
            placeholders = {
                'run_id': lambda: self.run_id,
                'site': lambda: constants.NAME,
                'crawl_date': lambda: self.date_string,
                'url': lambda: response.url,
                'country': lambda: rules.get_country(response.url),
                'portal_itemid': lambda: rules.extract_sku(response),
                'product_name': lambda: rules.extract_product_name(response),
                'gender': lambda: rules.extract_gender_from_breadcrumbs(response),
                'brand': lambda: rules.extract_product_brand(response),
                'category': lambda: rules.extract_category_and_subcategory_from_breadcrumbs(response)[0],
                'subcategory': lambda: rules.extract_category_and_subcategory_from_breadcrumbs(response)[1],
                'price': lambda: rules.extract_price(response),
                'currency': lambda: rules.extract_currency(response),
                'price_discount': lambda: rules.extract_price_discount(response),
                'primary_label': lambda: rules.extract_badges(response),
                'image_urls': lambda: rules.extract_first_image_url(response),
                'text': lambda: rules.extract_product_details(response),
                'out_of_stock': lambda: rules.is_out_of_stock(response),
                'level_category_id': lambda: rules.extract_level_category_id(response)
            }

            for key, provider in placeholders.items():
                if data_dict.get(key) is None:
                    value = provider()
                    if value is not None:
                        data_dict[key] = value
                    else:
                        data_dict[key] = None

            yield data_dict