import scrapy
from scrapy.http import HtmlResponse, Request

from ecommercecrawl.spiders.bloomingdales_crawl import BloomingdalesSpider


PLP_URL = "https://en.bloomingdales.sa/womens-bags-tote-bags/"
PLP_HTML = """
<a href="/khaite-kye-mini-BAG219032925xBLK.html">bag</a>
<button class="js-show-more-btn" data-url="/on/demandware.store?cgid=women-womens-bags-tote-bags&start=48&sz=48">
"""
GRID_HTML = '<a href="/marc-jacobs-scene-BAG219542223xBLK.html">bag</a>'


def _response(url, html, meta=None):
    return HtmlResponse(url=url, request=Request(url=url, meta=meta or {}), body=html, encoding="utf-8")


def _grid_requests(results):
    return [r for r in results if isinstance(r, scrapy.Request) and r.callback.__name__ == "parse_plp_page"]


def test_first_plp_page_requests_the_next_batch_without_limit():
    spider = BloomingdalesSpider()
    grid = _grid_requests(spider.parse_plp(_response(PLP_URL, PLP_HTML)))
    assert len(grid) == 1
    assert grid[0].meta["page"] == 2


def test_limit_one_stops_after_the_first_plp_page():
    spider = BloomingdalesSpider(limit="1")
    results = list(spider.parse_plp(_response(PLP_URL, PLP_HTML)))
    assert _grid_requests(results) == []
    # The first page's products are still crawled.
    assert [r.url for r in results] == ["https://en.bloomingdales.sa/khaite-kye-mini-BAG219032925xBLK.html"]


def test_limit_caps_update_grid_pages():
    spider = BloomingdalesSpider(limit="2")
    meta = {"cgid": "women-womens-bags-tote-bags", "start": 48, "base_url": PLP_URL, "page": 2}
    grid_url = "https://en.bloomingdales.sa/on/demandware.store/Sites-BloomingDales_SA-Site/en_SA/Search-UpdateGrid?cgid=x&start=48"
    results = list(spider.parse_plp_page(_response(grid_url, GRID_HTML, meta)))
    assert _grid_requests(results) == []
    assert len(results) == 1

    spider = BloomingdalesSpider(limit="3")
    grid = _grid_requests(spider.parse_plp_page(_response(grid_url, GRID_HTML, meta)))
    assert [r.meta["page"] for r in grid] == [3]
