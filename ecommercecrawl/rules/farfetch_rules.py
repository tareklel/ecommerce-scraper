import re
from ecommercecrawl.xpaths import farfetch_xpaths as xpaths


def is_items_page(url):
    return url.split('/')[-1].split('?')[0] == 'items.aspx'

def is_first_page(url):
    return (len(url.split('?')) == 1) & (is_items_page(url))

def is_pdp_url(url):
    lastdir = url.split('/')[-1].split('?')[0]
    pattern = r"-item-\d+\.aspx(?:\?.*)?$"

    return re.search(pattern, lastdir) is not None

def get_country(url):
    country = url.split('/')[3]
    return country

def get_portal_itemid(url):
    if is_pdp_url(url):
        itemid = url.split('?')[0].split('/')[-1].split('.')[0].split('-')[-1]
        # check if int else return None
        try:
            int(itemid)
        except ValueError:
            return None
        return itemid
    else:
        return None

def get_gender(url):
    if is_pdp_url(url):
        return url.split('/')[5]
    else:
        return None

def get_pdp_subfolder(url):
    if is_pdp_url(url):
        return url.url.split('/')[-1].split('.')[0]
    else:
        return None

def get_pagination(response):
    return response.xpath(xpaths.PAGINATION_XPATH).get()

def get_max_page(pagination):
    numbers = re.findall(r'\d+', pagination)
    total_pages = int(numbers[-1]) if numbers else 1
    return total_pages

def get_list_page_urls(url, max_page):
    """
    Return ONLY pages 2..max_page to avoid duplicating page 1.
    Assumes `url` is the canonical page-1 URL (without ?page=1).
    """
    urls = [f"{url}?page={page}" for page in range(2, max_page + 1)]
    urls = [u for u in urls if u != url]
    urls = [u for u in urls if not (u.endswith("?page=1") and url == u.split("?")[0])]
    urls = [url] + urls
    return urls

def get_category_from_breadcrumbs(breadcrumbs):
    if len(breadcrumbs) >= 3:
        return breadcrumbs[2]
    return None

def get_subcategory_from_breadcrumbs(breadcrumbs):
    if len(breadcrumbs) >= 4:
        return breadcrumbs[3]
    return None

def get_price_and_currency(price_str):
    if price_str is None:
        return None, None
    parts = price_str.split(' ')
    if len(parts) >= 2:
        currency = parts[0]
        price = ' '.join(parts[1:])
        price = price.replace(',', '')
        try:
            price = float(price)
        except ValueError:
            return None, None
        return price, currency
    return None, None

def get_product_name(response):
    product_name_all = response.xpath(xpaths.PRODUCT_NAME_XPATH).getall()[-1]
    product_name = None if not product_name_all else product_name_all
    return product_name

def get_pdp_urls(response):
    return response.xpath(xpaths.PDP_XPATH).getall() or []

def get_price(response):
    return response.xpath(xpaths.PRICE_XPATH).get()

def get_breadcrumbs(response):
    return response.xpath(xpaths.BREADCRUMBS_XPATH).getall()

def get_image_url(response):
    return response.xpath(xpaths.IMAGE_URL_XPATH).get()

def get_brand(response):
    return response.xpath(xpaths.BRAND_XPATH).get()

def get_discount(response):
    return response.xpath(xpaths.DISCOUNT_XPATH).get()

def is_sold_out(response):
    return bool(response.xpath(xpaths.SOLD_OUT_XPATH).get())

def get_primary_label(response):
    return response.xpath(xpaths.PRIMARY_LABEL_XPATH).get()

def get_text(response):
    highlights = response.xpath(xpaths.HIGHLIGHTS_XPATH).getall()
    composition = response.xpath(xpaths.COMPOSITION_XPATH).get()
    print(', '.join([*map(str.strip, highlights), composition]) if composition else ', '.join(map(str.strip, highlights)))
    return ', '.join([*map(str.strip, highlights), composition]) if composition else ', '.join(map(str.strip, highlights))

def get_url_drop_param(url):
    return url.split('?')[0]