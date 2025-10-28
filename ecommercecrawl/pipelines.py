# Define your item pipelines here
#
# Don't forget to add your pipeline to the ITEM_PIPELINES setting
# See: https://docs.scrapy.org/en/latest/topics/item-pipeline.html


# useful for handling different item types with a single interface
from itemadapter import ItemAdapter
import os
import json
import hashlib
from datetime import datetime, timezone
from scrapy import signals


class EcommercecrawlPipeline:
    def process_item(self, item, spider):
        return item


class PostCrawlPipeline:
    def __init__(self):
        self.output_dir = None
        self.run_id = None
        self.crawler_name = None
        self.entry_points = {}
        self.output_filepath = None
        self.items_written = 0
        self.stats = None
        self.crawler = None

    @classmethod
    def from_crawler(cls, crawler):
        pipeline = cls()
        crawler.signals.connect(pipeline.spider_closed, signal=signals.spider_closed)
        pipeline.crawler = crawler
        return pipeline

    def spider_closed(self, spider, reason):
        # The spider's attributes might have been updated during the crawl.
        # Especially output_filepath after gzipping.
        self.output_dir = spider.output_dir
        self.output_filepath = spider.output_filepath
        self.items_written = spider.items_written
        self.run_id = spider.run_id
        self.crawler_name = spider.name
        self.entry_points = spider.entry_points
        self.stats = self.crawler.stats.get_stats()
        self._generate_manifest(spider, reason)

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

    def _generate_manifest(self, spider, reason):
        """
        Generates a manifest.json file at the end of the crawl.
        """
        if not self.output_dir:
            spider.logger.info("No files were saved, so no manifest will be generated.")
            return

        stats = self.stats
        finish_time = stats.get('finish_time') or datetime.now(timezone.utc)
        start_time = stats.get('start_time')

        manifest = {
            "run_id": self.run_id,
            "crawler_name": self.crawler_name,
            "exit_reason": reason,
            "entry_points": self.entry_points,
            "start_time": start_time.isoformat() if start_time else None,
            "finish_time": finish_time.isoformat(),
            "duration_seconds": (finish_time - start_time).total_seconds() if start_time else None,
            "stats": self._build_manifest_stats(stats),
            "artifacts": self._build_manifest_artifacts()
        }

        # add manifest bronze_verification
        manifest["bronze_verification"] = {
            "expected": {
                "file_size_bytes": manifest["artifacts"].get("file_size_bytes", 0),
                "hashes": manifest["artifacts"]["hashes"].get("sha256", "") if "hashes" in manifest["artifacts"] else ""
            }
        }

        manifest_path = os.path.join(self.output_dir, 'manifest.json')
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=4)
        spider.logger.info(f"Manifest file created at: {manifest_path}")

    def _build_manifest_stats(self, stats):
        """Builds the stats dictionary for the manifest."""
        return {
            "items_scraped": self.items_written,
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