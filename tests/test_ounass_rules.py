import json
import pytest
from scrapy.http import HtmlResponse, TextResponse, Request

from ecommercecrawl.rules import ounass_rules as rules
from ecommercecrawl.constants.ounass_constants import MAIN_SITE

# Helper to create a mock Scrapy TextResponse object
def create_mock_response(body_dict, url=MAIN_SITE):
    """Creates a Scrapy TextResponse object with a JSON body."""
    body = json.dumps(body_dict)
    request = Request(url=url)
    return TextResponse(url=url, request=request, body=body, encoding='utf-8')

def create_mock_html_response(body_html, url="http://fake.com/product.html"):
    request = Request(url=url)
    return HtmlResponse(url=url, request=request, body=body_html, encoding='utf-8')

# --- Tests for is_plp ---

def test_is_plp_true_for_plp_route():
    """Should return True when routeType is 'plp'."""
    response = create_mock_response({"routeType": "plp"})
    assert rules.is_plp(response) is True

def test_is_plp_false_for_other_route():
    """Should return False when routeType is not 'plp'."""
    response = create_mock_response({"routeType": "pdp"})
    assert rules.is_plp(response) is False

def test_is_plp_false_for_missing_key():
    """Should return False when routeType key is missing."""
    response = create_mock_response({"otherKey": "value"})
    assert rules.is_plp(response) is False

# --- Tests for get_max_pages ---

def test_get_max_pages_extracts_correctly():
    """Should return the correct number of total pages."""
    response = create_mock_response({"pagination": {"totalPages": 42}})
    assert rules.get_max_pages(response) == 42

def test_get_max_pages_raises_error_if_key_missing():
    """Should raise KeyError if 'totalPages' or 'pagination' is missing."""
    with pytest.raises(KeyError):
        rules.get_max_pages(create_mock_response({}))
    with pytest.raises(KeyError):
        rules.get_max_pages(create_mock_response({"pagination": {}}))

# --- Tests for is_first_page ---

def test_is_first_page_true_for_page_zero():
    """Should return True when currentPage is 0."""
    response = create_mock_response({"pagination": {"currentPage": 0}})
    assert rules.is_first_page(response) is True

def test_is_first_page_false_for_other_pages():
    """Should return False when currentPage is not 0."""
    response = create_mock_response({"pagination": {"currentPage": 1}})
    assert rules.is_first_page(response) is False

def test_is_first_page_raises_error_if_key_missing():
    """Should raise KeyError if keys are missing."""
    with pytest.raises(KeyError):
        rules.is_first_page(create_mock_response({}))


# --- Tests for get_pdps ---

def test_get_pdps_extracts_and_deduplicates_slugs():
    """
    Test that get_pdps extracts primary and additional slugs, deduplicates them, and builds correct URLs.
    """
    # Arrange
    mock_data = {
        "hits": [
            {
                "slug": "product-one",
                "configurableAttributes": [
                    {
                        "options": [
                            {"attributeSpecificProperties": {"slug": "product-one-variant-a"}},
                            {"attributeSpecificProperties": {"slug": "product-one-variant-b"}}
                        ]
                    }
                ]
            },
            {
                "slug": "product-two",
                "configurableAttributes": []
            },
            {
                "slug": "product-one",  # Duplicate primary slug
                "configurableAttributes": [
                    {
                        "options": [
                            {"attributeSpecificProperties": {"slug": "product-one-variant-a"}} # Duplicate variant
                        ]
                    }
                ]
            }
        ]
    }
    response = TextResponse(url=MAIN_SITE, body=json.dumps(mock_data), encoding='utf-8')

    # Act
    urls = rules.get_pdps(response)

    # Assert
    expected_urls = {
        "https://www.ounass.ae/product-one.html",
        "https://www.ounass.ae/product-one-variant-a.html",
        "https://www.ounass.ae/product-one-variant-b.html",
        "https://www.ounass.ae/product-two.html"
    }
    
    # The order is not guaranteed because of the set, so we compare sets
    assert set(urls) == expected_urls
    assert len(urls) == 4


def test_get_pdps_handles_missing_keys():
    """
    Should return a list of full product URLs.
    """
    data = {
        "hits": [
            {"slug": "product-1"},
            {"slug": "product-2"}
        ]
    }
    response = create_mock_response(data)
    expected_urls = [
        f'{MAIN_SITE}product-1.html',
        f'{MAIN_SITE}product-2.html',

    ]
    assert rules.get_pdps(response) == expected_urls

def test_get_pdps_returns_empty_list_for_no_hits():
    """Should return an empty list if 'hits' is empty or missing."""
    # Test with 'hits' as an empty list
    response_empty = create_mock_response({"hits": []})
    assert rules.get_pdps(response_empty) == []

    # Test with 'hits' key missing entirely, which should not raise an error
    response_missing_hits = create_mock_response({})
    assert rules.get_pdps(response_missing_hits) == []

# --- Tests for is_pdp ---

def test_is_pdp_true_for_html_url():
    """Should return True for URLs ending in .html."""
    response = create_mock_response({}, url="https://www.ounass.ae/some-product.html")
    assert rules.is_pdp(response) is True

def test_is_pdp_false_for_non_html_url():
    """Should return False for URLs not ending in .html."""
    response = create_mock_response({}, url="https://api.ounass.ae/some/data")
    assert rules.is_pdp(response) is False

# --- Tests for get_state ---

def test_get_state_extracts_initial_state():
    state = {
        "routeType": "new-pdp",
        "country": "AE",
        "pdp": {"name": "Test Product"}
    }
    script = f"window.initialState = {json.dumps(state, separators=(',', ':'))};"
    html = f"<html><body><script>{script}</script></body></html>"
    response = create_mock_html_response(html)

    assert rules.get_state(response) == state


def test_get_state_returns_none_when_script_missing():
    html = "<html><body><div>No state script here</div></body></html>"
    response = create_mock_html_response(html)

    assert rules.get_state(response) is None


def test_get_state_returns_none_on_invalid_json():
    script = 'window.initialState = {"routeType":"new-pdp",};'
    html = f"<html><body><script>{script}</script></body></html>"
    response = create_mock_html_response(html)

    assert rules.get_state(response) is None


# --- Tests for safe_get ---

def test_safe_get_returns_nested_value():
    data = {"a": {"b": {"c": 5}}}
    assert rules.safe_get(data, ["a", "b", "c"]) == 5


def test_safe_get_returns_default_when_missing():
    data = {"a": {}}
    assert rules.safe_get(data, ["a", "b"], default="missing") == "missing"


def test_safe_get_returns_default_for_non_dict():
    assert rules.safe_get("not-a-dict", ["a"], default=None) is None


# --- Tests for extraction helpers ---

def test_get_sold_out_recognizes_badge_string():
    state = {"pdp": {"badge": {"value": "OUT OF STOCK"}}}
    assert rules.get_sold_out(state) is True


def test_get_sold_out_handles_non_matching_badge():
    state = {"pdp": {"badge": {}}}
    assert rules.get_sold_out(state) is None


def test_get_sold_out_returns_none_for_missing_badge():
    state = {"pdp": {}}
    assert rules.get_sold_out(state) is None


def test_get_discount_returns_value_or_none():
    assert rules.get_discount({"pdp": {"discountPercent": 30}}) == 30
    assert rules.get_discount({"pdp": {}}) is None


def test_get_primary_label_extracts_value():
    state = {"pdp": {"badge": {"value": "NEW"}}}
    assert rules.get_primary_label(state) == "NEW"


def test_get_primary_label_returns_none_for_missing_badge():
    state = {"pdp": {}}
    assert rules.get_primary_label(state) is None


def test_get_image_url_extracts_path():
    state = {"pdp": {"images": [{"oneX": "https://cdn.ounass.ae/image.jpg"}]}}
    assert rules.get_image_url(state) == "cdn.ounass.ae/image.jpg"


def test_get_image_url_returns_none_on_error():
    state = {"pdp": {}}
    assert rules.get_image_url(state) is None


def test_get_data_collects_expected_fields():
    state = {
        "country": "AE",
        "currency": "AED",
        "pdp": {
            "visibleSku": "SKU123",
            "name": "Product Name",
            "gender": "MEN",
            "designerCategoryName": "Brand",
            "designerId": "BRAND123",
            "department": "Shoes",
            "class": "Sneakers",
            "colorInEnglish": "Black",
            "price": 1500,
            "discountPercent": 20,
            "badge": {"value": "EXCLUSIVE"},
            "images": [{"oneX": "https://cdn.ounass.ae/path/img.jpg"}],
            "contentTabs": [
                {"tabId": "designDetails", "html": "<p>Leather upper</p>"},
                {"tabId": "sizeAndFit", "html": "<p>True to size</p>"},
            ],
        }
    }

    assert rules.get_data(state) == {
        "country": "AE",
        "portal_itemid": "SKU123",
        "product_name": "Product Name",
        "gender": "MEN",
        "brand": "Brand",
        "brand_id": "BRAND123",
        "category": "Shoes",
        "subcategory": "Sneakers",
        "color": "Black",
        "price": 1500,
        "currency": "AED",
        "price_discount": 20,
        "primary_label": "EXCLUSIVE",
        "image_urls": "cdn.ounass.ae/path/img.jpg",
        "out_of_stock": False,
        "text": {"design_details": "Leather upper", "size_fit": "True to size"},
    }
