import pytest
import requests
import scrapy
from scrapy.http import HtmlResponse
from ecommercecrawl.spiders.level_crawl import LevelSpider
from ecommercecrawl.constants import level_constants as constants
from ecommercecrawl.rules import level_rules as rules


def test_get_api_params_for_plp():
    spider = LevelSpider()
    url = "https://www.levelshoes.com/women/bags"

    api, params, headers = spider.get_api_params_plp(url, page_number=3)

    assert api == f"{constants.API_BASE_URL}/ae/en/{constants.API_ENDPOINT}"
    assert params["urlPath"] == "bags"
    assert params["genderType"] == "women"
    assert params["mediaGender"] == "women"
    assert params["page"] == 3
    assert headers == constants.API_HEADERS


def test_get_api_params_raises_for_non_plp():
    spider = LevelSpider()
    with pytest.raises(ValueError):
        spider.get_api_params_plp("https://www.levelshoes.com/stories/all")


def test_fetch_plp_via_api_returns_payload(monkeypatch):
    spider = LevelSpider()
    url = "https://www.levelshoes.com/women/bags"
    payload = {"products": [{"id": 1}]}
    captured = {}

    class FakeResponse:
        url = "https://api.levelshoes.digital/catalog"
        content = b"{}"

        def json(self):
            return payload

        def raise_for_status(self):
            return None

    def fake_get(api, params=None, headers=None):
        captured["api"] = api
        captured["params"] = params
        captured["headers"] = headers
        return FakeResponse()

    monkeypatch.setattr("ecommercecrawl.spiders.level_crawl.requests.get", fake_get)

    result = spider._fetch_plp_via_api(url, page_number=2)

    assert result == payload
    assert captured["api"] == f"{constants.API_BASE_URL}/ae/en/{constants.API_ENDPOINT}"
    assert captured["params"]["page"] == 2
    assert captured["params"]["urlPath"] == "bags"
    assert captured["headers"] == constants.API_HEADERS


def test_fetch_plp_via_api_handles_errors(monkeypatch):
    spider = LevelSpider()

    monkeypatch.setattr("ecommercecrawl.spiders.level_crawl.requests.get", lambda *a, **kw: (_ for _ in ()).throw(requests.exceptions.RequestException("boom")))

    assert spider._fetch_plp_via_api("https://www.levelshoes.com/women/bags") is None


def test_handle_plp_url_processes_products(monkeypatch):
    spider = LevelSpider()
    seen = []

    payloads = [
        {"products": [{"id": 1}, {"id": 2}]},
        {"products": [{"id": 3}]},
        {"products": []},
    ]

    def fake_fetch(url, page_number=0):
        return payloads[page_number]

    def fake_handle_item(item, listing_url=None):
        seen.append(item)
        return []

    monkeypatch.setattr(spider, "_fetch_plp_via_api", fake_fetch)
    monkeypatch.setattr(spider, "_handle_item", fake_handle_item)

    list(spider.handle_plp_url("https://www.levelshoes.com/women/bags"))

    assert seen == [{"id": 1}, {"id": 2}, {"id": 3}]


def _run_plp(monkeypatch, spider, payloads):
    seen, fetched = [], []

    def fake_fetch(url, page_number=0):
        fetched.append(page_number)
        return payloads[page_number]

    monkeypatch.setattr(spider, "_fetch_plp_via_api", fake_fetch)
    monkeypatch.setattr(spider, "_handle_item", lambda item, listing_url=None: seen.append(item) or [])
    list(spider.handle_plp_url("https://www.levelshoes.com/women/bags"))
    return seen, fetched


def test_handle_plp_url_skips_gift_with_product(monkeypatch):
    gift = {"id": 2, "productType": "gift-with-product"}
    seen, _ = _run_plp(monkeypatch, LevelSpider(), [
        {"products": [{"id": 1, "productType": "normal-sku"}, gift]},
        {"products": []},
    ])
    assert seen == [{"id": 1, "productType": "normal-sku"}]


def test_handle_plp_url_stops_at_limit_pages(monkeypatch):
    seen, fetched = _run_plp(monkeypatch, LevelSpider(limit="1"), [
        {"products": [{"id": 1}]},
        {"products": [{"id": 2}]},
        {"products": []},
    ])
    assert fetched == [0]
    assert seen == [{"id": 1}]


def test_handle_seed_url_routes_plp(monkeypatch):
    spider = LevelSpider()
    called = {"plp": False}

    def fake_handle_plp(url):
        called["plp"] = True
        return iter(["plp_request"])

    monkeypatch.setattr(spider, "handle_plp_url", fake_handle_plp)

    results = list(spider._handle_seed_url("https://www.levelshoes.com/women/bags"))

    assert called["plp"] is True
    assert results == ["plp_request"]


def test_handle_seed_url_skips_plp_logic_for_non_plp(monkeypatch):
    spider = LevelSpider()
    called = {"plp": False}

    def fake_handle_plp(url):
        called["plp"] = True

    def fake_base(self, url):
        return iter(["base_request"])

    monkeypatch.setattr(spider, "handle_plp_url", fake_handle_plp)
    monkeypatch.setattr("ecommercecrawl.spiders.level_crawl.MasterCrawl._handle_seed_url", fake_base)

    results = list(spider._handle_seed_url("https://www.levelshoes.com/some-product.html"))

    assert called["plp"] is False
    # Non-PLP goes through the spider's own logic (parse_pdp request), not the PLP handler.
    assert len(results) == 1
    assert isinstance(results[0], scrapy.Request)


def test_handle_plp_item_builds_request_with_meta():
    spider = LevelSpider()
    item = {
        "action": {"url": "https://www.levelshoes.com/p/sneaker.html"},
        "name": "Sneaker",
        "analytics": {
            "item_id": "SKU123",
            "category1": "Shoes",
            "category2": "Sneakers",
            "gender": "men",
            "price": 123,
            "brand": "BrandX",
        },
        "originalPrice": "123 AED",
        "discountPercentage": 20,
        "badges": [{"text": "NEW"}],
        "image": {"url": "https://cdn.levelshoes.com/hero.jpg"},
        "imagePreviewGallery": [
            {"url": "https://cdn.levelshoes.com/hero.jpg"},
            {"url": "https://cdn.levelshoes.com/side.jpg"},
        ],
    }

    requests_out = list(spider._handle_item(item))
    assert len(requests_out) == 1
    req = requests_out[0]
    assert isinstance(req, scrapy.Request)
    meta_item = req.meta["data_dict"]

    assert meta_item["url"] == "https://www.levelshoes.com/p/sneaker.html"
    assert meta_item["portal_itemid"] == "SKU123"
    assert meta_item["product_name"] == "Sneaker"
    assert meta_item["gender"] == "men"
    assert meta_item["brand"] == "BrandX"
    assert meta_item["category"] == "shoes"
    assert meta_item["subcategory"] == "sneakers"
    assert meta_item["price"] == 123
    assert meta_item["currency"] == "AED"
    assert meta_item["price_discount"] == 20
    assert meta_item["primary_label"] == ["NEW"]
    assert meta_item["image_urls"] == [
        "https://cdn.levelshoes.com/hero.jpg",
        "https://cdn.levelshoes.com/side.jpg",
    ]


def test_handle_plp_item_with_cut_down_analytics_still_requests_the_pdp():
    spider = LevelSpider()
    item = {
        "action": {"url": "https://en-saudi.levelshoes.com/jimmy-choo-cinch-bag.html"},
        "name": "Cinch small bucket bag",
        "vpn": "J000188796-062233",
        "brandName": "Jimmy Choo",
        "analytics": {"constructor": {"variationId": "016528090924"}},
        "originalPrice": "5,910 SAR",
    }

    requests_out = list(spider._handle_item(item))
    assert len(requests_out) == 1
    meta_item = requests_out[0].meta["data_dict"]
    assert meta_item["portal_itemid"] == "J000188796-062233"
    assert meta_item["brand"] == "Jimmy Choo"
    # Left blank here; parse_pdp fills them from the product page.
    assert meta_item["category"] is None
    assert meta_item["gender"] is None
    assert meta_item["price"] is None


def test_parse_direct_pdp_emits_image_gallery_array():
    spider = LevelSpider()
    url = "https://www.levelshoes.com/example-product.html"
    html = """
    <script id="__NEXT_DATA__" type="application/json">
      {"props":{"pageProps":{"productDetails":{
        "image":{"url":"https://cdn.levelshoes.com/hero.jpg"},
        "imagePreviewGallery":[
          {"url":"https://cdn.levelshoes.com/hero.jpg"},
          {"url":"https://cdn.levelshoes.com/side.jpg"}
        ]
      }}}}
    </script>
    """
    request = scrapy.Request(url)
    response = HtmlResponse(url=url, request=request, body=html, encoding="utf-8")

    [item] = list(spider.parse_pdp(response))

    assert item["image_urls"] == [
        "https://cdn.levelshoes.com/hero.jpg",
        "https://cdn.levelshoes.com/side.jpg",
    ]


def test_parse_pdp_preserves_explicit_empty_plp_gallery(monkeypatch):
    spider = LevelSpider()
    url = "https://www.levelshoes.com/example-product.html"
    request = scrapy.Request(url, meta={"data_dict": {"image_urls": []}})
    response = HtmlResponse(url=url, request=request, body="<html></html>", encoding="utf-8")

    def fail_if_called(_response):
        raise AssertionError("PDP fallback must not replace a confirmed empty gallery")

    monkeypatch.setattr(
        "ecommercecrawl.spiders.level_crawl.rules.extract_image_urls",
        fail_if_called,
    )

    [item] = list(spider.parse_pdp(response))

    assert item["image_urls"] == []


CUT_DOWN_TOTE = {
    "action": {"url": "https://ar-saudi.levelshoes.com/bottega-veneta-large-cabat-tote-bag-women-totes-xmuayr.html"},
    "name": "Large Cabat tote bag",
    "vpn": "741270V2VW19277",
    "brandName": "Bottega Veneta",
    "analytics": {"constructor": {"variationId": "812904595"}},
}
TOTE_LISTING = "https://ar-saudi.levelshoes.com/women/bags/tote-bags"
# The Cabat tote's real breadcrumb (2026-11-16): no category level.
SHORT_BREADCRUMB = """
<script type="application/ld+json">[{"@type":"BreadcrumbList","itemListElement":[
{"@type":"ListItem","position":1,"name":"Home","item":"https://ar-saudi.levelshoes.com/"},
{"@type":"ListItem","position":2,"name":"\u0644\u0644\u0646\u0633\u0627\u0621","item":"https://ar-saudi.levelshoes.com/women"},
{"@type":"ListItem","position":3,"name":"Large Cabat tote bag"}]}]</script>
"""


def test_listing_gives_gender_when_the_listing_data_has_none():
    [request] = list(LevelSpider()._handle_item(CUT_DOWN_TOTE, listing_url=TOTE_LISTING))
    assert request.meta["data_dict"]["gender"] == "Women"
    assert request.meta["listing_url"] == TOTE_LISTING


def test_listing_data_gender_still_wins_over_the_listing():
    item = dict(CUT_DOWN_TOTE, analytics={"gender": "Unisex"})
    [request] = list(LevelSpider()._handle_item(item, listing_url=TOTE_LISTING))
    assert request.meta["data_dict"]["gender"] == "Unisex"


def _parse_cut_down_tote(body, meta_extra=None):
    spider = LevelSpider()
    [request] = list(spider._handle_item(CUT_DOWN_TOTE, listing_url=TOTE_LISTING))
    meta = dict(request.meta, **(meta_extra or {}))
    response = HtmlResponse(url=request.url, request=scrapy.Request(request.url, meta=meta),
                            body=body, encoding="utf-8")
    [item] = list(spider.parse_pdp(response))
    return item


def test_short_breadcrumb_takes_category_from_the_listing():
    item = _parse_cut_down_tote(SHORT_BREADCRUMB)
    assert (item["gender"], item["category"], item["subcategory"]) == ("Women", "bags", "tote-bags")


def test_breadcrumb_category_wins_over_the_listing():
    body = SHORT_BREADCRUMB.replace(
        '"item":"https://ar-saudi.levelshoes.com/women"}',
        '"item":"https://ar-saudi.levelshoes.com/women"},'
        '{"@type":"ListItem","position":3,"name":"x","item":"https://ar-saudi.levelshoes.com/women/bags/totes"}')
    item = _parse_cut_down_tote(body)
    assert (item["category"], item["subcategory"]) == ("bags", "totes")


@pytest.mark.parametrize("url, expected", [
    ("https://en-saudi.levelshoes.com/women/bags/tote-bags", ("bags", "tote-bags")),
    ("https://en-saudi.levelshoes.com/women/bags", ("bags", None)),
    ("https://en-saudi.levelshoes.com/sale", (None, None)),
    (None, (None, None)),
])
def test_category_and_subcategory_from_listing(url, expected):
    assert rules.get_category_and_subcategory_from_listing(url) == expected
