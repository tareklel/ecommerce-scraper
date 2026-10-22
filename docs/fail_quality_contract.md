# Fail Quality Contract

This contract defines local, stateless quality checks for crawler outputs.

By default, this quality gate runs automatically in `PostCrawlPipeline` when a spider finishes.
It writes `metadata/quality_report.json` inside each crawl output directory and adds a summary under
`quality_gate` in `metadata/manifest.json`.

## Rule Set

Current rule set id:
- `default`

Quality reports include:
- `rule_set`: `default`

Current hard-fail rules (rows are split by `plp_extract_flag` since 2026-10-16):
- `field_blankness_threshold`, **product-page rows** (`plp_extract_flag` not `1`): fail if any non-exempt field is blank in `>= blank_threshold` ratio of a site's product-page rows.
- `plp_extract_required_fields`, **listing-extract rows** (`plp_extract_flag = 1`, Ounass PLP-efficient crawl): every row must have `portal_itemid`, `url`, `price`, `site`, `country`, `language`, with `price > 0` and `url` not a listing URL (no `/api/`, not the `plp_source_url`). One bad row fails the run: the crawler never writes such rows, so one means a bug. These rows leave name, images, category etc. blank on purpose, so the blank-ratio rule doesn't apply to them. Reported under `plp_extract_rows` in the quality report.

A failed gate makes the run `failed / quality` (marker `_FAIL_QUALITY`); see
`docs/crawl_run_status.md` for every status and marker.

## Parameters

- `blank_threshold` (code default `0.8`; **crawls run with `0.2`**, set by `QUALITY_GATE_BLANK_THRESHOLD` in `ecommercecrawl/settings.py`)
  - Example: `0.2` means a field is a violation when 20% or more of rows are blank.
- `min_rows_for_blank_check` (default `20`)
  - Blankness checks are skipped for sites with fewer rows than this value.
  - This avoids overreacting to very small crawl samples.

## Blank value definition

A field is treated as blank when it is:
- missing from a row
- `null`
- empty string or whitespace-only string
- empty list, dict, tuple, or set

## Site exceptions

You can exempt fields by site using `{site: [fields]}`.

Default config location in this repo:
- `resources/quality_gate_exclusions.json`

Example:

```json
{
  "ounass": ["brand_id", "color", "price_discount", "primary_label"],
  "level-shoes": ["level_category_id", "color", "price_discount", "primary_label"]
}
```

Notes:
- Site aliases are normalized (for example `level` and `level_shoes` become `level-shoes`).
- `*` applies to all sites.

## CLI usage

Run locally:

```bash
python3 run_quality_gate.py \
  --input-jsonl output/2026/02/26/2026-02-26T13-51-38-133/metadata/sample_ounass.jsonl \
  --blank-threshold 0.8 \
  --min-rows-for-blank-check 20 \
  --blank-field-exceptions-json '{"ounass":["primary_label"]}'
```

Exit codes:
- `0`: quality checks passed.
- `1`: `FAIL_QUALITY`.
