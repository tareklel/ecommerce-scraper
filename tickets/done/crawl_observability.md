# Ticket: Crawl Run Observability — `crawl_manifest_raw` Athena Table

**Status: implemented — pending deploy**

## Checklist

### Implemented
- [x] Lambda: write markers to `crawls/markers/{site}/{dt}/{run_id}/`
- [x] Lambda: write verified manifest with verification block to `crawls/manifests/{site}/{dt}/{run_id}/data.json`
- [x] Lambda: append `verification.outcome`, `verification.failure_reason`, `verification.verified_at` to manifest
- [x] Lambda: register Glue partitions for both crawl data table and `crawl_manifest_raw` on `_SUCCESS`
- [x] `lambda.tf`: S3 notification filter prefix → `bronze/{env}/crawls/markers/`
- [x] `iam.tf`: `glue:CreatePartition` already present — no change needed
- [x] scraper-pipeline: `crawl_manifest_raw` external table DDL (`sql/athena/bronze_crawl_manifest_raw.sql`)
- [x] scraper-pipeline: `silver_crawl_manifest` dbt model (`dbt/models/silver/silver_crawl_manifest.sql`)
- [x] `scripts/backfill_manifests.py`: one-time historical backfill script
- [x] Decision: Option B (dedicated directories per file type)
- [x] Decision: clean break — `metadata/` writes removed, backfill script covers historical data
- [x] Decision: scraper-pipeline owns `crawl_manifest_raw` Glue table

### Pending (deploy steps)
- [ ] `make tf-apply` in ecommerce-scraper to update Lambda and S3 notification filter
- [ ] `make athena-ddl DDL_FILE=sql/athena/bronze_crawl_manifest_raw.sql` in scraper-pipeline (dev then prod)
- [ ] Run `scripts/backfill_manifests.py --env prod` to backfill historical manifests
- [ ] `make dbt-run` in scraper-pipeline to build `silver_crawl_manifest`

### Out of Scope (future tickets)
- [ ] `crawl_quality_raw` Athena table from `quality_report.json`
- [ ] Alerting on failed crawls (CloudWatch alarm or SNS)

## Goal

Replace manual S3 browsing with a queryable Athena table that surfaces crawl run
outcomes over time. Every crawl run produces a manifest — this ticket makes that
data accessible as a table so trends, failures, and row counts are queryable
without opening individual S3 directories.

---

## Current S3 Layout

```
bronze/{env}/crawls/{site}/{dt}/{run_id}/
  {site}.jsonl.gz                        ← crawl data — Athena reads this today

bronze/{env}/crawls/metadata/{site}/{dt}/{run_id}/
  manifest.json
  quality_report.json
  _SUCCESS  |  _FAILED  |  _FAIL_QUALITY  ← markers block Athena from reading this dir
```

**Problem:** markers and data files share the same directory. Athena cannot be
pointed at `metadata/` because it would try to parse `_SUCCESS` as JSON.

---

## Final S3 Layout (Option B, implemented)

```
bronze/{env}/crawls/{site}/{dt}/{run_id}/
  {site}.jsonl.gz                        ← crawl data — unchanged

bronze/{env}/crawls/metadata/{site}/{dt}/{run_id}/
  manifest.json                          ← crawl writer still writes here (Lambda trigger)
  quality_report.json                    ← crawl writer still writes here

bronze/{env}/crawls/manifests/{site}/{dt}/{run_id}/
  data.json                              ← verified manifest + verification block (written by Lambda)

bronze/{env}/crawls/markers/{site}/{dt}/{run_id}/
  _SUCCESS  |  _FAILED  |  _FAIL_QUALITY ← written by Lambda (triggers partition registration)

bronze/{env}/crawls/quality_reports/{site}/{dt}/{run_id}/
  data.json                              ← future (crawl_quality_raw ticket)
```

`crawl_manifest_raw` points at `bronze/{env}/crawls/manifests/`.
`metadata/` is still written by the crawl writer (Lambda trigger path unchanged) but is no longer
the Athena-readable location.

---

## Option A vs Option B — File Co-location

### Option A: Leave manifest + quality_report together in `metadata/` (simpler)

Point `crawl_manifest_raw` at `bronze/crawls/metadata/`. Athena reads both
`manifest.json` and `quality_report.json`. With `raw_json STRING` column, both
become rows in the same table. dbt distinguishes them by checking for fields
that only exist in one type (e.g. `json_extract_scalar(raw_json, '$.run_id') IS NOT NULL`).

**Pros:** No Lambda changes beyond marker path.  
**Cons:** Two unrelated schemas mixed in one table. dbt filtering is a smell.

### Option B: Dedicated directories per file type (recommended)

Lambda writes each file to its own top-level dir:

```
bronze/{env}/crawls/manifests/{site}/{dt}/{run_id}/data.json
bronze/{env}/crawls/quality_reports/{site}/{dt}/{run_id}/data.json
```

`crawl_manifest_raw` points at `bronze/{env}/crawls/manifests/`. Clean, one schema per table.
Future `crawl_quality_raw` table points at `bronze/{env}/crawls/quality_reports/`.

**Pros:** Clean separation. Each table has one schema.  
**Cons:** Small Lambda change — write to new paths in addition to (or instead of) `metadata/`.

**Recommendation: Option B.** The Lambda change is minimal and avoids a mixed-schema
table that produces confusing NULL patterns in dbt.

---

## manifest.json — Verification Result

After writing the marker, Lambda updates `manifest.json` to append a
`verification` block:

```json
{
  "...existing fields...": "...",
  "verification": {
    "verified_at": "2026-05-18T14:13:42Z",
    "outcome": "SUCCESS",
    "failure_reason": null
  }
}
```

**Why not store this in the marker only?** The marker is a trigger artifact —
it fires downstream jobs. `manifest.json` is the data record. Querying the Athena
table should return full context in one row without joining to S3 object metadata
or Lambda logs to learn why a run failed.

`failure_reason` captures the human-readable explanation (e.g. `"hash_mismatch"`,
`"quality_gate_blank_threshold_exceeded"`) — the marker filename only gives you
pass/fail, not why.

---

## `crawl_manifest_raw` Athena Table

One row per crawl run. Schema is intentionally minimal — raw JSON stored as a
string so the table never breaks when manifest fields are added or removed.
All parsing and column extraction handled downstream in scraper-pipeline dbt.

```sql
CREATE EXTERNAL TABLE crawl_manifest_raw (
  raw_json STRING
)
PARTITIONED BY (env STRING, site STRING, dt STRING)
ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
WITH SERDEPROPERTIES ('serialization.format' = '1')
STORED AS INPUTFORMAT 'org.apache.hadoop.mapred.TextInputFormat'
OUTPUTFORMAT 'org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat'
LOCATION 's3://price-comparison-bucket-eu-central-1/bronze/{env}/crawls/manifests/'
TBLPROPERTIES ('classification' = 'json');
```

Partition registered by Lambda on each crawl run (same pattern as image pipeline).

**dbt (scraper-pipeline) extracts columns from `raw_json`:**
```sql
-- example staging model
select
  json_extract_scalar(raw_json, '$.run_id')              as run_id,
  json_extract_scalar(raw_json, '$.site')                as site,
  json_extract_scalar(raw_json, '$.env')                 as env,
  json_extract_scalar(raw_json, '$.row_count')           as row_count,
  json_extract_scalar(raw_json, '$.verification.outcome') as outcome,
  json_extract_scalar(raw_json, '$.verification.failure_reason') as failure_reason,
  json_extract_scalar(raw_json, '$.verification.verified_at')    as verified_at,
  dt
from {{ source('bronze', 'crawl_manifest_raw') }}
```
name dbt 'silver_crawl_manifest'

---

## Lambda Changes (`lambda/bronze_manifest_verifier/handler.py`)

1. **Write markers to new path:**
   `bronze/{env}/crawls/markers/{site}/{dt}/{run_id}/_SUCCESS`
   instead of `bronze/{env}/crawls/metadata/{site}/{dt}/{run_id}/_SUCCESS`

2. **Write manifest to dedicated dir:**
   `bronze/{env}/crawls/manifests/{site}/{dt}/{run_id}/data.json`
   (in addition to or replacing the existing metadata path write)

3. **Append verification block to manifest before writing:**
   Add `verified_at`, `outcome`, `failure_reason` fields.

4. **Register Glue partition** for `crawl_manifest_raw` on success:
   `ALTER TABLE crawl_manifest_raw ADD IF NOT EXISTS PARTITION (env=..., site=..., dt=...)`
   (or direct `glue.create_partition()` — use Glue API directly, same as image pipeline fix)

5. **S3 notification filter update** in Terraform:
   Lambda trigger filter changes from `bronze/{env}/crawls/metadata/` to `bronze/{env}/crawls/markers/`

---

## Infrastructure Changes

| File | Change |
|------|--------|
| `lambda/bronze_manifest_verifier/handler.py` | Marker path → `crawls/markers/`, manifest write → `crawls/manifests/`, verification block, dual Glue partition registration |
| `infra/terraform/lambda.tf` | S3 notification filter prefix → `bronze/{env}/crawls/markers/` |
| `infra/terraform/iam.tf` | No change — `glue:CreatePartition` with `Resource = "*"` already present |
| `scraper-pipeline/sql/athena/bronze_crawl_manifest_raw.sql` | New DDL for `crawl_manifest_raw` external table |
| `scraper-pipeline/dbt/models/silver/silver_crawl_manifest.sql` | New silver model extracting columns from `raw_json` |
| `scripts/backfill_manifests.py` | One-time backfill script for historical manifests |

---

## Out of Scope (Future Ticket)

- `crawl_quality_raw` Athena table from `quality_report.json` — same pattern,
  more complex schema. Deferred until `crawl_manifest_raw` is stable.
- Alerting on failed crawls (CloudWatch alarm or SNS on Lambda error).

---

## One-Time Backfill (Clean Break)

`metadata/` files are not deleted — they stay in S3. But `crawl_manifest_raw` points at
`manifests/`, so any run written before the cutover is invisible to the table.

A one-time backfill script copies historical manifests into the new path and registers
the Glue partitions so the table has continuous history from day one.

**What the script does:**

1. List all objects matching `bronze/{env}/crawls/metadata/{site}/{dt}/{run_id}/manifest.json`
2. Copy each to `bronze/{env}/crawls/manifests/{site}/{dt}/{run_id}/data.json`
3. Register a Glue partition for each `(env, site, dt)` triple

**Caveat:** historical manifests pre-date the verification block, so `outcome`,
`failure_reason`, and `verified_at` will be NULL for all backfilled rows. This is
correct — outcomes were not recorded at the time. Filter with `WHERE verified_at IS NOT NULL`
when you need verified-only data.

**Script location:** `scripts/backfill_manifests.py` (to be written as part of this ticket)

---

## Open Questions

- [x] Should `metadata/` dir be kept as-is for backwards compatibility, or fully
      replaced by the new paths? → **Clean break.** See One-Time Backfill above.
- [x] Who owns the `crawl_manifest_raw` Glue table — this repo or scraper-pipeline? → **scraper-pipeline**, use `make` in that repo to create it.

## From Tarik
Make sure crawl_manifest_raw and silver_crawl_manifest dbt are written to scraper-pipeline
