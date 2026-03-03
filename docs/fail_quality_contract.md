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

Current hard-fail rule:
- `field_blankness_threshold`: fail if any non-exempt field is blank in `>= blank_threshold` ratio of rows for a site.

## Parameters

- `blank_threshold` (default `0.8`)
  - Example: `0.8` means a field is a violation when 80% or more of rows are blank.
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
