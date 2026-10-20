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



def test_geolocation_by_host_wins_over_global_and_other_hosts_keep_global():
    settings = Settings({
        "CRAWLER_API_ZYTE_GEOLOCATION": "AE",
        "CRAWLER_API_ZYTE_GEOLOCATION_BY_HOST": {"saudi.ounass.com": "TR"},
    })
    saudi = build_zyte_api_params(settings, REQUEST_TYPE_HTTP_RESPONSE,
                                  url="https://saudi.ounass.com/api/women/bags/tote-bags")
    uae = build_zyte_api_params(settings, REQUEST_TYPE_HTTP_RESPONSE,
                                url="https://www.ounass.ae/api/women/bags/tote-bags")
    assert saudi["geolocation"] == "TR"
    assert uae["geolocation"] == "AE"


def test_project_settings_route_ounass_saudi_hosts_through_turkiye():
    from ecommercecrawl import settings as project_settings
    by_host = project_settings.CRAWLER_API_ZYTE_GEOLOCATION_BY_HOST
    assert {by_host[h] for h in ("saudi.ounass.com", "en-saudi.ounass.com", "ar.ounass.sa")} == {"TR"}
    params = build_zyte_api_params(Settings({"CRAWLER_API_ZYTE_GEOLOCATION_BY_HOST": by_host}),
                                   REQUEST_TYPE_HTTP_RESPONSE, url="https://www.levelshoes.com/x")
    assert "geolocation" not in params
