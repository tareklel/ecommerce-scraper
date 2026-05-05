import pytest
from unittest.mock import patch, MagicMock

import scrapy
from scrapy.http import HtmlResponse
from scrapy.settings import Settings
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


def configure_spider(spider, **overrides):
    settings = Settings(
        {
            "CRAWLER_API_SERVICE": "zyte",
            "OUNASS_FETCH_BACKEND": "auto",
            "OUNASS_REQUESTS_TLDS": [],
            "OUNASS_CRAWLER_API_PLP_REQUEST_TYPE": "http_response",
            "OUNASS_CRAWLER_API_PDP_REQUEST_TYPE": "rendered_html",
            "OUNASS_REQUEST_DELAY_SECONDS": "0",
            "OUNASS_REQUEST_JITTER_SECONDS": "0",
            "OUNASS_REQUEST_TIMEOUT_SECONDS": "20",
            **overrides,
        }
    )
    spider.settings = settings
    return spider


# --- Tests for _handle_seed_url ---

def test_handle_seed_url_auto_backend_uses_api_for_plp_by_default(spider):
    """
    Auto mode is API-first when OUNASS_REQUESTS_TLDS is empty.
    """
    configure_spider(spider)
    url = "https://www.ounass.ae/api/women/designers/burberry/bags"

    results = list(spider._handle_seed_url(url))

    assert len(results) == 1
    request = results[0]
    assert isinstance(request, scrapy.Request)
    assert request.url == url
    assert request.callback == spider.parse
    assert request.meta["zyte_api"] == {
        "httpResponseBody": True,
        "httpResponseHeaders": True,
    }


def test_handle_seed_url_auto_backend_uses_api_for_pdp_by_default(spider):
    """
    PDP URLs use rendered HTML through the API by default.
    """
    configure_spider(spider)
    url = "https://www.ounass.ae/shop-product.html"

    results = list(spider._handle_seed_url(url))

    assert len(results) == 1
    assert results[0].meta["zyte_api"] == {"browserHtml": True}


def test_handle_seed_url_auto_backend_uses_api_for_unlisted_tld_by_default(spider):
    """
    Unlisted TLDs also use API when the requests allowlist is empty.
    """
    configure_spider(spider)
    url = "https://kuwait.ounass.com/shop-product.html"

    results = list(spider._handle_seed_url(url))

    assert len(results) == 1
    assert isinstance(results[0], scrapy.Request)
    assert results[0].meta["zyte_api"] == {"browserHtml": True}


@patch('ecommercecrawl.spiders.ounass_crawl.requests.get')
def test_handle_seed_url_auto_backend_uses_requests_for_allowlisted_tld(mock_get, spider):
    """
    OUNASS_REQUESTS_TLDS is the explicit allowlist for normal requests.
    """
    configure_spider(spider, OUNASS_REQUESTS_TLDS=["kuwait.ounass.com"])
    url = "https://kuwait.ounass.com/shop-product.html"
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.url = url
    mock_response.content = b"<html></html>"
    mock_get.return_value = mock_response
    spider.parse = MagicMock(return_value=iter(["item1"]))

    results = list(spider._handle_seed_url(url))

    assert results == ["item1"]
    mock_get.assert_called_once_with(url, timeout=20)


def test_handle_seed_url_api_backend_forces_api_for_requests_allowlisted_tld(spider):
    """
    Forced API mode ignores the normal-requests allowlist.
    """
    configure_spider(
        spider,
        OUNASS_FETCH_BACKEND="api",
        OUNASS_REQUESTS_TLDS=["kuwait.ounass.com"],
    )
    url = "https://kuwait.ounass.com/shop-product.html"

    results = list(spider._handle_seed_url(url))

    assert len(results) == 1
    assert isinstance(results[0], scrapy.Request)
    assert results[0].meta["zyte_api"] == {"browserHtml": True}


@patch('ecommercecrawl.spiders.ounass_crawl.requests.get')
def test_handle_seed_url_requests_backend_success(mock_get, spider):
    """
    Requests mode keeps the legacy direct fetch and parse behavior available.
    """
    configure_spider(spider, OUNASS_FETCH_BACKEND="requests")
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
    mock_get.assert_called_once_with(url, timeout=20)
    spider.parse.assert_called_once()
    assert results == ["item1", "item2"]


@patch('ecommercecrawl.spiders.ounass_crawl.requests.get')
def test_handle_seed_url_requests_backend_skips_duplicate_pdp_url(mock_get, spider):
    """
    If the same PDP URL is encountered twice (e.g. seed + PLP discovery),
    it should only be fetched/parsed once.
    """
    configure_spider(spider, OUNASS_FETCH_BACKEND="requests")
    url = "https://www.ounass.ae/shop-same-product.html"
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.url = url
    mock_response.content = b"<html></html>"
    mock_get.return_value = mock_response

    spider.parse = MagicMock(return_value=iter(["item1"]))

    first = list(spider._handle_seed_url(url))
    second = list(spider._handle_seed_url(url))

    assert first == ["item1"]
    assert second == []
    mock_get.assert_called_once_with(url, timeout=20)
    spider.parse.assert_called_once()


def test_handle_seed_url_api_backend_skips_duplicate_pdp_url(spider):
    configure_spider(spider)
    url = "https://www.ounass.ae/shop-same-product.html"

    first = list(spider._handle_seed_url(url))
    second = list(spider._handle_seed_url(url))

    assert len(first) == 1
    assert second == []


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
        f"http://fake.com/plp?{constants.PLPSORT_KEY}={constants.PLPSORT}&p=0",
        f"http://fake.com/plp?{constants.PLPSORT_KEY}={constants.PLPSORT}&p=1",
        f"http://fake.com/plp?{constants.PLPSORT_KEY}={constants.PLPSORT}&p=2",
    ]
    assert urls == expected

@patch('ecommercecrawl.spiders.ounass_crawl.rules.get_max_pages', return_value=3)
def test_get_pages_sorted_url(mock_get_max, spider):
    """
    If URL is sorted, should return subsequent pages (1, 2).
    """
    # Arrange
    url = f"http://fake.com/plp?{constants.PLPSORT_KEY}={constants.PLPSORT}&p=0"
    response = create_mock_response(b'', url=url)
    
    # Act
    urls = spider.get_pages(response)

    # Assert
    expected = [
        f"http://fake.com/plp?{constants.PLPSORT_KEY}={constants.PLPSORT}&p=1",
        f"http://fake.com/plp?{constants.PLPSORT_KEY}={constants.PLPSORT}&p=2",
    ]
    assert urls == expected


# --- Tests for parse_plp ---

@patch('ecommercecrawl.spiders.ounass_crawl.rules.get_max_pages', return_value=2)
def test_parse_plp_unsorted_first_page(mock_get_max, spider):
    """
    If URL is unsorted, should return all pages (0, 1) with sort param.
    """
    # Arrange
    url = f"http://fake.com/plp?{constants.PLPSORT_KEY}=x&p=0"
    response = create_mock_response(b'', url=url)
    
    # Act
    urls = spider.get_pages(response)

    # Assert
    expected = [
        f"http://fake.com/plp?{constants.PLPSORT_KEY}={constants.PLPSORT}&p=0",
        f"http://fake.com/plp?{constants.PLPSORT_KEY}={constants.PLPSORT}&p=1",
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
    url = f"http://fake.com/plp?{constants.PLPSORT_KEY}={constants.PLPSORT}"
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
