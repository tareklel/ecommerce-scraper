# Define your item pipelines here
#
# Don't forget to add your pipeline to the ITEM_PIPELINES setting
# See: https://docs.scrapy.org/en/latest/topics/item-pipeline.html


# useful for handling different item types with a single interface
from itemadapter import ItemAdapter
from scrapy.exceptions import DropItem
from urllib.parse import urlparse

from scrapy.pipelines.images import ImagesPipeline



class EcommercecrawlPipeline:
    def __init__(self):
        self.urls = set()

    def process_item(self, item, spider):
        # check for duplicates
        adapter = ItemAdapter(item)
        if adapter['url'].split('?')[0] in self.urls:
            raise DropItem(f"Duplicate item found: {item!r}")
        else:
            url = adapter['url'].split('?')[0]
            self.urls.add(url)
            return item