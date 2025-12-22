import pytest
import requests
from ecommercecrawl.spiders.level_crawl import LevelSpider
from ecommercecrawl.constants import level_constants as constants


def test_get_api_params_for_plp():
    spider = LevelSpider()
    url = "https://www.levelshoes.com/women/bags"

    api, params, headers = spider.get_api_params(url, page_number=3)

    assert api == f"{constants.API_BASE_URL}/ae/en/{constants.API_ENDPOINT}"
    assert params["urlPath"] == "bags"
    assert params["genderType"] == "women"
    assert params["mediaGender"] == "women"
    assert params["page"] == 3
    assert headers == constants.API_HEADERS


def test_get_api_params_raises_for_non_plp():
    spider = LevelSpider()
    with pytest.raises(ValueError):
        spider.get_api_params("https://www.levelshoes.com/stories/all")


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

    monkeypatch.setattr(spider, "_fetch_plp_via_api", fake_fetch)
    monkeypatch.setattr(spider, "handle_plp_item", fake_handle_item)

    spider.handle_plp_url("https://www.levelshoes.com/women/bags")

    assert seen == [{"id": 1}, {"id": 2}, {"id": 3}]


def test_handle_seed_url_routes_plp(monkeypatch):
    spider = LevelSpider()
    called = {"plp": False, "base": False}

    def fake_handle_plp(url):
        called["plp"] = True

    def fake_base(self, url):
        called["base"] = True
        return iter(["base_request"])

    monkeypatch.setattr(spider, "handle_plp_url", fake_handle_plp)
    monkeypatch.setattr("ecommercecrawl.spiders.level_crawl.MasterCrawl._handle_seed_url", fake_base)

    results = list(spider._handle_seed_url("https://www.levelshoes.com/women/bags"))

    assert called["plp"] is True
    assert called["base"] is True
    assert results == ["base_request"]


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
    assert results == ["base_request"]
