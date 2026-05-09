import sys
from unittest.mock import MagicMock, patch

import pytest

import run_crawler


def test_urls_from_csv_text_reads_first_column_and_skips_header():
    csv_text = "url,label\nhttps://example.com/a,A\n\n https://example.com/b ,B\n"

    urls = run_crawler._urls_from_csv_text(csv_text)

    assert urls == ["https://example.com/a", "https://example.com/b"]


def test_load_urls_source_reads_local_csv(tmp_path):
    csv_file = tmp_path / "urls.csv"
    csv_file.write_text("url\nhttps://example.com/a\n", encoding="utf-8")

    urls = run_crawler.load_urls_source(str(csv_file))

    assert urls == ["https://example.com/a"]


def test_load_urls_source_reads_s3_csv():
    body = MagicMock()
    body.read.return_value = b"url\nhttps://example.com/a\n"
    s3_client = MagicMock()
    s3_client.get_object.return_value = {"Body": body}

    with patch("boto3.client", return_value=s3_client):
        urls = run_crawler.load_urls_source("s3://seed-bucket/prod/farfetch.csv")

    assert urls == ["https://example.com/a"]
    s3_client.get_object.assert_called_once_with(
        Bucket="seed-bucket",
        Key="prod/farfetch.csv",
    )


def test_load_urls_source_rejects_invalid_s3_source():
    with pytest.raises(ValueError, match="Invalid S3 URL source"):
        run_crawler.load_urls_source("s3://seed-bucket")


def test_main_passes_urls_source_urls_to_spider(tmp_path, monkeypatch):
    csv_file = tmp_path / "urls.csv"
    csv_file.write_text("url\nhttps://example.com/a\n", encoding="utf-8")
    process = MagicMock()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_crawler.py",
            "farfetch",
            "--urls-source",
            str(csv_file),
            "--env",
            "prod",
        ],
    )

    with patch("run_crawler.CrawlerProcess", return_value=process), patch(
        "run_crawler.get_project_settings",
        return_value=MagicMock(),
    ):
        run_crawler.main()

    _, kwargs = process.crawl.call_args
    assert kwargs["urls"] == ["https://example.com/a"]
    assert kwargs["urls_source"] == str(csv_file)
    process.start.assert_called_once()
