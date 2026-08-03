import argparse
import csv
import os
from io import StringIO
from urllib.parse import urlparse

from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings
from ecommercecrawl.spiders.farfetch_crawl import FFSpider
from ecommercecrawl.spiders.ounass_crawl import OunassSpider
from ecommercecrawl.spiders.level_crawl import LevelSpider
from ecommercecrawl.spiders.bloomingdales_crawl import BloomingdalesSpider


spider_map = {
        'farfetch': FFSpider,
        'ounass': OunassSpider,
        'level': LevelSpider,
        'bloomingdales': BloomingdalesSpider,
    }


def _urls_from_csv_text(csv_text):
    urls = []
    for row in csv.reader(StringIO(csv_text)):
        if not row:
            continue
        first_column = row[0].strip()
        if not first_column or first_column.lower() == "url":
            continue
        urls.append(first_column)
    return urls


def _read_local_urls_source(source):
    with open(source, newline='', encoding='utf-8-sig') as inputfile:
        return _urls_from_csv_text(inputfile.read())


def _read_s3_urls_source(source):
    parsed = urlparse(source)
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    if not bucket or not key:
        raise ValueError(f"Invalid S3 URL source: {source}")

    import boto3

    response = boto3.client("s3").get_object(Bucket=bucket, Key=key)
    body = response["Body"].read().decode("utf-8-sig")
    return _urls_from_csv_text(body)


def load_urls_source(source):
    """
    Load crawl seed URLs from an external source.

    S3 sources keep production URL lists editable without rebuilding the image;
    local files keep the same path useful for development and tests.
    """
    if source.startswith("s3://"):
        return _read_s3_urls_source(source)
    return _read_local_urls_source(source)


def _rows_from_csv_text(csv_text):
    """
    Like `_urls_from_csv_text`, but also reads a "category" column when the
    header names it (e.g. `url,category`). Used for Ounass's per-URL category
    filter; a row's category is None when the column is absent or blank.
    """
    has_category_column = False
    rows = []
    for row in csv.reader(StringIO(csv_text)):
        if not row:
            continue
        first_column = row[0].strip()
        if not first_column:
            continue
        if first_column.lower() == "url":
            has_category_column = len(row) > 1 and row[1].strip().lower() == "category"
            continue
        category = None
        if has_category_column and len(row) > 1:
            category = row[1].strip() or None
        rows.append((first_column, category))
    return rows


def load_url_category_rows(source):
    """
    Load (url, category) rows from a CSV source, local or s3://.

    Superset of `load_urls_source` that additionally surfaces a per-row
    "category" column for spiders that support category filtering (Ounass).
    """
    if source.startswith("s3://"):
        parsed = urlparse(source)
        bucket = parsed.netloc
        key = parsed.path.lstrip("/")
        if not bucket or not key:
            raise ValueError(f"Invalid S3 URL source: {source}")

        import boto3

        response = boto3.client("s3").get_object(Bucket=bucket, Key=key)
        body = response["Body"].read().decode("utf-8-sig")
        return _rows_from_csv_text(body)

    with open(source, newline='', encoding='utf-8-sig') as inputfile:
        return _rows_from_csv_text(inputfile.read())


def main():
    parser = argparse.ArgumentParser(description="E-commerce scraper CLI.")
    parser.add_argument('spider', choices=list(spider_map.keys()), help='The spider to run.')
    urls_group = parser.add_mutually_exclusive_group()
    urls_group.add_argument(
        '--urls',
        nargs='+',
        help='One or more URLs to crawl, or a single path to a CSV file with URLs.',
    )
    urls_group.add_argument(
        '--urls-source',
        help='CSV URL source to crawl. Supports local paths and s3://bucket/key.csv.',
    )
    parser.add_argument('--env', choices=['dev', 'prod'], default='dev', help='Environment setting (dev or prod).')
    parser.add_argument('--limit', type=int, help='Limit the number of pages to crawl.')
    parser.add_argument(
        '--category',
        help=(
            'Ounass only: only crawl PDPs whose breadcrumb category matches this '
            'slug (e.g. "bags"). Applies to every seed URL unless overridden per-row '
            'by a "category" column in --urls-source CSV.'
        ),
    )

    args = parser.parse_args()

    spider_class = spider_map.get(args.spider)
    if not spider_class:
        print(f"Error: Spider '{args.spider}' not found.")
        return

    # Set the environment variable for settings
    os.environ['APP_ENV'] = args.env

    settings = get_project_settings()

    if args.env == 'prod':
        settings.set('LOG_LEVEL', 'INFO')
        log_file = 'logs/scrapy.log'
        log_dir = os.path.dirname(log_file)
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        settings.set('LOG_FILE', log_file)

    process = CrawlerProcess(settings)

    spider_kwargs = {}

    if args.urls:
        if len(args.urls) == 1 and os.path.isfile(args.urls[0]):
            spider_kwargs['urlpath'] = args.urls[0]
        else:
            spider_kwargs['urls'] = args.urls
    elif args.urls_source:
        rows = load_url_category_rows(args.urls_source)
        spider_kwargs['urls'] = [url for url, _category in rows]
        spider_kwargs['urls_source'] = args.urls_source
        if args.spider == 'ounass':
            url_categories = {url: category for url, category in rows if category}
            if url_categories:
                spider_kwargs['url_categories'] = url_categories

    if args.limit:
        spider_kwargs['limit'] = args.limit

    if args.spider == 'ounass' and args.category:
        spider_kwargs['category'] = args.category
    
    process.crawl(spider_class, **spider_kwargs)
    process.start()

if __name__ == "__main__":
    main()
