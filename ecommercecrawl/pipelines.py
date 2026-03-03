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
from pathlib import Path
from scrapy import signals
import gzip
import shutil
import boto3
from botocore.exceptions import NoCredentialsError
from ecommercecrawl.quality_gate import QualityGateParams
from ecommercecrawl.quality_gate import evaluate_fail_quality
from ecommercecrawl.quality_gate import load_blank_field_exceptions
from ecommercecrawl.quality_gate import load_jsonl_rows
from ecommercecrawl.quality_gate import RULE_SET_ID


class EcommercecrawlPipeline:
    def process_item(self, item, spider):
        return item


class JsonlWriterPipeline:
    def __init__(self):
        self.file = None
        self.items_written = 0
        self.output_filepath = None
        self.output_dir = None

    @classmethod
    def from_crawler(cls, crawler):
        pipeline = cls()
        crawler.signals.connect(pipeline.spider_opened, signals.spider_opened)
        crawler.signals.connect(pipeline.spider_closed, signals.spider_closed)
        return pipeline

    def spider_opened(self, spider):
        # Create a dummy filepath to establish the output_dir, which is used by other pipelines
        # The final output_filepath will be set in process_item
        if not self.output_dir:
            basename = spider.build_output_basename(
                output_dir='output',
                date_string=datetime.now(timezone.utc).strftime('%Y-%m-%d'),
                filename=spider.name
            )
            self.output_dir = os.path.dirname(f'{basename}.jsonl')
            spider.output_dir = self.output_dir

    def spider_closed(self, spider):
        if self.file:
            self.file.close()
        spider.items_written = self.items_written
        spider.output_filepath = self.output_filepath

    def process_item(self, item, spider):
        if not self.file:
            # The output path is determined by the first item processed
            # This assumes all items from a spider go to the same file
            basename = spider.build_output_basename(
                output_dir='output',
                date_string=datetime.now(timezone.utc).strftime('%Y-%m-%d'),
                filename=spider.name
            )
            self.output_filepath = f'{basename}.jsonl'
            self.output_dir = os.path.dirname(self.output_filepath)
            self.ensure_dir(self.output_dir)
            self.file = open(self.output_filepath, 'a', encoding='utf-8')

            # Update spider attributes for other pipelines
            spider.output_dir = self.output_dir
            spider.output_filepath = self.output_filepath

        line = json.dumps(ItemAdapter(item).asdict(), ensure_ascii=False) + "\n"
        self.file.write(line)
        self.items_written += 1
        return item

    def ensure_dir(self, directory_path):
        """Ensures that a directory exists, creating it if necessary."""
        os.makedirs(directory_path, exist_ok=True)


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
        self.quality_gate_report = None

    @classmethod
    def from_crawler(cls, crawler):
        pipeline = cls()
        crawler.signals.connect(pipeline.spider_closed, signal=signals.spider_closed)
        pipeline.crawler = crawler
        return pipeline

    def spider_closed(self, spider, reason):
        # The spider's attributes might have been updated during the crawl.
        # Especially output_filepath after gzipping.

        self.output_dir = getattr(spider, 'output_dir', None)
        if self.output_dir:
            os.makedirs(self.output_dir, exist_ok=True)
        self.output_filepath = getattr(spider, 'output_filepath', None)
        self.items_written = getattr(spider, 'items_written', 0)
        self.run_id = spider.run_id
        self.date = spider.date
        self.crawler_name = spider.name
        self.entry_points = spider.entry_points
        self.stats = self.crawler.stats.get_stats()
        self._sample_output(spider)
        self._run_quality_gate(spider)
        self._gzip_output(spider)
        self._generate_manifest(spider, reason)
        # upload to S3 if in prod environment or S3 upload is enabled
        if os.environ.get('APP_ENV') == 'prod' or os.environ.get('S3_UPLOAD_ENABLED') == 'true':
            self._upload_to_s3(spider)

    def _get_setting(self, key, default):
        """Safely read Scrapy settings while tolerating mocked settings in tests."""
        try:
            settings = getattr(self.crawler, "settings", None)
            if settings is None:
                return default
            value = settings.get(key, default)
        except Exception:
            return default

        if value is None:
            return default

        # Ignore mock objects or unsupported types and use fallback.
        if not isinstance(value, (str, int, float, bool)):
            return default
        return value

    @staticmethod
    def _to_bool(value, default=False):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y", "on"}
        if isinstance(value, (int, float)):
            return value != 0
        return default

    @staticmethod
    def _project_scoped_path(path):
        """
        Keep report paths project-scoped for readability.
        If outside project root, fall back to filename only.
        """
        input_path = Path(path).resolve()
        project_root = Path.cwd().resolve()
        try:
            return input_path.relative_to(project_root).as_posix()
        except ValueError:
            return input_path.name

    def _run_quality_gate(self, spider):
        """Run fail-quality checks after scraping and persist report under metadata."""
        enabled = self._to_bool(self._get_setting("QUALITY_GATE_ENABLED", True), default=True)
        if not enabled:
            spider.logger.info("Quality gate disabled, skipping.")
            return

        if not self.output_filepath or not os.path.exists(self.output_filepath):
            spider.logger.info("Output file not found, skipping quality gate.")
            return

        threshold_raw = self._get_setting("QUALITY_GATE_BLANK_THRESHOLD", 0.8)
        min_rows_raw = self._get_setting("QUALITY_GATE_MIN_ROWS_FOR_BLANK_CHECK", 20)
        exceptions_file = self._get_setting("QUALITY_GATE_EXCEPTIONS_FILE", "")

        try:
            params = QualityGateParams(
                blank_threshold=float(threshold_raw),
                min_rows_for_blank_check=int(min_rows_raw),
            )
        except (TypeError, ValueError):
            spider.logger.error(
                "Invalid quality gate params. threshold=%s min_rows=%s. Using defaults.",
                threshold_raw,
                min_rows_raw,
            )
            params = QualityGateParams()

        metadata_dir = os.path.join(self.output_dir, "metadata")
        os.makedirs(metadata_dir, exist_ok=True)
        quality_report_path = os.path.join(metadata_dir, "quality_report.json")

        try:
            rows = load_jsonl_rows(self.output_filepath)
            exceptions = load_blank_field_exceptions(
                exceptions_file=exceptions_file or None,
            )
            report = evaluate_fail_quality(
                rows,
                params=params,
                blank_field_exceptions={k: sorted(v) for k, v in exceptions.items()},
            )
            report["input_jsonl_path"] = self._project_scoped_path(self.output_filepath)
        except Exception as e:
            spider.logger.error("Quality gate failed to execute: %s", e)
            report = {
                "status": "error",
                "rule_set": RULE_SET_ID,
                "reason": "quality_gate_execution_error",
                "message": str(e),
                "input_jsonl_path": self._project_scoped_path(self.output_filepath),
                "violations_count": None,
            }

        with open(quality_report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        self.quality_gate_report = report
        spider.quality_gate_report = report
        spider.quality_gate_status = report.get("status")
        self.crawler.stats.set_value("quality_gate/status", report.get("status"))
        self.crawler.stats.set_value("quality_gate/violations_count", report.get("violations_count"))
        spider.logger.info(
            "Quality gate completed with status=%s report=%s",
            report.get("status"),
            quality_report_path,
        )

    def _upload_to_s3(self, spider):
        """Uploads the output directory to an S3 bucket."""
        s3_bucket = self.crawler.settings.get('S3_BUCKET')
        if not s3_bucket:
            spider.logger.info("S3_BUCKET not set, skipping S3 upload.")
            return

        if not self.output_dir or not os.path.exists(self.output_dir):
            spider.logger.info("Output directory not found, skipping S3 upload.")
            return

        s3_client = boto3.client('s3')
        s3_prefix = f"{self.crawler_name}/{self.date}/{self.run_id}"

        try:
            for root, _, files in os.walk(self.output_dir):
                for filename in files:
                    local_path = os.path.join(root, filename)
                    app_env = os.environ.get('APP_ENV', 'dev')
                    rel_path = os.path.relpath(local_path, self.output_dir)
                    rel_parts = rel_path.split(os.sep)

                    if rel_parts[0] == "metadata":
                        rel_path = os.path.join(*rel_parts[1:]) if len(rel_parts) > 1 else ""
                        if not rel_path:
                            spider.logger.warning(f"Skipping unexpected metadata path: {local_path}")
                            continue
                        s3_key = os.path.join('bronze', 'crawls', 'metadata', app_env, s3_prefix, rel_path)
                    else:
                        s3_key = os.path.join('bronze', 'crawls', app_env, s3_prefix, rel_path)

                    spider.logger.info(f"Uploading {local_path} to s3://{s3_bucket}/{s3_key}")
                    s3_client.upload_file(local_path, s3_bucket, s3_key)

            spider.logger.info(f"Successfully uploaded output to s3://{s3_bucket}/{s3_key}")

        except NoCredentialsError:
            spider.logger.error("S3 credentials not found. Please configure your AWS credentials.")
        except Exception as e:
            spider.logger.error(f"Error uploading to S3: {e}")
    
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

    def _sample_output(self, spider):
        """Takes at most three samples from the output file."""
        if not self.output_filepath or not os.path.exists(self.output_filepath):
            spider.logger.info("Output file not found, skipping sampling.")
            return

        samples = []
        try:  
            with open(self.output_filepath, 'r', encoding='utf-8') as f:
                for i, line in enumerate(f):
                    if i >= 3:
                        break
                    samples.append(line)
        except Exception as e:
            spider.logger.error(f"Error reading samples from {self.output_filepath}: {e}")
            return

        if samples:
            # Correctly join the path for the sample file
            sample_filename = f"sample_{os.path.basename(self.output_filepath)}"
            metadata_dir = os.path.join(self.output_dir, 'metadata')
            os.makedirs(metadata_dir, exist_ok=True)
            sample_filepath = os.path.join(metadata_dir, sample_filename)
            try:
                with open(sample_filepath, 'w', encoding='utf-8') as f:
                    f.writelines(samples)
                spider.logger.info(f"Saved {len(samples)} samples to {sample_filepath}")
            except Exception as e:
                spider.logger.error(f"Error writing samples to {sample_filepath}: {e}")

    def _gzip_output(self, spider):
        """Gzips the output file and updates the output_filepath."""
        if not self.output_filepath or not os.path.exists(self.output_filepath) or self.output_filepath.endswith('.gz'):
            spider.logger.info("Output file not found, already gzipped, or skipping gzip.")
            return

        gzipped_filepath = f"{self.output_filepath}.gz"
        
        try:
            with open(self.output_filepath, 'rb') as f_in:
                with gzip.open(gzipped_filepath, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            
            spider.logger.info(f"Gzipped output file to {gzipped_filepath}")
            
            original_filepath = self.output_filepath
            self.output_filepath = gzipped_filepath
            spider.output_filepath = gzipped_filepath # Also update spider's attribute
            
            os.remove(original_filepath)
            spider.logger.info(f"Removed original output file: {original_filepath}")

        except Exception as e:
            spider.logger.error(f"Error gzipping file {original_filepath}: {e}")

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

        if self.quality_gate_report:
            manifest["quality_gate"] = {
                "status": self.quality_gate_report.get("status"),
                "reason": self.quality_gate_report.get("reason"),
                "violations_count": self.quality_gate_report.get("violations_count"),
                "report_path": os.path.join(self.output_dir, "metadata", "quality_report.json"),
            }

        # add manifest bronze_verification
        manifest["bronze_verification"] = {
            "expected": {
                "file_size_bytes": manifest["artifacts"].get("file_size_bytes", 0),
                "hashes": manifest["artifacts"]["hashes"].get("sha256", "") if "hashes" in manifest["artifacts"] else ""
            }
        }

        metadata_dir = os.path.join(self.output_dir, 'metadata')
        os.makedirs(metadata_dir, exist_ok=True)
        manifest_path = os.path.join(metadata_dir, 'manifest.json')
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
