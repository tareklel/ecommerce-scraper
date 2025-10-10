import os
import csv
import json
from datetime import datetime, timezone
from scrapy import Spider
from scrapy import signals


class MasterCrawl(Spider):
    name = "mastercrawl"
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not hasattr(self, 'run_id'):
            self.run_id = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H-%M-%S')
        self.output_dir = None

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        """
        This is the standard Scrapy entry point.
        It's used to access the Crawler object and connect signals.
        """
        spider = super(MasterCrawl, cls).from_crawler(crawler, *args, **kwargs)
        
        spider.run_id = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H-%M-%S')
        
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

        manifest = {
            "run_id": self.run_id,
            "crawler_name": self.name,
            "start_time": stats.get('start_time').isoformat() if stats.get('start_time') else None,
            "finish_time": finish_time.isoformat(),
            "file_format": "jsonl"
        }

        manifest_path = os.path.join(self.output_dir, 'manifest.json')
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        spider.logger.info(f"Manifest file created at: {manifest_path}")
    
        # ---------- Utilities ----------
    def build_output_basename(self, output_dir, date_string: str, filename: str) -> str:
        year, month, day = date_string.split('-')
        return os.path.join(output_dir, year, month, day, self.run_id, filename)
    
    def ensure_dir(self, directory_path):
        """Ensures that a directory exists, creating it if necessary."""
        os.makedirs(directory_path, exist_ok=True)