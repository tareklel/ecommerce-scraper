import os
import json
import hashlib
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
from ecommercecrawl.spiders.mastercrawl import MasterCrawl
from ecommercecrawl.pipelines import PostCrawlPipeline


@pytest.fixture
def pipeline_setup(tmp_path):
    """
    A general fixture to set up a spider, a pipeline, and their mocks.
    It also creates a dummy output file.
    """
    mock_crawler = MagicMock()
    mock_stats = MagicMock()
    mock_crawler.stats = mock_stats

    with patch('ecommercecrawl.spiders.mastercrawl.MasterCrawl.logger', new_callable=PropertyMock) as mock_logger:
        mock_logger.return_value = MagicMock()

        # Initialize spider
        spider = MasterCrawl.from_crawler(mock_crawler)
        spider.name = 'test_spider'
        spider.output_dir = str(tmp_path)
        spider.run_id = "test_run_id"

        # Initialize pipeline
        pipeline = PostCrawlPipeline.from_crawler(mock_crawler)
        
        # Create a dummy output file
        output_filepath = tmp_path / "output.jsonl"
        lines_to_write = 5
        with open(output_filepath, "w") as f:
            for i in range(lines_to_write):
                f.write(json.dumps({f"item": i}) + '\n')
                
        spider.output_filepath = str(output_filepath)
        spider.items_written = lines_to_write
        
        yield pipeline, spider, mock_crawler


@pytest.fixture
def manifest_test_setup(pipeline_setup, tmp_path):
    """Fixture to set up and run the pipeline to generate a manifest for testing."""
    pipeline, spider, mock_crawler = pipeline_setup

    start_time = datetime.now(timezone.utc)
    finish_time = datetime.now(timezone.utc)
    entry_urls = ['http://example.com']
    spider.entry_points = {'urls': entry_urls}

    stats_dict = {
        'start_time': start_time,
        'finish_time': finish_time,
        'item_scraped_count': 150,
        'downloader/request_count': 200,
        'log_count/ERROR': 5,
        'downloader/response_status_count/200': 190,
        'downloader/response_status_count/404': 5,
        'downloader/response_status_count/500': 5,
    }
    mock_crawler.stats.get_stats.return_value = stats_dict

    # Run spider_closed to trigger all post-crawl logic including manifest generation
    pipeline.spider_closed(spider=spider, reason='finished')

    manifest_path = tmp_path / 'manifest.json'
    with open(manifest_path, 'r') as f:
        manifest_data = json.load(f)

    return {
        "spider": spider,
        "start_time": start_time,
        "finish_time": finish_time,
        "entry_urls": entry_urls,
        "tmp_path": tmp_path,
        "manifest_data": manifest_data
    }


class TestManifestPipeline:
    """Tests for the ManifestPipeline."""

    def test_manifest_structure_and_metadata(self, manifest_test_setup):
        """Tests the basic structure and metadata of the manifest."""
        manifest_data = manifest_test_setup['manifest_data']
        spider = manifest_test_setup['spider']
        start_time = manifest_test_setup['start_time']
        finish_time = manifest_test_setup['finish_time']
        entry_urls = manifest_test_setup['entry_urls']

        assert manifest_data['run_id'] == spider.run_id
        assert manifest_data['crawler_name'] == spider.name
        assert manifest_data['entry_points'] == {'urls': entry_urls}
        assert manifest_data['start_time'] == start_time.isoformat()
        assert manifest_data['finish_time'] == finish_time.isoformat()
        assert manifest_data['duration_seconds'] == (finish_time - start_time).total_seconds()
        assert manifest_data['exit_reason'] == 'finished'

    def test_manifest_stats_section(self, manifest_test_setup):
        """Tests the 'stats' section of the manifest."""
        manifest_data = manifest_test_setup['manifest_data']
        expected_stats = {
            "items_scraped": 5,
            "requests_made": 200,
            "errors_count": 5,
            "status_code_counts": {
                "200": 190,
                "301": 0,
                "404": 5,
                "500": 5
            }
        }
        assert manifest_data['stats'] == expected_stats

    def test_manifest_artifacts_section(self, manifest_test_setup):
        """Tests the 'artifacts' section of the manifest."""
        manifest_data = manifest_test_setup['manifest_data']
        tmp_path = manifest_test_setup['tmp_path']
        
        output_filepath = str(tmp_path / "output.jsonl.gz")
        assert os.path.exists(output_filepath)

        with open(output_filepath, 'rb') as f:
            file_content_bytes = f.read()

        artifacts = manifest_data['artifacts']
        assert artifacts['rows'] == 5
        assert artifacts['file_path'] == output_filepath
        assert artifacts['file_size_bytes'] == os.path.getsize(output_filepath)
        assert artifacts['file_format'] == 'jsonl.gz'
        assert artifacts['compressed'] is True
        
        expected_md5 = hashlib.md5(file_content_bytes).hexdigest()
        expected_sha256 = hashlib.sha256(file_content_bytes).hexdigest()
        assert artifacts['hashes']['md5'] == expected_md5
        assert artifacts['hashes']['sha256'] == expected_sha256

    def test_manifest_bronze_verification(self, manifest_test_setup):
        """Tests the 'bronze_verification' section of the manifest."""
        manifest_data = manifest_test_setup['manifest_data']
        artifacts = manifest_data['artifacts']

        assert 'bronze_verification' in manifest_data
        bronze_verification = manifest_data['bronze_verification']

        assert 'expected' in bronze_verification
        expected_verification = bronze_verification['expected']

        assert expected_verification['file_size_bytes'] == artifacts.get('file_size_bytes', 0)
        assert expected_verification['hashes'] == artifacts.get('hashes', {}).get('sha256', '')

    def test_generate_manifest_no_output(self, tmp_path):
        """
        Tests that no manifest is generated if no items are written.
        """
        mock_crawler = MagicMock()
        mock_stats = MagicMock()
        mock_stats.get_stats.return_value = {}
        mock_crawler.stats = mock_stats

        spider = MasterCrawl.from_crawler(mock_crawler)
        spider.output_dir = None  # No output dir

        pipeline = PostCrawlPipeline.from_crawler(mock_crawler)
        
        with patch('ecommercecrawl.spiders.mastercrawl.MasterCrawl.logger', new_callable=PropertyMock):
            pipeline.spider_closed(spider=spider, reason='finished')
            manifest_path = tmp_path / 'manifest.json'
            assert not manifest_path.exists()
            spider.logger.info.assert_called_with("No files were saved, so no manifest will be generated.")


@pytest.fixture
def helpers_test_setup(pipeline_setup):
    """Fixture to set up pipeline and spider for testing helper methods."""
    pipeline, spider, _ = pipeline_setup
    
    # The helper methods need some attributes on the pipeline instance.
    # These are normally copied over in spider_closed.
    pipeline.output_dir = spider.output_dir
    pipeline.output_filepath = spider.output_filepath
    pipeline.items_written = spider.items_written
    
    return pipeline, spider


class TestPostCrawlPipelineHelpers:
    def test_gzip_output(self, helpers_test_setup):
        pipeline, spider = helpers_test_setup
        
        original_filepath = spider.output_filepath
        
        pipeline._gzip_output(spider)
        
        gzipped_filepath = f"{original_filepath}.gz"

        assert not os.path.exists(original_filepath)
        assert os.path.exists(gzipped_filepath)
        assert pipeline.output_filepath == gzipped_filepath
        assert spider.output_filepath == gzipped_filepath

    def test_sample_output_from_jsonl(self, helpers_test_setup):
        pipeline, spider = helpers_test_setup
        
        pipeline._sample_output(spider)
        
        sample_filepath = os.path.join(spider.output_dir, f"sample_{os.path.basename(spider.output_filepath)}")
        
        assert os.path.exists(sample_filepath)
        
        with open(sample_filepath, 'r') as f:
            lines = f.readlines()
            assert len(lines) == 3
            assert json.loads(lines[0]) == {"item": 0}