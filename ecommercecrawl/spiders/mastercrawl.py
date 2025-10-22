import os
import hashlib
import json
import gzip
import shutil
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
        crawler.signals.connect(spider.post_closure, signal=signals.spider_closed)
        
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

    def post_closure(self, spider, reason):
        """Called when the spider is closed to perform post-crawl actions."""
        self._sample_output()
        self._gzip_output()
        self._generate_manifest(spider, reason)

    def _gzip_output(self):
        """Gzips the output file and updates the output_filepath."""
        if not self.output_filepath or not os.path.exists(self.output_filepath):
            self.logger.info("Output file not found, skipping gzip.")
            return

        gzipped_filepath = f"{self.output_filepath}.gz"
        
        try:
            with open(self.output_filepath, 'rb') as f_in:
                with gzip.open(gzipped_filepath, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            
            self.logger.info(f"Gzipped output file to {gzipped_filepath}")
            
            original_filepath = self.output_filepath
            self.output_filepath = gzipped_filepath
            
            os.remove(original_filepath)
            self.logger.info(f"Removed original output file: {original_filepath}")

        except Exception as e:
            self.logger.error(f"Error gzipping file {original_filepath}: {e}")

    def _sample_output(self):
        """Takes at most three samples from the output file."""
        if not self.output_filepath or not os.path.exists(self.output_filepath):
            self.logger.info("Output file not found, skipping sampling.")
            return

        samples = []
        try:
            with open(self.output_filepath, 'r', encoding='utf-8') as f:
                for i, line in enumerate(f):
                    if i >= 3:
                        break
                    samples.append(line)
        except Exception as e:
            self.logger.error(f"Error reading samples from {self.output_filepath}: {e}")
            return

        if samples:
            # Correctly join the path for the sample file
            sample_filename = f"sample_{os.path.basename(self.output_filepath)}"
            sample_filepath = os.path.join(self.output_dir, sample_filename)
            try:
                with open(sample_filepath, 'w', encoding='utf-8') as f:
                    f.writelines(samples)
                self.logger.info(f"Saved {len(samples)} samples to {sample_filepath}")
            except Exception as e:
                self.logger.error(f"Error writing samples to {sample_filepath}: {e}")

    def _generate_manifest(self, spider, reason):
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
            "artifacts": self._build_manifest_artifacts()
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
            artifacts_data["file_format"] = 'jsonl.gz' if self.output_filepath.endswith('.gz') else 'jsonl'
            artifacts_data["compressed"] = self.output_filepath.endswith('.gz')
        
        return artifacts_data
    
        # ---------- Utilities ----------
    def build_output_basename(self, output_dir, date_string: str, filename: str) -> str:
        year, month, day = date_string.split('-')
        return os.path.join(output_dir, year, month, day, self.run_id, filename)
    
    def ensure_dir(self, directory_path):
        """Ensures that a directory exists, creating it if necessary."""
        os.makedirs(directory_path, exist_ok=True)