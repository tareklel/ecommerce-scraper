
import pytest
from ecommercecrawl.rules import farfetch_rules as rules
from scrapy.http import HtmlResponse
from farfetch_html_fixtures import pdp, sold_out_pdp, plp
from ecommercecrawl.constants import farfetch_constants as constants



@pytest.fixture
def pdp_response():
    with open("tests/farfetch_html_fixtures/pdp.html", "r") as f:
        html_content = f.read()
    return HtmlResponse(url=pdp['url'], body=html_content, encoding='utf-8')

# Test pdp 
def test_is_items_pages():
    assert rules.is_items_page("https://www.farfetch.com/ca/shopping/women/") is False
    assert rules.is_items_page("https://www.farfetch.com/ca/shopping/women/versace-medusa-plaque-platform-sandals-item-18533473.aspx") is False
    assert rules.is_items_page("https://www.farfetch.com/ae/shopping/women/designer-a-roege-hove/items.aspx") is True


def test_get_country():
    assert rules.get_country("https://www.farfetch.com/ca/shopping/women/dion-lee/items.aspx") == "ca"

def test_get_url_drop_param():
    assert rules.get_url_drop_param("https://www.farfetch.com/ca/shopping/women/dion-lee/items.aspx?page=2&view=90&sort=3") == "https://www.farfetch.com/ca/shopping/women/dion-lee/items.aspx"

def test_get_portal_itemid():
    assert rules.get_portal_itemid("https://www.farfetch.com/ca/shopping/women/versace-medusa-plaque-platform-sandals-item-18533473.aspx?storeid=9359") == "18533473"
    assert rules.get_portal_itemid("https://www.farfetch.com/ca/shopping/women/dion-lee/items.aspx") is None


def test_get_gender():
    assert rules.get_gender("https://www.farfetch.com/ca/shopping/women/versace-medusa-plaque-platform-sandals-item-18533473.aspx") == "women"
    assert rules.get_gender("https://www.farfetch.com/ca/shopping/women/dion-lee/items.aspx") is None

def test_get_category_from_breadcrumbs():
    breadcrumbs = ["Home", "Women", "Shoes", "Sandals"]
    assert rules.get_category_from_breadcrumbs(breadcrumbs) == "Shoes"
    assert rules.get_category_from_breadcrumbs(["Home", "Women"]) is None

def test_get_subcategory_from_breadcrumbs():
    breadcrumbs = ["Home", "Women", "Shoes", "Sandals"]
    assert rules.get_subcategory_from_breadcrumbs(breadcrumbs) == "Sandals"
    assert rules.get_subcategory_from_breadcrumbs(["Home", "Women", "Shoes"]) is None

def test_get_price_and_currency():
    price, currency = rules.get_price_and_currency("AED 2,180")
    assert price == 2180
    assert currency == "AED"
    price, currency = rules.get_price_and_currency(None)
    assert price is None
    assert currency is None

def test_sold_out_label():
    assert rules.is_sold_out(constants.SOLD_OUT_LABEL) is True
    assert rules.is_sold_out("Other Label") is False

def test_get_product_name(pdp_response):
    assert rules.get_product_name(pdp_response) == pdp['product_name']

def test_get_brand(pdp_response):
    assert rules.get_brand(pdp_response) == pdp['brand']

def test_get_price(pdp_response):
    assert rules.get_price(pdp_response) == pdp['intermediary_price']

def test_get_discount(pdp_response):
    assert rules.get_discount(pdp_response) is None

def test_get_primary_label(pdp_response):
    assert rules.get_primary_label(pdp_response) == pdp['primary_label']

def test_get_image_url(pdp_response):
    assert rules.get_image_url(pdp_response) == pdp['image_url']

def test_get_text(pdp_response):
    assert rules.get_text(pdp_response) == pdp['text']

# Test sold out PDP
@pytest.fixture
def sold_out_pdp_response():
    with open("tests/farfetch_html_fixtures/sold_out_pdp.html", "r") as f:
        html_content = f.read()
    return HtmlResponse(url=sold_out_pdp["url"], body=html_content, encoding='utf-8')

def test_get_product_name_sold_out(sold_out_pdp_response):
    assert rules.get_product_name(sold_out_pdp_response) == sold_out_pdp['product_name']

def test_get_brand_sold_out(sold_out_pdp_response):
    assert rules.get_brand(sold_out_pdp_response) == sold_out_pdp['brand']

def test_get_primary_label_sold_out(sold_out_pdp_response):
    assert rules.get_primary_label(sold_out_pdp_response) == sold_out_pdp['primary_label']

def test_is_sold_out_sold_out(sold_out_pdp_response):
    primary_label = rules.get_primary_label(sold_out_pdp_response)
    assert rules.is_sold_out(primary_label) == sold_out_pdp['sold_out']


# Test PLP
@pytest.fixture
def plp_response():
    with open("tests/farfetch_html_fixtures/plp.html", "r") as f:
        html_content = f.read()
    return HtmlResponse(url=plp['url'], body=html_content, encoding='utf-8')
                        
def test_get_pdp_urls(plp_response):
    assert rules.get_pdp_urls(plp_response) == plp['list_page_urls']

# next steps set up test for these
# plp: get_pdp_urls, is_first_page 
# pages: get_pagination, get_max_page, get_list_page_urls
# parse: rules.is_items_page, rules.is_pdp_url
# image: rules.get_pdp_subfolder
