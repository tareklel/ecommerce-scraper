"""
Access layer (ecommercecrawl/access.py, PLP-efficient Part 5a): access vs
content classification, retry rounds after a cool-down, the total-wait cap,
and per-hostname reporting.
"""

import pytest
import scrapy
from scrapy.exceptions import DontCloseSpider, IgnoreRequest
from scrapy.http import Response
from scrapy.settings import Settings

from ecommercecrawl import access

URL = "https://saudi.ounass.com/api/women/bags/tote-bags"


class RequestError(Exception):
    """Stand-in for zyte_api.RequestError (matched by class name + status)."""

    def __init__(self, status):
        super().__init__(f"zyte {status}")
        self.status = status


class TimeoutError(Exception):      # noqa: A001 - mirrors twisted's class name
    pass


class _Engine:
    def __init__(self):
        self.crawled = []

    def crawl(self, request):
        self.crawled.append(request)


class _Signals:
    def connect(self, *args, **kwargs):
        pass


class _Crawler:
    def __init__(self, **settings):
        self.settings = Settings({"ACCESS_RETRY_COOLDOWN_SECONDS": 900, **settings})
        self.engine = _Engine()
        self.signals = _Signals()


def _middleware(**settings):
    crawler = _Crawler(**settings)
    mw = access.AccessRetryMiddleware.from_crawler(crawler)
    mw.scheduled = []
    mw._call_later = lambda delay, fn, *args: mw.scheduled.append((delay, fn, args))
    return mw


def _response(request, status):
    return Response(url=request.url, status=status, request=request)


# --- classification ---------------------------------------------------------------

@pytest.mark.parametrize("status, label", [(403, "http_403"), (429, "http_429"), (503, "http_503"),
                                           (200, None), (404, None)])
def test_response_classification(status, label):
    request = scrapy.Request(URL)
    assert access.classify_response(_response(request, status)) == label


@pytest.mark.parametrize("exc, label", [
    (RequestError(520), "zyte_520"),      # download error / "Website Ban"
    (RequestError(429), "zyte_429"),
    (RequestError(400), None),            # our request was wrong: not access
    (TimeoutError(), "timeout"),
    (ValueError("bad json"), None),       # content problem
])
def test_exception_classification(exc, label):
    assert access.classify_exception(exc) == label


# --- rounds -----------------------------------------------------------------------

def test_access_failure_is_set_aside_then_resent_after_cooldown():
    mw = _middleware()
    request = scrapy.Request(URL, meta={"retry_times": 5})
    with pytest.raises(access.AccessDeferred):
        mw.process_response(request, _response(request, 429), spider=None)
    assert mw.busy()

    with pytest.raises(DontCloseSpider):
        mw.spider_idle()
    [(delay, release, args)] = mw.scheduled
    assert delay == 900
    with pytest.raises(DontCloseSpider):      # still waiting: keep the spider open
        mw.spider_idle()

    release(*args)
    [resent] = mw.crawler.engine.crawled
    assert resent.url == URL and resent.dont_filter
    assert resent.meta["access_round"] == 1 and resent.meta["retry_times"] == 0
    assert not mw.busy()


def test_recovery_in_a_round_is_counted_and_host_not_blocked():
    mw = _middleware()
    request = scrapy.Request(URL)
    with pytest.raises(access.AccessDeferred):
        mw.process_exception(request, RequestError(520), spider=None)
    resent = request.replace(meta={"access_round": 1})
    response = _response(resent, 200)
    assert mw.process_response(resent, response, spider=None) is response
    host = mw.summary()["hosts"]["saudi.ounass.com"]
    assert host["recovered_in_rounds"] == 1 and host["gave_up"] == 0 and host["status"] == "ok"
    assert host["access_failures"] == {"zyte_520": 1}


def test_after_last_round_the_failure_goes_through():
    mw = _middleware(ACCESS_RETRY_ROUNDS=2)
    last = scrapy.Request(URL, meta={"access_round": 2})
    response = _response(last, 429)
    assert mw.process_response(last, response, spider=None) is response   # callback sees it
    assert mw.process_exception(last, RequestError(520), spider=None) is None  # errback sees it
    assert not mw.busy()


def test_rounds_off_means_no_deferral():
    mw = _middleware(ACCESS_RETRY_ROUNDS=0)
    request = scrapy.Request(URL)
    assert mw.process_exception(request, TimeoutError(), spider=None) is None


def test_content_errors_are_never_deferred():
    mw = _middleware()
    request = scrapy.Request(URL)
    assert mw.process_exception(request, ValueError("bad json"), spider=None) is None
    response = _response(request, 404)
    assert mw.process_response(request, response, spider=None) is response
    assert not mw.busy()
    host = mw.summary()["hosts"]["saudi.ounass.com"]
    assert host["access_failures"] == {} and host["other_errors"] == 1


def test_ignore_request_passes_untouched():
    mw = _middleware()
    assert mw.process_exception(scrapy.Request(URL), IgnoreRequest(), spider=None) is None
    assert mw.summary()["hosts"] == {}


def test_wait_cap_turns_into_one_final_immediate_attempt():
    mw = _middleware(ACCESS_RETRY_COOLDOWN_SECONDS=900, ACCESS_RETRY_MAX_TOTAL_SECONDS=1000)
    request = scrapy.Request(URL)
    with pytest.raises(access.AccessDeferred):
        mw.process_exception(request, TimeoutError(), spider=None)
    with pytest.raises(DontCloseSpider):
        mw.spider_idle()
    _, release, args = mw.scheduled[0]
    release(*args)                                    # waited 900 of 1000
    resent = mw.crawler.engine.crawled[0]
    with pytest.raises(access.AccessDeferred):        # round 1 < 2 rounds: deferred again
        mw.process_exception(resent, TimeoutError(), spider=None)
    with pytest.raises(DontCloseSpider):              # another 900s would exceed the cap
        mw.spider_idle()
    assert len(mw.scheduled) == 1                     # no second cool-down scheduled
    final = mw.crawler.engine.crawled[1]              # sent immediately
    assert mw.final_flush
    assert mw.process_exception(final, TimeoutError(), spider=None) is None  # no more deferral


# --- reporting --------------------------------------------------------------------

def test_blocked_host_is_reported_with_an_access_degradation():
    mw = _middleware(ACCESS_RETRY_ROUNDS=0)
    for i in range(6):
        request = scrapy.Request(f"{URL}?p={i}")
        if i < 4:
            mw.process_exception(request, RequestError(520), spider=None)
        else:
            mw.process_response(request, _response(request, 200), spider=None)
    host = mw.summary()["hosts"]["saudi.ounass.com"]
    assert host["requests"] == 6 and host["gave_up"] == 4 and host["status"] == "blocked"
    [degradation] = mw.degradations()
    assert degradation["kind"] == "access" and degradation["scope"] == "saudi.ounass.com"


def test_small_host_partly_failing_is_not_blocked():
    mw = _middleware(ACCESS_RETRY_ROUNDS=0)
    for i in range(3):
        request = scrapy.Request(f"{URL}?p={i}")
        if i == 0:
            mw.process_exception(request, RequestError(520), spider=None)   # 1 of 3, below min 5
        else:
            mw.process_response(request, _response(request, 200), spider=None)
    assert mw.summary()["hosts"]["saudi.ounass.com"]["status"] == "ok"
    assert mw.degradations() == []


def test_host_with_every_request_lost_is_blocked_whatever_its_size():
    # The 2026-10-20 Acler run: 1 of 1 request banned, reported "ok" before.
    mw = _middleware(ACCESS_RETRY_ROUNDS=0)
    mw.process_exception(scrapy.Request(URL), RequestError(520), spider=None)
    assert mw.summary()["hosts"]["saudi.ounass.com"]["status"] == "blocked"
    assert mw.degradations()[0]["kind"] == "access"
