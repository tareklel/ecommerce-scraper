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
