import argparse
import os
from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings
from ecommercecrawl.spiders.farfetch_crawl import FFSpider
from ecommercecrawl.spiders.ounass_crawl import OunassSpider
from ecommercecrawl.spiders.level_crawl import LevelSpider



spider_map = {
        'farfetch': FFSpider,
        'ounass': OunassSpider,
        'level': LevelSpider,
    }

def main():
    parser = argparse.ArgumentParser(description="E-commerce scraper CLI.")
    parser.add_argument('spider', choices=list(spider_map.keys()), help='The spider to run.')
    parser.add_argument(
        '--urls',
        nargs='+',
        help='One or more URLs to crawl, or a single path to a CSV file with URLs.',
    )
    parser.add_argument('--env', choices=['dev', 'prod'], default='dev', help='Environment setting (dev or prod).')
    parser.add_argument('--limit', type=int, help='Limit the number of pages to crawl.')

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

    if args.limit:
        spider_kwargs['limit'] = args.limit
    
    process.crawl(spider_class, **spider_kwargs)
    process.start()

if __name__ == "__main__":
    main()
