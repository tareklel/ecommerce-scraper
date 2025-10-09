import os
import json
from ecommercecrawl.spiders.mastercrawl import MasterCrawl

class TestMasterCrawl:
    def test_build_output_basename(self):
        """
        Tests the build_output_basename method.
        """
        spider = MasterCrawl()
        spider.name = 'test_spider'
        spider.run_id = 'test-run-id'
        date_string = '2024-01-15'
        
        expected_path = os.path.join('output', '2024', '01', '15', 'test-run-id', 'test_file')

        path = spider.build_output_basename('output', date_string, 'test_file')
        assert path == expected_path

    def test_save_to_jsonl(self, tmp_path):
        """
        Tests the save_to_jsonl method.
        """
        spider = MasterCrawl()
        spider.name = 'test_spider'
        basename = tmp_path / "output" / "test_output"
        data = {"col1": "val1", "col2": "val2"}

        # Test creating a new file and directory
        spider.save_to_jsonl(str(basename), data)
        
        jsonl_path = tmp_path / "output" / "test_output.jsonl"
        assert (tmp_path / "output").exists()
        assert (tmp_path / "output").is_dir()
        assert jsonl_path.exists()
        with open(jsonl_path, 'r') as f:
            lines = f.readlines()
            assert len(lines) == 1
            assert json.loads(lines[0]) == data

        # Test appending to an existing file
        data2 = {"col1": "val3", "col2": "val4"}
        spider.save_to_jsonl(str(basename), data2)

        with open(jsonl_path, 'r') as f:
            lines = f.readlines()
            assert len(lines) == 2
            assert json.loads(lines[1]) == data2

    def test_ensure_dir(self, tmp_path):
        """
        Tests the ensure_dir method.
        """
        spider = MasterCrawl()
        spider.name = 'test_spider'
        dir_path = tmp_path / "test_dir"
        assert not dir_path.exists()

        # Test creating a new directory
        spider.ensure_dir(str(dir_path))
        assert dir_path.exists()
        assert dir_path.is_dir()

        # Test again to ensure it doesn't fail if the directory already exists
        spider.ensure_dir(str(dir_path))
        assert dir_path.exists()