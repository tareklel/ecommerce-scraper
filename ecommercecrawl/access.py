"""
Access layer for all crawls (PLP-efficient Part 5a; see
docs/ounass_plp_efficient_crawl.md, section 5 "Access retry rounds").

Principle: an access error (the site or Zyte refusing us: "Website Ban", HTTP
429/403, repeated 5xx, timeouts) hits a whole hostname and says nothing about
whether our data or mapping is right. It is tracked per hostname, retried
patiently in rounds after a cool-down, and reported apart from content
problems. It must never be counted as a content failure.

AccessRetryMiddleware sits right after Scrapy's retry middleware, so it only
sees a request once the normal back-to-back retries have given up.
"""

import logging
from collections import defaultdict
from urllib.parse import urlparse

from scrapy import signals
from scrapy.exceptions import DontCloseSpider, IgnoreRequest

logger = logging.getLogger(__name__)

ACCESS = "access"
CONTENT = "content"

# Website statuses that mean "we were refused", not "the page is wrong".
ACCESS_HTTP_STATUSES = {403, 408, 429}
# Zyte API error statuses: 429/503 throttling, 520/521 download error (incl.
# "Website Ban"). Other 5xx from Zyte are treated the same way.
ZYTE_ACCESS_STATUSES = {429, 503, 520, 521}

# Network-level failures, matched by class name so this module doesn't need
# twisted/aiohttp imports that vary between versions.
NETWORK_ERROR_NAMES = {
    "TimeoutError", "TCPTimedOutError", "ConnectionRefusedError", "ConnectionDone",
    "ConnectionLost", "ConnectError", "DNSLookupError", "ResponseNeverReceived",
    "ResponseFailed", "ServerDisconnectedError", "ClientConnectorError",
    "ClientConnectionError", "ClientOSError", "PotentialDataLoss",
}


# Request meta flag a spider sets on listing-page requests. A flagged request
# given up on access makes the run degraded (kind access), naming the URL:
# losing one listing page silently drops every product it would have linked to.
LISTING_META_KEY = "access_listing_page"


class AccessDeferred(IgnoreRequest):
    """
    Raised for a request set aside for a later access retry round. Callbacks
    and errbacks must not treat it as a final failure: the same request comes
    back after the cool-down.
    """


def host_of(url):
    return (urlparse(url).hostname or "").lower()


def classify_response(response):
    """Return an access label (e.g. "http_429") or None if not an access error."""
    status = response.status
    if status in ACCESS_HTTP_STATUSES or status >= 500:
        return f"http_{status}"
    return None


def classify_exception(exc):
    """Return an access label (e.g. "zyte_520", "timeout") or None."""
    status = getattr(exc, "status", None)
    if type(exc).__name__ == "RequestError" and isinstance(status, int):
        # zyte_api.RequestError: Zyte refused or couldn't fetch the page.
        if status in ZYTE_ACCESS_STATUSES or status >= 500:
            return f"zyte_{status}"
        return None
    for cls in type(exc).__mro__:
        if cls.__name__ in NETWORK_ERROR_NAMES:
            return "timeout" if "Timeout" in cls.__name__ or "TimedOut" in cls.__name__ else "network"
    return None


class AccessTracker:
    """Per-hostname request outcomes for the manifest's `access` block."""

    def __init__(self):
        self.hosts = defaultdict(lambda: {
            "requests": 0, "succeeded": 0, "other_errors": 0, "recovered_in_rounds": 0,
            "access_failures": defaultdict(int), "deferred": 0, "gave_up": 0,
        })

    def success(self, host, round_no):
        stats = self.hosts[host]
        stats["requests"] += 1
        stats["succeeded"] += 1
        if round_no:
            stats["recovered_in_rounds"] += 1

    def failure(self, host, label, deferred):
        stats = self.hosts[host]
        stats["access_failures"][label] += 1
        if deferred:
            stats["deferred"] += 1
        else:
            stats["requests"] += 1
            stats["gave_up"] += 1

    def other(self, host):
        """A failure that isn't an access error (not retried in rounds)."""
        stats = self.hosts[host]
        stats["requests"] += 1
        stats["other_errors"] += 1

    def summary(self, blocked_ratio=0.5, min_requests=5):
        """
        One entry per hostname. `requests` counts final outcomes (a request
        retried in rounds counts once); `gave_up` = access failures after the
        last round. status "blocked" when every request was given up, or when
        gave_up / requests >= blocked_ratio with at least min_requests.
        """
        out = {}
        for host, stats in sorted(self.hosts.items()):
            requests = stats["requests"]
            gave_up = stats["gave_up"]
            # Blocked: every request lost to access (any size), or a large
            # enough share of a big enough sample.
            blocked = bool(gave_up) and (
                gave_up == requests
                or (requests >= min_requests and gave_up / requests >= blocked_ratio))
            out[host] = {
                "requests": requests,
                "succeeded": stats["succeeded"],
                "other_errors": stats["other_errors"],
                "gave_up": stats["gave_up"],
                "recovered_in_rounds": stats["recovered_in_rounds"],
                "deferred": stats["deferred"],
                "access_failures": dict(stats["access_failures"]),
                "status": "blocked" if blocked else "ok",
            }
        return out


class AccessRetryMiddleware:
    """
    Downloader middleware (priority just below the retry middleware) plus the
    idle-time retry rounds. Reachable as `crawler.access_retry`.
    """

    def __init__(self, crawler):
        settings = crawler.settings
        self.crawler = crawler
        self.rounds = settings.getint("ACCESS_RETRY_ROUNDS", 2)
        self.cooldown = settings.getfloat("ACCESS_RETRY_COOLDOWN_SECONDS", 900)
        self.max_total = settings.getfloat("ACCESS_RETRY_MAX_TOTAL_SECONDS", 3600)
        self.blocked_ratio = settings.getfloat("ACCESS_BLOCKED_HOST_RATIO", 0.5)
        self.tracker = AccessTracker()
        self.pending = []
        self.waiting = False
        self.final_flush = False   # cap reached: re-send once more, no deferral
        self.total_waited = 0.0
        self.rounds_run = 0
        self.lost_listings = []    # (url, label) of flagged listing pages given up
        self._call_later = None    # injectable for tests

    @classmethod
    def from_crawler(cls, crawler):
        mw = cls(crawler)
        crawler.access_retry = mw
        crawler.signals.connect(mw.spider_idle, signal=signals.spider_idle)
        return mw

    # --- request outcomes ------------------------------------------------------

    def _round(self, request):
        return request.meta.get("access_round", 0)

    def _can_defer(self, request):
        return self.rounds > 0 and not self.final_flush and self._round(request) < self.rounds

    def _defer(self, request, label):
        retry = request.replace(dont_filter=True)
        retry.meta["access_round"] = self._round(request) + 1
        retry.meta["retry_times"] = 0          # fresh normal retries next round
        retry.meta.setdefault("access_labels", []).append(label)
        self.pending.append(retry)
        self.tracker.failure(host_of(request.url), label, deferred=True)
        raise AccessDeferred(f"access error {label}; retrying in a later round: {request.url}")

    def process_response(self, request, response, spider):
        host = host_of(request.url)
        if not host:
            return response   # data: / file: requests (e.g. releasing held rows)
        label = classify_response(response)
        if label is None:
            self.tracker.success(host, self._round(request))
            return response
        if self._can_defer(request):
            self._defer(request, label)
        self._give_up(request, host, label)
        return response

    def process_exception(self, request, exception, spider):
        if isinstance(exception, IgnoreRequest):
            return None
        host = host_of(request.url)
        if not host:
            return None
        label = classify_exception(exception)
        if label is None:
            self.tracker.other(host)
            return None
        if self._can_defer(request):
            self._defer(request, label)
        self._give_up(request, host, label)
        return None

    def _give_up(self, request, host, label):
        self.tracker.failure(host, label, deferred=False)
        if request.meta.get(LISTING_META_KEY):
            self.lost_listings.append((request.url, label))

    # --- rounds ------------------------------------------------------------------

    def busy(self):
        """True while requests are set aside or a cool-down is running."""
        return bool(self.pending) or self.waiting

    def spider_idle(self, spider=None):
        if self.waiting:
            raise DontCloseSpider
        if not self.pending:
            return
        if self.total_waited + self.cooldown > self.max_total:
            # No more waiting allowed: one immediate last attempt, then any
            # failure goes through to callbacks/errbacks as final.
            self.final_flush = True
            logger.warning(
                f"Access retry: total wait cap ({self.max_total:.0f}s) reached; "
                f"final immediate attempt for {len(self.pending)} request(s)")
            self._release(waited=0)
            raise DontCloseSpider
        self.waiting = True
        hosts = sorted({host_of(r.url) for r in self.pending})
        logger.warning(
            f"Access retry: {len(self.pending)} request(s) failed on access "
            f"({', '.join(hosts)}); retrying in {self.cooldown:.0f}s")
        call_later = self._call_later
        if call_later is None:
            from twisted.internet import reactor
            call_later = reactor.callLater
        call_later(self.cooldown, self._release, self.cooldown)
        raise DontCloseSpider

    def _release(self, waited):
        self.waiting = False
        self.total_waited += waited
        self.rounds_run += 1
        batch, self.pending = self.pending, []
        logger.info(f"Access retry round {self.rounds_run}: re-sending {len(batch)} request(s)")
        for request in batch:
            self.crawler.engine.crawl(request)

    def summary(self):
        return {
            "retry_rounds_setting": self.rounds,
            "cooldown_seconds": self.cooldown,
            "rounds_run": self.rounds_run,
            "total_waited_seconds": self.total_waited,
            "hosts": self.tracker.summary(blocked_ratio=self.blocked_ratio),
        }

    def degradations(self):
        """Structured degradation entries: blocked hostnames, lost listing pages."""
        out = []
        for url, label in self.lost_listings:
            out.append({
                "kind": ACCESS,
                "scope": url,
                "message": (f"listing page lost to blocking ({label}) after {self.rounds_run} "
                            "retry round(s); the products on it weren't crawled"),
            })
        for host, stats in self.tracker.summary(blocked_ratio=self.blocked_ratio).items():
            if stats["status"] == "blocked":
                kinds = ", ".join(f"{k} {v}" for k, v in sorted(stats["access_failures"].items()))
                out.append({
                    "kind": ACCESS,
                    "scope": host,
                    "message": (f"blocked: {stats['gave_up']} of {stats['requests']} requests "
                                f"failed after {self.rounds_run} retry round(s) ({kinds})"),
                })
        return out
