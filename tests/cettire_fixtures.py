"""
Hand-written Cettire fixtures, shaped like the real responses but with
made-up products (no downloaded site data is committed).
"""
import json

CDN = "https://images.example.test/products"


def search_hit(handle="acme-flap-shoulder-bag-900000001", vendor="Acme", title="Acme Flap Shoulder Bag",
               title_ar="حقيبة كتف أكمي", price=3000, compare=4000, quantity=2, **overrides):
    """One `variantData` object of the search response."""
    hit = {
        "handle": handle,
        "product_id": "cHJvZHVjdDox",
        "title": title,
        "title_ar": title_ar,
        "vendor": vendor,
        "vendor_ar": vendor,
        "category": "Bags",
        "category_ar": "حقائب",
        "product_type": "Shoulder Bags",
        "product_type_ar": "حقائب الكتف",
        "department": ["women"],
        "tags": ["Shoulder Bags", vendor, "Women", "Bags"],
        "sa_sar_price_f": price,
        "sa_sar_compare_at_price_f": compare,
        "www_usd_price_f": 800.0,
        "inventory_quantity": quantity,
        "Color": "Black",
        "Size": "Only One Size",
        "designerModelNumber": "MODEL123",
        "designerColor": "001",
        "largeImage": f"{CDN}/list.jpg",
        "image_set2_url": f"{CDN}/set2.jpg",
        "media_medium": f"{CDN}/media.jpg",
        "set3_medium": f"{CDN}/set3.jpg",
        "product_images": [f"{CDN}/list.jpg"],
        "created_at": "2026-10-01T00:00:00.000Z",
        "updated_at": "2026-11-13T00:00:00.000Z",
    }
    hit.update(overrides)
    return hit


def search_payload(hits=None, vendor_facet=None, total=None):
    hits = [search_hit()] if hits is None else hits
    return {
        "result": True,
        "totalNumber": len(hits) if total is None else total,
        "remainNumber": 0,
        "errorMessage": "",
        "productQueryInfo": {"pageSize": 20, "currentPage": 0},
        "products": [{"repProductId": h["product_id"], "price": h["sa_sar_price_f"], "variantData": h} for h in hits],
        "facets": {"vendor": vendor_facet if vendor_facet is not None else {"Acme": len(hits)}},
    }


def _ref(key, typename, generated=True):
    return {"type": "id", "generated": generated, "id": key, "typename": typename}


def pdp_html(slug="acme-flap-shoulder-bag-900000001", sold_out=False, sa_price=3000, sa_compare=4000,
             images=3, api_key="test-search-key", with_product=True):
    """A product page: only the `__NEXT_DATA__` script matters to the parser."""
    product_key = "CatalogProduct:abc"
    variant_key = "CatalogProductVariant:def"
    cache = {"ROOT_QUERY": {}}
    if with_product:
        media = []
        for i in range(images):
            image_key, urls_key = f"{product_key}.media.{i}", f"${product_key}.media.{i}.URLs"
            cache[image_key] = {"priority": i + 1, "URLs": _ref(urls_key, "ImageSizes"), "__typename": "ImageInfo"}
            cache[urls_key] = {
                "thumbnail": f"{CDN}/g{i}-thumb.jpg", "small": f"{CDN}/g{i}-small.jpg",
                "medium": f"{CDN}/g{i}-medium.jpg", "large": f"{CDN}/g{i}-large.jpg",
                "original": f"{CDN}/g{i}-original.jpg", "__typename": "ImageSizes",
            }
            media.append(_ref(image_key, "ImageInfo"))
        prices = [("www", "USD", 800.0, 1000.0), ("sa", "SAR", sa_price, sa_compare)]
        price_refs = []
        for i, (region, currency, price, compare) in enumerate(prices):
            key = f"{variant_key}.currencyPrices.{i}"
            cache[key] = {"price": price, "currencyCode": currency, "compareAtPrice": compare,
                          "regionCode": region, "__typename": "CurrencyPriceInfo"}
            price_refs.append(_ref(key, "CurrencyPriceInfo"))
        tag_refs = []
        for i, name in enumerate(["Shoulder Bags", "Acme", "Women", "Bags"]):
            key = f"${product_key}.tags.nodes.{i}"
            cache[key] = {"name": name, "slug": name.lower().replace(" ", "-"), "__typename": "Tag"}
            tag_refs.append(_ref(key, "Tag"))
        cache[f"${product_key}.tags"] = {"nodes": tag_refs, "__typename": "TagConnection"}
        cache[variant_key] = {
            "title": "Only One Size", "size": "Only One Size", "color": "Black",
            "isSoldOut": sold_out, "inventoryAvailableToSell": 0 if sold_out else 2,
            "currencyPrices": price_refs, "__typename": "CatalogProductVariant",
        }
        cache[product_key] = {
            "title": "Acme Flap Shoulder Bag", "slug": slug, "vendor": "Acme",
            "description": "Dimensions: Width: 20cm<br /><br />100% Calf Leather<br />Made in Italy<br />",
            "isSoldOut": sold_out, "productType": "Shoulder Bags",
            "designerModelNumber": "MODEL123", "designerColor": "001",
            "highlights": {"type": "json", "json": ["Flap closure", "Gold-tone hardware"]},
            "composition": "100% Calf Leather", "madeIn": "Italy",
            "dimensions": "Width: 20cm, Height: 12cm<br />Strap: 50cm",
            "media": media, "tags": _ref(f"${product_key}.tags", "TagConnection"),
            "variants": [_ref(variant_key, "CatalogProductVariant", generated=False)],
            "__typename": "CatalogProduct",
        }
    next_data = {
        "props": {"apolloState": {"data": cache}},
        "page": "/product",
        "runtimeConfig": {"searchAIAPIKey": api_key, "graphqlUrl": "https://api.example.test/graphql"},
    }
    return (
        "<html><body><main></main><script>__NEXT_DATA__ = "
        + json.dumps(next_data)
        + ";__NEXT_LOADED_PAGES__=[];</script></body></html>"
    )
