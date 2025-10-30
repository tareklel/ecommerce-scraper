import argparse
import os
from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings
from ecommercecrawl.spiders.farfetch_crawl import FFSpider

def main():
    parser = argparse.ArgumentParser(description="E-commerce scraper CLI.")
    parser.add_argument('spider', choices=['farfetch'], help='The spider to run.')
    parser.add_argument('urls', help='URL to crawl or path to a CSV file with URLs.')
    parser.add_argument('--limit', type=int, help='Limit the number of pages to crawl.')
    parser.add_argument('--env', choices=['dev', 'prod'], default='dev', help='Environment setting (dev or prod).')

    args = parser.parse_args()

    # Set the environment variable for settings
    os.environ['APP_ENV'] = args.env

    settings = get_project_settings()
    process = CrawlerProcess(settings)

    if args.spider == 'farfetch':
        is_file = os.path.isfile(args.urls)
        if is_file:
            process.crawl(FFSpider, urlpath=args.urls, limit=args.limit)
        else:
            # Pass the single URL as a list to the spider
            process.crawl(FFSpider, urls=[args.urls], limit=args.limit)

    process.start()

if __name__ == "__main__":
    main()