import os
import json
import csv
from datetime import datetime, timezone
from scrapy import Spider

from ecommercecrawl.constants.mastercrawl_constants import RUN_ID_DATETIME_FORMAT


class MasterCrawl(Spider):
    name = "mastercrawl"
    default_urls_path_setting = None
    default_urls_path_constant = None

    @staticmethod
    def _generate_run_id():
        """Generates a unique run ID with millisecond precision."""
        now = datetime.now(timezone.utc)
        main_part = now.strftime(RUN_ID_DATETIME_FORMAT)
        ms_part = f"{now.microsecond // 1000:03d}"
        return f"{main_part}-{ms_part}"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Initialization of attributes that depend on constructor arguments
        # is moved to from_crawler to ensure all kwargs are available.
        self.output_dir = None
        self.entry_points = {}
        self.items_written = 0
        self.output_filepath = None
        if not hasattr(self, 'run_id'):
            self.run_id = MasterCrawl._generate_run_id()

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        """
        This is the standard Scrapy entry point.
        It's used to access the Crawler object, connect signals,
        and capture entry point arguments for the manifest.
        """
        spider = super(MasterCrawl, cls).from_crawler(crawler, *args, **kwargs)
        
        spider.settings = crawler.settings
        spider.run_id = MasterCrawl._generate_run_id()

        # Capture entry point arguments for the manifest.
        # This is done here because from_crawler receives all spider arguments.
        spider.entry_points = {
            key: value for key, value in kwargs.items()
            if key in ['start_urls', 'url', 'urls', 'urlpath', 'urls_file']
        }
        
        # Connect the generate_manifest method to the spider_closed signal
        # crawler.signals.connect(spider.post_closure, signal=signals.spider_closed)
        
        return spider
    
    def start_requests(self):
        """
        This method is called by Scrapy when the spider is opened for scraping.
        It's used to generate the initial requests for the spider to crawl.
        It prioritizes URLs passed via command line arguments (start_urls, urlpath)
        and falls back to a default path defined in spider-specific settings.
        """
        urls = []
        if self.start_urls:
            urls = self.start_urls
        elif hasattr(self, 'urlpath') and self.urlpath:
            with open(self.urlpath, newline='') as inputfile:
                for row in csv.reader(inputfile):
                    if row:
                        urls.append(row[0])
        else:
            # Fallback to default path from settings or constants
            urlpath = self.default_urls_path_constant
            if hasattr(self, 'settings') and self.default_urls_path_setting:
                urlpath = self.settings.get(self.default_urls_path_setting, self.default_urls_path_constant)

            if urlpath:
                with open(urlpath, newline='') as inputfile:
                    for row in csv.reader(inputfile):
                        if row:
                            urls.append(row[0])

        if not urls:
            self.logger.warning("No URLs found to crawl.")
            return

        for url in urls:
            # Assuming _schedule is defined in a base class or mixin
            yield self._schedule(url, callback=self.parse)

    def save_to_jsonl(self, basename, data):
        """Saves a dictionary to a JSONL file, creating dirs and appending if the file exists."""
        filepath = f'{basename}.jsonl'
        
        if not self.output_dir:
            self.output_dir = os.path.dirname(filepath)
        
        if not self.output_filepath:
            self.output_filepath = filepath

        self.ensure_dir(os.path.dirname(filepath))
        with open(filepath, "a", encoding='utf-8') as f:
            f.write(json.dumps(data, ensure_ascii=False) + '\n')
        
        self.items_written += 1

    def build_output_basename(self, output_dir, date_string: str, filename: str) -> str:
        year, month, day = date_string.split('-')
        return os.path.join(output_dir, year, month, day, self.run_id, filename)