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
