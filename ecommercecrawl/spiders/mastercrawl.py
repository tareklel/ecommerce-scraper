import os
import csv
import json
from scrapy import Spider
from datetime import datetime


class MasterCrawl(Spider):
    name = "mastercrawl"
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.run_id = datetime.utcnow().strftime('%Y-%m-%dT%H-%M-%S-%fZ')

    def save_to_jsonl(self, basename, data):
        """Saves a dictionary to a JSONL file, creating dirs and appending if the file exists."""
        filepath = f'{basename}.jsonl'
        self.ensure_dir(os.path.dirname(filepath))
        with open(filepath, "a") as f:
            f.write(json.dumps(data) + '\n')
    
        # ---------- Utilities ----------
    def build_output_basename(self, output_dir, date_string: str, filename: str) -> str:
        year, month, day = date_string.split('-')
        return os.path.join(output_dir, year, month, day, self.run_id, filename)
    
    def ensure_dir(self, directory_path):
        """Ensures that a directory exists, creating it if necessary."""
        os.makedirs(directory_path, exist_ok=True)