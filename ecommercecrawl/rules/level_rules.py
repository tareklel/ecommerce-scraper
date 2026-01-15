import json
import re
from typing import Optional, Tuple
from scrapy.http import Response
from lxml import html
from urllib.parse import urlparse


def get_products(payload: dict):
    # return products from payload
    v = payload.get('products')
    return v

def get_country(url: str):
    # return counry by analyzing subdomain or subpath
    subdomain = url.split('/')[2].split('.')[0]
    if 'saudi' in subdomain:
        return 'sa'
    elif 'kuwait' in subdomain:
        return 'kw'
    elif 'qatar' in subdomain:
        return 'qa'
    elif 'www' in subdomain:
        return 'ae'
    return None

def get_gender(url: str):
    # return gender from plp subpath
    if '/men/' in url:
        return 'men'
    elif '/women/' in url:
        return 'women'
    elif '/kids/' in url:
        return 'kids'
    return None

def get_language_plp(url: str):
    # return language from plp subpath
    if is_plp(url):
        return get_language(url).lower()
    else:
        raise ValueError(f'URL {url} is not a PLP URL')

def get_language(url: str):
    # return language from url
    subdomain = url.split('/')[2].split('.')[0]
    if '/ar/' in url or 'ar-' in subdomain:
        return 'AR'
    return 'EN'

def get_urlpath(url: str):
    # search plp for url path after gender
    match = re.search(r'/(men|women)/(.+?)(?:\?|$)', url)
    if match:
        return match.group(2)
    return None 

def is_plp(url):
    # check if plp is url
    return '.html' not in url and get_gender(url) is not None

def is_pdp(url):
    return '.html' in url and get_gender(url) is None

# extract from item
def get_url_from_item(x):
    if isinstance(x, dict) and x.get('action', {}).get('url'):
        return x['action']['url']
    return None

def get_id_from_item(x):
    if isinstance(x, dict) and x.get('analytics'):
        return x['analytics']['item_id']
    return None

def get_name_from_item(x):
    if isinstance(x, dict) and x.get('name'):
        return x['name']
    return None

def get_brand_from_item(x):
    if isinstance(x, dict) and x.get('brandName'):
        return x['brandName']
    return None

def get_category_from_item(x):
    if isinstance(x, dict) and x.get('analytics'):
        return x['analytics']['category1'].lower()
    return None

def get_gender_from_item(x):
    if isinstance(x, dict) and x.get('analytics'):
        return x['analytics']['gender']
    return None

def get_subcategory_from_item(x):
    if isinstance(x, dict) and x.get('analytics'):
        return x['analytics']['category2'].lower()
    return None

def get_price_from_item(x):
    if isinstance(x, dict) and x.get('analytics'):
        return x['analytics']['price']
    return None

def get_currency_from_item(x):
    if isinstance(x, dict) and x.get('originalPrice'):
        return x['originalPrice'].split(' ')[-1]
    return None

def get_price_discount_from_item(x):
    if isinstance(x, dict) and x.get('discountPercentage'):
        return x['discountPercentage']
    return None

def get_image_urls_from_item(x):
    if isinstance(x, dict) and x.get('imagePreviewGallery'):
        return x['imagePreviewGallery'][0]['url']
    return None

def get_primary_label_from_item(x):
    if isinstance(x, dict) and x.get('badges'):
        return [x['text'] for x in x['badges']]
    return None

def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()

def extract_product_details(response):
    accordion_nodes = response.xpath(
        '//div[contains(@class,"accordion-root")]'
        '[.//button//span[normalize-space()="Product Details"]]'
    )
    if not accordion_nodes:
        return ""
    root = accordion_nodes[0]

    detail_fragments = [
        text for text in root.css('div.accordion-details-root > p::text').getall()
        if text is not None
    ]
    details_text = _norm_ws(" ".join(detail_fragments))

    bullets = []
    for li in root.css('ul[data-testid="lineitems"] li::text').getall():
        cleaned = _norm_ws(li)
        if cleaned:
            bullets.append(cleaned)

    if details_text:
        bullets.append(details_text)

    return ' | '.join(bullets)


SKU_REGEX = re.compile(
    r"\b[A-Z0-9]{2,}(?:-[A-Z0-9]{2,})+\b|\b[A-Z]{2}\d{4,}[A-Z0-9]+\b",
    re.I,
)

def extract_sku(response: Response) -> Optional[str]:
    """
    Robust SKU extractor for modern e-commerce product pages.
    Works for examples like:
      - BB7844AZ00083028
      - ELISA-105-WHITE
      - IH9149-CBCBOW
    """

    # --------------------------------------------------
    # 1) JSON-LD (schema.org Product)
    # --------------------------------------------------
    json_ld_blocks = response.xpath(
        '//script[@type="application/ld+json"]/text()'
    ).getall()

    for block in json_ld_blocks:
        try:
            data = json.loads(block)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get("@type") == "Product" and item.get("sku"):
                    return item["sku"].strip()
        except Exception:
            pass

    # --------------------------------------------------
    # 2) Meta tags / microdata
    # --------------------------------------------------
    meta_sku = response.xpath(
        '//meta[@itemprop="sku"]/@content | '
        '//meta[@property="product:retailer_item_id"]/@content'
    ).get()
    if meta_sku:
        return meta_sku.strip()

    # --------------------------------------------------
    # 3) Embedded JS blobs (Next.js, dataLayer, etc.)
    # --------------------------------------------------
    script_text = " ".join(
        response.xpath('//script/text()').getall()
    )
    js_match = re.search(r'"sku"\s*:\s*"([^"]+)"', script_text, re.I)
    if js_match:
        return js_match.group(1).strip()

    # --------------------------------------------------
    # 4) Image URL heuristic (very common on LevelShoes)
    # --------------------------------------------------
    image_urls = response.xpath(
        '//meta[@property="og:image"]/@content | '
        '//img/@src'
    ).getall()

    for url in image_urls:
        m = re.search(r"/([a-z0-9\-]+)_\d+\.(?:jpg|png|webp)", url, re.I)
        if m:
            candidate = m.group(1).upper()
            if SKU_REGEX.search(candidate):
                return candidate

    # --------------------------------------------------
    # 5) URL fallback (last resort)
    # --------------------------------------------------
    url_slug = response.url.split("/")[-1]
    url_match = SKU_REGEX.search(url_slug.upper())
    if url_match:
        return url_match.group(0)

    return None

def extract_product_name(response: Response) -> Optional[str]:
    """
    Minimal and robust product name extractor.
    """

    # 1) JSON-LD (schema.org Product.name)
    for block in response.xpath(
        '//script[@type="application/ld+json"]/text()'
    ).getall():
        try:
            data = json.loads(block)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get("@type") == "Product" and item.get("name"):
                    return item["name"].strip()
        except Exception:
            pass

    # 2) OpenGraph title fallback
    og_title = response.xpath(
        '//meta[@property="og:title"]/@content'
    ).get()
    if og_title:
        # "Elisa pumps for Women - White in UAE | Level Shoes"
        return og_title.split(" for ")[0].strip()

    return None

def extract_gender_from_breadcrumbs(response: Response) -> Optional[str]:
    """
    Extract gender from breadcrumbs (returns 'Women' / 'Men' / 'Kids' exactly as displayed).
    Primary: JSON-LD BreadcrumbList (schema.org).
    Fallback: visible breadcrumb links in DOM.
    """

    # 1) JSON-LD BreadcrumbList
    for block in response.xpath('//script[@type="application/ld+json"]/text()').getall():
        try:
            data = json.loads(block)
        except Exception:
            continue

        items = data if isinstance(data, list) else [data]
        for item in items:
            if item.get("@type") != "BreadcrumbList":
                continue

            elems = item.get("itemListElement") or []
            # find position 2 breadcrumb ("Women", "Men", "Kids")
            for el in elems:
                try:
                    if int(el.get("position", -1)) == 2:
                        name = (el.get("name") or "").strip()
                        if name:
                            return name
                except Exception:
                    pass

    # 2) DOM breadcrumb fallback (still “breadcrumbs”, just not JSON-LD)
    # Common pattern: nav/ol/li with link text "Women" / "Men" / "Kids"
    crumb_texts = response.xpath(
        '//nav//*[self::a or self::span or self::li]/text()'
    ).getall()
    for t in crumb_texts:
        t = (t or "").strip()
        if t in {"Women", "Men", "Kids"}:
            return t

    return None


def extract_product_brand(response: Response) -> Optional[str]:
    """
    Minimal and robust product brand extractor.
    Returns brand as displayed (e.g. 'Dolce & Gabbana', 'Roberto Rubino', 'Adidas')
    """

    # 1) JSON-LD (schema.org Product.brand.name)
    for block in response.xpath(
        '//script[@type="application/ld+json"]/text()'
    ).getall():
        try:
            data = json.loads(block)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get("@type") == "Product":
                    brand = item.get("brand")
                    if isinstance(brand, dict) and brand.get("name"):
                        return brand["name"].strip()
                    if isinstance(brand, str):
                        return brand.strip()
        except Exception:
            pass

    # 2) OpenGraph title fallback
    # e.g. "Dolce&Gabbana Vittoria handbag for Women - Beige in UAE | Level Shoes"
    og_title = response.xpath(
        '//meta[@property="og:title"]/@content'
    ).get()
    if og_title:
        head = og_title.split(" for ")[0]
        # brand is usually the first token before the product name
        # take first 3 words max to avoid swallowing the product
        brand_guess = " ".join(head.split()[:3]).strip()
        return brand_guess

    return None

def extract_category_and_subcategory_from_breadcrumbs(
    response,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract (category, subcategory) from breadcrumb URLs.

    Finds a path segment equal to {men,women,kids} anywhere in the URL path,
    then returns the next two segments as slugs.

    Example:
      /women/bags/mini-bags -> ("bags", "mini-bags")
      /sale/women/bags/mini-bags -> ("bags", "mini-bags")
    """

    def iter_nodes(obj):
        # Flatten common JSON-LD shapes: list, dict, dict with @graph
        if isinstance(obj, list):
            for x in obj:
                yield from iter_nodes(x)
        elif isinstance(obj, dict):
            if "@graph" in obj and isinstance(obj["@graph"], list):
                for x in obj["@graph"]:
                    yield from iter_nodes(x)
            else:
                yield obj

    for block in response.xpath('//script[@type="application/ld+json"]/text()').getall():
        try:
            data = json.loads(block)
        except Exception:
            continue

        for node in iter_nodes(data):
            if node.get("@type") != "BreadcrumbList":
                continue

            for c in node.get("itemListElement", []) or []:
                item = c.get("item")

                # item can be a string URL or {"@id": "..."}
                if isinstance(item, dict):
                    item = item.get("@id")

                if not isinstance(item, str):
                    continue

                path = urlparse(item).path.lower().strip("/")
                parts = [p for p in path.split("/") if p]

                for i, seg in enumerate(parts):
                    if seg in {"men", "women", "kids"} and i + 2 < len(parts):
                        return parts[i + 1], parts[i + 2]

    return None, None

def extract_price(response: Response) -> int | None:
    """
    Extract numeric price (AED) from PDP.
    Returns integer price or None.
    """

    # 1) OpenGraph / product meta (most reliable)
    price = response.xpath(
        '//meta[@property="product:price:amount"]/@content'
    ).get()
    if price:
        return int(price.replace(',', '').split()[0])

    # 2) JSON-LD Product.offers.price
    for block in response.xpath(
        '//script[@type="application/ld+json"]/text()'
    ).getall():
        try:
            data = json.loads(block)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get('@type') == 'Product':
                    offers = item.get('offers', {})
                    if isinstance(offers, dict) and offers.get('price'):
                        return int(float(offers['price']))
        except Exception:
            pass

    # 3) Twitter card fallback
    price = response.xpath(
        '//meta[@name="twitter:data1"]/@content'
    ).get()
    if price:
        return int(price.replace(',', '').split()[0])

    return None

def extract_currency(response: Response) -> Optional[str]:
    """
    Extract currency code (e.g. 'AED') from PDP.
    """

    # 1) OpenGraph product currency (most reliable)
    currency = response.xpath(
        '//meta[@property="product:price:currency"]/@content'
    ).get()
    if currency:
        return currency.strip()

    # 2) JSON-LD Product.offers.priceCurrency
    for block in response.xpath(
        '//script[@type="application/ld+json"]/text()'
    ).getall():
        try:
            data = json.loads(block)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get("@type") == "Product":
                    offers = item.get("offers", {})
                    if isinstance(offers, dict) and offers.get("priceCurrency"):
                        return offers["priceCurrency"].strip()
        except Exception:
            pass

    # 3) Twitter card fallback (rare but safe)
    currency = response.xpath(
        '//meta[@name="twitter:data2"]/@content'
    ).get()
    if currency:
        return currency.strip()

    return None


def extract_price_discount(response: Response) -> Optional[int]:
    """
    Extract discount percent from embedded JS:
      "discountPercentage":"40% OFF"
    Returns 40, else None.
    """
    script_text = " ".join(response.xpath('//script/text()').getall())
    _DISCOUNT_LABEL_RE = re.compile(
    r'"discountPercentage"\s*:\s*"(\d{1,3}%\s*OFF)"',
    re.I)
    m = _DISCOUNT_LABEL_RE.search(script_text)
    return m.group(1) if m else None


def extract_badges(response) -> Optional[list[str]]:
    """Extract PDP badge labels (e.g. NEW, EXCLUSIVE, *).

    Returns a list of unique badge strings (preserving order), or None if empty.

    Notes:
    - Avoids global page chrome like "EASY RETURNS", "FOLLOW US", "SUBSCRIBE".
    - Avoids concatenating icon stars with text by excluding svg text.
    """

    tree = html.fromstring(response.text)

    def _norm(s: str) -> str:
        return re.sub(r"\s+", " ", (s or "")).strip()

    def _text_without_svg(el) -> str:
        # Important: badges may include an icon (svg star). Exclude svg descendants.
        parts = el.xpath(".//text()[not(ancestor::svg)]")
        return _norm("".join(parts))

    badges: list[str] = []

    # 1) Primary: LevelShoes badge ribbon that overlays the product imagery
    # Example container: <div class="absolute z-10 mt-4 flex gap-1 ms-4"> ... </div>
    containers = tree.xpath(
        "//div[contains(@class,'absolute') and contains(@class,'z-10') and "
        "contains(@class,'mt-4') and contains(@class,'gap-1') and "
        "(.//span[contains(@class,'typography-badge')] or .//span[contains(@class,'badge')])]"
    )
    for c in containers:
        for span in c.xpath(".//span"):
            t = _text_without_svg(span)
            if not t:
                continue
            badges.append(t)

    # 2) Fallback: any explicit badge span classes (still much safer than scanning all spans/divs)
    if not badges:
        for span in tree.xpath("//span[contains(@class,'typography-badge') or contains(@class,'badge')]"):
            t = _text_without_svg(span)
            if t:
                badges.append(t)

    # 3) Cleanup:
    # - strip leading icon stars when glued to text (e.g. "★EXCLUSIVE" -> "EXCLUSIVE")
    cleaned: list[str] = []
    for b in badges:
        b = _norm(b)
        if not b:
            continue

        # keep pure symbol badges
        if b in {"*", "★"}:
            cleaned.append(b)
            continue

        # remove leading star/asterisk glyphs attached to text
        b = re.sub(r"^[★*]+\s*", "", b)

        if b:
            cleaned.append(b)

    # de-dupe while preserving order
    seen = set()
    out: list[str] = []
    for b in cleaned:
        if b not in seen:
            seen.add(b)
            out.append(b)

    return out or None

def extract_first_image_url(response: Response) -> Optional[str]:
    """
    Extract primary (first) product image URL from LevelShoes PDP.
    """

    # 1) OpenGraph (most reliable, always primary image)
    img = response.xpath('//meta[@property="og:image"]/@content').get()
    if img:
        return img.strip()

    # 2) JSON-LD Product.image[0]
    for block in response.xpath('//script[@type="application/ld+json"]/text()').getall():
        try:
            data = json.loads(block)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get("@type") == "Product":
                    images = item.get("image")
                    if isinstance(images, list) and images:
                        return images[0].strip()
                    if isinstance(images, str):
                        return images.strip()
        except Exception:
            pass

    # 3) Twitter card fallback
    img = response.xpath('//meta[@name="twitter:image"]/@content').get()
    if img:
        return img.strip()

    # 4) DOM fallback: first catalog image ending with _1
    imgs = response.xpath('//img/@src').getall()
    for url in imgs:
        if re.search(r"_1\.(jpg|png|webp)", url, re.I):
            return url.strip()

    return None

from scrapy.http import Response

def is_out_of_stock(response: Response) -> bool:
    """
    STRICT: only trust availability fields in <head>:
      - meta name="product:availability"
      - meta name="twitter:data2" when twitter:label2 == Availability
    JSON-LD is used ONLY if both are missing (because it can be wrong on LevelShoes).
    """

    def norm(x: str | None) -> str:
        return (x or "").strip().lower()

    # 1) product:availability (most reliable in your files)
    pa = norm(response.xpath('//meta[@name="product:availability"]/@content').get())
    if pa:
        # examples: "in Stock"  [oai_citation:4‡dg_bag.html](sediment://file_00000000a90c71fda73069564ae72d1c), "out of stock"  [oai_citation:5‡ooo_shoe.html](sediment://file_00000000ced871fdac2e8a08eaa7e088)
        return pa == "out of stock"

    # 2) twitter availability (only if it's actually the Availability field)
    label2 = norm(response.xpath('//meta[@name="twitter:label2"]/@content').get())
    data2  = norm(response.xpath('//meta[@name="twitter:data2"]/@content').get())
    if label2 == "availability" and data2:
        return data2 == "out of stock"

    # 3) If neither exists, be strict and default to NOT out of stock
    # (you can change this to None/unknown if you prefer)
    return False

def extract_level_category_id(response: Response) -> Optional[int]:
    """
    Extract LevelShoes product category ID from JSON-LD Product.category (int).
    Returns int or None.
    """

    for block in response.xpath('//script[@type="application/ld+json"]/text()').getall():
        try:
            data = json.loads(block)
        except Exception:
            continue

        items = data if isinstance(data, list) else [data]
        for item in items:
            if item.get("@type") != "Product":
                continue

            cat = item.get("category")
            # examples: 33, 248, 2949 in your saved pages
            if isinstance(cat, int):
                return cat
            if isinstance(cat, str) and cat.strip().isdigit():
                return int(cat.strip())

    return None