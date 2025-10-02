
import pytest
from ecommercecrawl.rules import farfetch_rules as rules
from scrapy.http import HtmlResponse
from farfetch_html_fixtures import pdp

@pytest.fixture
def pdp_response():
    with open("tests/farfetch_html_fixtures/pdp.html", "r") as f:
        html_content = f.read()
    return HtmlResponse(url="https://www.farfetch.com/ca/shopping/women/versace-medusa-plaque-platform-sandals-item-18533473.aspx", body=html_content, encoding='utf-8')

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

def test_get_product_name(pdp_response):
    assert rules.get_product_name(pdp_response) == pdp['product_name']

def test_get_brand(pdp_response):
    assert rules.get_brand(pdp_response) == pdp['brand']

def test_get_price(pdp_response):
    assert rules.get_price(pdp_response) == pdp['intermediary_price']

def test_get_discount(pdp_response):
    assert rules.get_discount(pdp_response) is None

def test_is_sold_out(pdp_response):
    assert rules.is_sold_out(pdp_response) is False

def test_get_primary_label(pdp_response):
    assert rules.get_primary_label(pdp_response) == pdp['primary_label']

def test_get_image_url(pdp_response):
    assert rules.get_image_url(pdp_response) == pdp['image_url']

def test_get_text(pdp_response):
    assert rules.get_text(pdp_response) == pdp['text']