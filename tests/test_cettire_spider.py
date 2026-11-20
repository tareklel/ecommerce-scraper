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


class ParameterNotFound(Exception):
    """Same class name as boto3's, which is all the spider looks at."""


class FakeSSM:
    """Stands in for the Parameter Store client: one dict, optional failures."""

    def __init__(self, values=None, fail_get=None, fail_put=None):
        self.values = dict(values or {})
        self.fail_get = fail_get
        self.fail_put = fail_put
        self.puts = []

    def get_parameter(self, Name, WithDecryption=False):
        if self.fail_get:
            raise self.fail_get
        if Name not in self.values:
            raise ParameterNotFound(Name)
        return {"Parameter": {"Name": Name, "Value": self.values[Name]}}

    def put_parameter(self, Name, Value, Type, Overwrite):
        self.puts.append({"Name": Name, "Value": Value, "Type": Type, "Overwrite": Overwrite})
        if self.fail_put:
            raise self.fail_put
        self.values[Name] = Value


@pytest.fixture
def ssm():
    return FakeSSM({constants.SEARCH_KEY_PARAMETER: "stored-key"})


@pytest.fixture
def spider(monkeypatch, tmp_path, ssm):
    monkeypatch.setattr(cettire_crawl.time, "sleep", lambda s: None)
    allowlist = tmp_path / "allow.csv"
    allowlist.write_text("brand\nAcme\nBeta\n", encoding="utf-8")
    s = CettireSpider()
    monkeypatch.setattr(s, "_ssm_client", lambda: ssm)
    known = tmp_path / "known"
    known.mkdir()
    s.settings = {
        "CETTIRE_BRAND_ALLOWLIST_PATH": str(allowlist),
        "CETTIRE_FETCH_PRODUCT_PAGES": True,
        # An empty known-products list: nothing read yet.
        "CETTIRE_KNOWN_PRODUCTS_URI": str(known),
        "CETTIRE_MAX_PRODUCT_PAGES": 0,
        # Product addresses for key renewal: a local file, none saved yet.
        "CETTIRE_KEY_PAGES_URI": str(tmp_path / "key-pages.json"),
    }
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
        {"url": LISTING, "brands": 2, "groups": 1, "expected": 3, "received": 3, "limited": False,
         "product_pages_requested_so_far": 3, "skipped_known_so_far": 0, "over_cap_so_far": 0}
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
    assert fake.calls[1]["json"]["url"] == constants.API_KEY_PAGE_URLS[0]
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


def test_no_stored_key_reads_it_from_the_site(spider, monkeypatch, ssm):
    ssm.values.clear()
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
    # Saved for the next run.
    assert ssm.values[constants.SEARCH_KEY_PARAMETER] == "site-key"
    assert ssm.puts[0]["Type"] == "SecureString" and ssm.puts[0]["Overwrite"] is True


def _site_key_then_search(site_key="site-key", zyte_status=200, rejected=("stored-key",)):
    import base64

    def answer(url, body, headers):
        if url == constants.ZYTE_EXTRACT_URL:
            if zyte_status != 200:
                return FakeResponse(status=zyte_status)
            page = base64.b64encode(pdp_html(api_key=site_key).encode()).decode()
            return FakeResponse(payload={"httpResponseBody": page})
        if headers["x-api-key"] in rejected:
            return FakeResponse(status=403)
        return FakeResponse(payload=search_payload(hits=[], vendor_facet={}))
    return answer


QUERY = {"department": "women", "catQuery": "bags", "subCatQuery": ""}


def test_a_saved_key_that_works_needs_no_zyte_request_and_is_not_rewritten(spider, monkeypatch, ssm):
    fake = FakeSearch(_site_key_then_search(rejected=()))
    monkeypatch.setattr(cettire_crawl.requests, "post", fake)
    monkeypatch.setattr(spider, "_fetch_key_via_zyte", lambda: pytest.fail("no Zyte fetch expected"))
    spider._search(QUERY)
    spider._search(QUERY)
    assert ssm.puts == []
    assert [c["headers"]["x-api-key"] for c in fake.calls] == ["stored-key", "stored-key"]


def test_a_rejected_key_is_replaced_in_parameter_store(spider, monkeypatch, ssm):
    monkeypatch.setenv("ZYTE_API_KEY", "zyte-key")
    monkeypatch.setattr(cettire_crawl.requests, "post", FakeSearch(_site_key_then_search("fresh-key")))
    spider._search(QUERY)
    assert ssm.values[constants.SEARCH_KEY_PARAMETER] == "fresh-key"
    assert spider.run_degradations == []


def test_no_new_key_from_zyte_fails_the_run_and_keeps_the_saved_key(spider, monkeypatch, ssm):
    monkeypatch.setenv("ZYTE_API_KEY", "zyte-key")
    monkeypatch.setattr(cettire_crawl.requests, "post", FakeSearch(_site_key_then_search(zyte_status=520)))
    with pytest.raises(RuntimeError, match="Could not fetch a Cettire page through Zyte"):
        spider._search(QUERY)
    assert ssm.puts == []
    assert ssm.values[constants.SEARCH_KEY_PARAMETER] == "stored-key"


def test_a_new_key_that_cannot_be_saved_keeps_the_run_going_and_degrades_it(spider, monkeypatch, ssm):
    ssm.fail_put = RuntimeError("AccessDenied")
    monkeypatch.setenv("ZYTE_API_KEY", "zyte-key")
    fake = FakeSearch(_site_key_then_search("fresh-key"))
    monkeypatch.setattr(cettire_crawl.requests, "post", fake)
    spider._search(QUERY)
    assert fake.calls[-1]["headers"]["x-api-key"] == "fresh-key"
    [degradation] = spider.run_degradations
    assert degradation["kind"] == "setup"
    assert degradation["scope"] == constants.SEARCH_KEY_PARAMETER
    assert "Could not save" in degradation["message"]


def test_an_unreadable_parameter_store_reads_the_key_from_the_site(spider, monkeypatch, ssm):
    ssm.fail_get = RuntimeError("AccessDenied")
    monkeypatch.setenv("ZYTE_API_KEY", "zyte-key")
    fake = FakeSearch(_site_key_then_search())
    monkeypatch.setattr(cettire_crawl.requests, "post", fake)
    spider._search(QUERY)
    assert fake.calls[-1]["headers"]["x-api-key"] == "site-key"
    assert ssm.values[constants.SEARCH_KEY_PARAMETER] == "site-key"


def test_the_parameter_name_can_be_overridden(spider, ssm):
    spider.settings["CETTIRE_SEARCH_KEY_PARAMETER"] = "/other/name"
    ssm.values["/other/name"] = "other-key"
    assert spider._get_api_key() == "other-key"


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

    from twisted.python.failure import Failure

    failure = Failure(TimeoutError("timed out"))
    failure.request = Request(url=rows[0]["url"], meta={"rows": rows})
    assert list(spider.pdp_failed(failure)) == rows


def test_a_request_set_aside_for_a_retry_round_writes_nothing(spider):
    from ecommercecrawl import access
    from twisted.python.failure import Failure

    rows = spider_rows(spider)
    failure = Failure(access.AccessDeferred("later"))
    failure.request = Request(url=rows[0]["url"], meta={"rows": rows})
    assert list(spider.pdp_failed(failure)) == []


def test_product_pages_skip_access_retry_rounds(spider):
    from ecommercecrawl import access

    request = spider._pdp_request("https://www.cettire.com/sa/products/acme-bag-900000001", rows=[])
    assert request.meta[access.NO_DEFER_META_KEY] is True


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


def test_key_page_fetch_retries_zyte_bans_across_pages(spider, monkeypatch):
    monkeypatch.setenv("ZYTE_API_KEY", "zyte-key")
    import base64
    page = base64.b64encode(pdp_html(api_key="site-key").encode()).decode()
    answers = iter([FakeResponse(status=520), FakeResponse(status=520), FakeResponse(payload={"httpResponseBody": page})])
    fake = FakeSearch(lambda url, body, headers: next(answers))
    monkeypatch.setattr(cettire_crawl.requests, "post", fake)

    assert spider._refresh_api_key() == "site-key"
    assert [c["json"]["url"] for c in fake.calls] == list(constants.API_KEY_PAGE_URLS[:3])


def test_key_page_fetch_gives_up_with_a_clear_error(spider, monkeypatch):
    monkeypatch.setenv("ZYTE_API_KEY", "zyte-key")
    monkeypatch.setattr(constants, "API_KEY_MIN_PLAIN_ATTEMPTS", 2)
    monkeypatch.setattr(constants, "API_KEY_BROWSER_ATTEMPTS", 1)
    monkeypatch.setattr(cettire_crawl.requests, "post", FakeSearch(lambda url, body, headers: FakeResponse(status=520)))
    with pytest.raises(RuntimeError, match=r"4 attempts over 0 saved product page\(s\) and 3 listing pages: "
                                           r"3 plain, 1 browser; last: status 520"):
        spider._refresh_api_key()


def test_key_page_fetch_switches_to_browser_mode_after_the_plain_attempts(spider, monkeypatch, ssm):
    monkeypatch.setenv("ZYTE_API_KEY", "zyte-key")
    ssm.values.clear()
    plain = max(len(constants.API_KEY_PAGE_URLS), constants.API_KEY_MIN_PLAIN_ATTEMPTS)

    def answer(url, body, headers):
        if url != constants.ZYTE_EXTRACT_URL:
            return FakeResponse(payload=search_payload(hits=[], vendor_facet={}))
        if body.get("browserHtml"):
            return FakeResponse(payload={"browserHtml": pdp_html(api_key="browser-key")})
        return FakeResponse(status=520)

    fake = FakeSearch(answer)
    monkeypatch.setattr(cettire_crawl.requests, "post", fake)
    spider._search(QUERY)

    zyte = [c["json"] for c in fake.calls if c["url"] == constants.ZYTE_EXTRACT_URL]
    assert [("browserHtml" in b, "httpResponseBody" in b) for b in zyte] == [(False, True)] * plain + [(True, False)]
    assert fake.calls[-1]["headers"]["x-api-key"] == "browser-key"
    assert ssm.values[constants.SEARCH_KEY_PARAMETER] == "browser-key"


def test_a_page_without_the_key_is_retried(spider, monkeypatch):
    monkeypatch.setenv("ZYTE_API_KEY", "zyte-key")
    import base64
    without = base64.b64encode(b"<html>challenge</html>").decode()
    with_key = base64.b64encode(pdp_html(api_key="site-key").encode()).decode()
    answers = iter([FakeResponse(payload={"httpResponseBody": without}),
                    FakeResponse(payload={"httpResponseBody": with_key})])
    monkeypatch.setattr(cettire_crawl.requests, "post", FakeSearch(lambda url, body, headers: next(answers)))
    assert spider._refresh_api_key() == "site-key"


def test_product_pages_off_yields_search_rows_without_any_request(spider, monkeypatch):
    spider.settings["CETTIRE_FETCH_PRODUCT_PAGES"] = False
    fake = FakeSearch(_facets_then_groups({"Acme": 2}, {"Acme": [_hit(1), _hit(2)]}))
    monkeypatch.setattr(cettire_crawl.requests, "post", fake)

    out = list(spider.handle_plp_url(LISTING))

    assert not any(isinstance(o, scrapy.Request) for o in out)
    assert [(r["portal_itemid"], r["language"]) for r in out] == [
        ("900000001", "EN"), ("900000001", "AR"), ("900000002", "EN"), ("900000002", "AR"),
    ]


def test_product_pages_default_on_with_a_cap(monkeypatch):
    monkeypatch.delenv("CETTIRE_FETCH_PRODUCT_PAGES", raising=False)
    import importlib
    from ecommercecrawl import settings
    settings = importlib.reload(settings)
    assert settings.CETTIRE_FETCH_PRODUCT_PAGES is True
    # Pages stay bounded per run.
    assert settings.CETTIRE_MAX_PRODUCT_PAGES == 2000
    # Without project settings the spider itself stays off (safe default).
    assert CettireSpider()._fetch_product_pages() is False


# ---- efficient mode (known products)

def _write_known(spider, text, gz=True):
    import gzip, os
    path = os.path.join(spider.settings["CETTIRE_KNOWN_PRODUCTS_URI"], "part-0.gz" if gz else "part-0")
    with open(path, "wb") as f:
        f.write(gzip.compress(text.encode()) if gz else text.encode())


def test_known_product_skips_its_page_and_keeps_its_gallery(spider, monkeypatch):
    _write_known(spider, '900000001\t["https://g.example/1.jpg","https://g.example/2.jpg","https://g.example/3.jpg","https://g.example/4.jpg","https://g.example/5.jpg"]\n')
    fake = FakeSearch(_facets_then_groups({"Acme": 2}, {"Acme": [_hit(1), _hit(2)]}))
    monkeypatch.setattr(cettire_crawl.requests, "post", fake)

    out = list(spider.handle_plp_url(LISTING))

    rows = [o for o in out if isinstance(o, dict)]
    pages = [o for o in out if isinstance(o, scrapy.Request)]
    # Known product: no page, both rows carry the stored 5-image gallery.
    assert [(r["portal_itemid"], r["language"], len(r["image_urls"])) for r in rows] == [
        ("900000001", "EN", 5), ("900000001", "AR", 5),
    ]
    # Unknown product: page requested as before.
    assert [p.url for p in pages] == ["https://www.cettire.com/sa/products/acme-bag-900000002"]
    assert (spider.product_pages_skipped_known, spider.product_pages_requested) == (1, 1)


def test_known_products_are_skipped_even_with_pages_off(spider, monkeypatch):
    spider.settings["CETTIRE_FETCH_PRODUCT_PAGES"] = False
    _write_known(spider, '900000001\t["https://g.example/1.jpg"]\n', gz=False)
    fake = FakeSearch(_facets_then_groups({"Acme": 1}, {"Acme": [_hit(1)]}))
    monkeypatch.setattr(cettire_crawl.requests, "post", fake)

    rows = list(spider.handle_plp_url(LISTING))
    # The stored gallery still replaces the search images.
    assert [r["image_urls"] for r in rows] == [["https://g.example/1.jpg"]] * 2


def test_page_cap_writes_the_rest_from_search(spider, monkeypatch):
    spider.settings["CETTIRE_MAX_PRODUCT_PAGES"] = 2
    fake = FakeSearch(_facets_then_groups({"Acme": 3}, {"Acme": [_hit(1), _hit(2), _hit(3)]}))
    monkeypatch.setattr(cettire_crawl.requests, "post", fake)

    out = list(spider.handle_plp_url(LISTING))

    assert len([o for o in out if isinstance(o, scrapy.Request)]) == 2
    assert [r["portal_itemid"] for r in out if isinstance(r, dict)] == ["900000003", "900000003"]
    assert spider.product_pages_over_cap == 1


def test_unreadable_known_list_means_no_pages(spider, monkeypatch):
    def broken(uri):
        raise OSError("S3 unavailable")
    monkeypatch.setattr(spider, "_read_known_texts", broken)
    fake = FakeSearch(_facets_then_groups({"Acme": 1}, {"Acme": [_hit(1)]}))
    monkeypatch.setattr(cettire_crawl.requests, "post", fake)

    out = list(spider.handle_plp_url(LISTING))
    assert not any(isinstance(o, scrapy.Request) for o in out)
    assert len(out) == 2


def test_known_list_defaults_to_the_dbt_location(monkeypatch):
    monkeypatch.setenv("APP_ENV", "dev")
    s = CettireSpider()
    s.settings = {"S3_BUCKET": "bucket-x"}
    assert s._known_products_uri() == "s3://bucket-x/dbt/dev/gold_cettire_pdp_known/"


# ---------------------------------------------------------------- key renewal from product pages

def _product_url(n):
    return f"https://www.cettire.com/sa/products/acme-bag-90000000{n}"


def test_a_listing_saves_a_few_product_addresses_once(spider, monkeypatch, tmp_path):
    import json
    monkeypatch.setattr(constants, "KEY_PAGES_COUNT", 2)
    spider.settings["CETTIRE_FETCH_PRODUCT_PAGES"] = False
    hits = {"Acme": [_hit(1), _hit(2), _hit(3)]}
    monkeypatch.setattr(cettire_crawl.requests, "post", FakeSearch(_facets_then_groups({"Acme": 3}, hits)))
    list(spider.handle_plp_url(LISTING))

    saved = json.loads((tmp_path / "key-pages.json").read_text())
    assert saved["urls"] == [_product_url(1), _product_url(2)]
    # A second listing in the same run does not rewrite it.
    (tmp_path / "key-pages.json").write_text('{"urls": []}')
    list(spider.handle_plp_url(LISTING))
    assert json.loads((tmp_path / "key-pages.json").read_text())["urls"] == []


def test_renewal_tries_saved_product_pages_before_listing_pages(spider, monkeypatch, ssm, tmp_path, caplog):
    import base64
    import json
    import logging
    ssm.values.clear()
    monkeypatch.setenv("ZYTE_API_KEY", "zyte-key")
    (tmp_path / "key-pages.json").write_text(json.dumps({"urls": [_product_url(1), _product_url(2)]}))

    def answer(url, body, headers):
        if url != constants.ZYTE_EXTRACT_URL:
            return FakeResponse(payload=search_payload(hits=[], vendor_facet={}))
        if body["url"] == _product_url(2):
            page = base64.b64encode(pdp_html(api_key="product-page-key").encode()).decode()
            return FakeResponse(payload={"httpResponseBody": page})
        return FakeResponse(status=520)

    fake = FakeSearch(answer)
    monkeypatch.setattr(cettire_crawl.requests, "post", fake)
    with caplog.at_level(logging.INFO):
        spider._search(QUERY)

    zyte_urls = [c["json"]["url"] for c in fake.calls if c["url"] == constants.ZYTE_EXTRACT_URL]
    assert zyte_urls == [_product_url(1), _product_url(2)]
    assert ssm.values[constants.SEARCH_KEY_PARAMETER] == "product-page-key"
    # The logs carry a fingerprint, never the key.
    fingerprint = CettireSpider._fingerprint("product-page-key")
    assert fingerprint in caplog.text and "product-page-key" not in caplog.text


def test_renewal_candidates_are_product_pages_then_listing_pages(spider, tmp_path):
    import json
    (tmp_path / "key-pages.json").write_text(json.dumps(
        {"urls": [_product_url(1), "https://www.cettire.com/sa/collections/womens-bags", "not a url"]}))
    assert spider._key_page_candidates() == [_product_url(1)] + list(constants.API_KEY_PAGE_URLS)


def test_an_unreadable_address_file_falls_back_to_listing_pages(spider, tmp_path):
    (tmp_path / "key-pages.json").write_text("not json")
    assert spider._key_page_candidates() == list(constants.API_KEY_PAGE_URLS)


def test_the_saved_key_is_logged_by_fingerprint_only(spider, caplog):
    import logging
    with caplog.at_level(logging.INFO):
        assert spider._get_api_key() == "stored-key"
    assert CettireSpider._fingerprint("stored-key") in caplog.text and "stored-key" not in caplog.text
