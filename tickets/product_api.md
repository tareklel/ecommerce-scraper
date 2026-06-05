# Ticket: Minimal Product Read API

**Status: rumination — blocked on website description (see `tickets/website_description.md`)**

## Goal

Expose `gold_product_serving_latest` to the UI layer as a queryable HTTP API.

---

## Why This Layer Exists

`gold_product_serving_latest` lives in Athena (S3 + Glue metastore). A browser
cannot query Athena directly — there is no browser SDK, and each Athena query
costs ~$0.005 and takes 2–10 seconds of scan time. The API is the translation
layer between "queryable data warehouse" and "fast HTTP response the UI can use."

Beyond MVP, this is also where:
- Product matching logic gets applied (merge cross-site rows for the same item)
- Price history is served (query `silver_product_fact_*` over a date range)
- Personalisation or saved searches would be anchored
- A mobile app or third-party integration calls the same endpoints

Getting the API shape right early avoids a schema migration when those features arrive.

---

## What it needs to do (MVP)

Single endpoint:

```
GET /products
  ?site=ounass,level-shoes   (optional, multi-value)
  ?brand=gucci               (optional, canonical)
  ?category=shoes            (optional, canonical)
  ?subcategory=sneakers      (optional, canonical)
  ?language=ar               (optional, en or ar)
  ?page=1&page_size=48
```

Response: paginated list of product rows from `gold_product_serving_latest`,
image URL constructed from `IMAGE_CDN_HOST + s3_blob_key`.

---

## Option A: FastAPI on AWS Lambda (+ API Gateway)

Lambda function containing a FastAPI app, deployed via Lambda function URL or
API Gateway. Queries Athena on each request (or reads from a cache).

**Strengths**
- No always-on cost — Lambda scales to zero when idle, ideal for low-traffic MVP
- Lambda already used in the project (manifest verifier, image pipeline trigger) —
  same deployment pattern, same IAM/Terraform muscle memory
- Fast to ship: no ECS task definition, no load balancer, no service discovery

**Weaknesses**
- Cold start: Python + FastAPI + boto3 takes ~1–3 seconds on first request after
  idle. Combined with Athena scan time (2–10s), first-request latency can be 5–13s.
- Athena is a bad fit for interactive queries: 2–10s per query is acceptable for
  batch but noticeable in a UI. Mitigation: cache the full result set after each
  dbt run and serve from that cache (DynamoDB, S3 JSON, or Lambda memory with a TTL).
- 15-minute execution limit and 10GB memory ceiling — not a constraint for this use
  case but worth knowing.
- Connection pooling is meaningless in a stateless Lambda; if the API ever needs a
  persistent DB this becomes a problem.

**Mitigating Athena latency in Lambda:** After each dbt run, a post-run trigger
exports `gold_product_serving_latest` to a compressed JSON file at a known S3 path.
Lambda reads that file on cold start, holds it in memory for the lifetime of the
container (~15 minutes), and serves filtered slices from memory. Athena is only
queried for the export, not per-request. This pattern keeps Lambda viable and
response time under 200ms for warm requests.

**Long-term fit:** Acceptable for the product catalogue use case (read-heavy, daily
refresh cadence). Becomes awkward if real-time price updates or websockets are needed.

---

## Option B: FastAPI on ECS (Fargate)

A persistent ECS Fargate service running FastAPI, always on.

**Strengths**
- No cold starts — always warm, <50ms response time
- Can hold a full in-memory product cache that refreshes on a schedule (no S3 round-trip
  per request)
- Easier to add background tasks (cache refresh, health checks)
- Straightforward path to adding Redis or a proper DB later

**Weaknesses**
- Always-on cost: a minimal Fargate task (0.25 vCPU / 0.5GB) costs ~$10–15/month
  even at zero traffic — not significant but non-zero for a dev MVP
- More Terraform: ECS service, ALB or service connect, target group, security groups
- Another ECS task definition to maintain alongside image-pipeline and quality-checker

**Long-term fit:** This is the right shape for production. If the product eventually
has real user traffic, ECS (or EKS) is the natural home. ECS is already the execution
environment for batch jobs in this project, so the operational model is familiar.

---

## Recommendation

**Lambda for MVP, with a plan to migrate to ECS when traffic justifies it.**

The decisive factor is the Athena latency problem — but it disappears if the API
reads from a daily snapshot export rather than live Athena queries. Lambda + snapshot
cache gives fast responses, zero idle cost, and reuses existing deployment patterns.
The Lambda-to-ECS migration later is straightforward (same FastAPI app, different
host).

The snapshot export (a single compressed JSON or Parquet file written after dbt run)
is also independently useful: it's the artifact the UI and any future mobile app
consume, and it decouples the UI from dbt run timing.

---

## Proposed Architecture

```
dbt run completes
  → post-run script: Athena UNLOAD gold_product_serving_latest → s3://bucket/api-cache/latest.json.gz
  → Lambda reads latest.json.gz on cold start, caches in memory
  → GET /products → filter in-memory slice → return JSON
  → CloudFront CDN host prepended to s3_blob_key for image URLs
```

---

## Work Items

| File | Change |
|------|--------|
| `api/main.py` | New — FastAPI app, `/products` endpoint, in-memory cache from S3 snapshot |
| `scripts/export_api_cache.py` | New — Athena UNLOAD or boto3 scan → `api-cache/latest.json.gz` after dbt run |
| `infra/terraform/lambda.tf` | New Lambda function for API, function URL or API Gateway |
| `infra/terraform/iam.tf` | IAM: Lambda reads `api-cache/` prefix, no direct Athena access needed |
| `Makefile` | `run-api-local` target |

---

## Open Questions

- [ ] Athena UNLOAD or boto3 paginate-scan for the cache export? UNLOAD is simpler
      but requires Athena output bucket permissions; boto3 scan is more portable.
- [ ] Should the cache export be triggered by a dbt post-run hook or a separate
      EventBridge rule after the dbt ECS task exits?
- [ ] Pagination in-memory (slice the list) or cursor-based? Cursor is more correct
      but adds complexity; slice is fine for MVP catalogue sizes.
- [ ] Authentication on the API? Even a shared API key header to prevent public access
      during development.
