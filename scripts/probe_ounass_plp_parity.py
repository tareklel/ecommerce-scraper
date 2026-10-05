"""
Ounass PLP-vs-PDP parity probe (Phase 0 of tickets/ounass_plp_efficient_crawl.md).

For a mixed sample of products on one PLP, fetch each product's PDP in the
same run and compare what the PDP extractor records (ounass_rules.get_data)
against every candidate key on the PLP hit, for portal_itemid, price,
price_discount and primary_label. The winning PLP keys become the PLP-extract
implementation.

Usage:
    export ZYTE_API_KEY=<key>
    .venv/bin/python scripts/probe_ounass_plp_parity.py \
        --plp-url https://saudi.ounass.com/api/women/bags --pages 2 --per-bucket 4

Outputs (under output/, which is gitignored, so real product data is never committed):
    rows.csv     one row per sampled product: PDP value, each PLP candidate, match flags
    summary.csv  match rate per field x PLP candidate key
    raw/         PLP page JSON and PDP state JSON, for building synthetic test fixtures
"""

import argparse
import base64
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from scrapy.http import HtmlResponse

# Allow `python scripts/...` from the repo root without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ecommercecrawl.constants import ounass_constants as constants  # noqa: E402
from ecommercecrawl.rules import ounass_rules as rules  # noqa: E402

ZYTE_API_URL = "https://api.zyte.com/v1/extract"

# Buckets make sure the sample covers the cases where PLP and PDP are most
# likely to disagree, not just whatever sits at the top of page 0.
BUCKETS = [
    "sale",
    "private_sale",
    "multi_label",
    "labelled",
    "multi_price_sizes",
    "marketplace",
    "full_price_unlabelled",
]

# Candidate PLP keys per output field. Each entry is (column name, getter).
ID_CANDIDATES = {
    "visibleSku": lambda h: h.get("visibleSku"),
    "sku": lambda h: h.get("sku"),
    "productId": lambda h: h.get("productId"),
    "parentSku": lambda h: h.get("parentSku"),
}
PRICE_CANDIDATES = {
    "price": lambda h: h.get("price"),
    "priceByCustomerGroupId[-1]": lambda h: (h.get("priceByCustomerGroupId") or {}).get("-1"),
    "priceBySaleId[-1]": lambda h: (h.get("priceBySaleId") or {}).get("-1"),
    "minPrice": lambda h: h.get("minPrice"),
    "specialPrice": lambda h: h.get("specialPrice"),
    "initialPrice": lambda h: h.get("initialPrice"),
}
DISCOUNT_CANDIDATES = {
    "discountPercentBySaleId[-1]": lambda h: (h.get("discountPercentBySaleId") or {}).get("-1"),
    "discountPercentByCustomerGroupId[-1]": lambda h: (h.get("discountPercentByCustomerGroupId") or {}).get("-1"),
    "discountPercentRounded": lambda h: h.get("discountPercentRounded"),
}


def _badges(hit):
    return [b for b in (hit.get("badges") or []) if isinstance(b, dict) and b.get("value")]


def _clean_label(value):
    # Same whitespace normalisation as ounass_rules.get_primary_label.
    if not isinstance(value, str):
        return None
    label = " ".join(value.split()).strip()
    return label or None


LABEL_CANDIDATES = {
    "badges[highest priority]": lambda h: _clean_label(
        max(_badges(h), key=lambda b: b.get("priority") or 0)["value"]) if _badges(h) else None,
    "badges[lowest priority]": lambda h: _clean_label(
        min(_badges(h), key=lambda b: b.get("priority") or 0)["value"]) if _badges(h) else None,
    "badges[first]": lambda h: _clean_label(_badges(h)[0]["value"]) if _badges(h) else None,
}


def fetch(url, api_key, timeout=90, attempts=3):
    """Fetch via Zyte httpResponseBody, the same request type the Ounass spider uses.

    Retries Zyte's temporary errors (429 / 5xx such as 520), which the spider's
    scrapy-zyte-api middleware also retries, so the probe doesn't lose samples to them.
    """
    for attempt in range(1, attempts + 1):
        resp = requests.post(
            ZYTE_API_URL,
            auth=(api_key, ""),
            json={"url": url, "httpResponseBody": True},
            timeout=timeout,
        )
        if (resp.status_code == 429 or resp.status_code >= 500) and attempt < attempts:
            time.sleep(2 * attempt)
            continue
        resp.raise_for_status()
        return base64.b64decode(resp.json().get("httpResponseBody", ""))


def plp_page_url(plp_url, page):
    # Same sorted pagination the spider requests (see OunassSpider.get_pages).
    base = plp_url.split("?", 1)[0]
    return f"{base}?{constants.PLPSORT_KEY}={constants.PLPSORT}&p={page}"


def classify(hit):
    buckets = []
    badges = _badges(hit)
    size_prices = {s.get("price") for s in (hit.get("sizesById") or {}).values() if isinstance(s, dict)}
    if hit.get("discounted") == "yes":
        buckets.append("sale")
    if hit.get("privateSalePrice") is not None:
        buckets.append("private_sale")
    if len(badges) >= 2:
        buckets.append("multi_label")
    if len(badges) >= 1:
        buckets.append("labelled")
    if len(size_prices) > 1:
        buckets.append("multi_price_sizes")
    if hit.get("isMarketplaceItem") == "yes":
        buckets.append("marketplace")
    if hit.get("discounted") != "yes" and not badges:
        buckets.append("full_price_unlabelled")
    return buckets


def select_sample(hits, per_bucket, max_total):
    """Take up to per_bucket hits per bucket, rarest buckets first, deduped by slug."""
    by_bucket = {b: [] for b in BUCKETS}
    for hit in hits:
        for b in classify(hit):
            by_bucket[b].append(hit)
    chosen, seen = [], set()
    for bucket in sorted(BUCKETS, key=lambda b: len(by_bucket[b])):
        taken = 0
        for hit in by_bucket[bucket]:
            slug = hit.get("slug")
            if not slug or slug in seen or taken >= per_bucket or len(chosen) >= max_total:
                continue
            seen.add(slug)
            chosen.append(hit)
            taken += 1
    return chosen, {b: len(v) for b, v in by_bucket.items()}


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def price_equal(a, b):
    a, b = _num(a), _num(b)
    return a is not None and b is not None and abs(a - b) < 0.01


def discount_equal(pdp_value, plp_value):
    # PDP records None for full-price items while the PLP says "0"; both mean no discount.
    a, b = _num(pdp_value) or 0.0, _num(plp_value) or 0.0
    return abs(a - b) < 0.01


def label_equal(pdp_labels, plp_label):
    pdp_label = pdp_labels[0] if pdp_labels else None
    return pdp_label == plp_label


def build_row(hit, pdp_url, pdp_data, pdp_error):
    row = {
        "slug": hit.get("slug"),
        "pdp_url": pdp_url,
        "buckets": ";".join(classify(hit)),
        "pdp_error": pdp_error or "",
        "plp_name": hit.get("name"),
        "plp_discountText": hit.get("discountText"),
        "plp_badges_all": json.dumps(
            [{"value": b.get("value"), "priority": b.get("priority")} for b in _badges(hit)],
            ensure_ascii=False,
        ),
    }
    pdp = pdp_data or {}
    row["pdp_portal_itemid"] = pdp.get("portal_itemid")
    row["pdp_price"] = pdp.get("price")
    row["pdp_price_discount"] = pdp.get("price_discount")
    row["pdp_was_price"] = pdp.get("was_price")
    row["pdp_primary_label"] = json.dumps(pdp.get("primary_label"), ensure_ascii=False)

    comparable = pdp_data is not None
    for name, get in ID_CANDIDATES.items():
        value = get(hit)
        row[f"plp_id::{name}"] = value
        row[f"match_id::{name}"] = (str(value) == str(pdp.get("portal_itemid"))) if comparable else ""
    for name, get in PRICE_CANDIDATES.items():
        value = get(hit)
        row[f"plp_price::{name}"] = value
        row[f"match_price::{name}"] = price_equal(pdp.get("price"), value) if comparable else ""
    for name, get in DISCOUNT_CANDIDATES.items():
        value = get(hit)
        row[f"plp_discount::{name}"] = value
        row[f"match_discount::{name}"] = discount_equal(pdp.get("price_discount"), value) if comparable else ""
    for name, get in LABEL_CANDIDATES.items():
        value = get(hit)
        row[f"plp_label::{name}"] = value
        row[f"match_label::{name}"] = label_equal(pdp.get("primary_label"), value) if comparable else ""
    return row


def summarise(rows):
    summary = []
    compared = [r for r in rows if not r["pdp_error"]]
    for field, candidates in (
        ("id", ID_CANDIDATES),
        ("price", PRICE_CANDIDATES),
        ("discount", DISCOUNT_CANDIDATES),
        ("label", LABEL_CANDIDATES),
    ):
        for name in candidates:
            matches = sum(1 for r in compared if r[f"match_{field}::{name}"] is True)
            summary.append({
                "field": field,
                "plp_candidate": name,
                "compared": len(compared),
                "matched": matches,
                "match_rate": round(matches / len(compared), 3) if compared else "",
            })
    return summary


def write_csv(path, rows):
    if not rows:
        return
    # utf-8-sig so Excel opens Arabic text correctly.
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plp-url", default="https://saudi.ounass.com/api/women/bags")
    parser.add_argument("--pages", type=int, default=2, help="PLP pages to sample hits from")
    parser.add_argument("--per-bucket", type=int, default=4)
    parser.add_argument("--max-total", type=int, default=30, help="hard cap on PDP requests")
    parser.add_argument("--out-dir", default="output/probes/ounass_plp_parity")
    args = parser.parse_args()

    api_key = os.environ.get("ZYTE_API_KEY", "").strip()
    if not api_key:
        sys.exit("ZYTE_API_KEY is not set.")

    run_dir = Path(args.out_dir) / datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    raw_dir = run_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    requests_made = 0

    hits = []
    for page in range(args.pages):
        url = plp_page_url(args.plp_url, page)
        body = fetch(url, api_key)
        requests_made += 1
        (raw_dir / f"plp_p{page}.json").write_bytes(body)
        hits.extend(json.loads(body).get("hits", []))
    print(f"PLP: {len(hits)} hits from {args.pages} page(s)")

    sample, bucket_sizes = select_sample(hits, args.per_bucket, args.max_total)
    print("Bucket sizes on sampled pages:", bucket_sizes)
    print(f"Sampling {len(sample)} products; fetching their PDPs")

    parsed = urlparse(args.plp_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    rows = []
    for i, hit in enumerate(sample, 1):
        pdp_url = f"{base}/{hit['slug']}.html"
        pdp_data, pdp_error = None, None
        try:
            body = fetch(pdp_url, api_key)
            requests_made += 1
            response = HtmlResponse(url=pdp_url, body=body, encoding="utf-8")
            state = rules.get_state(response)
            if state is None:
                pdp_error = "no inline state in PDP"
            else:
                (raw_dir / f"pdp_{hit.get('visibleSku') or i}.json").write_text(
                    json.dumps(state.get("pdp", {}), ensure_ascii=False), encoding="utf-8"
                )
                pdp_data = rules.get_data(state)
        except Exception as e:  # keep going; one bad PDP shouldn't sink the probe
            pdp_error = f"{type(e).__name__}: {e}"
        rows.append(build_row(hit, pdp_url, pdp_data, pdp_error))
        print(f"  [{i}/{len(sample)}] {'ERR ' + pdp_error if pdp_error else 'ok'}  {pdp_url}")

    write_csv(run_dir / "rows.csv", rows)
    summary = summarise(rows)
    write_csv(run_dir / "summary.csv", summary)

    print(f"\nZyte requests made: {requests_made}")
    print(f"Wrote {run_dir / 'rows.csv'} and {run_dir / 'summary.csv'}\n")
    for s in summary:
        print(f"  {s['field']:<9} {s['plp_candidate']:<40} {s['matched']}/{s['compared']}")


if __name__ == "__main__":
    main()
