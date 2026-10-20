from urllib.parse import urlparse

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


def _geolocation_for(settings, url):
    """
    Per-hostname geolocation (CRAWLER_API_ZYTE_GEOLOCATION_BY_HOST) wins over
    the global CRAWLER_API_ZYTE_GEOLOCATION; neither set = Zyte's default.
    """
    by_host = _get_setting(settings, "CRAWLER_API_ZYTE_GEOLOCATION_BY_HOST", None) or {}
    if url and by_host:
        host = (urlparse(url).hostname or "").lower()
        value = by_host.get(host)
        if value:
            return str(value).strip() or None
    return _get_optional_setting(settings, "CRAWLER_API_ZYTE_GEOLOCATION")


def build_zyte_api_params(settings=None, request_type=REQUEST_TYPE_HTTP_RESPONSE, url=None):
    """
    Convert a generic crawler API request type into Zyte API parameters.

    `http_response` preserves existing JSON/API response parsing, and covers
    Ounass PDPs too: the PDP state is server-rendered into the plain HTML, so
    no browser is needed to read it. `rendered_html` asks Zyte for a browser
    render; Ounass only uses it as an opt-in, one-time retry (see
    OUNASS_PDP_BROWSER_HTML_FALLBACK, off by default) when a PDP's state is
    unexpectedly missing from the plain response.
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

    geolocation = _geolocation_for(settings, url)
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
    request_meta["zyte_api"] = build_zyte_api_params(settings, request_type, url=url)

    return scrapy.Request(
        url=url,
        callback=callback,
        meta=request_meta,
        **request_kwargs,
    )
