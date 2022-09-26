# Define your item pipelines here
#
# Don't forget to add your pipeline to the ITEM_PIPELINES setting
# See: https://docs.scrapy.org/en/latest/topics/item-pipeline.html


# useful for handling different item types with a single interface
from itemadapter import ItemAdapter
from scrapy.exceptions import DropItem



class EcommercecrawlPipeline:
    def __init__(self):
        self.ids_seen = set()

    def process_item(self, item, spider):
        # check for duplicates
        adapter = ItemAdapter(item)
        if spider.name == 'farfetch':
            if adapter['portal_itemid'] in self.ids_seen:
                raise DropItem(f"Duplicate item found: {item!r}")
            else:
                self.ids_seen.add(adapter['portal_itemid'])
                return item
        else:
            return item
