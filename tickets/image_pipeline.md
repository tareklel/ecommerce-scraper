# Ticket: Image Download Pipeline (Athena-driven)

## Goal

Build an end-to-end pipeline that reads undownloaded image URLs from an Athena table,
runs the image downloader (S3), writes download status directly to an Athena-queryable
S3 partition, and triggers a quality checker that validates and appends enriched image
metadata to a `raw_image` table — enabling downstream serving pipelines.

---

## Full Architecture

```
[Athena: image_catalog]
        │
        │  SELECT pending images (downloaded = false, latest partition)
        ▼
[1. run_image_pipeline.py]       ← new ECS orchestrator CLI
        │  queries Athena, runs downloads
        │  writes status partition + _SUCCESS marker
        ▼
[bronze/images/download_status/dt={dt}/data.jsonl.gz]   ← Athena partition
[bronze/images/download_status/meta/{dt}/_SUCCESS]       ← trigger marker (separate dir)
        │
        ▼
[2. ECS job: image_quality_checker]   ← triggered by _SUCCESS marker
        │  validates downloaded images (format, dimensions, not error page)
        │  appends enriched rows to raw_image Athena table
        ▼
[Athena: raw_image]              ← bronze layer, input to serving pipeline
```

**Note on S3 layout:** data files and marker files are in separate directories so Athena
does not try to parse `_SUCCESS` / `_FAILED` as data rows.

---

## Piece 1: `run_image_pipeline.py` (new ECS orchestrator)

**Responsibilities:**
1. Query Athena for images where `downloaded = false` on the latest partition — also retries `error`
2. Poll for Athena query completion (results land in S3 as CSV — not streamed)
3. Convert CSV results to JSONL job format expected by `image_downloader.py`
4. Call `image_downloader.download_jobs()` with chosen storage mode
5. Write per-image results to `bronze/images/download_status/dt={dt}/data.jsonl.gz`
6. Register new Athena partition in Glue
7. Write `_SUCCESS` or `_FAILED` to `bronze/images/download_status/meta/{dt}/`

No manifest, no Lambda — the orchestrator knows the results directly and writes them itself.
Mirrors how `PostCrawlPipeline` writes crawl output directly to S3.

**CLI flags:**
```
--run-id             required, trace ID for this batch
--athena-database    Glue/Athena database name
--athena-table       image catalog table or view name
--athena-output-loc  s3://... for Athena query results
--storage-mode       local | s3 | both  (default: s3)
--output-dir         local output dir (default: output/images)
--max-workers        concurrent download threads (default: 10)
--limit              optional row cap for testing
--log-level          default: INFO
```

**S3 bucket:** passed as `S3_BUCKET` ECS environment variable set in Terraform —
same pattern as existing scraper tasks. Do not use `.env` (not pushed to ECR).
Bucket: `price-comparison-bucket-eu-central-1`

**Athena query (pending + retry images):**
```sql
SELECT c.site, c.primary_key, c.url
FROM image_catalog c
LEFT JOIN (
    SELECT site, primary_key, status,
           ROW_NUMBER() OVER (PARTITION BY site, primary_key ORDER BY dt DESC) AS rn
    FROM image_download_status
) s ON c.site = s.site AND c.primary_key = s.primary_key AND s.rn = 1
WHERE s.status IS NULL OR s.status = 'error'
```

**S3 layout:**
```
bronze/images/
  by-hash/{sha256}{ext}                          ← image blobs
  download_status/
    dt=2026-05-15/
      data.jsonl.gz                              ← Athena reads this
    meta/
      2026-05-15/
        _SUCCESS                                 ← trigger for quality checker
        _FAILED
```

**Status values:** `ok`, `error`, `skipped_invalid`, `skipped_duplicate`

---

## Piece 2: `image_downloader.py` — extend with S3 upload

`build_canonical_blob_key()` already exists but no actual upload is implemented. Add:

- `storage_mode: Literal["local", "s3", "both"]` param to `download_jobs()` and `download_one_job()`
- After local write + hash, upload blob to `bronze/images/by-hash/{sha256}{ext}`
- Return `s3_blob_key` in the result object
- Drop `by-primary` — product→image mapping resolved through `image_download_status` and `raw_image`

---

## Piece 3: ECS job — `image_quality_checker` (new)

Triggered by `_SUCCESS` marker. Runs as a separate ECS task — image validation can be slow
and is not safe to run inside a Lambda with a 15-min ceiling.

**Responsibilities:**
1. Read `data.jsonl.gz` for the run from `bronze/images/download_status/dt={dt}/`
2. For each `status=ok` row, fetch the image from S3 (`by-hash` key)
3. Validate:
   - File is a valid image format (not an HTML error page that slipped content-type check)
   - Dimensions are reasonable (reject 1×1 tracking pixels)
   - SHA256 matches the stored key
4. Append validated rows to `raw_image` Athena table partitioned by `dt`
5. Register new partition in Glue

**`raw_image`** — presence in this table means the image passed both download and quality
gates. No explicit status column needed. Input to the serving pipeline.

---

## Athena Tables

```sql
-- Written by run_image_pipeline.py (orchestrator)
CREATE EXTERNAL TABLE image_download_status (
  site         STRING,
  primary_key  STRING,
  url          STRING,
  run_id       STRING,
  status       STRING,
  s3_blob_key  STRING
)
PARTITIONED BY (dt STRING)
STORED AS ... LOCATION 's3://price-comparison-bucket-eu-central-1/bronze/images/download_status/';

-- Written by image_quality_checker ECS job
CREATE EXTERNAL TABLE raw_image (
  site         STRING,
  primary_key  STRING,
  image_url    STRING,
  s3_blob_key  STRING,
  sha256       STRING,
  width        INT,
  height       INT,
  format       STRING,
  run_id       STRING
)
PARTITIONED BY (dt STRING)
STORED AS ... LOCATION 's3://price-comparison-bucket-eu-central-1/bronze/images/raw/';
```

---

## Infrastructure Changes

- **New ECS task** `run_image_pipeline` (same cluster as scrapers)
- **New ECS task** `image_quality_checker` (same cluster)
- **IAM ECS:** `s3:GetObject`, `s3:PutObject` on `bronze/images/*`; `athena:StartQueryExecution`, `glue:CreatePartition`
- **Glue:** 2 new external tables
- **`S3_BUCKET`** passed as ECS env var in Terraform — bucket name is not sensitive, no Secrets Manager needed

---

## File Changes Summary

| File | Change |
|------|--------|
| `run_image_pipeline.py` | New — ECS orchestrator |
| `ecommercecrawl/image_downloader.py` | Add `storage_mode` + S3 upload; drop `by-primary` |
| `scripts/image_quality_checker.py` | New ECS job |
| `infra/terraform/ecs.tf` | Two new task definitions |
| `infra/terraform/iam_ecs.tf` | IAM permissions for new tasks |
| `infra/terraform/glue.tf` | Two new external tables |

---

## Completed

- [x] `ecommercecrawl/image_downloader.py` — extended with `storage_mode` (`local | s3 | both`), S3 upload via boto3, path updated to `bronze/images/by-hash/`, `by-primary` dropped
- [x] `run_image_pipeline.py` — ECS orchestrator: Athena query → JSONL jobs → downloads → status partition write → Glue partition registration → `_SUCCESS`/`_FAILED` marker
- [x] `scripts/image_quality_checker.py` — validates downloaded images (Pillow: format, dimensions ≥10px, SHA256), writes `raw_image` partition + registers Glue partition
- [x] `lambda/image_pipeline_trigger/handler.py` — S3 trigger shim: parses `dt` from `_SUCCESS` key, calls `ecs.run_task()` with `--dt` override
- [x] `infra/terraform/glue.tf` — two external Glue tables: `image_download_status`, `raw_image`
- [x] `infra/terraform/ecs.tf` — two new Fargate task definitions: `image-pipeline`, `image-quality-checker`
- [x] `infra/terraform/iam_ecs.tf` — IAM role for image pipeline tasks (S3 `bronze/images/*`, Athena, Glue)
- [x] `infra/terraform/lambda.tf` — `image_pipeline_trigger` Lambda + S3 notification on `bronze/images/download_status/meta/**/_SUCCESS`
- [x] `infra/terraform/iam.tf` — IAM role for trigger Lambda (`ecs:RunTask`, `iam:PassRole`, CloudWatch logs)
- [x] `infra/terraform/outputs.tf` — added `ecs_image_pipeline_task_definition_arn`
- [x] `makefile` — added `run-image-pipeline-local` and `ecs-run-image-pipeline` targets
- [x] Pillow added to `pyproject.toml` for image validation

---

## Dry Run Checklist

**Prerequisites:**
1. `make tf-apply` — deploys Glue tables, Lambda, ECS task defs, IAM roles. Must run before anything else or the Athena query will fail (tables won't exist).

**Step 1 — Validate locally (no Docker, no ECS):**
```bash
make run-image-pipeline-local IMAGE_PIPELINE_LIMIT=5
```
Check S3 for:
- `bronze/images/download_status/dt={today}/data.jsonl.gz` — status rows
- `bronze/images/download_status/meta/{today}/_SUCCESS` — trigger marker
- `bronze/images/by-hash/*.jpg` — image blobs
- CloudWatch `/ecs/ecommerce-scraper` — Lambda should fire and trigger quality checker

**Step 2 — Only if Step 1 passes, run via ECS:**
```bash
make ecr-push
make ecs-run-image-pipeline IMAGE_PIPELINE_LIMIT=10
```

**Note on first run:** `image_download_status` will be an empty Glue table with no partitions — the LEFT JOIN in the Athena query handles this correctly, returning all catalog rows with `status IS NULL`.

---

## Next Steps / To Be Discussed

- [ ] What triggers `run_image_pipeline.py` in production — scheduled ECS cron, or event-driven after a crawl completes?
- [x] `image_catalog` confirmed as `stg_product_image_download_status` — update `--athena-table` default in `run_image_pipeline.py` to `stg_product_image_download_status`
- [x] scraper-pipeline: `stg_product_image_download_status` extended with `download_status`, `download_error_run_id`, `s3_blob_key`; `downloaded` now derived from `raw_image` presence; `stg_product_serving_latest` surfaces `s3_blob_key`
