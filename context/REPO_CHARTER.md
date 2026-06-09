# Repo Charter

## Purpose

`ecommerce-scraper` is the data acquisition layer for the luxury fashion price
comparison system. It is responsible for fetching, extracting, validating, and
storing raw observations from luxury ecommerce retailers, and for producing the
image assets and crawl metadata that downstream systems depend on.

This repo should answer a specific question:

> How should retailer websites be crawled reliably, at scale, and with enough
> quality assurance that the observations produced can be trusted by the
> normalization and modeling layer downstream?

## Role In The Wider System

`ecommerce-scraper` is the acquisition system. It owns everything up to and
including the raw bronze S3 layer.

`../scraper-pipeline` is the interpretation layer. It consumes bronze
observations and publishes canonical, normalized, and modeled datasets.

`../price-comparison-web` is the presentation layer. It serves end users from
the gold datasets published by scraper-pipeline.

## What This Repo Is Today

- **Scrapy spiders** for Ounass and Level Shoes (PLP pagination + PDP extraction)
  with Zyte API routing for rendered pages
- **Image download pipeline**: ECS-orchestrated batch job that queries
  `stg_product_image_download_status`, downloads images, validates with Pillow,
  and stores content-addressed blobs at `bronze/images/by-hash/{sha256}`
- **Crawl quality gate**: post-crawl blank-field threshold checks; emits
  `_SUCCESS`, `_FAIL_QUALITY`, or `_FAILED` markers to S3
- **Lambda triggers**: manifest verifier writes verified manifests to
  `bronze/crawls/manifests/`; image pipeline trigger chains quality checker
  after successful downloads
- **Observability**: crawl manifests and quality reports queryable in Athena
  via `crawl_manifest_raw` and `crawl_quality_raw` Glue tables
- **Infrastructure**: Terraform-managed ECS tasks, Lambda functions, IAM roles,
  Glue tables, S3 notification triggers, and Secrets Manager wiring

## What This Repo Should Become

A reliable, observable, self-correcting acquisition system:

- **Recrawl loop closed**: `gold_pdp_recrawl_{site}_daily` outputs feed back
  into the crawler as daily seed CSVs (see `tickets/recrawl_loop.md`)
- **Scheduler**: EventBridge-driven daily crawl orchestration replacing manual
  `make` invocations (see `tickets/crawl_scheduler.md`)
- **Wider site coverage**: additional luxury retailers added as new Scrapy
  spiders following the same spider/quality/image pipeline pattern
- **Image pipeline trigger automated**: Lambda triggers image pipeline on crawl
  `_SUCCESS` without manual intervention (see `tickets/image_pipeline_trigger.md`)

## Owned Responsibilities

- Scrapy spiders: PLP pagination, PDP extraction, site-specific request handling
- Crawl orchestration: ECS task definitions, Makefile targets, seed management
- Crawl quality gate: blank-field checks, quality report emission
- Image download and validation pipeline: download, SHA256 store, Pillow validate
- Lambda triggers: manifest verification, Glue partition registration, pipeline chaining
- Bronze S3 layer: raw crawl data, manifests, quality reports, image blobs
- Crawl observability: Athena-queryable manifests and quality reports
- Infrastructure: Terraform for all of the above

## Non-Responsibilities

- Data normalization, canonical seeds, or dbt models (`../scraper-pipeline`)
- Gold table publication or serving contracts (`../scraper-pipeline`)
- Frontend UI or product API (`../price-comparison-web`)
- Product matching or cross-site deduplication (`../product-matching`)

## Principles

- Acquisition can be noisy and site-specific. This repo absorbs that.
- Every crawl should produce a verifiable artifact (manifest + quality report).
- Images are content-addressed: the blob store is immutable by design.
- Infrastructure is Terraform-managed; no manual console changes.
- New spiders follow the existing spider → quality gate → image pipeline pattern.
