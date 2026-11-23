import importlib

import pytest

import ecommercecrawl.settings as settings


@pytest.fixture(autouse=True)
def restore_settings_module(monkeypatch):
    yield
    monkeypatch.delenv("ZYTE_API_KEY", raising=False)
    monkeypatch.delenv("ZYTE_API_ENABLED", raising=False)
    monkeypatch.delenv("SCRAPY_LOG_LEVEL", raising=False)
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


def test_scrapy_log_level_defaults_to_debug(monkeypatch):
    monkeypatch.delenv("SCRAPY_LOG_LEVEL", raising=False)

    loaded = importlib.reload(settings)

    assert loaded.LOG_LEVEL == "DEBUG"


def test_scrapy_log_level_accepts_opt_in_override(monkeypatch):
    monkeypatch.setenv("SCRAPY_LOG_LEVEL", "WARNING")

    loaded = importlib.reload(settings)

    assert loaded.LOG_LEVEL == "WARNING"


def test_aws_sdk_loggers_never_log_debug_even_at_debug_level(monkeypatch):
    # At DEBUG, botocore logs response bodies, which put the decrypted
    # Cettire search key from Parameter Store into CloudWatch (2026-11-23).
    import logging

    from scrapy.settings import Settings
    from scrapy.utils.log import configure_logging

    # In a crawl the root logger lets DEBUG through; pytest's default doesn't.
    root = logging.getLogger()
    monkeypatch.setattr(root, "level", logging.DEBUG)
    monkeypatch.setenv("SCRAPY_LOG_LEVEL", "DEBUG")
    reloaded = importlib.reload(settings)
    assert reloaded.LOG_LEVEL == "DEBUG"
    # Scrapy's own logging setup must not undo the levels.
    configure_logging(Settings({"LOG_LEVEL": "DEBUG"}), install_root_handler=False)

    for name in ("botocore", "botocore.parsers", "boto3", "s3transfer"):
        logger = logging.getLogger(name)
        assert not logger.isEnabledFor(logging.DEBUG), name
        assert logger.isEnabledFor(logging.INFO), name
