import importlib

import pytest

import ecommercecrawl.settings as settings


@pytest.fixture(autouse=True)
def restore_settings_module(monkeypatch):
    yield
    monkeypatch.delenv("ZYTE_API_KEY", raising=False)
    monkeypatch.delenv("ZYTE_API_ENABLED", raising=False)
    importlib.reload(settings)


def _reload_settings(monkeypatch, *, zyte_key=None, zyte_enabled=None):
    if zyte_key is None:
        monkeypatch.delenv("ZYTE_API_KEY", raising=False)
    else:
        monkeypatch.setenv("ZYTE_API_KEY", zyte_key)

    if zyte_enabled is None:
        monkeypatch.delenv("ZYTE_API_ENABLED", raising=False)
    else:
        monkeypatch.setenv("ZYTE_API_ENABLED", zyte_enabled)

    return importlib.reload(settings)


def test_zyte_scrapy_handlers_are_disabled_without_key_or_flag(monkeypatch):
    loaded = _reload_settings(monkeypatch)

    assert loaded.ZYTE_API_ENABLED is False
    assert "scrapy_zyte_api.ScrapyZyteAPIDownloaderMiddleware" not in loaded.DOWNLOADER_MIDDLEWARES
    assert loaded.DOWNLOAD_HANDLERS == {}
    assert loaded.SPIDER_MIDDLEWARES == {}
    assert loaded.REQUEST_FINGERPRINTER_CLASS == "scrapy.utils.request.RequestFingerprinter"


def test_zyte_scrapy_handlers_are_enabled_with_key(monkeypatch):
    loaded = _reload_settings(monkeypatch, zyte_key="test-key")

    assert loaded.ZYTE_API_ENABLED is True
    assert loaded.DOWNLOADER_MIDDLEWARES[
        "scrapy_zyte_api.ScrapyZyteAPIDownloaderMiddleware"
    ] == 1000
    assert loaded.DOWNLOAD_HANDLERS["https"] == "scrapy_zyte_api.ScrapyZyteAPIDownloadHandler"
    assert loaded.SPIDER_MIDDLEWARES["scrapy_zyte_api.ScrapyZyteAPISpiderMiddleware"] == 100
    assert loaded.REQUEST_FINGERPRINTER_CLASS == "scrapy_zyte_api.ScrapyZyteAPIRequestFingerprinter"
