import os 


ENV = os.getenv("APP_ENV", "dev").lower()


def _env_bool(name, default):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


BOT_NAME = 'ecommercecrawl'
FARFETCH_URLS_PATH = "resources/farfetch_urls.csv"
OUNASS_URLS_PATH = "resources/ounass_urls.csv"
LEVEL_URLS_PATH = "resources/level_urls.csv"



SPIDER_MODULES = ['ecommercecrawl.spiders']
NEWSPIDER_MODULE = 'ecommercecrawl.spiders'

# Retry many times since proxies often fail
# Retries (include 429) and respect Retry-After
RETRY_ENABLED = True
RETRY_TIMES = 5
RETRY_HTTP_CODES = [429, 500, 502, 503, 504, 522, 524, 408]


# Proxy mode
# 0 = Every requests have different proxy
# 1 = Take only one proxy from the list and assign it to every requests
# 2 = Put a custom proxy to use in the settings
PROXY_MODE = 0

# Crawl responsibly by identifying yourself (and your website) on the user-agent
#USER_AGENT = 'ecommercecrawl (+http://www.yourdomain.com)'

# Obey robots.txt rules
ROBOTSTXT_OBEY = False

# Concurrency & delays
CONCURRENT_REQUESTS = 16
CONCURRENT_REQUESTS_PER_DOMAIN = 2
CONCURRENT_REQUESTS_PER_IP = 8
DOWNLOAD_DELAY = 1          # add jitter via AutoThrottle below
RANDOMIZE_DOWNLOAD_DELAY = False
DOWNLOAD_TIMEOUT = 25           # keep it tight to avoid long hangs
REACTOR_THREADPOOL_MAXSIZE = 20

# Configure a delay for requests for the same website (default: 0)
# See https://docs.scrapy.org/en/latest/topics/settings.html#download-delay
# See also autothrottle settings and docs
#DOWNLOAD_DELAY = 3
# The download delay setting will honor only one of:
# CONCURRENT_REQUESTS_PER_IP = 16

# AutoThrottle
AUTOTHROTTLE_ENABLED = False
AUTOTHROTTLE_START_DELAY = 0.25
AUTOTHROTTLE_MAX_DELAY = 8
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.5   # stay under the radar
AUTOTHROTTLE_DEBUG = True

# By default, HttpErrorMiddleware discards 4xx unless you allow them:
HTTPERROR_ALLOWED_CODES = [429, 403]

# Rotate UAs + keep cookies/session
DEFAULT_REQUEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Upgrade-Insecure-Requests": "1",
}
COOKIES_ENABLED = True

# Enable or disable downloader middlewares
# See https://docs.scrapy.org/en/latest/topics/downloader-middleware.html
DOWNLOADER_MIDDLEWARES = {
    'ecommercecrawl.middlewares.RetryAfterMiddleware': 550,  # after default RetryMiddleware (543)
    "scrapy_zyte_api.ScrapyZyteAPIDownloaderMiddleware": 1000,
}

# Zyte API is opt-in per request through meta["zyte_api"]; transparent mode
# remains disabled so non-Ounass spiders keep using normal Scrapy downloads.
DOWNLOAD_HANDLERS = {
    "http": "scrapy_zyte_api.ScrapyZyteAPIDownloadHandler",
    "https": "scrapy_zyte_api.ScrapyZyteAPIDownloadHandler",
}
SPIDER_MIDDLEWARES = {
    "scrapy_zyte_api.ScrapyZyteAPISpiderMiddleware": 100,
}
REQUEST_FINGERPRINTER_CLASS = "scrapy_zyte_api.ScrapyZyteAPIRequestFingerprinter"
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
ZYTE_API_KEY = os.getenv("ZYTE_API_KEY")
ZYTE_API_TRANSPARENT_MODE = False
ZYTE_API_EXPERIMENTAL_COOKIES_ENABLED = _env_bool(
    "ZYTE_API_EXPERIMENTAL_COOKIES_ENABLED",
    True,
)

# Enable or disable extensions
# See https://docs.scrapy.org/en/latest/topics/extensions.html
#EXTENSIONS = {
#    'scrapy.extensions.telnet.TelnetConsole': None,
#}

# Configure item pipelines
# See https://docs.scrapy.org/en/latest/topics/item-pipeline.html
ITEM_PIPELINES = {
   "ecommercecrawl.pipelines.JsonlWriterPipeline": 200,
   "ecommercecrawl.pipelines.EcommercecrawlPipeline": 300,
   "ecommercecrawl.pipelines.PostCrawlPipeline": 900,
}

# Logging
LOG_FORMAT = '%(asctime)s [%(name)s] %(levelname)s: %(message)s'
LOG_LEVEL = "DEBUG"


# Enable and configure the AutoThrottle extension (disabled by default)
# See https://docs.scrapy.org/en/latest/topics/autothrottle.html
FILES_STORE = 'output'
S3_BUCKET = os.getenv("S3_BUCKET")

# Crawler API routing. Ounass defaults to "auto": API for every hostname
# unless the hostname is explicitly listed in OUNASS_REQUESTS_TLDS.
CRAWLER_API_SERVICE = os.getenv("CRAWLER_API_SERVICE", "zyte").lower()
CRAWLER_API_ZYTE_GEOLOCATION = os.getenv("CRAWLER_API_ZYTE_GEOLOCATION")
OUNASS_FETCH_BACKEND = os.getenv("OUNASS_FETCH_BACKEND", "auto").lower()
# Ounass hostnames allowed to stay on normal requests in auto mode.
# Empty list means all Ounass hostnames use the configured crawler API.
OUNASS_REQUESTS_TLDS = []
OUNASS_CRAWLER_API_PLP_REQUEST_TYPE = os.getenv(
    "OUNASS_CRAWLER_API_PLP_REQUEST_TYPE",
    "http_response",
)
OUNASS_CRAWLER_API_PDP_REQUEST_TYPE = os.getenv(
    "OUNASS_CRAWLER_API_PDP_REQUEST_TYPE",
    "rendered_html",
)

# Used only when Ounass falls back to requests mode.
OUNASS_REQUEST_DELAY_SECONDS = os.getenv("OUNASS_REQUEST_DELAY_SECONDS", "0.2")
OUNASS_REQUEST_JITTER_SECONDS = os.getenv("OUNASS_REQUEST_JITTER_SECONDS", "0.1")
OUNASS_REQUEST_TIMEOUT_SECONDS = os.getenv("OUNASS_REQUEST_TIMEOUT_SECONDS", "20")

# Quality gate (executed automatically in PostCrawlPipeline on spider close)
QUALITY_GATE_ENABLED = os.getenv("QUALITY_GATE_ENABLED", "true")
QUALITY_GATE_BLANK_THRESHOLD = os.getenv("QUALITY_GATE_BLANK_THRESHOLD", "0.2")
QUALITY_GATE_MIN_ROWS_FOR_BLANK_CHECK = os.getenv("QUALITY_GATE_MIN_ROWS_FOR_BLANK_CHECK", "20")
QUALITY_GATE_EXCEPTIONS_FILE = os.getenv(
    "QUALITY_GATE_EXCEPTIONS_FILE",
    "resources/quality_gate_exclusions.json",
)
