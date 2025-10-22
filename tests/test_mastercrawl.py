import os
import json
import hashlib
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
from ecommercecrawl.spiders.mastercrawl import MasterCrawl


@pytest.fixture
def post_closure_test_setup(tmp_path):
    """Fixture to set up a spider and mock crawler for manifest tests."""
    mock_crawler = MagicMock()
    mock_stats = MagicMock()
    
    start_time = datetime.now(timezone.utc)
    finish_time = datetime.now(timezone.utc)
    entry_urls = ['http://example.com']

    stats_dict = {
        'start_time': start_time,
        'item_scraped_count': 150,
        'downloader/request_count': 200,
        'log_count/ERROR': 5,
        'downloader/response_status_count/200': 190,
        'downloader/response_status_count/404': 5,
        'downloader/response_status_count/500': 5,
    }
    mock_stats.get_stats.return_value = stats_dict
    mock_crawler.stats = mock_stats

    spider = MasterCrawl.from_crawler(mock_crawler, urls=entry_urls)
    spider.name = 'test_spider'
    spider.output_dir = str(tmp_path)

    # Simulate saving some items
    basename = tmp_path / "output"
    for i in range(5):
        spider.save_to_jsonl(str(basename), {f"item": i})

    with patch('ecommercecrawl.spiders.mastercrawl.datetime') as mock_dt:
        mock_dt.now.return_value = finish_time
        spider.post_closure(spider=spider, reason='finished')

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


class TestMasterCrawlManifest:
    """Tests for the manifest generation of the MasterCrawl spider."""

    def test_manifest_structure_and_metadata(self, post_closure_test_setup):
        """Tests the basic structure and metadata of the manifest."""
        manifest_data = post_closure_test_setup['manifest_data']
        spider = post_closure_test_setup['spider']
        start_time = post_closure_test_setup['start_time']
        finish_time = post_closure_test_setup['finish_time']
        entry_urls = post_closure_test_setup['entry_urls']

        assert manifest_data['run_id'] == spider.run_id
        assert manifest_data['crawler_name'] == spider.name
        assert manifest_data['entry_points'] == {'urls': entry_urls}
        assert manifest_data['start_time'] == start_time.isoformat()
        assert manifest_data['finish_time'] == finish_time.isoformat()
        assert manifest_data['duration_seconds'] == (finish_time - start_time).total_seconds()
        assert manifest_data['exit_reason'] == 'finished'

    def test_manifest_stats_section(self, post_closure_test_setup):
        """Tests the 'stats' section of the manifest."""
        manifest_data = post_closure_test_setup['manifest_data']
        expected_stats = {
            "items_scraped": 150,
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

    def test_manifest_artifacts_section(self, post_closure_test_setup):
        """Tests the 'artifacts' section of the manifest."""
        manifest_data = post_closure_test_setup['manifest_data']
        tmp_path = post_closure_test_setup['tmp_path']
        
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

    def test_generate_manifest_no_output(self, tmp_path):
        """
        Tests that no manifest is generated if no items are written.
        """
        # 1. Setup
        mock_crawler = MagicMock()
        mock_stats = MagicMock()
        mock_stats.get_stats.return_value = {}
        mock_crawler.stats = mock_stats

        spider = MasterCrawl.from_crawler(mock_crawler)
        spider.output_dir = None  # Explicitly set to None, as no files are saved

        # 2. Execution & Assertion
        # The logger is a property on the Spider class, so we patch it here.
        with patch.object(MasterCrawl, 'logger', new_callable=PropertyMock) as mock_logger_prop:
            spider._generate_manifest(spider=spider, reason='finished')

            manifest_path = tmp_path / 'manifest.json'
            assert not manifest_path.exists()
            mock_logger_prop.return_value.info.assert_called_with("No files were saved, so no manifest will be generated.")

class TestMasterCrawlUtils:
    """Tests for the utility methods of the MasterCrawl spider."""

    def test_generate_run_id(self):
        """
        Tests the _generate_run_id static method for correct format.
        """
        fixed_dt = datetime(2023, 10, 27, 10, 30, 5, 123456, tzinfo=timezone.utc)
        expected_id = "2023-10-27T10-30-05-123"

        with patch('ecommercecrawl.spiders.mastercrawl.datetime') as mock_dt:
            mock_dt.now.return_value = fixed_dt
            run_id = MasterCrawl._generate_run_id()
        
        assert run_id == expected_id

    def test_generate_run_id_padding(self):
        """
        Tests that _generate_run_id correctly pads milliseconds.
        """
        # Test with milliseconds that require padding (e.g., 7ms -> 007)
        fixed_dt = datetime(2023, 10, 27, 10, 30, 5, 7000, tzinfo=timezone.utc)
        expected_id = "2023-10-27T10-30-05-007"

        with patch('ecommercecrawl.spiders.mastercrawl.datetime') as mock_dt:
            mock_dt.now.return_value = fixed_dt
            run_id = MasterCrawl._generate_run_id()

        assert run_id == expected_id