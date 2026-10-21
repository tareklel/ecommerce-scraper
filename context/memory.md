# Memory

## 2026-10-21 - Part 4b success path verified in AWS
- Dev ECS run `2026-10-21T14-27-38-056` (Saudi Tory Burch bags via Zyte `TR`): 137/137 requests 200, 126 rows, published from `crawl-unverified/` into `crawls/`, `_SUCCESS`, partitions registered, `run_status success`. Athena returns the 126 rows and the `crawl_started_raw` records. The Türkiye routing fixed Saudi access.

## 2026-10-21 - Lost listing pages degrade the run
- `access.LISTING_META_KEY`: a flagged listing request given up on access adds a `kind: access` degradation naming the URL, even when its hostname isn't blocked. Ounass normal mode flags its `/api/` requests; PLP-efficient listings aren't flagged (G3 covers them).
- Degraded runs still publish everything they wrote; only failed runs stay out of raw. Level Shoes listing fetches (plain `requests`) bypass the access layer: follow-up in the ticket.

## 2026-10-21 - failure_reason access; blocked-host fix
- A run with no rows whose requests were given up on access fails as `access` (`_FAIL_ACCESS`), not `quality`, in both `pipelines.crawler_run_status` and the verifier; no extra quality/verification markers for it.
- A hostname that lost every request is `blocked` even under the 5-request minimum (the Acler run showed 1/1 blocked as "ok").
- 6 new tests; suite 430 passed. Verifier redeploy needed for the new marker.

## 2026-10-21 - Registry guard: category listings with no brand only
- G1 (`plp_efficient._page_kind_errors`) rejects PLP rows with a brand or a `/designers/` URL: a listing returns what its URL contains, and only category pages with no brand match what a row claims (otherwise a daily Phase 2 flood or G11).
- Brand-page support (filter entries by breadcrumbs + brand; needs a raw→canonical map) recorded as a possible extension. `plp_covers_pdp`'s brand rule kept for it. scraper-pipeline's export doc updated in the same change.
- 2 new tests replace the brand-scoped coverage test; suite 424 passed.

## 2026-10-20 - Saudi Ounass via Zyte Türkiye exits
- `CRAWLER_API_ZYTE_GEOLOCATION_BY_HOST` (settings.py) routes `saudi.ounass.com`, `en-saudi.ounass.com`, `ar.ounass.sa` through Zyte geolocation `TR`; it wins over the global `CRAWLER_API_ZYTE_GEOLOCATION`. Other hosts keep Zyte's default.
- Evidence: the same Tory Burch listing request was banned (520) 5/5 times on default routing and returned 200 (48 hits, SAR) via `TR`. The user confirmed prices don't change by exit country.

## 2026-10-20 - Cloud check of Part 4b; work stopped for the day
- Two dev ECS runs: a 404 test URL verified the failure path end to end (failed/quality, markers, no publish, manifest registered, run-started record, `RUN FAILED` log); an Acler en-saudi run was banned by Zyte (520) through both retry rounds. Success path still unverified in AWS.
- Saudi bans are intermittent (playground too). Agreed next commit, not built: Zyte aggressive retry policy, 6 × 300 s rounds, `failure_reason: access`, blocked-host fix, registry brand guard (pending yes), then a success-path ECS test. Full list in the ticket's "Resume here".
- `ECS_TEST_COMMAND` / `OUNASS_TEST_URL` now point at `saudi.ounass.com/api/women/designers/ami/` (the user's change).

## 2026-10-20 - Part 5a: access layer for all crawls
- Verifier deployed (05:36 UTC) and the crawl-unverified/ crawler change pushed.
- New `ecommercecrawl/access.py`: `AccessRetryMiddleware` (priority 540) sets access failures aside after normal retries (`AccessDeferred`) and re-sends them after a cool-down (`ACCESS_RETRY_ROUNDS` 2 × 900 s, cap 3600 s); per-hostname `access` manifest block; blocked hostnames become `kind = access` degradations.
- Degradations are now structured `{kind, scope, message}`; end-of-run `RUN DEGRADED` / `RUN FAILED` / `ACCESS` log lines.
- PLP-efficient: Phase 2 waits for retry rounds; G3 separates access from content and counts pages that never came back (a blocked HTML listing page used to be dropped silently).
- 24 new tests (420 total); real Scrapy run against a local server confirmed recovery in a round and the final failure reaching the callback.

## 2026-10-20 - PLP-efficient Part 5 design recorded (not built)
- 5a (all crawls): access failures retried in rounds after a cool-down (`ACCESS_RETRY_ROUNDS` 2, `…_COOLDOWN_SECONDS` 900, `…_MAX_TOTAL_SECONDS` 3600), per-hostname `access` manifest block, structured `degradations` (`kind` content/access), end-of-run `RUN DEGRADED` / `ACCESS` log lines.
- 5b parity (G9): ~20 per hostname, re-check re-fetches listing + product page, hostname fails at ≥ 20% (min 2) of ≥ 10 usable comparisons, blocked hostnames borrow others' verdict, nothing checkable → listing rows dropped (access); rows held per hostname until verdict; no whole-run stop. Parity now drawn in the reference doc's section 3 flow.

## 2026-10-19 - Principle: access errors are not content errors
- Ounass blocking (Zyte "Website Ban", HTTP 429/403, repeated 5xx/timeouts) affects a whole hostname and says nothing about data correctness. It must never count as a parity mismatch, a missing product (G4), a field mismatch (G11) or any other content failure.
- The crawler must track access failures per hostname and report them separately from content checks (to build in PLP-efficient Part 5; recorded in `docs/ounass_plp_efficient_crawl.md` section 5 and the ticket's decision log).

## 2026-10-16 - Part 4b: run status and publish-on-pass (all crawls)
- Found: `_SUCCESS` registers the whole day folder (`crawls/<site>/<dt>/`), so a failed run's file was read whenever another run that day passed.
- Crawler now uploads data to `bronze/<env>/crawl-unverified/…`; the verifier copies it to `crawls/…` only on success/degraded, then writes `_SUCCESS`. Failed runs keep their file in `crawl-unverified/` with `_FAIL_ABORTED` / `_FAIL_STARTUP_CHECK` / `_FAIL_QUALITY` / `_FAILED`.
- Manifest gets `run_status` / `failure_reason` / `degradations` (crawler view in `pipelines.crawler_run_status`, final in the verifier). `crawl_manifest_raw` days are registered for every run.
- Run-started record at spider open (`bronze/<env>/crawl-started/…`) + scraper-pipeline `crawl_started_raw` (`1bba8cd`) to spot killed runs.
- Rollout order: deploy verifier (`091227d`), then push the crawler change.

## 2026-10-16 - PLP-efficient Part 4a: manifest block and quality-gate split
- `quality_gate.py`: rows with `plp_extract_flag = 1` skip the blank-ratio rule (which only counts product-page rows now) and must each have ID, url, price > 0, site, country, language, with a non-listing url; one bad row fails the run.
- `plp_efficient.manifest_block` + `OunassSpider.plp_efficient_manifest_block`: the manifest gets a `plp_efficient` block (inputs, startup decisions, per-listing outcomes, Phase 2, `degradations`), also when the run stops at startup.
- Run status agreed for Part 4b (all crawls): success / degraded / failed (aborted, startup_check, quality, verification) / killed. Aborted runs are failed and never reach dbt.
- 15 new tests; suite 381 passed.

## 2026-10-16 - PLP-efficient Part 3: crawler core (local only until Part 4)
- `ecommercecrawl/plp_efficient.py` gains `PlpEfficientRun` (Scrapy-free bookkeeping: match listing entries by country + language + `visibleSku`, PLP-extract row with the URL copied from gold, per-listing stats, `listing_health()` for G3/G7/G11/G4, `select_phase2()` with hold-backs and the 10k ceiling) and the `plp_hit_*` price/discount/label helpers.
- Ounass spider: `--plp-efficient` (or `OUNASS_PLP_EFFICIENT_CRAWL`) loads the export (or local files), runs the startup checks, sweeps listings with an errback per page, then schedules Phase 2 PDPs from `spider_idle`. Every normal PDP row now carries `plp_extract_flag: 0`.
- G11/G4 are judged after the sweep: rows already written stay, a bad listing's leftovers are held back. Partial runs must become an "incomplete" status in Part 4; until then the mode is local-only.
- New settings `OUNASS_PLP_EFFICIENT_MISSING_RATIO_CAP` (0.25) and `…_FIELD_MISMATCH_RATIO` (0.05); `COUNTRY_CURRENCY` constant.
- Terraform: ECS task role may invoke `price-comparison-plp-efficient-export-{dev,prod}` (applied 2026-10-16, targeted).
- 23 new tests; suite 366 passed. Live smoke run (1 Saudi tote listing): 29/29 pages, 1 product refreshed and verified against gold, Phase 2 skipped by a lowered ceiling as designed.

## 2026-10-16 - PLP-efficient Part 2: inputs, startup checks and preflight
- New `ecommercecrawl/plp_efficient.py` (plain functions shared by the future spider wiring and preflight):
  - `invoke_export` calls scraper-pipeline's export Lambda; any failure raises `ExportError`, so the run stops before Zyte spend.
  - `load_inputs[_from_manifest]` reads local or s3:// files.
  - `validate` runs G2 (files/columns: stop), G1/G7 (listing rows canonical, host ↔ country/language: skip, >25% stop), G10 (product rows: quarantine, >5% stop), G8 (gold rebuild age: warn 2d, stop 3d), a stale-crawl warning (`last_crawl_date` > 7 days, warn only), and coverage (held back / uncovered, Phase 2 ceiling hint).
- Settings `OUNASS_PLP_EFFICIENT_*` (mode off by default, thresholds overridable through env vars) and `TLD_COUNTRY_MAP`.
- `make preflight-ounass-plp-efficient` (and `-probe` for 1 Zyte request): exit 0 = would start, 1 = would stop.
- 44 new tests on synthetic data; full suite 343 passed.
- Live preflight on the dev export: 4 listings and 5 products valid; warned about gold age (2.9 days) and 5 stale products (last crawled 2026-08-08).
- Next: Part 3 (wire into the spider).

## 2026-10-16 - PLP-efficient Part 1 verified in dev; scraper-pipeline pushed
- Dev export test passed (`2026-10-15T13-32-21Z-dec3e27c`): 4 PLP rows, 5 PDP rows (exactly the in-scope dev products), 19 bag pairs, `gold_built_at` correct, 13 KB scanned.
- Auto-deploy verified: `latest` = `sha-6f94c7f`.
- scraper-pipeline pushed: `7335ebd` (Part 1) and `9ca7bfb` (requirements.txt tracked and pinned).
- Ticket handoffs updated. Next: Part 2 (crawler-side loading, validation, `make preflight`).

## 2026-10-15 - Crawler image auto-deploys on green CI; cloud updated
- The user promoted `sha-f3737dd`, so the cloud crawler now runs current `main` (ECR `latest` = `sha256:503f669f…`); the old image is kept as `legacy-20260803`.
- Switched to auto-deploy: `crawler-image.yml` pushes `sha-<7>` and `latest` once tests pass, and its summary names the previously live image. `promote-crawler-image.yml` is now for rollback only. The required reviewer was removed from the `production` environment (the `main`-only branch rule stays). Crawler-code pushes to `main` now go live at the next crawl.

## 2026-10-15 - `1435584` - Tests skip when their saved product pages are absent
- The first crawler-image CI run failed: 15 Farfetch and Bloomingdale's tests read real product pages (`*.html`) that are gitignored, because downloaded product data must not be committed, so they don't exist in CI.
- Those tests now skip with a stated reason when the page is missing, and still run locally. Simulated CI: 284 passed, 15 skipped.
- Follow-up in `tickets/cicd_pipeline.md`: a synthetic Bloomingdale's PDP fixture so CI covers its `extract_product`.

## 2026-10-15 - `f27b920` - Crawler image built in GitHub Actions; promotion needs approval
- The cloud crawler image (ECR `latest`, 2026-08-03) was missing `28c7fc7` and `2e1a482`, and the laptop can't build images (company HTTPS inspection breaks pip inside `docker build`). Builds moved to GitHub Actions.
- `.github/workflows/crawler-image.yml`: on pushes to `main` touching crawler code, run pytest, then build and push `sha-<7>` to ECR via OIDC. It never moves `latest`. `.github/workflows/promote-crawler-image.yml`: re-tags a `sha-…` / `legacy-YYYYMMDD` image as `latest` in the `production` environment (required reviewer tareklel, `main` only). Rollback = promote an older tag.
- Applied `infra/terraform/github_actions.tf` (GitHub OIDC provider + role `ecommerce-scraper-github-actions`, trusted only by `main` and the `production` environment, ECR push/re-tag on this repo only) and a new ECR lifecycle policy. Rule 1 protects `latest`; the old "keep last 10, any tag" rule could have expired the live image.
- GitHub settings (run by the user): `production` environment and repo variable `AWS_CRAWLER_IMAGE_ROLE_ARN`. No secrets exist: OIDC issues short-lived credentials per run.
- The live 2026-08-03 image is also tagged `legacy-20260803` (never expires) as a rollback target.
- Added `tickets/cicd_pipeline.md` (CI/CD roadmap across all three repos, with evidence of deploy drift) and "▶" handoff sections in it and in `tickets/ounass_plp_efficient_crawl.md`.

## 2026-10-05 - `1c19886` - Ounass PLP-efficient crawl mode designed (no behaviour change yet)
- Designed an opt-in mode that refreshes known Ounass products (from gold) from listing pages instead of product pages, then PDP-crawls only what's left. Cost note `notes/2026-09-17-ounass-zyte-crawl-cost.md` puts women/bags (SA) at ≈ $2/month vs ≈ $181/month for daily full PDP re-crawls.
- `tickets/ounass_plp_efficient_crawl.md` holds the plan split into Parts 0–7 (0 done; 1 and 6 are scraper-pipeline work), input contracts, guardrails with failure scopes, and a dated decision log.
- Part 0 parity probe (`scripts/probe_ounass_plp_parity.py`): across 42 SA/AE products, listing `visibleSku`, `priceByCustomerGroupId["-1"]` and a discount computed from the two listing prices match the PDP extractor 42/42; the listing's own discount fields and plain `price` key don't. Sold-out colours appear only as swatches without IDs (11/12 sampled).
- Found while designing: silver merges with `coalesce(new, previous)`, so PLP-extract rows must copy `url` from gold (never the listing URL), and ended sales can't clear `price_discount` today (existing scraper-pipeline bug, both paths).
- Added living reference doc `docs/ounass_plp_efficient_crawl.md`, an AGENTS.md rule to update it with any behaviour change, and `tests/test_plp_efficient_docs.py`, which fails if an `OUNASS_PLP_EFFICIENT_*` setting is undocumented.
- Next: Part 1 (scraper-pipeline inputs); plan proposed, waiting on decisions about registry scope, export scoping, one vs three export Lambdas, and `portal_itemid` reaching the API cache.

## 2026-09-16 - `28c7fc7` - Ounass PDP browserHtml fallback made opt-in
- The `parse_pdp` retry that forces a Zyte `rendered_html` (browserHtml) render when a PDP's plain `httpResponseBody` has no inline `state` was unconditional; gated it behind new setting `OUNASS_PDP_BROWSER_HTML_FALLBACK`, explicitly `False` by default in `settings.py`, since browserHtml costs more per Zyte request than `httpResponseBody`.
- When the fallback is off (default) and state is missing, the PDP is now logged and dropped instead of retried.
- Fixed a latent inconsistency in `_get_crawler_api_request_type`'s hardcoded PDP default: it fell back to `rendered_html` when the setting was absent from settings, contradicting `settings.py`'s actual `http_response` default; now both agree.
- Updated `tests/test_ounass.py` to cover fallback-disabled (default, expects skip) and fallback-enabled (expects retry) cases.

## 2026-08-03 - `0caf14f`, `2aef7cd` - Bloomingdale's image downloads and Ounass crawl hardening
- Added Bloomingdale's to the shared image-downloader site registry and send `https://bloomingdales.sa/` as the request referer, preventing valid gallery jobs from being rejected as an unsupported site.
- Operationally validated the Bloomingdale's downloader change in dev: all 983 previously skipped jobs downloaded successfully; shared `latest` and production targets were not changed.
- Reworked Ounass brand-PLP crawling for the upstream removal of brand+category API paths: brand PLP hits are now filtered by each product's breadcrumb category before primary and variation PDP slugs are emitted.
- Added Ounass `--category` CLI filtering plus optional per-seed `url,category` CSV values for both local and `s3://` URL sources; per-row categories override the global category and persist across pagination URLs.
- Changed the default Ounass Zyte PDP request from `browserHtml` to the cheaper plain `httpResponseBody`, because PDP state is normally server-rendered; missing state triggers one forced rendered retry and then logs an error rather than retrying forever.
- Normalized Ounass `primary_label` to the schema's list shape, made Scrapy log level configurable with `SCRAPY_LOG_LEVEL`, and aligned image-downloader documentation with `bronze/images/by-hash/` and removal of primary-key pointer blobs.
- Added regression coverage for category matching/filter propagation, local and S3 category CSV parsing, PDP rendered fallback behavior, settings, label shape, and gallery smoke behavior.
- Git handoff state after `2aef7cd`: working tree clean; local `main` was two commits ahead of `origin/main`. Both commits were saved locally but not pushed.

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

## 2026-06-03 - Implement and close crawl_observability; open crawl_quality_raw ticket
- Fixed `crawl_manifest_raw` blank `raw_json`: Lambda now writes wrapper `{"run_id": "...", "raw_json": "<manifest string>"}` so JsonSerDe maps both columns correctly.
- Fixed `backfill_manifests.py`: reads + wraps source manifest instead of raw S3 copy; fixed partition `Values` from `[env, site, dt]` → `[site, dt]` to match table's two-key schema.
- Moved `tickets/crawl_observability.md` → `tickets/done/`.
- Created `tickets/crawl_quality_raw.md`: covers Lambda reading `quality_report.json` and writing wrapper to `quality_reports/`, DDL + silver dbt model in scraper-pipeline, backfill script, and open question on whether to unnest violations into a separate model.

## 2026-06-03 - Fix crawl_manifest_raw blank raw_json and add run_id column
- Root cause: JsonSerDe maps JSON keys to column names — `raw_json STRING` was NULL because the manifest JSON has no `raw_json` key.
- Lambda now writes a wrapper `{"run_id": "...", "raw_json": "<full verified manifest as JSON string>"}` to `manifests/.../data.json` so both columns map correctly.
- DDL (`bronze_crawl_manifest_raw.sql` in scraper-pipeline) updated to add `run_id string` alongside `raw_json string`.
- Backfill script updated to read+wrap rather than raw S3 copy, matching the new format.

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

## 2026-06-05 - Add frontend planning tickets and close image download error observability
- Moved `tickets/image_download_error_observability.md` → `tickets/done/` (implemented: reason, error_message, http_status now populated in download_log rows and logged per-failure at WARN).
- Added `tickets/image_serving.md`: CloudFront vs presigned URLs rumination — recommends CloudFront; content-addressed keys allow infinite CDN TTL.
- Added `tickets/product_api.md`: Lambda vs ECS API rumination — recommends Lambda with daily snapshot export from gold table to avoid per-request Athena latency.
- Added `tickets/plp_debug_ui.md`: PLP debug UI spec — plain HTML + Tailwind recommended over Streamlit for RTL/Arabic support.
- Added `tickets/website_description.md`: owner action required before frontend work begins.
- Added `tickets/frontend_v0_discussion.md`: repo/framework/infra v0 discussion covering hosting, design process, and first priorities.
- All three serving/API/UI tickets blocked on website_description.md.

## 2026-07-15 - `103b588` - Implement Bloomingdales.sa spider
- Spider implemented: constants/bloomingdales_constants.py, rules/bloomingdales_rules.py, spiders/bloomingdales_crawl.py.
- Platform confirmed SFCC (Demandware). No Zyte needed; Cloudflare does not block.
- PLP pagination: first page SSR HTML (48 items) + SFCC Search-UpdateGrid API for pages 2+, stop when response has 0 PDP hrefs.
- PDP extraction: JSON-LD @type=Product (name/brand/price/SAR/availability/images) + DOM microdata breadcrumbs (position 2=gender, 3=category, 4=subcategory). Color from URL PID suffix (`BAG219542223xBLK` → `Black`).
- Multiple color variants: each gets its own PLP tile + href, harvested naturally — no special handling needed.
- Smoke: 19 items, 0 errors, quality_gate=pass.
- Quality gate exclusions added for bloomingdales (color, sizes, price_discount, primary_label).

## 2026-07-20 - `e6ba2ab` - Emit ordered Ounass and Level product galleries
- Changed Ounass and Level Shoes crawler output from a single image to an ordered, deduplicated `image_urls` array with the retailer's hero first.
- Added shared HTTPS URL normalization and explicit `null` versus `[]` gallery semantics, including direct Level PDP fallbacks and spider propagation tests.
- Added ordered array-to-scalar backfill fanout and a local-only smoke command that crawls one PDP per site, downloads every image, validates saved bytes, and refuses S3-enabled runs.
- Updated the product schema, crawling methodology, downloader contract, and implementation ticket for the V2 gallery boundary.
- Validation: 142 focused tests and 225 full-suite tests passed; the live network smoke remains pending before deployment.

## 2026-07-15 - `fabadb0` - Add Bloomingdales.sa crawl ticket, site methodology, and product schema
- Added `context/crawling_methodology.md`: reusable phase-by-phase guide for onboarding new sites — WAF/SSR probe, API discovery, data source priority, raw HTML vs extract-on-crawl decision, language derivation, pagination types, and implementation file checklist.
- Added `ecommercecrawl/constants/product_schema.py`: site-agnostic canonical field contract with per-field type, required flag, and description; `REQUIRED_FIELDS`/`OPTIONAL_FIELDS` frozensets for quality checks and LLM evaluation.
- Added `tickets/bloomingdales_crawl.md`: implementation-ready ticket after live probe (2026-07-15). Platform: SFCC (Demandware). No Zyte needed — Cloudflare present but not blocking. Language: `bloomingdales.sa`=AR, `en.bloomingdales.sa`=EN (subdomain). PLP: SSR HTML (48 items, `data-pid` extraction) + `Search-UpdateGrid` API for pagination (`?cgid=...&start=N&sz=48`). PDP: JSON-LD `@type=Product` with name/brand/sku/price/SAR/availability/6 images; category from DOM microdata breadcrumbs (position 3/4); `portal_itemid` from URL PID suffix (e.g. `BAG219542223xBLK`).
- Added `scripts/probe_bloomingdales.py`: feasibility probe (6/6 checks passed). `--en` flag for English subdomain.
- Added `resources/bloomingdales_urls.csv`: EN + AR PLP seeds for bags/shoes/clothing categories plus one EN/AR PDP for smoke testing.
- Moved Farfetch crawl ticket to `tickets/blocked/` — Akamai WAF blocks httpResponseBody even via Zyte; browserHtml only viable mode but prohibitively expensive at scale.

## 2026-07-28 - Deploy Bloomingdales to dev; canonical seeds; image downloader fix

### Image downloader blob_prefix fix (`e6ba2ab` already had the scaffolding; fixed in this session)
- `canonical_blob_key` returned `/{sha256}.jpg` when `blob_prefix` was omitted. Fixed default: `blob_prefix or "bronze/images/by-hash"`.
- Note on path: images are stored as `bronze/{env}/images/by-hash/{sha256}` — CloudFront OAC policy covers both `dev` and `prod` prefixes.

### Bloomingdales V2 contract wired + deployed
- `run_crawler.py`: added `from ecommercecrawl.spiders.bloomingdales_crawl import BloomingdalesSpider` and `'bloomingdales': BloomingdalesSpider` entry — critical for ECS launch.
- Added `tests/test_bloomingdales_rules.py` (36 tests) covering language derivation, URL classification, PID extraction, pagination URL construction, color/price/label extraction, and AR fixture integration test.
- ECR image pushed (`sha256:600863c4...`). `make tf-apply APP_ENV=dev` confirmed no infrastructure drift.
- All local commits pushed: `c0faed4` (run_crawler + tests + tickets) on `main`.

### Canonical seeds (in scraper-pipeline, committed + pushed)
- `dim_map_brand.csv`: +36 bloomingdales rows (413→449). 8 new canonical slugs: `anya_hindmarch`, `gianvito_rossi`, `july`, `krivokoso`, `kurt_geiger`, `moncler`, `pucci`, `verafied`; 28 reuse ounass/level slugs.
- `dim_map_site_category_subcategory.csv`: +22 bloomingdales rows (35→56). EN + AR bag subcategory pairs. `Lanyards and Keyrings` and its AR equivalent both mapped to `bag_accessories`.
- `dim_map_gender.csv`: +2 rows (`women,Women,bloomingdales,0` and `women,النساء,bloomingdales,0`).
- Arabic brand i18n is a separate later task — brands are Latin-script only in bloom source.

### Image serving (tickets/image_serving.md updated)
- CloudFront live at `https://d2wbzj01hegmbm.cloudfront.net` (implemented in `price-comparison-web`, 2026-06-27).
- URL scheme: `/i/{sha256}.{ext}` → `bronze/{env}/images/by-hash/{sha256}.{ext}` via CloudFront Function.
- Placeholder domain is temporary — pending custom `images.{domain}` once site name confirmed.
- Remaining: custom domain + image resizing (separate ticket).

### GCC expansion notes (in bloomingdales_crawl.md)
- `get_language` is GCC-ready (`en.` prefix, not SA-specific).
- Two SA-specific constants to update per country: `LOCALE_MAP` (`ar_SA`/`en_SA`) and `SFCC_SITE_ID` (`BloomingDales_SA-Site`).

### Bloomingdales data quality bug (not yet fixed)
- 18 items (9 EN + 9 AR) from sub-PLP filter pages emit category label as gender value and product name as subcategory — breadcrumb depth shifts on these pages. Fix: breadcrumb depth guard in `bloomingdales_rules.py`. Tracked in ticket open questions.

## 2026-06-08 - Establish product vision and reorganise project context
- Completed product brief: Arabic-first luxury fashion discovery for Saudi Arabia/GCC, aspiring Saudi women buyers first, widest range available in Saudi as core value proposition, discovery/range identity (not cheapest-price messaging), mobile-first, clean like Farfetch, new arrivals default sort, sale surfaced via filters not front-and-centre, SAR pricing, mid-term: cross-site comparison + price alerts.
- Moved `AGENTS.md` and `memory.md` into `context/`; added `context/product-brief.md`.
- `CLAUDE.md` remains in root as a thin index pointing into `context/`.
- Updated three frontend tickets (image_serving, product_api, plp_debug_ui) status to blocked on website description; website_description.md now superseded by product-brief.md.

## 2026-10-03 - Set image Content-Type metadata on S3 uploads
- Fixed `ecommercecrawl/image_downloader.py::_upload_blob` to pass `ExtraArgs={"ContentType": ...}` to `s3_client.upload_file`, so canonical image blobs are no longer stored/served as generic `binary/octet-stream`.
- Added `CONTENT_TYPE_BY_EXTENSION` and `canonical_content_type_for_extension`, keyed by the same fixed extension set `extension_from_content_type`/`extension_from_url` already use (jpg/jpeg/png/webp/gif/avif), so the uploaded media type is always derived from our own enum, never the raw upstream response header.
- `download_one_job` now passes `canonical_content_type_for_extension(content_ext)` into `_upload_blob`.
- Added 4 focused tests covering the uploader's `ExtraArgs` behavior (set when known, omitted when not) and the end-to-end `download_one_job` S3 path for JPEG/PNG/GIF/WebP; all 9 tests in `tests/test_image_downloader.py` pass.
- Part of `scraper-pipeline/ticket/set-image-content-type-metadata.md`. The dev S3 backfill (existing `bronze/dev/images/by-hash/` objects, 1176 total, currently all `binary/octet-stream`) and the required CloudFront `/i/*` cache invalidation afterward were blocked by a "Modify Shared Resources" permission denial on the in-place `copy-object` call; that part is still open and needs explicit user action.
