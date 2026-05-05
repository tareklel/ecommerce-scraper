import pytest
import scrapy
from scrapy.settings import Settings

from ecommercecrawl.crawler_api import (
    REQUEST_TYPE_HTTP_RESPONSE,
    REQUEST_TYPE_RENDERED_HTML,
    build_crawler_api_request,
)
from ecommercecrawl.crawler_api.zyte_api import build_zyte_api_params


def test_build_crawler_api_request_dispatches_to_zyte():
    settings = Settings({"CRAWLER_API_SERVICE": "zyte"})

    request = build_crawler_api_request(
        url="https://www.ounass.ae/api/women/designers/burberry/bags",
        callback=lambda response: None,
        settings=settings,
        request_type=REQUEST_TYPE_HTTP_RESPONSE,
    )

    assert isinstance(request, scrapy.Request)
    assert request.meta["zyte_api"] == {
        "httpResponseBody": True,
        "httpResponseHeaders": True,
    }


def test_build_crawler_api_request_rejects_unknown_service():
    settings = Settings({"CRAWLER_API_SERVICE": "unknown"})

    with pytest.raises(ValueError, match="Unsupported crawler API service"):
        build_crawler_api_request(
            url="https://example.com",
            callback=lambda response: None,
            settings=settings,
        )


def test_build_zyte_api_params_for_rendered_html():
    assert build_zyte_api_params(request_type=REQUEST_TYPE_RENDERED_HTML) == {
        "browserHtml": True,
    }


def test_build_zyte_api_params_includes_optional_geolocation():
    settings = Settings({"CRAWLER_API_ZYTE_GEOLOCATION": "AE"})

    assert build_zyte_api_params(settings, REQUEST_TYPE_HTTP_RESPONSE) == {
        "httpResponseBody": True,
        "httpResponseHeaders": True,
        "geolocation": "AE",
    }
