import time
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
    Custom retry logic that respects Retry-After headers and uses exponential backoff.

    Usage:
    ------
    Add this to settings.py:

    DOWNLOADER_MIDDLEWARES = {
        'middlewares.RetryAfterMiddleware': 550,  # after default RetryMiddleware (543)
    }

    And make sure RETRY_HTTP_CODES includes 429, 503, etc.
    """

    def process_response(self, request, response, spider):
        """
        Called every time Scrapy gets an HTTP response.
        If the response code is retryable (e.g. 429, 503), decide how long to wait
        before retrying the request.
        """
        # Check if the status code is in the retry list
        if response.status in spider.settings.get('RETRY_HTTP_CODES'):

            # Check if the server sent a Retry-After header
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    # Retry-After usually contains seconds to wait
                    delay = int(retry_after.decode())
                except Exception:
                    # If parsing fails, fall back to a safe default
                    delay = 5
            else:
                # No Retry-After header → use exponential backoff
                retry_count = request.meta.get('retry_times', 0)
                delay = min(60, 2 ** retry_count)  # cap delay at 60s

            # Ask parent class if retry is allowed for this request
            if self._retry(request, response_status_message(response.status), spider):
                spider.logger.info(
                    f"Retryable error {response.status} on {request.url}; "
                    f"waiting {delay}s before retry"
                )
                # Wait asynchronously, then return a fresh copy of the request
                return _sleep(delay).addCallback(lambda _: request.copy())

        # If status code not in retry list → just return the response normally
        return response

    def process_exception(self, request, exception, spider):
        """
        Handles network errors, timeouts, DNS errors, etc.
        For those, we just fall back to Scrapy’s default retry logic.
        """
        return super().process_exception(request, exception, spider)