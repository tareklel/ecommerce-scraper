"""
Bloomingdales.sa feasibility probe.

Probe results (2026-07-15): all 6/6 checks pass.
- Platform: Salesforce Commerce Cloud (SFCC). No Zyte needed.
- Language: bloomingdales.sa=AR, en.bloomingdales.sa=EN (subdomain-based).
- PLP: SSR HTML with 48 products + Search-UpdateGrid API for pagination.
- PDP: JSON-LD @type=Product with name/brand/price/currency/availability/images.
- Category from DOM microdata breadcrumbs (position 3 = category, 4 = subcategory).

Usage:
    python scripts/probe_bloomingdales.py
    python scripts/probe_bloomingdales.py --save-fixtures   # write HTML to tests/fixtures/
    python scripts/probe_bloomingdales.py --plp-url URL --pdp-url URL
    python scripts/probe_bloomingdales.py --en   # probe EN subdomain
"""

import argparse
import json
import os
import re
import sys
import unicodedata
from urllib.parse import urlparse, parse_qs

import requests

DEFAULT_PLP_AR = "https://bloomingdales.sa/womens-bags-cross-body-bags/"
DEFAULT_PLP_EN = "https://en.bloomingdales.sa/womens-bags-cross-body-bags/"
DEFAULT_PDP_AR = "https://bloomingdales.sa/marc-jacobs-%D8%AD%D9%82%D9%8A%D8%A9-%D9%85%D9%83%D9%8A%D8%A7%D8%AC-%D8%B3%D9%8A%D9%86-BAG219542223xBLK.html"
DEFAULT_PDP_EN = "https://en.bloomingdales.sa/marc-jacobs-scene-vanity-bag-BAG219542223xBLK.html"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

HEADERS_AR = {
    **HEADERS,
    "Accept-Language": "ar,en;q=0.5",
}


def fetch(url: str, headers: dict = HEADERS, timeout: int = 20) -> requests.Response:
    resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    return resp


def extract_jsonld(html: str) -> list[dict]:
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


def find_product(blocks: list[dict]) -> dict | None:
    for b in blocks:
        t = b.get("@type", "")
        if t in ("Product", "ProductGroup"):
            return b
    return None


def find_breadcrumbs(blocks: list[dict]) -> list[dict]:
    for b in blocks:
        if b.get("@type") == "BreadcrumbList":
            return b.get("itemListElement", [])
    return []


def extract_pdp_links(html: str, base_url: str) -> list[str]:
    """Extract product PDP URLs from PLP HTML using the PID suffix pattern."""
    base = f"{urlparse(base_url).scheme}://{urlparse(base_url).netloc}"
    # Match URLs ending with -PIDxCOLOR.html (product variant pattern)
    hrefs = re.findall(r'href="(/[^"]*-[A-Z]{2,}\d{5,}x[^"]+\.html)"', html)
    return [f"{base}{h}" for h in dict.fromkeys(hrefs)]


def has_arabic(text: str) -> bool:
    return any(unicodedata.bidirectional(c) in ('AL', 'AN', 'R') for c in text)


def check(label: str, ok: bool, detail: str = ""):
    status = "PASS" if ok else "FAIL"
    line = f"  [{status}] {label}"
    if detail:
        line += f"  ({detail})"
    print(line)
    return ok


def probe_waf(url: str) -> tuple[bool, str]:
    """Return (accessible, detail)."""
    try:
        resp = fetch(url)
        headers_lower = {k.lower(): v for k, v in resp.headers.items()}
        waf = None
        if "cf-ray" in headers_lower:
            waf = "Cloudflare"
        elif any(k.startswith("x-akamai") for k in headers_lower):
            waf = "Akamai"
        elif "x-sucuri-id" in headers_lower:
            waf = "Sucuri"

        accessible = resp.status_code == 200 and len(resp.text) > 5000
        detail = f"HTTP {resp.status_code}, {len(resp.text):,} chars"
        if waf:
            detail += f", WAF: {waf}"
        return accessible, detail, resp.text
    except Exception as e:
        return False, str(e), ""


def probe_plp(url: str) -> tuple[bool, str, list[str], str]:
    """Return (ok, detail, pdp_urls, html)."""
    accessible, detail, html = probe_waf(url)
    if not accessible:
        return False, detail, [], html

    pdp_urls = extract_pdp_links(html, url)

    # Check for JSON-LD on PLP (ItemList)
    blocks = extract_jsonld(html)
    item_list = next((b for b in blocks if b.get("@type") == "ItemList"), None)
    if item_list:
        il_urls = [e.get("url") or (e.get("item") or {}).get("url") for e in item_list.get("itemListElement", [])]
        il_urls = [u for u in il_urls if u]
        if il_urls:
            pdp_urls = il_urls

    # Detect pagination signal
    pagination_signal = None
    if re.search(r'[?&]page=\d', html):
        pagination_signal = "page param"
    elif re.search(r'[?&]offset=\d', html):
        pagination_signal = "offset param"
    elif 'totalPages' in html or 'total_pages' in html:
        pagination_signal = "totalPages in response"

    detail_out = f"{detail}, {len(pdp_urls)} PDP links found"
    if pagination_signal:
        detail_out += f", pagination: {pagination_signal}"

    return bool(pdp_urls), detail_out, pdp_urls, html


def probe_pdp(url: str) -> tuple[bool, str, dict, str]:
    """Return (ok, detail, extracted_fields, html)."""
    accessible, detail, html = probe_waf(url)
    if not accessible:
        return False, detail, {}, html

    blocks = extract_jsonld(html)
    product = find_product(blocks)

    if not product:
        # Check for common framework signals
        signals = []
        if "__NEXT_DATA__" in html:
            signals.append("Next.js __NEXT_DATA__")
        if "window.initialState" in html:
            signals.append("window.initialState")
        if "data-reactroot" in html:
            signals.append("data-reactroot (CSR)")
        return False, f"{detail}, no JSON-LD Product, signals: {signals or 'none'}", {}, html

    breadcrumbs = find_breadcrumbs(blocks)
    crumb_names = {el.get("position"): (el.get("item") or {}).get("name") for el in breadcrumbs}

    offers = product.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}

    images = product.get("image") or []
    if isinstance(images, str):
        images = [images]
    image_urls = [img.get("contentUrl") or img.get("url") if isinstance(img, dict) else img for img in images]
    image_urls = [u for u in image_urls if u]

    extracted = {
        "portal_itemid": product.get("sku") or product.get("productGroupID"),
        "product_name": (product.get("name") or "").strip(),
        "brand": (product.get("brand") or {}).get("name") if isinstance(product.get("brand"), dict) else product.get("brand"),
        "price": offers.get("price"),
        "currency": offers.get("priceCurrency"),
        "out_of_stock": "OutOfStock" in (offers.get("availability") or ""),
        "image_urls": image_urls,
        "category": crumb_names.get(3),
        "subcategory": crumb_names.get(4),
        "color": product.get("color"),
        "description": product.get("description"),
        "n_images": len(image_urls),
        "jsonld_type": product.get("@type"),
    }

    required = ["portal_itemid", "product_name", "brand", "price", "currency", "image_urls"]
    missing = [k for k in required if not extracted.get(k)]

    ok = not missing
    detail_out = f"{detail}, JSON-LD @type={product.get('@type')}"
    if missing:
        detail_out += f", MISSING: {missing}"

    return ok, detail_out, extracted, html


def probe_language(plp_html: str, pdp_html: str, pdp_url: str) -> str:
    """Attempt to identify language mechanism from probed HTML."""
    findings = []

    # Check URL for /en/ or /ar/ path
    path = urlparse(pdp_url).path
    if "/en/" in path or path.startswith("/en"):
        findings.append("URL path: /en/ detected")
    if "/ar/" in path or path.startswith("/ar"):
        findings.append("URL path: /ar/ detected")

    # Check for lang meta tag
    lang_meta = re.search(r'<html[^>]+lang=["\']([^"\']+)["\']', pdp_html, re.I)
    if lang_meta:
        findings.append(f"<html lang='{lang_meta.group(1)}'>")

    # Check for hreflang links (indicates alternate language URLs)
    hreflangs = re.findall(r'hreflang=["\']([^"\']+)["\']', pdp_html, re.I)
    if hreflangs:
        findings.append(f"hreflang values: {hreflangs}")

    # Check for language toggle or cookie pattern in HTML
    if 'lang=ar' in pdp_html.lower() or 'language=ar' in pdp_html.lower():
        findings.append("'lang=ar' found in HTML")

    # Arabic characters in the product name field
    blocks = extract_jsonld(pdp_html)
    product = find_product(blocks)
    if product:
        name = product.get("name", "")
        if has_arabic(name):
            findings.append(f"JSON-LD product.name contains Arabic: '{name[:40]}'")
        else:
            findings.append(f"JSON-LD product.name is Latin: '{name[:40]}'")

    if not findings:
        findings.append("No clear language signal found — likely cookie/session based")

    return "; ".join(findings)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--en", action="store_true", help="Probe English subdomain (en.bloomingdales.sa)")
    parser.add_argument("--plp-url", default=None)
    parser.add_argument("--pdp-url", default=None)
    parser.add_argument("--save-fixtures", action="store_true",
                        help="Save HTML to tests/fixtures/")
    args = parser.parse_args()

    lang = "EN" if args.en else "AR"
    plp_url = args.plp_url or (DEFAULT_PLP_EN if args.en else DEFAULT_PLP_AR)
    pdp_url = args.pdp_url or (DEFAULT_PDP_EN if args.en else DEFAULT_PDP_AR)

    results = []

    # ---- PLP probe ----
    print(f"\n=== PLP Probe [{lang}]: {plp_url} ===")
    plp_ok, plp_detail, pdp_urls, plp_html = probe_plp(plp_url)
    results.append(check("WAF / direct access (PLP)", len(plp_html) > 5000, plp_detail))
    results.append(check("PLP yields ≥1 PDP URL", plp_ok, f"{len(pdp_urls)} URLs"))
    if pdp_urls:
        print(f"    First 3 PDP URLs:")
        for u in pdp_urls[:3]:
            print(f"      {u}")

    # ---- PDP probe ----
    print(f"\n=== PDP Probe [{lang}]: {pdp_url} ===")
    pdp_ok, pdp_detail, fields, pdp_html = probe_pdp(pdp_url)
    results.append(check("WAF / direct access (PDP)", len(pdp_html) > 5000, pdp_detail))
    results.append(check("JSON-LD Product block found", pdp_ok, pdp_detail))
    if fields:
        print("  Extracted fields:")
        for k, v in fields.items():
            print(f"    {k:20s}: {v}")

    # ---- Language probe ----
    print(f"\n=== Language Mechanism ===")
    lang_finding = probe_language(plp_html, pdp_html, pdp_url)
    print(f"  {lang_finding}")
    results.append(check("Language mechanism identified", "No clear" not in lang_finding, lang_finding))

    # ---- SSR check ----
    print(f"\n=== SSR / CSR ===")
    is_ssr = len(pdp_html) > 50_000
    signals = []
    for sig in ("__NEXT_DATA__", "window.initialState", "data-reactroot", "__NUXT__"):
        if sig in pdp_html:
            signals.append(sig)
    results.append(check("SSR (>50KB response)", is_ssr, f"{len(pdp_html):,} chars, signals: {signals or 'none'}"))

    # ---- Summary ----
    passed = sum(results)
    total = len(results)
    print(f"\n=== Result: {passed}/{total} checks passed ===")
    if passed == total:
        print("  Site is ready for implementation. Proceed with tickets/bloomingdales_crawl.md.")
    else:
        print("  Resolve failing checks before implementing the spider.")

    # ---- Save fixtures ----
    if args.save_fixtures:
        os.makedirs("tests/fixtures", exist_ok=True)
        if plp_html:
            with open("tests/fixtures/bloomingdales_plp.html", "w", encoding="utf-8") as f:
                f.write(plp_html)
            print("  Saved: tests/fixtures/bloomingdales_plp.html")
        if pdp_html:
            with open("tests/fixtures/bloomingdales_pdp.html", "w", encoding="utf-8") as f:
                f.write(pdp_html)
            print("  Saved: tests/fixtures/bloomingdales_pdp.html")


if __name__ == "__main__":
    main()
