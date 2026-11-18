import json
from urllib.parse import parse_qs, urlparse

import scrapy
from scrapy.http import HtmlResponse, Request, TextResponse
from twisted.python.failure import Failure

from ecommercecrawl.spiders.bloomingdales_crawl import BloomingdalesSpider


PLP_URL = "https://en.bloomingdales.sa/womens-bags-shoulder-bags/"
SETTINGS = (
    '"commerceAPI":{"proxyPath":"\\u002Fmobify\\u002Fproxy\\u002Fapi","parameters":'
    '{"clientId":"client-1","organizationId":"f_ecom_test","siteId":"BloomingDales_SA"}}'
    '<meta href="https://x/dw/shop/v99_9/product_search?refine_1=cgid%3Dwomen-womens-bags-shoulder-bags&amp;c=1"/>'
)
FIRST_BATCH = '<a href="/khaite-Kye-Mini-BAG219032925xBLK.html">bag</a>'
API = "https://en.bloomingdales.sa/mobify/proxy/api"


def _html(url, body, meta=None):
    return HtmlResponse(url=url, request=Request(url=url, meta=meta or {}), body=body, encoding="utf-8")


def _json(request, data, status=200, headers=None):
    return TextResponse(url=request.url, request=request, body=json.dumps(data), encoding="utf-8",
                        status=status, headers=headers)


def _hits(start, count):
    return [{"productId": f"BAG2195{i:05d}xBLK", "c_brand_en": "Furla", "c_name_en": f"Bag {i}"}
            for i in range(start, start + count)]


def _by_callback(results, name):
    return [r for r in results if isinstance(r, scrapy.Request) and r.callback.__name__ == name]


def _to_search(spider):
    """Listing page -> guest login -> token; returns the first search request."""
    [authorize] = _by_callback(list(spider.parse_plp(_html(PLP_URL, FIRST_BATCH + SETTINGS))), "parse_guest_code")
    redirect = _json(authorize, {}, status=303,
                     headers={"Location": "https://en.bloomingdales.sa/callback?code=c1&usid=u1"})
    [token_request] = list(spider.parse_guest_code(redirect))
    [search] = list(spider.parse_guest_token(_json(token_request, {"access_token": "t1", "expires_in": 1800})))
    return authorize, token_request, search


def test_listing_logs_in_as_guest_and_searches_the_listing():
    spider = BloomingdalesSpider()
    results = list(spider.parse_plp(_html(PLP_URL, FIRST_BATCH + SETTINGS)))
    # The first batch is still crawled from the page.
    assert [r.url for r in _by_callback(results, "parse_pdp")] == [
        "https://en.bloomingdales.sa/khaite-Kye-Mini-BAG219032925xBLK.html"]

    authorize, token_request, search = _to_search(spider)
    query = parse_qs(urlparse(authorize.url).query)
    assert authorize.url.startswith(f"{API}/shopper/auth/v1/organizations/f_ecom_test/oauth2/authorize?")
    assert query["hint"] == ["guest"] and query["client_id"] == ["client-1"]
    assert authorize.meta["dont_redirect"] and 303 in authorize.meta["handle_httpstatus_list"]
    form = parse_qs(token_request.body.decode())
    assert form["grant_type"] == ["authorization_code_pkce"] and form["code"] == ["c1"] and form["usid"] == ["u1"]
    assert search.headers["Authorization"] == b"Bearer t1"
    params = parse_qs(urlparse(search.url).query)
    assert params["refine"] == ["cgid=women-womens-bags-shoulder-bags"]
    assert params["locale"] == ["en-SA"] and params["currency"] == ["SAR"] and params["offset"] == ["0"]


def test_search_pages_until_the_total_and_requests_every_product_page():
    spider = BloomingdalesSpider()
    _, _, search = _to_search(spider)
    results = list(spider.parse_search(_json(search, {"total": 60, "hits": _hits(0, 48)})))
    assert len(_by_callback(results, "parse_pdp")) == 48
    [following] = _by_callback(results, "parse_search")
    assert parse_qs(urlparse(following.url).query)["offset"] == ["48"]

    results = list(spider.parse_search(_json(following, {"total": 60, "hits": _hits(48, 12)})))
    assert len(_by_callback(results, "parse_pdp")) == 12
    assert _by_callback(results, "parse_search") == []        # reached the total
    assert spider.run_degradations == []


def test_limit_caps_search_pages():
    spider = BloomingdalesSpider(limit="1")
    _, _, search = _to_search(spider)
    results = list(spider.parse_search(_json(search, {"total": 455, "hits": _hits(0, 48)})))
    assert len(_by_callback(results, "parse_pdp")) == 48
    assert _by_callback(results, "parse_search") == []


def test_page_without_search_settings_crawls_its_first_batch_and_says_so():
    spider = BloomingdalesSpider()
    results = list(spider.parse_plp(_html(PLP_URL, FIRST_BATCH)))
    assert [r.callback.__name__ for r in results] == ["parse_pdp"]
    [degradation] = spider.run_degradations
    assert degradation["kind"] == "content" and degradation["scope"] == PLP_URL
    assert "only its first batch" in degradation["message"]


def test_failed_guest_login_is_a_degradation():
    spider = BloomingdalesSpider()
    [authorize] = _by_callback(list(spider.parse_plp(_html(PLP_URL, SETTINGS))), "parse_guest_code")
    assert list(spider.parse_guest_code(_json(authorize, {}, status=200))) == []
    assert "guest login gave no code" in spider.run_degradations[0]["message"]


def test_failed_search_request_is_a_degradation():
    spider = BloomingdalesSpider()
    _, _, search = _to_search(spider)
    failure = Failure(RuntimeError("HTTP 401"))
    failure.request = search
    spider.listing_failed(failure)
    [degradation] = spider.run_degradations
    assert degradation["scope"] == PLP_URL and "listing search failed (HTTP 401)" in degradation["message"]
