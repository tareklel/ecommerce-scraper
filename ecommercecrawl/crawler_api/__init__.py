DEFAULT_CRAWLER_API_SERVICE = "zyte"
REQUEST_TYPE_HTTP_RESPONSE = "http_response"
REQUEST_TYPE_RENDERED_HTML = "rendered_html"


def _get_setting(settings, name, default):
    if settings is None:
        return default
    return settings.get(name, default)


def get_crawler_api_service(settings=None):
    service = _get_setting(settings, "CRAWLER_API_SERVICE", DEFAULT_CRAWLER_API_SERVICE)
    return str(service).strip().lower()


def build_crawler_api_request(
    url,
    callback,
    settings=None,
    request_type=REQUEST_TYPE_HTTP_RESPONSE,
    meta=None,
    **request_kwargs,
):
    """
    Build a Scrapy request for the configured crawler API service.

    The spider layer stays service-agnostic; each service module maps the
    generic request type to provider-specific request parameters.
    """
    service = get_crawler_api_service(settings)

    if service == "zyte":
        from ecommercecrawl.crawler_api import zyte_api

        return zyte_api.build_request(
            url=url,
            callback=callback,
            settings=settings,
            request_type=request_type,
            meta=meta,
            **request_kwargs,
        )

    raise ValueError(f"Unsupported crawler API service: {service}")
