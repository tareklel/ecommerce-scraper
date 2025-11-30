import pytest
from unittest.mock import patch, MagicMock

from scrapy.http import HtmlResponse
import requests
from ecommercecrawl.spiders.ounass_crawl import OunassSpider
from ecommercecrawl.constants import ounass_constants as constants


# Helper to create a mock Scrapy TextResponse object
def create_mock_response(body, url="http://fake.com"):
    """Creates a Scrapy HtmlResponse object."""
    return HtmlResponse(url=url, body=body, encoding='utf-8')

@pytest.fixture
def spider():
    """Fixture to create an instance of the OunassSpider."""
    return OunassSpider()

# --- Tests for _handle_seed_url ---

@patch('ecommercecrawl.spiders.ounass_crawl.requests.get')
def test_handle_seed_url_success(mock_get, spider):
    """
    Test that _handle_seed_url fetches a URL, creates a response,
    and yields the results from the parse method.
    """
    # Arrange
    url = "http://success.com"
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.url = url
    mock_response.content = b'<html></html>'
    mock_get.return_value = mock_response

    # Mock the parse method to see what it yields
    spider.parse = MagicMock(return_value=iter(["item1", "item2"]))

    # Act
    results = list(spider._handle_seed_url(url))

    # Assert
    mock_get.assert_called_once_with(url)
    spider.parse.assert_called_once()
    assert results == ["item1", "item2"]


# --- Tests for get_pages ---

@patch('ecommercecrawl.spiders.ounass_crawl.rules.get_max_pages', return_value=3)
def test_get_pages_unsorted_url(mock_get_max, spider):
    """
    If URL is unsorted, should return all pages (0, 1, 2) with sort param.
    """
    # Arrange
    response = create_mock_response(b'', url="http://fake.com/plp")
    
    # Act
    urls = spider.get_pages(response)

    # Assert
    expected = [
        f"http://fake.com/plp?sortBy={constants.PLPSORT}&p=0",
        f"http://fake.com/plp?sortBy={constants.PLPSORT}&p=1",
        f"http://fake.com/plp?sortBy={constants.PLPSORT}&p=2",
    ]
    assert urls == expected

@patch('ecommercecrawl.spiders.ounass_crawl.rules.get_max_pages', return_value=3)
def test_get_pages_sorted_url(mock_get_max, spider):
    """
    If URL is sorted, should return subsequent pages (1, 2).
    """
    # Arrange
    url = f"http://fake.com/plp?sortBy={constants.PLPSORT}&p=0"
    response = create_mock_response(b'', url=url)
    
    # Act
    urls = spider.get_pages(response)

    # Assert
    expected = [
        f"http://fake.com/plp?sortBy={constants.PLPSORT}&p=1",
        f"http://fake.com/plp?sortBy={constants.PLPSORT}&p=2",
    ]
    assert urls == expected


# --- Tests for parse_plp ---

@patch('ecommercecrawl.spiders.ounass_crawl.rules.get_max_pages', return_value=2)
def test_parse_plp_unsorted_first_page(mock_get_max, spider):
    """
    If URL is unsorted, should return all pages (0, 1) with sort param.
    """
    # Arrange
    url = f"http://fake.com/plp?sortBy=x&p=0"
    response = create_mock_response(b'', url=url)
    
    # Act
    urls = spider.get_pages(response)

    # Assert
    expected = [
        f"http://fake.com/plp?sortBy={constants.PLPSORT}&p=0",
        f"http://fake.com/plp?sortBy={constants.PLPSORT}&p=1",
    ]
    assert urls == expected

@patch('ecommercecrawl.spiders.ounass_crawl.rules')
def test_parse_plp_sorted_first_page(mock_rules, spider):
    """
    Should schedule subsequent pages AND process current products.
    """
    # Arrange
    mock_rules.is_first_page.return_value = True
    mock_rules.get_pdps.return_value = ["pdp_url_1"]
    url = f"http://fake.com/plp?sortBy={constants.PLPSORT}"
    response = create_mock_response(b'', url=url)
    
    spider.get_pages = MagicMock(return_value=["page_2_url"])
    spider._handle_seed_url = MagicMock(return_value=iter(["request"]))

    # Act
    results = list(spider.parse_plp(response))

    # Assert
    mock_rules.is_first_page.assert_called_with(response)
    # It should get pages to schedule
    spider.get_pages.assert_called_once_with(response)
    # It should also get products from the current page
    mock_rules.get_pdps.assert_called_once_with(response)
    # It should have handled one pagination URL and one product URL
    assert spider._handle_seed_url.call_count == 2