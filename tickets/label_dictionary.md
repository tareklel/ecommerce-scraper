# Ticket: Label Dictionary Export

**Status: draft — not reviewed**

## Goal

Generate a small JSON file mapping canonical identifiers to their localised display
names in Arabic and English, and upload it to S3 alongside the gold export.
The frontend filter dropdowns read this file at startup to show Arabic brand,
category, and subcategory names instead of canonical English keys.

---

## Background

The product API filter endpoint returns canonical keys — `toteme`, `bags`,
`clutches`. The frontend needs to display these as `TOTEME`, `حقائب`, `مقبضات`.
The gold table already contains all three canonical→label pairs per product per language:

| Canonical field | Label field | Example canonical | Example AR label |
|---|---|---|---|
| `brand_canonical` | `language_brand` | `toteme` | `توتيم` |
| `category_canonical` | `language_category` | `bags` | `حقائب` |
| `sub_category_canonical` | `language_subcategory` | `clutches` | `مقبضات` |

All three must be included in the dictionary — the filter bar has separate dropdowns
for brand, category, and subcategory, and all three show canonical keys today.

A static dict file is the right pattern here:
- It is tiny (typically < 50 KB for a luxury catalogue)
- It can be served from the existing CloudFront CDN with a long TTL
- It is regenerated automatically each time the gold table is refreshed
- The frontend fetches it once at startup — no per-request cost

---

## Output

| Environment | S3 key | CloudFront path |
|-------------|--------|-----------------|
| dev  | `api-cache/dev/products/label_dict.json`  | `/api-cache/dev/products/label_dict.json`  |
| prod | `api-cache/prod/products/label_dict.json` | `/api-cache/prod/products/label_dict.json` |

JSON shape:

```json
{
  "brands": {
    "toteme":    { "en": "TOTEME",   "ar": "توتيم"   },
    "valentino": { "en": "Valentino","ar": "فالنتينو" }
  },
  "categories": {
    "bags":  { "en": "Bags",  "ar": "حقائب" },
    "shoes": { "en": "Shoes", "ar": "أحذية" }
  },
  "subcategories": {
    "clutches":  { "en": "Clutches",  "ar": "مقبضات" },
    "sneakers":  { "en": "Sneakers",  "ar": "أحذية رياضية" }
  }
}
```

For any brand whose Arabic name is identical to its English name (e.g. transliterated
luxury brands that choose not to localise), both `en` and `ar` carry the same string.

---

## Implementation

### Where to add it

Extend the existing gold export Lambda (the one that writes
`api-cache/{env}/products/gold_product_serving_latest.json.gz`). After it finishes
writing the product file, it derives and uploads `label_dict.json` from the same
in-memory dataset — no second Athena query needed.

### Derivation logic (Python)

```python
import json, io
from collections import defaultdict

def build_label_dict(products: list[dict]) -> dict:
    """
    products: the list already loaded from the gold table (one row per product
    per language, i.e. the same data that goes into the .json.gz export).
    """
    brands = defaultdict(dict)
    categories = defaultdict(dict)
    subcategories = defaultdict(dict)

    for p in products:
        lang = p.get("language")          # "ar" or "en"
        if not lang:
            continue

        bc = p.get("brand_canonical")
        lb = p.get("language_brand")
        if bc and lb:
            brands[bc][lang] = lb

        cc = p.get("category_canonical")
        lc = p.get("language_category")
        if cc and lc:
            categories[cc][lang] = lc

        sc = p.get("sub_category_canonical")
        ls = p.get("language_subcategory")
        if sc and ls:
            subcategories[sc][lang] = ls

    return {
        "brands":        dict(brands),
        "categories":    dict(categories),
        "subcategories": dict(subcategories),
    }


def upload_label_dict(s3, bucket: str, key: str, label_dict: dict) -> None:
    body = json.dumps(label_dict, ensure_ascii=False, indent=2).encode("utf-8")
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType="application/json",
        CacheControl="public, max-age=3600",   # 1 h — same cadence as gold refresh
    )
```

Call `build_label_dict` right after the gold dataset is loaded into memory, then
`upload_label_dict` before the Lambda exits. No new IAM permissions needed — the
Lambda already has `s3:PutObject` on `api-cache/`.

### S3 key

```python
label_key = f"api-cache/{app_env}/products/label_dict.json"
```

---

## Files to Change

| File | Change |
|------|--------|
| `lambda/gold_export/handler.py` (or equivalent) | Add `build_label_dict` + `upload_label_dict` call after product write |

---

## Acceptance Criteria

- After a gold export run, `label_dict.json` appears next to `gold_product_serving_latest.json.gz` in S3.
- The file contains entries for every brand, category, and subcategory present in the gold table.
- Both `"en"` and `"ar"` keys are present for every entry (no half-populated entries).
- File is valid JSON, `Content-Type: application/json`, `Cache-Control: public, max-age=3600`.
- No new IAM roles or Terraform resources required.

---

## Depends On

- Gold export Lambda already writing to `api-cache/{env}/products/` (done for dev).

## Blocks

- `price-comparison-web/tickets/i18n_copy.md` — frontend filter labels wait on this file.
