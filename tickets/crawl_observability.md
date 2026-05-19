# Ticket: Crawl Run Observability — `crawl_manifest_raw` Athena Table

**Status: draft — not reviewed**

## Goal

Replace manual S3 browsing with a queryable Athena table that surfaces crawl run
outcomes over time. Every crawl run produces a manifest — this ticket makes that
data accessible as a table so trends, failures, and row counts are queryable
without opening individual S3 directories.

---

## Current S3 Layout

```
bronze/crawls/{env}/{site}/{dt}/{run_id}/
  {site}.jsonl.gz                        ← crawl data — Athena reads this today

bronze/crawls/metadata/{env}/{site}/{dt}/{run_id}/
  manifest.json
  quality_report.json
  _SUCCESS  |  _FAILED  |  _FAIL_QUALITY  ← markers block Athena from reading this dir
```

**Problem:** markers and data files share the same directory. Athena cannot be
pointed at `metadata/` because it would try to parse `_SUCCESS` as JSON.

---

## Proposed S3 Layout

```
bronze/crawls/{env}/{site}/{dt}/{run_id}/
  {site}.jsonl.gz                        ← unchanged

bronze/crawls/metadata/{env}/{site}/{dt}/{run_id}/
  manifest.json                          ← Athena-readable once markers removed
  quality_report.json

bronze/crawls/markers/{env}/{site}/{dt}/{run_id}/
  _SUCCESS  |  _FAILED  |  _FAIL_QUALITY ← forked to own dir
```

Markers move to `bronze/crawls/markers/`. The `metadata/` directory becomes
Athena-readable with no other changes to the crawl writer.

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
bronze/crawls/manifests/{env}/{site}/{dt}/{run_id}/data.json
bronze/crawls/quality_reports/{env}/{site}/{dt}/{run_id}/data.json
```

`crawl_manifest_raw` points at `bronze/crawls/manifests/`. Clean, one schema per table.
Future `crawl_quality_raw` table points at `bronze/crawls/quality_reports/`.

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
LOCATION 's3://price-comparison-bucket-eu-central-1/bronze/crawls/manifests/'
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

---

## Lambda Changes (`lambda/bronze_manifest_verifier/handler.py`)

1. **Write markers to new path:**
   `bronze/crawls/markers/{env}/{site}/{dt}/{run_id}/_SUCCESS`
   instead of `bronze/crawls/metadata/{env}/{site}/{dt}/{run_id}/_SUCCESS`

2. **Write manifest to dedicated dir:**
   `bronze/crawls/manifests/{env}/{site}/{dt}/{run_id}/data.json`
   (in addition to or replacing the existing metadata path write)

3. **Append verification block to manifest before writing:**
   Add `verified_at`, `outcome`, `failure_reason` fields.

4. **Register Glue partition** for `crawl_manifest_raw` on success:
   `ALTER TABLE crawl_manifest_raw ADD IF NOT EXISTS PARTITION (env=..., site=..., dt=...)`
   (or direct `glue.create_partition()` — use Glue API directly, same as image pipeline fix)

5. **S3 notification filter update** in Terraform:
   Lambda trigger filter changes from `bronze/crawls/metadata/` to `bronze/crawls/markers/`

---

## Infrastructure Changes

| File | Change |
|------|--------|
| `lambda/bronze_manifest_verifier/handler.py` | Marker path, manifest path, verification block, Glue partition registration |
| `infra/terraform/lambda.tf` | S3 notification filter prefix → `bronze/crawls/markers/` |
| `infra/terraform/iam.tf` | Add `glue:CreatePartition` to Lambda role for `crawl_manifest_raw` table |
| Glue (scraper-pipeline or manual DDL) | Create `crawl_manifest_raw` external table |

---

## Out of Scope (Future Ticket)

- `crawl_quality_raw` Athena table from `quality_report.json` — same pattern,
  more complex schema. Deferred until `crawl_manifest_raw` is stable.
- Alerting on failed crawls (CloudWatch alarm or SNS on Lambda error).

---

## Open Questions

- [ ] Should `metadata/` dir be kept as-is for backwards compatibility, or fully
      replaced by the new paths? (Backwards compat keeps both; clean break removes metadata writes)
- [ ] Who owns the `crawl_manifest_raw` Glue table — this repo or scraper-pipeline?
