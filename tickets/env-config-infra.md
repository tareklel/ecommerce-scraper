# Ticket: Environment-Aware Config — Lambda, Terraform, IAM

**Status: draft — not reviewed**

## Goal

Update the Lambda handler, Terraform S3 notification filters, and IAM grants to
align with the new `bronze/{env}/...` path layout and env-split databases
introduced in `env-config-python`.

Source ticket: `scraper-pipeline/ticket/environment-aware-scraper-workflows.md`

---

## Depends On

`env-config-python` must be merged first. Lambda paths must match what `pipelines.py` writes.

---

## 0. Pre-Deploy Audit (do this before any code changes)

Before touching Lambda or Terraform, audit all tickets and code in this repo for
stale naming and path assumptions. Find and fix every occurrence of:

| Old | New |
|-----|-----|
| `bronze/crawls/{env}/` | `bronze/{env}/crawls/` |
| `bronze/crawls/metadata/{env}/` | `bronze/{env}/crawls/metadata/` |
| `bronze/images/download_log/` | `bronze/{env}/images/download_log/` |
| `bronze/images/validated/` | `bronze/{env}/images/validated/` |
| `bronze/images/by-hash/` | `bronze/{env}/images/by-hash/` |
| `stg_product_image_download_status` | `silver_product_image_download_status` |
| `stg_pdp_recrawl_level_shoes_daily` | `gold_pdp_recrawl_level_shoes_daily` |
| `stg_pdp_recrawl_ounass_daily` | `gold_pdp_recrawl_ounass_daily` |
| `price_comparison_dbt/` | `dbt/dev/` and `dbt/prod/` |
| `price_comparison` (bare database name) | `price_comparison_dev` or `price_comparison_prod` |

Scope: all `.md` files in `tickets/`, all `.py` scripts, all `.tf` files,
`Makefile`, `README.MD`.

This audit should be its own commit before the Lambda/Terraform changes so stale
references are cleaned up independently of functional changes.

---

## 1. Update `lambda/bronze_manifest_verifier/handler.py`

Current hardcoded assumptions:
```python
BRONZE_METADATA_PREFIX = "bronze/crawls/metadata/"
BRONZE_DATA_PREFIX = "bronze/crawls/"
```

Required behavior:
- read `APP_ENV` from Lambda environment variable
- default to `dev` only for local/test runs — never silently to prod
- read metadata from `bronze/{app_env}/crawls/metadata/`
- derive data prefix as `bronze/{app_env}/crawls/`
- register partitions in the bronze database from environment config
- remove `env` from partition keys — partition spec is `site`, `dt` only

## 2. Update Terraform S3 Notification Filter (`infra/terraform/lambda.tf`)

Change the S3 event notification prefix for `bronze_manifest_verifier` from:
```
bronze/crawls/metadata/
```
to:
```
bronze/dev/crawls/metadata/     # dev stack
bronze/prod/crawls/metadata/    # prod stack
```

Drive this from a Terraform variable so the same config deploys to both stacks.

## 3. Update Terraform Variables (`infra/terraform/variables.tf`)

Add:
```hcl
variable "app_env" {
  type    = string
  default = "dev"
  validation {
    condition     = contains(["dev", "prod"], var.app_env)
    error_message = "app_env must be dev or prod"
  }
}

variable "bronze_database_name" {
  type    = string
  default = "price_comparison_dev"
}

variable "dbt_database_name" {
  type    = string
  default = "price_comparison_dev"
}
```

Update ECS task commands for image pipeline and quality checker to pass
`--app-env ${var.app_env}`.

## 4. Update IAM (`infra/terraform/iam_ecs.tf` and `iam.tf`)

Replace old S3 grant:
```
price_comparison_dbt/*
```

With:
```
dbt/dev/*
dbt/prod/*
bronze/dev/*
bronze/prod/*
```

Ensure image pipeline task role, quality checker task role, and manifest verifier
Lambda role all cover the new prefixes.

---

## Files to Change

| File | Change |
|------|--------|
| `lambda/bronze_manifest_verifier/handler.py` | `APP_ENV` from env var, new S3 paths, updated partition keys |
| `infra/terraform/lambda.tf` | S3 notification filter prefix driven by `var.app_env` |
| `infra/terraform/variables.tf` | Add `app_env`, `bronze_database_name`, `dbt_database_name` |
| `infra/terraform/ecs.tf` | Pass `--app-env` to image pipeline and quality checker commands |
| `infra/terraform/iam_ecs.tf` | New S3 grants for `dbt/dev/*`, `dbt/prod/*`, `bronze/dev/*`, `bronze/prod/*` |
| `infra/terraform/iam.tf` | Same for Lambda role |

---

## Acceptance Criteria

- Lambda reads metadata from `bronze/{env}/crawls/metadata/` where `env` comes from `APP_ENV`.
- S3 notification filter matches the deployed env's metadata prefix.
- IAM grants cover `dbt/dev/*`, `dbt/prod/*`, `bronze/dev/*`, `bronze/prod/*`.
- No code path silently defaults to prod.
- All stale path/table name references removed from tickets and code (audit commit).
- `tf-apply` with `app_env=dev` deploys a dev-only stack; prod requires explicit override.

---

## Follow-up Before First Prod Deploy

- Create and register prod bronze tables in Glue.
- Ensure prod crawlers write only to `bronze/prod/...`.
- Run explicit prod dbt deployment only after `bronze/prod/` contains deliberate prod data.
