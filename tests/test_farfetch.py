import pytest
from scrapy.settings import Settings
from unittest.mock import MagicMock
from ecommercecrawl.spiders.farfetch_crawl import FFSpider
from pathlib import Path

class TestFFSpider:
    def test_start_requests_reads_path_from_settings(self, tmp_path):
        # prepare a small CSV with two URLs
        csv_file = tmp_path / "urls.csv"
        csv_file.write_text("http://example.com/a\nhttp://example.com/b\n")

        # provide settings with FARFETCH_URLS_PATH
        settings = Settings({'FARFETCH_URLS_PATH': str(csv_file)})

        spider = FFSpider()
        spider.settings = settings

        requests = list(spider.start_requests())
        assert [r.url for r in requests] == ["http://example.com/a", "http://example.com/b"]

    def test_get_pages(self):
        spider = FFSpider()
        mock_response = MagicMock()
        # Simulate response.xpath(PAGINATION_XPATH).get() returning 'Total 4'
        mock_response.xpath.return_value.get.return_value = '1 of 4'
        mock_response.url = "https://www.example.com/category"
        result = spider.get_pages(mock_response)
        expected = [
            "https://www.example.com/category",
            "https://www.example.com/category?page=2",
            "https://www.example.com/category?page=3",
            "https://www.example.com/category?page=4"
        ]
        assert result == expected
    
    # test case with no pagination
    def test_get_pages_no_pagination(self):
        spider = FFSpider()
        mock_response = MagicMock()
        # Simulate response.xpath(PAGINATION_XPATH).get() returning None
        mock_response.xpath.return_value.get.return_value = None
        mock_response.url = "https://www.example.com/category"
        result = spider.get_pages(mock_response)
        expected = ["https://www.example.com/category"]
        assert result == expected
