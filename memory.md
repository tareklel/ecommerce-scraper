# Memory

## 2026-02-24 - `d4ee777` - Add bronze Athena partition registration on success
- Added repo-level `AGENTS.md` guidance for project scope and workflow expectations.
- Extended `lambda/bronze_manifest_verifier` to handle both `manifest.json` and `_SUCCESS` S3 events in one handler.
- Kept manifest verification behavior (hash + row count checks) and `_SUCCESS`/`_FAILED` marker writes.
- Added Athena partition registration on `_SUCCESS` using `ALTER TABLE ... ADD IF NOT EXISTS PARTITION` for `env/site/dt`.
- Made Athena naming align with `scraper-pipeline` conventions: `ATHENA_WORKGROUP`, `ATHENA_DATA_CATALOG`, `GLUE_DATABASE`.
- Defaulted table naming to site-based convention (`bronze_<site>_raw`) with optional `ATHENA_TABLE` override.
- Updated Terraform to pass Lambda env vars, add `_SUCCESS` S3 notification trigger, increase Lambda timeout, and grant Athena/Glue permissions.
- Added Terraform variables for workgroup/catalog/glue database/results prefix/table override to match `scraper-pipeline` naming.

## 2026-02-26 - Ounass duplicate PDP guard and multi-URL CLI support
- Added Ounass spider URL-level dedupe (`_seen_fetch_urls`) because it fetches via `requests.get` and bypasses Scrapy's request dupefilter.
- Skips duplicate URLs both before fetch and after redirects (handles alias URLs resolving to the same PDP).
- Added a regression test proving duplicate PDP URLs are only fetched/parsed once.
- Updated `run_crawler.py` so `--urls` accepts multiple inline URLs (`nargs='+'`) while preserving single-file CSV path behavior.

## 2026-03-01 - Add image downloader runner, blob contract docs, and smoke fixtures
- Added `run_image_downloader.py` CLI with two input modes: JSONL batch or inline single-job, plus argument validation and per-run result output.
- Added `ecommercecrawl/image_downloader.py` download pipeline with site normalization, scheme-less URL handling, per-run dedupe, structured result blobs, and status/reason reporting.
- Introduced result blob schema `image_download_result_v1` including job/request/storage/transfer/error/details fields.
- Added docs for long-term reference: `docs/image_downloader_blob_contract.md` and linked it from `README.MD`.
- Added fixtures: `resources/image_download_test_jobs.jsonl` (mixed scenario checks) and `resources/image_download_smoke_100.jsonl` (100-row smoke input).
- Added tests for downloader logic and CLI mode validation in `tests/test_image_downloader.py` and `tests/test_run_image_downloader.py`.
- Updated `makefile` with local image-downloader run target and configurable input/output/worker/timeout variables.

## 2026-03-03 - Add automatic quality gate and lambda quality-aware success markers
- Added stateless quality gate core (`ecommercecrawl/quality_gate.py`) and local adapter (`run_quality_gate.py`) with configurable blank-threshold checks and per-site exclusions.
- Wired quality checks into `PostCrawlPipeline` so each crawl auto-generates `metadata/quality_report.json` and includes a `quality_gate` summary in `metadata/manifest.json`.
- Added default quality exclusions config (`resources/quality_gate_exclusions.json`) and default settings/make variables for quality gate execution.
- Added docs for fail-quality contract (`docs/fail_quality_contract.md`) and updated tests covering quality core, adapter, and pipeline integration.
- Updated bronze manifest verifier lambda so `_SUCCESS` is emitted only when both verification and quality gate pass.
- Added independent `_FAIL_QUALITY` marker emission when quality is not pass; `_FAILED` remains for verification failures and can co-exist with `_FAIL_QUALITY`.
- Added lambda unit tests for marker behavior across success, quality-only fail, and dual-fail scenarios.

## 2026-03-07 - Ounass language and request pacing updates
- Added `en-saudi.ounass.com -> EN` in `ecommercecrawl/constants/ounass_constants.py` so Ounass EN Saudi PDP URLs populate `language` correctly.
- Added Ounass-specific request tuning settings in `ecommercecrawl/settings.py`: `OUNASS_REQUEST_DELAY_SECONDS`, `OUNASS_REQUEST_JITTER_SECONDS`, `OUNASS_REQUEST_TIMEOUT_SECONDS`.
- Updated `ecommercecrawl/spiders/ounass_crawl.py` to apply per-request sleep (`delay + jitter`) and request timeout for `requests.get(...)` calls used by Ounass seed/PLP/PDP fetch flow.

## 2026-04-06 - EU region migration and deployment hardening
- Switched scraper Terraform and Make defaults from `me-central-1` to `eu-central-1`, including a Frankfurt-specific Terraform backend key and default scraper bucket name.
- Made ECS and Lambda IAM role names region-scoped so the EU stack can coexist with the MENA stack in the same AWS account without global IAM name collisions.
- Changed `ecr-push` to rebuild before push, and updated Make AWS/Terraform calls to stay on the configured `AWS_PROFILE`.
- Reworked `ecr-login` to derive the ECR registry from STS account identity instead of Terraform output, which fixed Docker login for the EU registry.
- Made Ounass request tuning fall back to built-in defaults when the spider is instantiated outside Scrapy's `from_crawler()` path, and aligned Ounass tests with the explicit request timeout behavior.

## 2026-05-05 - Add API-first Ounass crawler API routing
- Added a generic `ecommercecrawl/crawler_api` layer with Zyte as the current provider and request-type mapping for raw HTTP responses vs rendered HTML.
- Wired `scrapy-zyte-api` into Scrapy settings with opt-in request metadata and disabled transparent mode for non-Ounass traffic.
- Refactored Ounass seed handling to support `auto`, `api`, and `requests` fetch backends; `auto` now uses API by default unless the hostname is in `OUNASS_REQUESTS_TLDS`.
- Added `PLPSORT_KEY`-based Ounass pagination and updated first-page parsing to use the current top-level `page` payload field.
- Expanded Ounass and crawler API tests for API/request routing, pagination URL generation, and updated PLP page payload behavior.

## 2026-05-09 - Add cloud URL sources and local env command helper
- Added `--urls-source` to `run_crawler.py` for local or `s3://` CSV seed lists, preserving existing inline `--urls` and CSV path behavior.
- Recorded `urls_source` in crawler entry-point metadata so manifests identify externally supplied seed lists.
- Made Zyte Scrapy handlers conditional on `ZYTE_API_KEY` or `ZYTE_API_ENABLED=true`, keeping non-Zyte local runs on normal HTTP handlers.
- Added Make helpers for Docker prune-before-rebuild and `run-with-env` to execute arbitrary local commands with `.env` exported.
- Added tests covering URL-source parsing/loading, CLI handoff, and conditional Zyte settings.

## 2026-05-15 - `172af17` - Add Athena-driven image download pipeline
- Added `run_image_pipeline.py` ECS orchestrator: queries `stg_product_image_download_status` for pending/error images via Athena, runs downloads, writes `bronze/images/download_status/dt={dt}/data.jsonl.gz` partition, registers Glue partition, writes `_SUCCESS`/`_FAILED` marker to `bronze/images/download_status/meta/{dt}/`.
- Extended `ecommercecrawl/image_downloader.py` with `storage_mode` (`local | s3 | both`), S3 blob upload via boto3, updated blob path from `silver/` to `bronze/images/by-hash/`, dropped `by-primary` pointer keys.
- Added `scripts/image_quality_checker.py` ECS job: reads status partition, fetches blobs from S3, validates with Pillow (format, min 10px dimensions, SHA256 integrity), writes `bronze/images/raw/dt={dt}/` partition.
- Added `lambda/image_pipeline_trigger/handler.py`: S3 shim triggered by `_SUCCESS` marker, extracts `dt` from key, calls `ecs.run_task()` with `--dt` command override to launch quality checker.
- Added `infra/terraform/glue.tf` with two external tables: `image_download_status` and `raw_image`.
- Extended `infra/terraform/ecs.tf` with `image-pipeline` and `image-quality-checker` Fargate task definitions.
- Extended `infra/terraform/iam_ecs.tf` with dedicated IAM role for image pipeline tasks (S3 `bronze/images/*`, Athena, Glue).
- Extended `infra/terraform/iam.tf` with IAM role for trigger Lambda (`ecs:RunTask`, `iam:PassRole`).
- Extended `infra/terraform/lambda.tf` with `image_pipeline_trigger` Lambda and S3 notification on `bronze/images/download_status/meta/**/_SUCCESS`.
- Added Makefile targets `run-image-pipeline-local` and `ecs-run-image-pipeline` with `IMAGE_PIPELINE_LIMIT` for dry runs.
- Added `.claude/settings.json` with project permission allowlist for terraform/poetry commands.
- Dry run order: `make tf-apply` → `make run-image-pipeline-local IMAGE_PIPELINE_LIMIT=5` → `make ecr-push && make ecs-run-image-pipeline IMAGE_PIPELINE_LIMIT=10`.

## 2026-05-18 - `8d4b38a` - Fix image pipeline: per-run paths, Glue API, IAM, ECS command bugs
- Renamed S3 paths and Glue tables: `download_status` → `download_log`, `raw` → `validated`, `raw_image` → `image_validated`, `image_download_status` → `image_download_log`.
- Added `run_id` subdirectory to data and marker S3 paths (`dt={dt}/run={run_id}/`) so multiple runs on the same day no longer overwrite each other.
- Replaced Athena DDL partition registration (`ALTER TABLE ... ADD PARTITION`) with direct `glue.create_partition()` in both scripts — eliminates silent failures from missing `--athena-output-loc`.
- Added `--run-id` arg to `image_quality_checker.py`; Lambda now extracts both `dt` and `run_id` from `_SUCCESS` key and passes them to the quality checker.
- Fixed Lambda command override: was passing `["python", "script.py", ...]` list to a task with `entryPoint=["/bin/sh", "-c"]`, causing only `python` to run with no script. Now passes a single shell string.
- Fixed `ecs-run-image-pipeline` makefile override: was wrapping command in redundant `/bin/sh -c` (task definition already has entryPoint), causing container to exit 0 with no output.
- Added `s3:GetBucketLocation` to image pipeline IAM role (Athena needs it to verify output bucket) and `price_comparison_dbt/*` read grant (Athena scans dbt model partitions for `stg_product_image_download_status`).
- Added `run-quality-checker-local DT=... RUN_ID=...` makefile target for local testing.

## 2026-06-03 - Fix image pipeline pending-images query: per-URL status tracking and deterministic same-day ordering
- Bug 1: `_query_pending_images` joined status on `(site, primary_key)` only — a new image URL for an existing product was silently skipped because an old `ok` status for the same product matched and filtered it out. Fixed by adding `url` to the subquery SELECT, partitioning ROW_NUMBER by `(site, primary_key, url)`, and adding `AND c.url = s.url` to the JOIN. Status is now tracked per `(site, primary_key, url)`.
- Bug 2: `ORDER BY dt DESC` in the ROW_NUMBER window used date-only precision, so two runs on the same day (e.g., one error, one ok) produced identical `dt` values and the winning row was non-deterministic. Fixed by changing to `ORDER BY run_id DESC`; `run_id` is `YYYY-MM-DDTHH-MM-SS-mmm` and sorts correctly within the same day.
- The same two bugs exist in `scraper-pipeline/dbt/models/silver/silver_product_image_download_status.sql` and were fixed there in a parallel session.

## 2026-06-02 - scraper-pipeline: add crawl_manifest_raw DDL and silver_crawl_manifest dbt model
- Added `sql/athena/bronze_crawl_manifest_raw.sql` in scraper-pipeline: external table with single `raw_json STRING` column, `PARTITIONED BY (site string, dt string)`, `LOCATION '__BRONZE_PREFIX__/crawls/manifests/'`.
- Added `dbt/models/silver/silver_crawl_manifest.sql`: incremental model extracting run_id, crawler_name, exit_reason, start/finish time, duration, row_count, quality gate fields, and verification fields from `raw_json` via `json_extract_scalar`.
- Aligned Lambda partition registration: `crawl_manifest_raw` uses `(site, dt)` values (not `(env, site, dt)`) to match the existing scraper-pipeline pattern where env is baked into the table LOCATION prefix.
- Use `make athena-ddl DDL_FILE=sql/athena/bronze_crawl_manifest_raw.sql` in scraper-pipeline to create the table.

## 2026-06-02 - Implement crawl_observability ticket: manifests/ dir, verified manifest write, crawl_manifest_raw partition
- Forked markers out of `metadata/` into `bronze/{env}/crawls/markers/{site}/{dt}/{run_id}/` (clean break, no backwards compat).
- Lambda now writes a verified copy of `manifest.json` — with `verification.outcome`, `verification.failure_reason`, `verification.verified_at` appended — to `bronze/{env}/crawls/manifests/{site}/{dt}/{run_id}/data.json`.
- `_register_bronze_partition` (triggered by `_SUCCESS` in `markers/`) now registers two Glue partitions: the existing crawl data table `(site, dt)` and the new `crawl_manifest_raw` table `(env, site, dt)`.
- Updated `infra/terraform/lambda.tf` `_SUCCESS` notification filter prefix from `metadata/` to `markers/`.
- Added `scripts/backfill_manifests.py`: idempotent one-time script that copies historical `metadata/*/manifest.json` → `manifests/*/data.json` and registers `crawl_manifest_raw` Glue partitions; historical rows will have NULL verification fields.
- Updated tests: marker path assertions updated to `markers/` prefix; added tests for verified manifest write, outcome field values, and dual-table partition registration.

## 2026-05-11 - Add Secrets Manager runtime env wiring and dynamic status counts
- Added Terraform wiring for one JSON Secrets Manager secret (`ecommerce-scraper/env`) and ECS task secret injection for allowlisted runtime env keys.
- Added Make helpers to fetch remote secret keys for local crawler runs, list secret keys without values, and update a single remote secret key without storing values in `.env` or Terraform state.
- Added ignore coverage for `.env`/`env` variants and a JSON-to-shell export helper for safe local secret hydration.
- Changed manifest status-code counts to include all observed Scrapy response status counters dynamically, including important statuses such as `403`.
