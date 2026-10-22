# Crawl Run Status and Markers (all crawls)

**What this doc is:** how every crawl run is classified, what lands in S3,
and what a person should do about it. It applies to all spiders (Ounass,
Level, Farfetch, Bloomingdale's), normal and PLP-efficient mode. Keep it
current: any change to run statuses, failure reasons or markers updates this
doc in the same commit (`context/AGENTS.md`). `tests/test_crawl_run_status_docs.py`
fails if a marker or failure reason in the verifier is missing here.

Code: `ecommercecrawl/pipelines.py` (`crawler_run_status`, the crawler's own
view, written into the manifest) and `lambda/bronze_manifest_verifier/handler.py`
(`FAILURE_REASONS`, the final call, after checking the file).

---

## The one question

**Did the crawler reach its own end, and did it skip anything on purpose?**

| `run_status` | Meaning | Marker | Rows reach raw / dbt |
|---|---|---|---|
| `success` | Reached its end, nothing skipped | `_SUCCESS` | yes |
| `degraded` | Reached its end, but some work was skipped. The manifest's `degradations` lists each skip as `{kind: content \| access, scope, message}` | `_SUCCESS` | yes: everything it wrote. Skipped products keep their previous values |
| `failed` | Rows can't be trusted, or the run didn't finish. See `failure_reason` | one per reason (below) | **no**: the file stays in `crawl-unverified/` |
| `killed` | Started (record in `crawl_started_raw`) but never wrote a manifest: hard kill, out-of-memory | none | no |

## Failure markers

Written by the verifier Lambda to
`bronze/<env>/crawls/markers/<site>/<dt>/<run_id>/`, one per reason that
applies. The first in this order is the run's `failure_reason`.

| Marker | `failure_reason` | Written when | Example | What to do |
|---|---|---|---|---|
| `_FAIL_ABORTED` | `aborted` | The crawl closed for any reason other than finishing (`exit_reason` ≠ `finished`) | Ctrl+C, ECS task stopped | Re-run. If it recurs, check why the task was stopped |
| `_FAIL_STARTUP_CHECK` | `startup_check` | A PLP-efficient run stopped before any request | broken registry, export Lambda failed | `make preflight-ounass-plp-efficient` lists every failed check |
| `_FAIL_ACCESS` | `access` | **No rows written**, and requests were given up on blocking after every retry round | 2026-10-20 Acler run: Saudi Zyte ban | Manifest `access` block shows which hostnames and errors; check Zyte routing (`CRAWLER_API_ZYTE_GEOLOCATION_BY_HOST`); re-run later |
| `_FAIL_QUALITY` | `quality` | The quality gate failed, or nothing was written for a reason **other than** blocking | 2026-10-20 Burberry run: URL 404, zero rows | `metadata/quality_report.json`; check the seed URL still exists and the page format |
| `_FAILED` | `verification` | The **file check** failed: data file missing, hash or row-count mismatch, unreadable manifest, or the copy into `crawls/` failed | upload cut off halfway | Verifier Lambda logs; re-run |

**Failures explain themselves** (2026-10-22). Every failure marker's JSON,
the verified manifest (`failure_explanation`) and the crawler's `RUN FAILED`
log line carry a plain-language `meaning`, `what_to_do` and a link to this
section, so you can read what a failure means wherever you meet it:

```json
{"run_status": "failed", "failure_reason": "access",
 "meaning": "Nothing was written because the site blocked our requests through every retry round.",
 "what_to_do": "See the manifest's access block for which hostnames and errors; check Zyte routing (CRAWLER_API_ZYTE_GEOLOCATION_BY_HOST); re-run later.",
 "doc": "docs/crawl_run_status.md#failure-markers", "...": "other fields"}
```

The texts live in the verifier (`FAILURE_REASONS`) and, as an identical copy
for the crawler's logs, in `ecommercecrawl/run_status.py` (the Lambda ships
as its own zip and can't import the crawler).
`tests/test_run_status_explanations.py` fails if the copies differ. Change
the wording in both places.

Notes:
- `_FAILED` is the oldest marker and only means "the file didn't verify". It
  would read better as `_FAIL_VERIFICATION`; it keeps its name because older
  runs carry it.
- A startup-stopped or fully blocked run has no data file by design, so it
  gets only its own marker, not `_FAIL_QUALITY` / `_FAILED` as well.
- Causes can stack: an aborted run whose file is also broken gets
  `_FAIL_ABORTED` + `_FAILED`, `failure_reason aborted`.
- Nothing reads the failure markers automatically. Only `_SUCCESS` triggers
  anything (it registers the data partition). Alerting is planned in
  `tickets/cicd_pipeline.md`.

## Where a run's data and record go

1. **Start:** `bronze/<env>/crawl-started/<site>/<dt>/<run_id>.json`
   (table `crawl_started_raw`), only when uploads are on (`APP_ENV=prod` or
   `S3_UPLOAD_ENABLED=true`).
2. **End:** the crawler uploads the data file to
   `bronze/<env>/crawl-unverified/<site>/<dt>/<run_id>/` (read by nothing)
   and the manifest to `bronze/<env>/crawls/metadata/…`.
3. **Verifier:** checks the file and decides the final status.
   - **Pass** (`success` / `degraded`): copies the file to
     `bronze/<env>/crawls/<site>/<dt>/<run_id>/`, the folder Athena reads,
     then writes `_SUCCESS`, which registers the day's partition.
   - **Fail:** the file stays in `crawl-unverified/`, and the failure markers
     are written.
4. **Record:** every verified manifest, failed ones included, goes to
   `crawl_manifest_raw` (`raw_json` holds the whole manifest: `run_status`,
   `failure_reason`, `degradations`, `access`, `verification`, and for
   PLP-efficient runs `plp_efficient`).
5. **Logs** (CloudWatch `/ecs/<ecs_name>`), end of run: `RUN DEGRADED`
   (with what was skipped), `RUN FAILED <reason>: <meaning> What to do: …`,
   and `ACCESS <hostname>` for any hostname with access failures.

Why publish-on-pass: Athena reads a whole day folder once any run that day
writes `_SUCCESS`. Before 2026-10-16, a failed run's file sat next to a
passing run's file and was read too.

## Useful queries

Runs by status (Athena, `price_comparison_<env>`):

```sql
select dt, json_extract_scalar(raw_json, '$.run_id') as run_id,
       json_extract_scalar(raw_json, '$.run_status') as run_status,
       json_extract_scalar(raw_json, '$.failure_reason') as failure_reason
from crawl_manifest_raw
where site = 'ounass' and dt >= '2026-10-20'
order by 2;
```

Killed runs (started, no manifest):

```sql
select s.crawler_name, s.dt, s.run_id, s.started_at
from crawl_started_raw s
left join crawl_manifest_raw m on m.run_id = s.run_id
where m.run_id is null;
```

## Related

- Access layer (retry rounds, blocked hostnames, `kind: access`):
  `docs/ounass_plp_efficient_crawl.md`, section 5, "Access retry rounds".
- Quality gate rules: `docs/fail_quality_contract.md`.
- Design history: `tickets/ounass_plp_efficient_crawl.md`, Part 4.
