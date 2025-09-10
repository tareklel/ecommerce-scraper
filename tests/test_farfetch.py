import pytest
from scrapy.settings import Settings
from ecommercecrawl.spiders.farfetch_crawl import FFSpider
from pathlib import Path


def test_start_requests_reads_path_from_settings(tmp_path):
    # prepare a small CSV with two URLs
    csv_file = tmp_path / "urls.csv"
    csv_file.write_text("http://example.com/a\nhttp://example.com/b\n")

    # provide settings with FARFETCH_URLS_PATH
    settings = Settings({'FARFETCH_URLS_PATH': str(csv_file)})

    spider = FFSpider()
    spider.settings = settings

    requests = list(spider.start_requests())
    assert [r.url for r in requests] == ["http://example.com/a", "http://example.com/b"]