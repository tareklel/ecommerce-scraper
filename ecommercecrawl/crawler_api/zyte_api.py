import scrapy

from ecommercecrawl.crawler_api import (
    REQUEST_TYPE_HTTP_RESPONSE,
    REQUEST_TYPE_RENDERED_HTML,
)


def _get_setting(settings, name, default):
    if settings is None:
        return default
    return settings.get(name, default)


def _get_optional_setting(settings, name):
    value = _get_setting(settings, name, None)
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def build_zyte_api_params(settings=None, request_type=REQUEST_TYPE_HTTP_RESPONSE):
    """
    Convert a generic crawler API request type into Zyte API parameters.

    `http_response` preserves existing JSON/API response parsing. `rendered_html`
    asks Zyte for browser-rendered HTML, which is needed for Ounass PDP pages.
    """
    if request_type == REQUEST_TYPE_RENDERED_HTML:
        params = {"browserHtml": True}
    elif request_type == REQUEST_TYPE_HTTP_RESPONSE:
        params = {
            "httpResponseBody": True,
            "httpResponseHeaders": True,
        }
    else:
        raise ValueError(f"Unsupported crawler API request type: {request_type}")

    geolocation = _get_optional_setting(settings, "CRAWLER_API_ZYTE_GEOLOCATION")
    if geolocation:
        params["geolocation"] = geolocation

    return params


def build_request(
    url,
    callback,
    settings=None,
    request_type=REQUEST_TYPE_HTTP_RESPONSE,
    meta=None,
    **request_kwargs,
):
    request_meta = dict(meta or {})
    request_meta["zyte_api"] = build_zyte_api_params(settings, request_type)

    return scrapy.Request(
        url=url,
        callback=callback,
        meta=request_meta,
        **request_kwargs,
    )
