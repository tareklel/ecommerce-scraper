import os
import hashlib
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

    @staticmethod
    def _calculate_hashes(filepath):
        """Calculates MD5 and SHA256 hashes for a given file."""
        hashes = {
            'md5': hashlib.md5(),
            'sha256': hashlib.sha256()
        }
        try:
            with open(filepath, 'rb') as f:
                while chunk := f.read(8192):
                    for h in hashes.values():
                        h.update(chunk)
            return {name: h.hexdigest() for name, h in hashes.items()}
        except FileNotFoundError:
            return {}

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
        
        if not self.output_filepath:
            self.output_filepath = filepath

        self.ensure_dir(os.path.dirname(filepath))
        with open(filepath, "a", encoding='utf-8') as f:
            f.write(json.dumps(data, ensure_ascii=False) + '\n')
        
        self.items_written += 1

    def generate_manifest(self, spider, reason):
        """
        Generates a manifest.json file at the end of the crawl.
        This method is connected to the spider_closed signal.
        """
        if not self.output_dir:
            self.logger.info("No files were saved, so no manifest will be generated.")
            return

        stats = self.crawler.stats.get_stats()
        finish_time = stats.get('finish_time') or datetime.now(timezone.utc)
        start_time = stats.get('start_time')
        
        manifest = {
            "run_id": self.run_id,
            "crawler_name": self.name,
            "exit_reason": reason,
            "entry_points": self.entry_points,
            "start_time": start_time.isoformat() if start_time else None,
            "finish_time": finish_time.isoformat(),
            "duration_seconds": (finish_time - start_time).total_seconds() if start_time else None,
            "stats": self._build_manifest_stats(stats),
            "artifacts": self._build_manifest_artifacts(),
            "file_format": "jsonl"
        }

        manifest_path = os.path.join(self.output_dir, 'manifest.json')
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=4)
        self.logger.info(f"Manifest file created at: {manifest_path}")

    def _build_manifest_stats(self, stats):
        """Builds the stats dictionary for the manifest."""
        return {
            "items_scraped": stats.get('item_scraped_count', 0),
            "requests_made": stats.get('downloader/request_count', 0),
            "errors_count": stats.get('log_count/ERROR', 0),
            "status_code_counts": {
                "200": stats.get('downloader/response_status_count/200', 0),
                "301": stats.get('downloader/response_status_count/301', 0),
                "404": stats.get('downloader/response_status_count/404', 0),
                "500": stats.get('downloader/response_status_count/500', 0)
            },
        }

    def _build_manifest_artifacts(self):
        """Builds the artifacts dictionary for the manifest."""
        artifacts_data = {
            "rows": self.items_written
        }

        if self.output_filepath and os.path.exists(self.output_filepath):
            artifacts_data["file_path"] = self.output_filepath
            artifacts_data["file_size_bytes"] = os.path.getsize(self.output_filepath)
            artifacts_data["hashes"] = self._calculate_hashes(self.output_filepath)
        
        return artifacts_data
    
        # ---------- Utilities ----------
    def build_output_basename(self, output_dir, date_string: str, filename: str) -> str:
        year, month, day = date_string.split('-')
        return os.path.join(output_dir, year, month, day, self.run_id, filename)
    
    def ensure_dir(self, directory_path):
        """Ensures that a directory exists, creating it if necessary."""
        os.makedirs(directory_path, exist_ok=True)