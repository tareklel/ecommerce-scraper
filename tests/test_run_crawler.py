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


def test_rows_from_csv_text_reads_category_column_when_present():
    csv_text = "url,category\nhttps://example.com/a,Bags\nhttps://example.com/b,\n"

    rows = run_crawler._rows_from_csv_text(csv_text)

    assert rows == [
        ("https://example.com/a", "Bags"),
        ("https://example.com/b", None),
    ]


def test_rows_from_csv_text_without_category_column_returns_none_categories():
    csv_text = "url,label\nhttps://example.com/a,A\n"

    rows = run_crawler._rows_from_csv_text(csv_text)

    assert rows == [("https://example.com/a", None)]


def test_load_url_category_rows_reads_local_csv(tmp_path):
    csv_file = tmp_path / "urls.csv"
    csv_file.write_text("url,category\nhttps://example.com/a,bags\n", encoding="utf-8")

    rows = run_crawler.load_url_category_rows(str(csv_file))

    assert rows == [("https://example.com/a", "bags")]


def test_load_url_category_rows_reads_s3_csv():
    body = MagicMock()
    body.read.return_value = b"url,category\nhttps://example.com/a,bags\n"
    s3_client = MagicMock()
    s3_client.get_object.return_value = {"Body": body}

    with patch("boto3.client", return_value=s3_client):
        rows = run_crawler.load_url_category_rows("s3://seed-bucket/prod/ounass.csv")

    assert rows == [("https://example.com/a", "bags")]


def test_main_passes_category_flag_to_ounass_spider(monkeypatch):
    process = MagicMock()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_crawler.py",
            "ounass",
            "--urls",
            "https://example.com/a",
            "--category",
            "bags",
        ],
    )

    with patch("run_crawler.CrawlerProcess", return_value=process), patch(
        "run_crawler.get_project_settings",
        return_value=MagicMock(),
    ):
        run_crawler.main()

    _, kwargs = process.crawl.call_args
    assert kwargs["category"] == "bags"


def test_main_ignores_category_flag_for_non_ounass_spider(monkeypatch):
    process = MagicMock()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_crawler.py",
            "farfetch",
            "--urls",
            "https://example.com/a",
            "--category",
            "bags",
        ],
    )

    with patch("run_crawler.CrawlerProcess", return_value=process), patch(
        "run_crawler.get_project_settings",
        return_value=MagicMock(),
    ):
        run_crawler.main()

    _, kwargs = process.crawl.call_args
    assert "category" not in kwargs


def test_main_passes_per_row_categories_from_urls_source_for_ounass(tmp_path, monkeypatch):
    csv_file = tmp_path / "urls.csv"
    csv_file.write_text(
        "url,category\nhttps://example.com/a,bags\nhttps://example.com/b,\n",
        encoding="utf-8",
    )
    process = MagicMock()
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_crawler.py", "ounass", "--urls-source", str(csv_file)],
    )

    with patch("run_crawler.CrawlerProcess", return_value=process), patch(
        "run_crawler.get_project_settings",
        return_value=MagicMock(),
    ):
        run_crawler.main()

    _, kwargs = process.crawl.call_args
    assert kwargs["urls"] == ["https://example.com/a", "https://example.com/b"]
    assert kwargs["url_categories"] == {"https://example.com/a": "bags"}


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
