import json
import re
from typing import Optional, Tuple
from scrapy.http import Response
from lxml import html
from urllib.parse import urlparse

from ecommercecrawl.rules.image_rules import normalize_ordered_image_urls


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
    if isinstance(x, dict) and x.get('analytics'):
        return x['analytics']['brand']
    return None

def get_category_from_item(x):
    if isinstance(x, dict) and x.get('analytics'):
        return x['analytics']['category1'].lower()
    return None

def get_gender_from_item(x):
    if isinstance(x, dict) and x.get('analytics'):
        return x['analytics']['gender']
    return None

def get_color_from_item(item):
    if isinstance(item, dict) and item.get('color'):
        return item['color'].lower()
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

def get_was_price_from_item(x):
    # originalPrice format: "1,200.00 AED" — number is first token
    if isinstance(x, dict) and x.get('originalPrice'):
        try:
            return float(x['originalPrice'].split(' ')[0].replace(',', ''))
        except (ValueError, IndexError):
            return None
    return None

def get_price_discount_from_item(x):
    if isinstance(x, dict) and x.get('discountPercentage'):
        return x['discountPercentage']
    return None

def _image_url_value(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get('url') or value.get('contentUrl')
    return None


def _collect_image_urls(hero_url, gallery: list) -> list[str] | None:
    candidates = []
    if hero_url is not None:
        candidates.append(_image_url_value(hero_url))
    candidates.extend(_image_url_value(value) for value in gallery)
    return normalize_ordered_image_urls(candidates)

def get_image_urls_from_item(x) -> list[str] | None:
    if not isinstance(x, dict):
        return None
    if 'imagePreviewGallery' not in x:
        return None

    gallery = x['imagePreviewGallery']
    if not isinstance(gallery, list):
        return None
    hero = (x.get('image') or {}).get('url') if isinstance(x.get('image'), dict) else None
    return _collect_image_urls(hero, gallery)

def get_primary_label_from_item(x):
    if isinstance(x, dict) and x.get('badges'):
        return [x['text'] for x in x['badges']]
    return None

def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()

def extract_product_details(response) -> dict:
    description = None
    details = None
    size_fit = None

    # Product Details accordion
    pd_nodes = response.xpath(
        '//div[contains(@class,"accordion-root")]'
        '[.//button//*[normalize-space()="Product Details" or normalize-space()="تفاصيل المنتج"]]'
    )
    if pd_nodes:
        root = pd_nodes[0]
        # Prose from <p> tags
        p_texts = [_norm_ws(t) for t in root.css('div.accordion-details-root > p::text').getall()]
        desc = _norm_ws(' '.join(t for t in p_texts if t))
        if desc:
            description = desc
        # Bullets from <ul data-testid="lineitems"> <li>
        bullets = [_norm_ws(li) for li in root.css('ul[data-testid="lineitems"] li::text').getall()]
        bullets = [b for b in bullets if b]
        if bullets:
            details = bullets

    # Size and Fit accordion
    sf_nodes = response.xpath(
        '//div[contains(@class,"accordion-root")]'
        '[.//button//*[normalize-space()="Size and Fit" or normalize-space()="المقاس والملاءمة"]]'
    )
    if sf_nodes:
        root = sf_nodes[0]
        bullets = [_norm_ws(li) for li in root.css('ul li::text').getall()]
        bullets = [b for b in bullets if b]
        if bullets:
            size_fit = bullets

    result = {'description': description, 'details': details, 'size_fit': size_fit}
    return result if any(v is not None for v in result.values()) else None


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


def extract_was_price(response: Response) -> float | None:
    # Original price is rendered with Tailwind's line-through class, text is "500 AED"
    m = re.search(
        r'class="[^"]*\bline-through\b[^"]*"[^>]*>(\d[\d,]*(?:\.\d+)?)\s+[A-Z]{2,4}',
        response.text, re.IGNORECASE,
    )
    if m:
        try:
            return float(m.group(1).replace(',', ''))
        except ValueError:
            pass
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

def extract_image_urls(response: Response) -> list[str] | None:
    # 1) __NEXT_DATA__ — authoritative ordered gallery
    nd = response.xpath('//script[@id="__NEXT_DATA__"]/text()').get()
    if nd:
        try:
            data = json.loads(nd)
            pd = data.get('props', {}).get('pageProps', {}).get('productDetails')
            if isinstance(pd, dict) and 'imagePreviewGallery' in pd:
                gallery = pd['imagePreviewGallery']
                if isinstance(gallery, list):
                    hero = pd.get('image')
                    return _collect_image_urls(hero, gallery)
        except Exception:
            pass

    # 2) JSON-LD Product.image list
    for block in response.xpath('//script[@type="application/ld+json"]/text()').getall():
        try:
            data = json.loads(block)
            items = data if isinstance(data, list) else [data]
            for item in items:
                item_types = item.get('@type')
                is_product = item_types == 'Product' or (
                    isinstance(item_types, list) and 'Product' in item_types
                )
                if not is_product or 'image' not in item:
                    continue

                images = item['image']
                if isinstance(images, list):
                    gallery = images
                elif isinstance(images, (str, dict)):
                    gallery = [images]
                else:
                    continue

                og = response.xpath('//meta[@property="og:image"]/@content').get()
                return _collect_image_urls(og, gallery)
        except Exception:
            pass

    # 3) OpenGraph/Twitter scalar last resort
    img = (
        response.xpath('//meta[@property="og:image"]/@content').get()
        or response.xpath('//meta[@name="twitter:image"]/@content').get()
    )
    if img:
        return normalize_ordered_image_urls([img])

    return None


def extract_first_image_url(response: Response) -> Optional[str]:
    """Kept for backwards compatibility; delegates to extract_image_urls."""
    urls = extract_image_urls(response)
    return urls[0] if urls else None

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
