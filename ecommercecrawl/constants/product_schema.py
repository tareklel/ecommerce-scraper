# Canonical product schema — site-agnostic field contract.
#
# Every spider must output a dict whose keys are a superset of REQUIRED_FIELDS.
# This schema is also used by LLMs to evaluate scrape completeness and quality.

PRODUCT_SCHEMA = {
    # ---- Run metadata ----
    "run_id": {
        "type": "str",
        "required": True,
        "description": "Unique crawl run ID. Format: YYYY-MM-DDTHH-MM-SS-mmm (UTC).",
    },
    "site": {
        "type": "str",
        "required": True,
        "description": "Site slug matching the spider name. E.g. 'ounass', 'level-shoes', 'bloomingdales'.",
    },
    "crawl_date": {
        "type": "str",
        "required": True,
        "description": "Date the item was crawled. YYYY-MM-DD.",
    },
    # ---- Page identity ----
    "url": {
        "type": "str",
        "required": True,
        "description": "PDP URL that was crawled (including any language/country params).",
    },
    "country": {
        "type": "str",
        "required": True,
        "description": "ISO 3166-1 alpha-2 country code derived from URL. E.g. 'AE', 'SA', 'KW', 'QA'.",
    },
    "language": {
        "type": "str",
        "required": True,
        "description": "Language of the crawled content. 'EN' or 'AR'. Uppercase, no country suffix.",
    },
    # ---- Product identity ----
    "portal_itemid": {
        "type": "str",
        "required": True,
        "description": "Site-native product or SKU identifier. Primary key per site.",
    },
    "product_name": {
        "type": "str",
        "required": True,
        "description": "Product name in the crawled language. Varies between EN and AR runs.",
    },
    "brand": {
        "type": "str",
        "required": True,
        "description": "Brand / designer name. Language-independent (Latin script). E.g. 'TOTEME', 'Valentino'.",
    },
    "gender": {
        "type": "str | None",
        "required": False,
        "description": (
            "Gender target: 'women', 'men', 'kids', 'unisex'. "
            "Derived from URL path or breadcrumbs. NULL if not determinable."
        ),
    },
    # ---- Attributes ----
    "color": {
        "type": "str | None",
        "required": False,
        "description": "Primary color of this variant in the crawled language. NULL if not available.",
    },
    "sizes": {
        "type": "list[str] | None",
        "required": False,
        "description": (
            "Available sizes as strings. E.g. ['36', '37', 'XS', 'M', 'One Size']. "
            "Language-independent. NULL if size information is not available."
        ),
    },
    "category": {
        "type": "str | None",
        "required": False,
        "description": (
            "Top-level product category in the crawled language. "
            "E.g. 'Shoes', 'Clothing', 'Bags', 'أحذية'. "
            "Derived from breadcrumbs or JSON-LD BreadcrumbList."
        ),
    },
    "subcategory": {
        "type": "str | None",
        "required": False,
        "description": (
            "Sub-level product category in the crawled language. "
            "E.g. 'Boots', 'Mini Dresses', 'Tote Bags'. "
            "NULL if not available."
        ),
    },
    # ---- Pricing ----
    "price": {
        "type": "float | None",
        "required": True,
        "description": (
            "Current selling price (may be sale price). In the local currency. "
            "For multi-variant products, use the minimum in-stock price."
        ),
    },
    "currency": {
        "type": "str | None",
        "required": True,
        "description": "ISO 4217 currency code. E.g. 'AED', 'SAR', 'KWD', 'QAR'.",
    },
    "price_discount": {
        "type": "str | None",
        "required": False,
        "description": "Discount label as displayed on site. E.g. '40% OFF'. NULL if full price.",
    },
    # ---- Availability ----
    "out_of_stock": {
        "type": "bool",
        "required": True,
        "description": (
            "True if all variants / sizes are sold out or out of stock. "
            "False if any variant is purchasable. "
            "Default to False if stock status is not available."
        ),
    },
    # ---- Merchandising ----
    "primary_label": {
        "type": "list[str] | None",
        "required": False,
        "description": (
            "Promotional badge or label text visible on the product card or PDP. "
            "E.g. ['NEW', 'EXCLUSIVE', 'SALE', 'ONLINE EXCLUSIVE']. NULL if none."
        ),
    },
    # ---- Media ----
    "image_urls": {
        "type": "list[str]",
        "required": True,
        "description": (
            "All product image URLs, ordered: first element is the hero/primary image. "
            "Must be absolute URLs (https://...). Language-independent. "
            "Must be a non-empty list. "
            "Do not include thumbnail variants or duplicates."
        ),
    },
    # ---- Text ----
    "text": {
        "type": "dict | None",
        "required": False,
        "description": (
            "Structured product copy, always a dict with three optional slots: "
            "{'description': str | None, 'details': list[str] | None, 'size_fit': list[str] | None}. "
            "'description' is the prose flavor paragraph. "
            "'details' is a list of material/care/composition bullet strings. "
            "'size_fit' is a list of dimension/fit bullet strings. "
            "Any slot may be None if the site does not provide that content. "
            "Used downstream by the website for structured rendering and by LLMs for quality evaluation."
        ),
    },
}

REQUIRED_FIELDS: frozenset[str] = frozenset(
    k for k, v in PRODUCT_SCHEMA.items() if v["required"]
)
OPTIONAL_FIELDS: frozenset[str] = frozenset(
    k for k, v in PRODUCT_SCHEMA.items() if not v["required"]
)
