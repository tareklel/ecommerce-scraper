from collections import defaultdict
from urllib.parse import urlparse

from scrapy.downloadermiddlewares.retry import RetryMiddleware
from scrapy.utils.response import response_status_message
from twisted.internet.task import deferLater
from twisted.internet import reactor


def _sleep(seconds):
    """
    Async sleep for 'seconds' using Twisted reactor.
    Unlike time.sleep(), this won’t block the entire Scrapy engine.
    """
    return deferLater(reactor, seconds, lambda: None)


class RetryAfterMiddleware(RetryMiddleware):
    """
    Domain-level backoff middleware:

    - Keeps a penalty per domain (www.farfetch.com, etc.)
    - Domain delay grows exponentially with repeated 429/5xx
    - Domain delay is used for:
        * per-request retry sleep
        * the downloader slot delay (so *all* requests slow down)
    - When responses start succeeding, the penalty decays and the
      domain delay shrinks back toward a base delay.

    Settings (optional):
    --------------------
    RETRY_AFTER_BASE_DELAY   = 1.0   # base delay in seconds when penalty = 1
    RETRY_AFTER_MAX_DELAY    = 180.0 # max domain delay in seconds
    RETRY_AFTER_DECAY        = 1     # how much to reduce penalty on success
    RETRY_AFTER_MAX_SLOT_DELAY = 60.0  # cap for slot.delay
    """

    def __init__(self, settings):
        super().__init__(settings)

        # domain -> penalty (integer)
        self.domain_penalties = defaultdict(int)

        # Base + caps for delay
        self.base_delay = settings.getfloat("RETRY_AFTER_BASE_DELAY", 1.0)
        self.max_delay = settings.getfloat("RETRY_AFTER_MAX_DELAY", 300)
        self.decay = settings.getint("RETRY_AFTER_DECAY", 1)

        # Slot delay base: use DOWNLOAD_DELAY or AUTOTHROTTLE_START_DELAY as min
        dl_delay = settings.getfloat("DOWNLOAD_DELAY", 0.0)
        at_start = settings.getfloat("AUTOTHROTTLE_START_DELAY", 0.0)
        self.min_slot_delay = dl_delay or at_start or 0.25
        self.max_slot_delay = settings.getfloat("RETRY_AFTER_MAX_SLOT_DELAY", self.max_delay)

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler.settings)

    # ------------------------------------------------------------------ helpers

    def _get_domain(self, request):
        return urlparse(request.url).netloc

    def _calc_domain_delay_from_penalty(self, penalty):
        """
        Convert a non-negative penalty into a domain delay.
        penalty = 0 => base_delay (or very small)
        penalty >= 1 => base_delay * 2^(penalty-1), capped at max_delay
        """
        if penalty <= 0:
            return self.base_delay
        delay = self.base_delay * (2 ** (penalty - 1))
        return min(self.max_delay, delay)

    def _update_slot_delay(self, request, spider, delay):
        """
        Set the downloader slot delay for this domain to the given delay.
        This controls how often *any* request to that domain is fired.
        """
        key = request.meta.get("download_slot") or urlparse(request.url).hostname
        slot = spider.crawler.engine.downloader.slots.get(key)
        if not slot:
            return

        # Clamp to allowed slot delay range
        new_delay = min(self.max_slot_delay, max(self.min_slot_delay, delay))

        if abs(slot.delay - new_delay) > 1e-3:
            spider.logger.info(
                f"[RetryAfter] Updating slot delay for {key}: "
                f"{slot.delay:.2f} -> {new_delay:.2f}"
            )
            slot.delay = new_delay

    def _bump_penalty_and_get_delay(self, domain, response=None):
        """
        Increment domain penalty, compute new domain-level delay.
        Optionally respect Retry-After header as a floor.
        """
        self.domain_penalties[domain] += 1
        penalty = self.domain_penalties[domain]

        exp_delay = self._calc_domain_delay_from_penalty(penalty)

        retry_after_delay = None
        if response is not None:
            retry_after_header = response.headers.get(b"Retry-After")
            if retry_after_header:
                try:
                    retry_after_delay = float(retry_after_header.decode())
                except Exception:
                    retry_after_delay = None

        if retry_after_delay is not None:
            # prioritize retry_after_delay
            delay = retry_after_delay
        else:
            delay = exp_delay

        return delay, penalty

    def _decay_penalty_and_get_delay(self, domain):
        """
        Decay domain penalty on success and compute the new domain delay.
        """
        if domain not in self.domain_penalties:
            return self.base_delay, 0

        old_penalty = self.domain_penalties[domain]
        new_penalty = max(0, old_penalty - self.decay)

        if new_penalty == 0:
            self.domain_penalties.pop(domain, None)
        else:
            self.domain_penalties[domain] = new_penalty

        delay = self._calc_domain_delay_from_penalty(new_penalty)
        return delay, new_penalty

    # ---------------------------------------------------------------- middleware

    def process_response(self, request, response, spider):
        domain = self._get_domain(request)

        if response.status in self.retry_http_codes:
            # Use parent logic to decide if we still retry at all
            retry_req = self._retry(
                request,
                response_status_message(response.status),
                spider,
            )
            if retry_req:
                # Bump domain penalty, get domain-level delay
                delay, penalty = self._bump_penalty_and_get_delay(domain, response)

                # Apply this delay to the whole domain (slot.delay)
                self._update_slot_delay(request, spider, delay)

                spider.logger.info(
                    f"[RetryAfter] Retryable {response.status} on {request.url}; "
                    f"domain={domain}, domain_penalty={penalty}, "
                    f"retry_times={retry_req.meta.get('retry_times')}, "
                    f"domain_delay={delay:.2f}s"
                )

                # Sleep domain_delay before retrying this request
                return _sleep(delay).addCallback(lambda _: retry_req)

            # Max retries reached → still let domain cool down a bit
            delay, new_penalty = self._decay_penalty_and_get_delay(domain)
            self._update_slot_delay(request, spider, delay)
            spider.logger.info(
                f"[RetryAfter] Max retries reached for {domain}, "
                f"penalty decayed to {new_penalty}, delay={delay:.2f}s"
            )
            return response

        # Non-retryable status: consider it a "good" signal → decay domain penalty
        delay, new_penalty = self._decay_penalty_and_get_delay(domain)
        self._update_slot_delay(request, spider, delay)
        return response

    def process_exception(self, request, exception, spider):
        # Use parent logic to decide if this exception is retryable
        retry_req = super().process_exception(request, exception, spider)
        if retry_req is None:
            return None

        domain = self._get_domain(request)

        # No response here, so no Retry-After — purely exponential backoff
        delay, penalty = self._bump_penalty_and_get_delay(domain, response=None)
        self._update_slot_delay(request, spider, delay)

        spider.logger.info(
            f"[RetryAfter] Exception {type(exception).__name__} on {request.url}; "
            f"domain={domain}, domain_penalty={penalty}, "
            f"retry_times={retry_req.meta.get('retry_times')}, "
            f"domain_delay={delay:.2f}s"
        )

        return _sleep(delay).addCallback(lambda _: retry_req)