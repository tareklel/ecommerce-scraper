import os
import csv
import json
from datetime import datetime, timezone
from scrapy import Spider
from scrapy import signals

from ecommercecrawl.constants.mastercrawl_constants import RUN_ID_DATETIME_FORMAT


class MasterCrawl(Spider):
    name = "mastercrawl"

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
        
        spider.run_id = MasterCrawl._generate_run_id()

        # Capture entry point arguments for the manifest.
        # This is done here because from_crawler receives all spider arguments.
        spider.entry_points = {
            key: value for key, value in kwargs.items()
            if key in ['start_urls', 'url', 'urls', 'urlpath', 'urls_file']
        }
        
        # Connect the generate_manifest method to the spider_closed signal
        crawler.signals.connect(spider.generate_manifest, signal=signals.spider_closed)
        
        return spider

    def save_to_jsonl(self, basename, data):
        """Saves a dictionary to a JSONL file, creating dirs and appending if the file exists."""
        filepath = f'{basename}.jsonl'
        
        if not self.output_dir:
            self.output_dir = os.path.dirname(filepath)

        self.ensure_dir(os.path.dirname(filepath))
        with open(filepath, "a", encoding='utf-8') as f:
            f.write(json.dumps(data, ensure_ascii=False) + '\n')

    def generate_manifest(self, spider, reason):
        """
        Generates a manifest.json file at the end of the crawl.
        This method is connected to the spider_closed signal.
        """
        # The 'spider' and 'reason' arguments are passed by the signal.
        # We'll use 'self' which is the same instance as 'spider'.
        if not self.output_dir:
            # Use the spider's logger for logging.
            spider.logger.info("No files were saved, so no manifest will be generated.")
            return

        stats = self.crawler.stats.get_stats()

        # The finish_time from stats can sometimes be unavailable. To ensure this
        # value is always present, we'll use the stat if it exists, otherwise
        # fall back to the current time.
        finish_time = stats.get('finish_time') or datetime.now(timezone.utc)
        start_time = stats.get('start_time')
        duration = (finish_time - start_time).total_seconds() if start_time else None    

        manifest = {
            "run_id": self.run_id,
            "crawler_name": self.name,
            "entry_points": self.entry_points,
            "start_time": start_time.isoformat() if start_time else None,
            "finish_time": finish_time.isoformat(),
            "duration_seconds": duration,
            "stats": {
                "items_scraped": stats.get('item_scraped_count', 0),
                "requests_made": stats.get('downloader/request_count', 0),
                "errors_count": stats.get('log_count/ERROR', 0),
            },
            "file_format": "jsonl"
        }

        manifest_path = os.path.join(self.output_dir, 'manifest.json')
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=4)
        spider.logger.info(f"Manifest file created at: {manifest_path}")
    
        # ---------- Utilities ----------
    def build_output_basename(self, output_dir, date_string: str, filename: str) -> str:
        year, month, day = date_string.split('-')
        return os.path.join(output_dir, year, month, day, self.run_id, filename)
    
    def ensure_dir(self, directory_path):
        """Ensures that a directory exists, creating it if necessary."""
        os.makedirs(directory_path, exist_ok=True)