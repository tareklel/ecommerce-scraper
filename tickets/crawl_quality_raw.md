# Ticket: Crawl Quality Observability — `crawl_quality_raw` Athena Table

**Status: draft**

## Goal

Surface per-crawl quality gate results in Athena. Every crawl run that passes through
the quality gate produces a `quality_report.json`. This ticket makes that data queryable
as a table so blank-field violations, thresholds, and gate outcomes are inspectable
over time without opening individual S3 files.

Prerequisite: `crawl_manifest_raw` is stable (done — see `tickets/done/crawl_observability.md`).

---

## quality_report.json Schema

Written by `PostCrawlPipeline` to `metadata/{site}/{dt}/{run_id}/quality_report.json`.

```json
{
  "status": "pass | fail_quality | error",
  "event_time_utc": "2026-06-03T10:44:18Z",
  "rule_set": "v1_blank_field_threshold",
  "reason": "blank_field_threshold_breach | all_rules_passed | quality_gate_execution_error",
  "total_rows": 1234,
  "blank_threshold": 0.1,
  "min_rows_for_blank_check": 10,
  "violations_count": 2,
  "input_jsonl_path": "output/ounass.jsonl.gz",
  "sites": {
    "ounass": {
      "row_count": 1234,
      "blank_rule_checked": true,
      "blank_rule_skipped_reason": null,
      "exceptions": ["text"],
      "checked_fields": 18,
      "violations": [
        {
          "rule": "field_blankness_threshold",
          "field": "brand",
          "blank_count": 200,
          "row_count": 1234,
          "blank_ratio": 0.162,
          "threshold": 0.1
        }
      ]
    }
  }
}
```

**Note:** `sites` is a nested map (one key per site, with a `violations` array inside).
The `raw_json` wrapper approach handles this without requiring a complex DDL — downstream
models use `json_extract` for summary fields and can unnest violations via `json_parse`
if needed.

---

## S3 Target Path

```
bronze/{env}/crawls/quality_reports/{site}/{dt}/{run_id}/data.json
```

Written by Lambda as:
```json
{"run_id": "...", "raw_json": "{...full quality_report.json content...}"}
```

Same wrapper pattern as `crawl_manifest_raw`.

---

## Lambda Changes (`lambda/bronze_manifest_verifier/handler.py`)

The Lambda already reads `manifest.json` (which contains `run_id`). It also has access
to the `metadata/` prefix where `quality_report.json` lives alongside the manifest.

Add to `_verify_manifest_and_write_success`:

1. **Read `quality_report.json`** from `metadata/{site}/{dt}/{run_id}/quality_report.json`
2. **Write wrapper** to `bronze/{env}/crawls/quality_reports/{site}/{dt}/{run_id}/data.json`:
   ```json
   {"run_id": "<from manifest>", "raw_json": "<quality_report.json content>"}
   ```
3. **Register Glue partition** for `crawl_quality_raw (site, dt)` — same trigger point
   as `crawl_manifest_raw`, inside `_register_bronze_partition`.

Write happens on every verification pass (success, fail_quality, failed) so all outcomes
are queryable. If `quality_report.json` is missing (e.g. quality gate errored before write),
log a warning and skip — do not fail verification.

---

## `crawl_quality_raw` Athena Table (scraper-pipeline)

DDL at `sql/athena/bronze_crawl_quality_raw.sql`:

```sql
CREATE EXTERNAL TABLE IF NOT EXISTS __BRONZE_DATABASE__.crawl_quality_raw (
  run_id   string,
  raw_json string
)
PARTITIONED BY (
  site string,
  dt   string
)
ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
WITH SERDEPROPERTIES ('serialization.format' = '1')
LOCATION '__BRONZE_PREFIX__/crawls/quality_reports/';
```

---

## `silver_crawl_quality` dbt Model (scraper-pipeline)

Extracts summary fields. `sites` and `violations` are left in `raw_json` for ad-hoc
`json_extract` rather than unnested — violations are sparse and multi-row unnesting
in Athena/dbt is verbose.

```sql
select
  run_id,
  json_extract_scalar(raw_json, '$.status')              as status,
  json_extract_scalar(raw_json, '$.event_time_utc')      as event_time_utc,
  json_extract_scalar(raw_json, '$.reason')              as reason,
  cast(json_extract_scalar(raw_json, '$.total_rows') as bigint)       as total_rows,
  cast(json_extract_scalar(raw_json, '$.violations_count') as bigint) as violations_count,
  cast(json_extract_scalar(raw_json, '$.blank_threshold') as double)  as blank_threshold,
  raw_json,
  site,
  dt
from {{ bronze_relation('crawl_quality_raw') }}
```

Partitioned by `(site, dt)`. Incremental insert_overwrite.

---

## Backfill

Extend `scripts/backfill_manifests.py` (or write a sibling `backfill_quality_reports.py`)
to copy historical `metadata/{site}/{dt}/{run_id}/quality_report.json` →
`quality_reports/{site}/{dt}/{run_id}/data.json` as wrapper JSON and register partitions.

---

## Work Items

| File | Change |
|------|--------|
| `lambda/bronze_manifest_verifier/handler.py` | Read quality_report.json, write wrapper to quality_reports/, register crawl_quality_raw partition |
| `scraper-pipeline/sql/athena/bronze_crawl_quality_raw.sql` | New DDL |
| `scraper-pipeline/dbt/models/silver/silver_crawl_quality.sql` | New silver model |
| `scraper-pipeline/dbt/models/schema.yml` | Add silver_crawl_quality entry |
| `scripts/backfill_quality_reports.py` | One-time historical backfill |

---

## Open Questions

- [ ] Should violations be unnested into a separate `silver_crawl_quality_violations` model
      (one row per violation per run) for easier field-level trend analysis?
- [ ] Alerting on `violations_count > 0` or `status = 'fail_quality'` — CloudWatch metric
      filter on Lambda logs, or SNS? (also applies to `crawl_manifest_raw` failures)
