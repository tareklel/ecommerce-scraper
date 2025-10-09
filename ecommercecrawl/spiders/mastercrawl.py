import os
import csv
import json
from scrapy import Spider
from datetime import datetime


class MasterCrawl(Spider):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.run_id = datetime.utcnow().strftime('%Y-%m-%dT%H-%M-%S-%fZ')

    def save_to_jsonl(self, filename, data):
        """Saves a dictionary to a JSONL file, appending if the file exists."""
        filename = f'{filename}.jsonl'
        with open(filename, "a") as f:
            f.write(json.dumps(data) + '\n')

    def save_image(self, response):
        image_dir = response.meta['image_dir']
        image_name = response.url.split('/')[-1]
        with open(os.path.join(image_dir, image_name), 'wb') as f:
            f.write(response.body)
    
        # ---------- Utilities ----------
    def build_output_basename(self, output_dir, name, date_string: str) -> str:
        return f'{output_dir}/{name}-{date_string}'

    def ensure_dir(self, path: str):
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)