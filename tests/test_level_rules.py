import pytest
from types import SimpleNamespace
from scrapy.http import HtmlResponse, Request

from ecommercecrawl.rules import level_rules as rules


def test_get_products_returns_value():
    payload = {"products": [{"id": 1}, {"id": 2}]}
    assert rules.get_products(payload) == payload["products"]


def test_get_products_missing_key():
    assert rules.get_products({"other": []}) is None


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.levelshoes.com/women/bags", "ae"),
        ("https://en-saudi.levelshoes.com/women/bags", "sa"),
        ("https://ar-saudi.levelshoes.com/women/bags", "sa"),
        ("https://en-kuwait.levelshoes.com/men/bags", "kw"),
        ("https://en-qatar.levelshoes.com/women/sale", "qa"),
        ("https://levels.example.com/women/bags", None),
    ],
)
def test_get_country(url, expected):
    assert rules.get_country(url) == expected


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.levelshoes.com/men/shoes", "men"),
        ("https://www.levelshoes.com/women/bags", "women"),
        ("https://www.levelshoes.com/kids/sneakers", "kids"),
        ("https://www.levelshoes.com/stories/all", None),
    ],
)
def test_get_gender(url, expected):
    assert rules.get_gender(url) == expected


def test_get_language_defaults_to_en():
    url = "https://www.levelshoes.com/women/bags"
    assert rules.get_language_plp(url) == "en"


def test_get_language_detects_arabic_from_path():
    url = "https://www.levelshoes.com/ar/women/bags"
    assert rules.get_language_plp(url) == "ar"


def test_get_language_detects_arabic_from_subdomain():
    url = "https://ar-saudi.levelshoes.com/women/bags"
    assert rules.get_language_plp(url) == "ar"


def test_get_language_raises_for_non_plp():
    with pytest.raises(ValueError):
        rules.get_language_plp("https://www.levelshoes.com/stories/all")


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.levelshoes.com/women/brands/miu-miu/bags", "brands/miu-miu/bags"),
        ("https://www.levelshoes.com/women/sale?color=black", "sale"),
        ("https://www.levelshoes.com/women", None),
    ],
)
def test_get_urlpath(url, expected):
    assert rules.get_urlpath(url) == expected


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.levelshoes.com/women/bags", True),
        ("https://www.levelshoes.com/women/sale?color=black", True),
        ("https://www.levelshoes.com/bally-bag.html", False),
        ("https://www.levelshoes.com/stories/all", False),
    ],
)
def test_is_plp(url, expected):
    assert rules.is_plp(url) is expected


def test_is_pdp_true_when_html_and_no_gender():
    response = SimpleNamespace(url="https://www.levelshoes.com/bally-bag.html")
    assert rules.is_pdp(response) is True


def test_is_pdp_false_when_gender_present_in_html_url():
    response = SimpleNamespace(url="https://www.levelshoes.com/women/bally-bag.html")
    assert rules.is_pdp(response) is False


def test_is_pdp_false_when_not_html():
    response = SimpleNamespace(url="https://www.levelshoes.com/women/bags")
    assert rules.is_pdp(response) is False


def test_get_url_from_item_returns_url():
    item = {"action": {"url": "https://www.levelshoes.com/p/some-pdp.html"}}
    assert rules.get_url_from_item(item) == "https://www.levelshoes.com/p/some-pdp.html"


def test_get_category_and_price_from_item():
    item = {
        "analytics": {
            "category1": "Bags",
            "category2": "Totes",
            "gender": "women",
            "originalPrice": 1234,
        }
    }
    assert rules.get_category_from_item(item) == "Bags"
    assert rules.get_subcategory_from_item(item) == "Totes"
    assert rules.get_gender_from_item(item) == "women"
    assert rules.get_price_from_item(item) == 1234


def test_get_currency_from_item_splits_amount_and_currency():
    item = {"originalPrice": "1234 AED"}
    assert rules.get_currency_from_item(item) == "AED"


def test_get_image_urls_from_item_returns_first_url():
    item = {"imagePreviewGallery": [{"url": "https://cdn.levelshoes.com/img.jpg"}]}
    assert rules.get_image_urls_from_item(item) == "https://cdn.levelshoes.com/img.jpg"


def test_get_primary_label_from_item_extracts_texts():
    item = {"badges": [{"text": "NEW"}, {"text": "EXCLUSIVE"}]}
    assert rules.get_primary_label_from_item(item) == ["NEW", "EXCLUSIVE"]


def test_extract_product_details_returns_bullets_and_text():
    html = """
    <div class="accordion-root">
      <button><span>Product Details</span></button>
      <div class="accordion-details-root">
        <p>100% calf leather</p>
        <p>Made in Italy</p>
      </div>
      <ul data-testid="lineitems">
        <li>Leather upper</li>
        <li>Rubber sole</li>
      </ul>
    </div>
    """
    response = HtmlResponse(
        url="https://www.levelshoes.com/product.html",
        request=Request(url="https://www.levelshoes.com/product.html"),
        body=html,
        encoding="utf-8",
    )
    assert rules.extract_product_details(response) == "Leather upper | Rubber sole | 100% calf leather Made in Italy"


def test_extract_product_details_returns_empty_when_missing():
    html = "<div class='other-section'>No product details here</div>"
    response = HtmlResponse(
        url="https://www.levelshoes.com/product.html",
        request=Request(url="https://www.levelshoes.com/product.html"),
        body=html,
        encoding="utf-8",
    )
    assert rules.extract_product_details(response) == ""
