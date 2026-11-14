import pytest
import scrapy
from scrapy.http import HtmlResponse, Request

from ecommercecrawl.constants import cettire_constants as constants
from ecommercecrawl.spiders import cettire_crawl
from ecommercecrawl.spiders.cettire_crawl import CettireSpider
from tests.cettire_fixtures import pdp_html, search_hit, search_payload

LISTING = "https://www.cettire.com/sa/collections/womens-bags/shoulder-bags"


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise cettire_crawl.requests.HTTPError(f"status {self.status_code}")


class FakeSearch:
    """Stands in for requests.post: records calls, answers from a queue or a function."""

    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def __call__(self, url, json=None, headers=None, timeout=None, auth=None):
        self.calls.append({"url": url, "json": json, "headers": headers, "auth": auth})
        return self.answer(url, json, headers)


@pytest.fixture
def spider(monkeypatch, tmp_path):
    monkeypatch.setattr(cettire_crawl.time, "sleep", lambda s: None)
    monkeypatch.setenv("CETTIRE_SEARCH_API_KEY", "stored-key")
    allowlist = tmp_path / "allow.csv"
    allowlist.write_text("brand\nAcme\nBeta\n", encoding="utf-8")
    s = CettireSpider()
    s.settings = {"CETTIRE_BRAND_ALLOWLIST_PATH": str(allowlist)}
    return s


def _facets_then_groups(facet, hits_by_brand):
    def answer(url, body, headers):
        vendors = body["productQueryInfo"]["vendorQuery"]
        if not vendors:
            return FakeResponse(payload=search_payload(hits=[], vendor_facet=facet))
        return FakeResponse(payload=search_payload(hits=[h for v in vendors for h in hits_by_brand.get(v, [])]))
    return answer


def _hit(n, vendor="Acme"):
    return search_hit(handle=f"{vendor.lower()}-bag-90000000{n}", vendor=vendor)


def test_listing_asks_only_for_allowlisted_brands_and_requests_each_product_page(spider, monkeypatch):
    facet = {"Acme": 2, "Beta": 1, "NotAllowed": 500}
    fake = FakeSearch(_facets_then_groups(facet, {"Acme": [_hit(1), _hit(2)], "Beta": [_hit(3, "Beta")]}))
    monkeypatch.setattr(cettire_crawl.requests, "post", fake)

    requests_out = list(spider.handle_plp_url(LISTING))

    assert all(call["url"] == constants.SEARCH_URL for call in fake.calls)
    assert all(call["headers"]["x-api-key"] == "stored-key" for call in fake.calls)
    # One facet call, then one call holding both allowlisted brands.
    assert [call["json"]["productQueryInfo"]["vendorQuery"] for call in fake.calls] == [[], ["Acme", "Beta"]]
    assert fake.calls[1]["json"]["productQueryInfo"]["pageSize"] == constants.SEARCH_PAGE_SIZE
    assert [r.url for r in requests_out] == [
        "https://www.cettire.com/sa/products/acme-bag-900000001",
        "https://www.cettire.com/sa/products/acme-bag-900000002",
        "https://www.cettire.com/sa/products/beta-bag-900000003",
    ]
    # Product pages go through the crawler API; each carries its EN and AR rows.
    assert all("zyte_api" in r.meta and len(r.meta["rows"]) == 2 for r in requests_out)
    assert spider.listing_summaries == [
        {"url": LISTING, "brands": 2, "groups": 1, "expected": 3, "received": 3, "limited": False}
    ]


def test_limit_caps_groups_and_asks_for_a_small_page(spider, monkeypatch):
    spider.limit = "1"
    # 600 + 600 is over the per-call cap, so the two brands land in separate groups.
    fake = FakeSearch(_facets_then_groups({"Acme": 600, "Beta": 600}, {"Acme": [_hit(1)], "Beta": [_hit(2, "Beta")]}))
    monkeypatch.setattr(cettire_crawl.requests, "post", fake)

    requests_out = list(spider.handle_plp_url(LISTING))

    group_calls = [c for c in fake.calls if c["json"]["productQueryInfo"]["vendorQuery"]]
    assert len(group_calls) == 1
    assert group_calls[0]["json"]["productQueryInfo"]["pageSize"] == constants.LIMITED_PAGE_SIZE
    assert len(requests_out) == 1


def test_a_product_seen_twice_is_requested_once(spider, monkeypatch):
    fake = FakeSearch(_facets_then_groups({"Acme": 2}, {"Acme": [_hit(1), _hit(1)]}))
    monkeypatch.setattr(cettire_crawl.requests, "post", fake)
    assert len(list(spider.handle_plp_url(LISTING))) == 1


def test_rejected_key_is_refreshed_from_the_site_and_retried_once(spider, monkeypatch):
    monkeypatch.setenv("ZYTE_API_KEY", "zyte-key")
    import base64

    def answer(url, body, headers):
        if url == constants.ZYTE_EXTRACT_URL:
            page = base64.b64encode(pdp_html(api_key="fresh-key").encode()).decode()
            return FakeResponse(payload={"httpResponseBody": page})
        if headers["x-api-key"] == "stored-key":
            return FakeResponse(status=403)
        return FakeResponse(payload=search_payload(hits=[], vendor_facet={}))

    fake = FakeSearch(answer)
    monkeypatch.setattr(cettire_crawl.requests, "post", fake)

    spider._search({"department": "women", "catQuery": "bags", "subCatQuery": ""})

    urls = [c["url"] for c in fake.calls]
    assert urls == [constants.SEARCH_URL, constants.ZYTE_EXTRACT_URL, constants.SEARCH_URL]
    assert fake.calls[1]["json"]["url"] == constants.API_KEY_PAGE_URL
    assert fake.calls[2]["headers"]["x-api-key"] == "fresh-key"


def test_a_key_rejected_after_refresh_stops_the_crawl(spider, monkeypatch):
    monkeypatch.setenv("ZYTE_API_KEY", "zyte-key")
    import base64

    def answer(url, body, headers):
        if url == constants.ZYTE_EXTRACT_URL:
            return FakeResponse(payload={"httpResponseBody": base64.b64encode(pdp_html().encode()).decode()})
        return FakeResponse(status=403)

    monkeypatch.setattr(cettire_crawl.requests, "post", FakeSearch(answer))
    query = {"department": "women", "catQuery": "bags", "subCatQuery": ""}
    with pytest.raises(cettire_crawl.requests.HTTPError):
        spider._search(query)
    # A second rejection in the same run does not fetch the page again.
    with pytest.raises(RuntimeError, match="rejected the key read from the site"):
        spider._search(query)


def test_no_stored_key_reads_it_from_the_site(spider, monkeypatch):
    monkeypatch.delenv("CETTIRE_SEARCH_API_KEY")
    monkeypatch.setenv("ZYTE_API_KEY", "zyte-key")
    import base64

    def answer(url, body, headers):
        if url == constants.ZYTE_EXTRACT_URL:
            page = base64.b64encode(pdp_html(api_key="site-key").encode()).decode()
            return FakeResponse(payload={"httpResponseBody": page})
        return FakeResponse(payload=search_payload(hits=[]))

    fake = FakeSearch(answer)
    monkeypatch.setattr(cettire_crawl.requests, "post", fake)
    spider._search({"department": "women", "catQuery": "bags", "subCatQuery": ""})
    assert fake.calls[-1]["headers"]["x-api-key"] == "site-key"


def _pdp_response(spider, html):
    rows = spider_rows(spider)
    url = rows[0]["url"]
    return HtmlResponse(url=url, request=Request(url=url, meta={"rows": rows}), body=html, encoding="utf-8")


def spider_rows(spider):
    from ecommercecrawl.rules import cettire_rules as rules
    return rules.rows_from_hit(search_hit(), spider.run_id, spider.date_string)


def test_product_page_is_merged_into_both_rows(spider):
    english, arabic = list(spider.parse_pdp(_pdp_response(spider, pdp_html(images=4))))
    assert (english["language"], arabic["language"]) == ("EN", "AR")
    assert len(english["image_urls"]) == 4 and english["text"] is not None
    assert arabic["text"] is None and arabic["product_name"] == "حقيبة كتف أكمي"


def test_blocked_product_page_still_writes_the_search_rows(spider):
    rows = list(spider.parse_pdp(_pdp_response(spider, "<html>Please enable JS</html>")))
    assert [r["language"] for r in rows] == ["EN", "AR"]
    assert rows[0]["text"] is None and len(rows[0]["image_urls"]) == 4


def test_failed_product_page_request_still_writes_the_search_rows(spider):
    rows = spider_rows(spider)

    class Failure:
        type = TimeoutError
        request = Request(url=rows[0]["url"], meta={"rows": rows})

    assert list(spider.pdp_failed(Failure())) == rows


def test_seed_urls_are_routed_by_kind(spider, monkeypatch):
    monkeypatch.setattr(spider, "handle_plp_url", lambda url: iter(["listing"]))
    assert list(spider._handle_seed_url(LISTING)) == ["listing"]
    product = list(spider._handle_seed_url("https://www.cettire.com/sa/products/acme-bag-900000001"))
    assert isinstance(product[0], scrapy.Request) and product[0].meta["rows"] == []
    assert list(spider._handle_seed_url("https://www.cettire.com/sa/pages/about")) == []


def test_product_url_seed_gives_one_english_row(spider):
    url = "https://www.cettire.com/sa/products/acme-flap-shoulder-bag-900000001"
    response = HtmlResponse(url=url, request=Request(url=url, meta={"rows": []}), body=pdp_html(), encoding="utf-8")
    (row,) = list(spider.parse_pdp(response))
    assert row["language"] == "EN" and row["portal_itemid"] == "900000001" and row["site"] == "cettire"
