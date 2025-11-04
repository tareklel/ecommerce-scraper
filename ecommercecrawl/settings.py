import os 


ENV = os.getenv("APP_ENV", "dev").lower()
BOT_NAME = 'ecommercecrawl'
FARFETCH_URLS_PATH = "resources/farfetch_urls.csv"


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
CONCURRENT_REQUESTS_PER_DOMAIN = 8
CONCURRENT_REQUESTS_PER_IP = 8
DOWNLOAD_DELAY = 0           # add jitter via AutoThrottle below
RANDOMIZE_DOWNLOAD_DELAY = False
DOWNLOAD_TIMEOUT = 25           # keep it tight to avoid long hangs
REACTOR_THREADPOOL_MAXSIZE = 20

# Configure a delay for requests for the same website (default: 0)
# See https://docs.scrapy.org/en/latest/topics/settings.html#download-delay
# See also autothrottle settings and docs
#DOWNLOAD_DELAY = 3
# The download delay setting will honor only one of:
CONCURRENT_REQUESTS_PER_DOMAIN = 128
# CONCURRENT_REQUESTS_PER_IP = 16

# AutoThrottle
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 0.25
AUTOTHROTTLE_MAX_DELAY = 8
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.5   # stay under the radar
AUTOTHROTTLE_DEBUG = False

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
    }

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

if ENV == "prod":
    LOG_LEVEL = "INFO"
    LOG_FILE = "logs/scrapy.log"
    if not os.path.exists('logs'):
        os.makedirs('logs')
else:
    LOG_LEVEL = "DEBUG"

# Enable and configure the AutoThrottle extension (disabled by default)
# See https://docs.scrapy.org/en/latest/topics/autothrottle.html
FILES_STORE = 'output'
S3_BUCKET = os.getenv("S3_BUCKET_NAME")