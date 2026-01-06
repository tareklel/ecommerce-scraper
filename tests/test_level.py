import pytest
import requests
import scrapy
from ecommercecrawl.spiders.level_crawl import LevelSpider
from ecommercecrawl.constants import level_constants as constants


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

    def fake_handle_item(item):
        seen.append(item)
        return []

    monkeypatch.setattr(spider, "_fetch_plp_via_api", fake_fetch)
    monkeypatch.setattr(spider, "_handle_item", fake_handle_item)

    list(spider.handle_plp_url("https://www.levelshoes.com/women/bags"))

    assert seen == [{"id": 1}, {"id": 2}, {"id": 3}]


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
        "brandName": "BrandX",
        "analytics": {
            "item_id": "SKU123",
            "category1": "Shoes",
            "category2": "Sneakers",
            "gender": "men",
            "price": 123,
        },
        "originalPrice": "123 AED",
        "discountPercentage": 20,
        "badges": [{"text": "NEW"}],
        "imagePreviewGallery": [{"url": "https://cdn.levelshoes.com/img.jpg"}],
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
    assert meta_item["image_urls"] == "https://cdn.levelshoes.com/img.jpg"
