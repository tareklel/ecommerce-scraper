import json
import pytest
from scrapy.http import TextResponse, Request

from ecommercecrawl.rules import ounass_rules as rules
from ecommercecrawl.constants.ounass_constants import MAIN_SITE

# Helper to create a mock Scrapy TextResponse object
def create_mock_response(body_dict, url="http://fake.com"):
    """Creates a Scrapy TextResponse object with a JSON body."""
    body = json.dumps(body_dict)
    request = Request(url=url)
    return TextResponse(url=url, request=request, body=body, encoding='utf-8')

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

def test_get_pdps_extracts_slugs_and_builds_urls():
    """Should return a list of full product URLs."""
    data = {
        "hits": [
            {"slug": "product-one"},
            {"slug": "product-two"}
        ]
    }
    response = create_mock_response(data)
    expected_urls = [
        f'{MAIN_SITE}product-one.html',
        f'{MAIN_SITE}product-two.html'
    ]
    assert rules.get_pdps(response) == expected_urls

def test_get_pdps_returns_empty_list_for_no_hits():
    """Should return an empty list if 'hits' is empty or missing."""
    response_empty = create_mock_response({"hits": []})
    assert rules.get_pdps(response_empty) == []
    with pytest.raises(KeyError):
        rules.get_pdps(create_mock_response({}))

# --- Tests for is_pdp ---

def test_is_pdp_true_for_html_url():
    """Should return True for URLs ending in .html."""
    response = create_mock_response({}, url="https://www.ounass.ae/some-product.html")
    assert rules.is_pdp(response) is True

def test_is_pdp_false_for_non_html_url():
    """Should return False for URLs not ending in .html."""
    response = create_mock_response({}, url="https://api.ounass.ae/some/data")
    assert rules.is_pdp(response) is False