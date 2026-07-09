"""
Farfetch PDP probe via Zyte API.

Farfetch embeds a JSON-LD schema.org ProductGroup block on every PDP.
That is the extraction target — more stable than CSS/XPath or custom JS variables.

Usage:
    export ZYTE_API_KEY=<your-key>
    poetry run python scripts/zyte_farfetch_probe.py [--url <pdp_url>]
    poetry run python scripts/zyte_farfetch_probe.py --dump-jsonld    # raw JSON-LD block
    poetry run python scripts/zyte_farfetch_probe.py --probe-plp      # also test a PLP

Default PDP: a known live Farfetch AE women's boots PDP.
"""

import argparse
import json
import os
import re
import sys
from pprint import pformat

import requests

ZYTE_API_URL = "https://api.zyte.com/v1/extract"

# Known-live PDP for probe runs
DEFAULT_PDP = "https://www.farfetch.com/ae/shopping/women/toteme-square-toe-leather-boots-item-32020644.aspx"
# Brand PLP — stable seed for discovering live PDPs
DEFAULT_PLP = "https://www.farfetch.com/ae/shopping/women/toteme/items.aspx"


def fetch_rendered(url: str, api_key: str, timeout: int = 90) -> str:
    resp = requests.post(
        ZYTE_API_URL,
        auth=(api_key, ""),
        json={"url": url, "browserHtml": True},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["browserHtml"]


def extract_jsonld_blocks(html: str) -> list[dict]:
    blocks = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL | re.IGNORECASE,
    )
    results = []
    for b in blocks:
        try:
            results.append(json.loads(b.strip()))
        except Exception:
            pass
    return results


def find_product_group(blocks: list[dict]) -> dict | None:
    for b in blocks:
        if b.get("@type") == "ProductGroup":
            return b
    return None


def find_breadcrumbs(blocks: list[dict]) -> list[dict]:
    for b in blocks:
        if b.get("@type") == "BreadcrumbList":
            return b.get("itemListElement", [])
    return []


def find_item_list_urls(blocks: list[dict]) -> list[str]:
    """Extract PDP URLs from a PLP ItemList JSON-LD block."""
    urls = []
    for b in blocks:
        if b.get("@type") == "ItemList":
            for elem in b.get("itemListElement", []):
                url = elem.get("url") or (elem.get("item") or {}).get("url")
                if url:
                    urls.append(url)
    return urls


def summarise_product(pg: dict, breadcrumbs: list[dict]) -> dict:
    """Extract product fields from a schema.org ProductGroup block."""
    variants = pg.get("hasVariant") or []
    images = pg.get("image") or []

    # Price: min across in-stock variants (Farfetch can vary by size)
    prices = []
    currency = None
    any_in_stock = False
    for v in variants:
        offers = v.get("offers") or {}
        avail = offers.get("availability", "")
        in_stock = "InStock" in avail
        if in_stock:
            any_in_stock = True
        specs = offers.get("priceSpecification") or []
        for spec in specs:
            p = spec.get("price")
            c = spec.get("priceCurrency")
            if p is not None:
                prices.append(p)
                currency = currency or c

    price = min(prices) if prices else None
    out_of_stock = not any_in_stock and bool(variants)

    # Sizes: all available sizes
    sizes = [v.get("size") for v in variants if v.get("size")]

    # Category/subcategory from BreadcrumbList (position 3 and 4, 1-indexed)
    crumb_names = {item.get("position"): (item.get("item") or {}).get("name")
                   for item in breadcrumbs}

    # Images: all contentUrls
    image_urls = [img.get("contentUrl") for img in images if img.get("contentUrl")]

    return {
        "portal_itemid": pg.get("productGroupID"),
        "product_name":  pg.get("name", "").strip(),
        "brand":         (pg.get("brand") or {}).get("name"),
        "colour":        pg.get("color"),
        "price":         price,
        "currency":      currency,
        "out_of_stock":  out_of_stock,
        "sizes":         sizes,
        "n_images":      len(image_urls),
        "first_image":   image_urls[0] if image_urls else None,
        "all_images":    image_urls,
        "category":      crumb_names.get(3),
        "subcategory":   crumb_names.get(4),
        "description":   pg.get("description"),
        "url":           pg.get("url"),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_PDP, help="Farfetch PDP URL to probe")
    parser.add_argument("--dump-jsonld", action="store_true", help="Print raw JSON-LD blocks")
    parser.add_argument("--probe-plp", action="store_true", help="Also probe the default PLP for ItemList")
    args = parser.parse_args()

    api_key = os.environ.get("ZYTE_API_KEY", "").strip()
    if not api_key:
        sys.exit("ZYTE_API_KEY is not set.")

    # --- PDP probe ---
    print(f"Fetching PDP: {args.url}")
    html = fetch_rendered(args.url, api_key)
    print(f"Got {len(html):,} chars")

    title_m = re.search(r'<title>(.*?)</title>', html)
    print(f"Title: {title_m.group(1) if title_m else 'n/a'}")

    blocks = extract_jsonld_blocks(html)
    print(f"JSON-LD blocks: {len(blocks)} ({[b.get('@type') for b in blocks]})")

    pg = find_product_group(blocks)
    if not pg:
        print("\nFAIL: No ProductGroup JSON-LD found.")
        ids = re.findall(r'<script[^>]+id=["\']([^"\']+)["\']', html)
        print(f"Script IDs: {ids}")
        sys.exit(1)

    if args.dump_jsonld:
        print("\n--- Raw ProductGroup JSON-LD ---")
        print(json.dumps(pg, indent=2))
        breadcrumbs = find_breadcrumbs(blocks)
        print("\n--- BreadcrumbList ---")
        print(json.dumps(breadcrumbs, indent=2))

    breadcrumbs = find_breadcrumbs(blocks)
    summary = summarise_product(pg, breadcrumbs)

    print("\n--- Extracted fields ---")
    for k, v in summary.items():
        if k == "all_images":
            continue
        print(f"  {k:20s}: {v}")

    required = {"portal_itemid", "product_name", "brand", "price", "currency"}
    missing_required = [k for k in required if not summary.get(k)]
    missing_optional = [k for k, v in summary.items()
                        if v is None and k not in required and k != "all_images"]

    print("\n--- Verdict ---")
    if missing_required:
        print(f"FAIL: missing required fields: {missing_required}")
    elif missing_optional:
        print(f"PARTIAL: required OK, optional missing: {missing_optional}")
    else:
        print("OK: all fields extracted")

    # --- PLP probe (optional) ---
    if args.probe_plp:
        print(f"\n\nFetching PLP: {DEFAULT_PLP}")
        plp_html = fetch_rendered(DEFAULT_PLP, api_key)
        print(f"Got {len(plp_html):,} chars")
        plp_blocks = extract_jsonld_blocks(plp_html)
        print(f"JSON-LD blocks: {len(plp_blocks)} ({[b.get('@type') for b in plp_blocks]})")
        pdp_urls = find_item_list_urls(plp_blocks)
        print(f"PDP URLs found in ItemList: {len(pdp_urls)}")
        for u in pdp_urls[:5]:
            print(f"  {u}")


if __name__ == "__main__":
    main()
