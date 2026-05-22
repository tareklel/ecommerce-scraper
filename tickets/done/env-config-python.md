# Ticket: Environment-Aware Config — Python, Scripts, Makefile

**Status: draft — not reviewed**

## Goal

Add a central environment config and wire it through all Python scripts and
Makefile targets so crawl, image, and recrawl workflows can run explicitly against
`dev` or `prod` without hardcoded paths or table names.

Source ticket: `scraper-pipeline/ticket/environment-aware-scraper-workflows.md`

---

## New S3 Path Convention

```
old crawl data:      bronze/crawls/{env}/{site}/{dt}/{run_id}/
new crawl data:      bronze/{env}/crawls/{site}/{dt}/{run_id}/

old crawl metadata:  bronze/crawls/metadata/{env}/{site}/{dt}/{run_id}/
new crawl metadata:  bronze/{env}/crawls/metadata/{site}/{dt}/{run_id}/

old image log:       bronze/images/download_log/dt={dt}/
new image log:       bronze/{env}/images/download_log/dt={dt}/

old image validated: bronze/images/validated/dt={dt}/
new image validated: bronze/{env}/images/validated/dt={dt}/

old image blobs:     bronze/images/by-hash/
new image blobs:     bronze/{env}/images/by-hash/
```

---

## 1. Add `config/environments.yaml`

```yaml
dev:
  dbt_database: price_comparison_dev
  bronze_database: price_comparison_dev
  bronze_s3_prefix: s3://price-comparison-bucket-eu-central-1/bronze/dev/
  dbt_s3_prefix: s3://price-comparison-bucket-eu-central-1/dbt/dev/
  recrawl_seed_prefix: s3://price-comparison-bucket-eu-central-1/recrawl-seeds/dev/
  image_catalog_table: silver_product_image_download_status
  serving_table: gold_product_serving_latest
  recrawl_level_shoes_table: gold_pdp_recrawl_level_shoes_daily
  recrawl_ounass_table: gold_pdp_recrawl_ounass_daily

prod:
  dbt_database: price_comparison_prod
  bronze_database: price_comparison_prod
  bronze_s3_prefix: s3://price-comparison-bucket-eu-central-1/bronze/prod/
  dbt_s3_prefix: s3://price-comparison-bucket-eu-central-1/dbt/prod/
  recrawl_seed_prefix: s3://price-comparison-bucket-eu-central-1/recrawl-seeds/prod/
  image_catalog_table: silver_product_image_download_status
  serving_table: gold_product_serving_latest
  recrawl_level_shoes_table: gold_pdp_recrawl_level_shoes_daily
  recrawl_ounass_table: gold_pdp_recrawl_ounass_daily
```

Do not use string templates like `price_comparison_{env}`. Names stay explicit.

## 2. Add `ecommercecrawl/env_config.py`

Small loader:
- reads `config/environments.yaml`
- accepts `app_env: str`
- returns a config dict
- raises immediately for unknown environments
- never silently defaults to `prod` — local default is `dev`

## 3. Update `ecommercecrawl/pipelines.py`

Change S3 upload paths from:
```
bronze/crawls/{app_env}/{site}/{dt}/{run_id}/
bronze/crawls/metadata/{app_env}/{site}/{dt}/{run_id}/
```
to:
```
bronze/{app_env}/crawls/{site}/{dt}/{run_id}/
bronze/{app_env}/crawls/metadata/{site}/{dt}/{run_id}/
```

Validate `APP_ENV` is `dev` or `prod`; fail fast otherwise.

## 4. Update `run_image_pipeline.py`

- add `--app-env`, default `dev`
- load environment config
- use `dbt_database` when querying `silver_product_image_download_status`
- use `bronze_database` for `image_download_log` reads and partition registration
- write image download logs and markers under `bronze/{env}/images/`

Pending image query must fully qualify both sides:
```sql
FROM {dbt_database}.{image_catalog_table} c
LEFT JOIN {bronze_database}.image_download_log s
```

## 5. Update `scripts/image_quality_checker.py`

- add `--app-env`, default `dev`
- load environment config
- write validated metadata under `bronze/{env}/images/validated/`
- register partitions in `bronze_database` from config

## 6. Update Makefile

Replace single targets with explicit dev/prod variants:

```makefile
IMAGE_PIPELINE_APP_ENV ?= dev

run-image-pipeline-local:
	poetry run python run_image_pipeline.py --app-env $(IMAGE_PIPELINE_APP_ENV) ...

ecs-run-image-pipeline-dev:
	# passes --app-env dev explicitly

ecs-run-image-pipeline-prod:
	# passes --app-env prod explicitly — never reachable through a default
```

Same pattern for quality checker and recrawl export targets.

---

## Files to Change

| File | Change |
|------|--------|
| `config/environments.yaml` | New — central env config |
| `ecommercecrawl/env_config.py` | New — config loader |
| `ecommercecrawl/pipelines.py` | New bronze S3 paths |
| `run_image_pipeline.py` | `--app-env`, split dbt/bronze databases, new S3 paths |
| `scripts/image_quality_checker.py` | `--app-env`, new S3 paths, bronze database from config |
| `Makefile` | Explicit dev/prod targets |

---

## Acceptance Criteria

- Config loader raises for unknown env, never silently defaults to prod.
- `run_image_pipeline.py --app-env dev` reads `price_comparison_dev` dbt tables and writes under `bronze/dev/images/`.
- `pipelines.py` writes crawl data under `bronze/{env}/crawls/`.
- All Makefile targets require an explicit env choice for prod runs.
- Unit tests updated to reflect new paths and table names.

---

## Depends On

Nothing — can be developed and tested locally before infra changes.

## Blocks

`env-config-infra` — Lambda and Terraform must align with the paths this ticket produces.
