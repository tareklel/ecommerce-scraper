# Ticket: Close the Recrawl Loop — dbt Candidates → Crawler Input

**Status: draft — not reviewed**

## Goal

`gold_pdp_recrawl_{site}_daily` already computes which PDPs need recrawling and
why (OOS recheck, sale recheck, stale fact). This ticket wires that output back
into the crawler as a daily `--urls-source` seed, closing the feedback loop the
dbt model was designed for.

---

## Current State

- dbt writes `gold_pdp_recrawl_level_shoes_daily` and `gold_pdp_recrawl_ounass_daily`
  as Athena-queryable tables partitioned by `[site, dt]`
- Each row has: `primary_key`, `country`, `pdp_url`, `reason_code`
- The crawler accepts `--urls-source s3://` via `run_crawler.py`
- **Gap:** nothing exports the recrawl candidates to S3 as a CSV seed

---

## Proposed Flow

```
dbt run (daily)
  → gold_pdp_recrawl_{site}_daily partition for today
  → export job: Athena UNLOAD → s3://price-comparison-bucket-eu-central-1/recrawl-seeds/{site}/dt={dt}/urls.csv
  → crawl job reads --urls-source s3://.../{site}/dt={today}/urls.csv
```

---

## Export Step

A new ECS job (or Lambda for small volumes) runs after dbt and executes:

```sql
-- Athena UNLOAD to S3 CSV
UNLOAD (
  SELECT pdp_url
  FROM {dbt_database}.gold_pdp_recrawl_level_shoes_daily
  WHERE dt = '{dt}'
)
TO 's3://price-comparison-bucket-eu-central-1/recrawl-seeds/level-shoes/dt={dt}/'
WITH (format = 'TEXTFILE', field_delimiter = ',')
```

Repeat per site. Output is a single `url` column CSV — compatible with existing
`--urls-source` parsing in `run_crawler.py`.

**Alternative:** dbt post-hook using `UNLOAD` — avoids a separate job but ties
dbt run time to S3 export. Prefer a separate job for cleaner failure isolation.

---

## Crawler Changes

None to `run_crawler.py` — `--urls-source s3://` already works. The only change
is in how the daily crawl is invoked (pass the recrawl seed path instead of a
full-site seed).

---

## Makefile Target

```makefile
run-recrawl-local:
	poetry run python run_crawler.py \
	  --site $(SITE) \
	  --urls-source s3://$(PRICE_COMPARISON_BUCKET)/recrawl-seeds/$(SITE)/dt=$(DT)/urls.csv \
	  --env $(ENV)
```

---

## Files to Change

| File | Change |
|------|--------|
| `scripts/export_recrawl_seeds.py` | New — Athena UNLOAD per site for a given `--dt` |
| `infra/terraform/ecs.tf` | New ECS task definition for `export-recrawl-seeds` |
| `infra/terraform/iam_ecs.tf` | IAM grants: Athena read on `gold_pdp_recrawl_*`, S3 write on `recrawl-seeds/` |
| `Makefile` | `run-recrawl-export-local` and `ecs-run-recrawl-export` targets |

---

## Open Questions

- [ ] Should the export job run per-site sequentially or as parallel ECS tasks?
- [ ] What happens if `gold_pdp_recrawl_*` has 0 rows for a site on a given day — skip or still trigger crawl?
- [ ] Should `reason_code` be passed through to the crawler for priority ordering, or is URL list enough?
- [ ] Who triggers the export job — EventBridge after dbt, or chained from the crawl scheduler ticket?
