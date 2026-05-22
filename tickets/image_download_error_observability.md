# Image Download Error Observability

**Status:** draft — not reviewed

## Problem

When image downloads fail, the reason is invisible. The `status=error` row in the download log has no `error_message`, no HTTP status, no reason field — just a `canonical_blob_key` that was never written. Diagnosing failures requires guesswork (today: discovered via AccessDenied IAM gap only by reading ECS logs manually).

Two surfaces are broken:
1. **Recorded data** (`download_log/dt=.../data.jsonl.gz`) — error rows have no `reason` or `error_message` field even though `_result_blob` accepts both.
2. **ECS/CloudWatch logs** — `run_image_pipeline.py` logs aggregate counts (`error=29`) but never logs individual failure reasons.

## What to fix

### 1. Populate `reason` and `error_message` in error rows

`_result_blob` already has `reason` and `error_message` parameters but `_build_status_rows` in `run_image_pipeline.py` only extracts `status` and `s3_blob_key`. Extend it to include:
- `reason` — from the result blob (e.g. `s3_upload_failed`, `request_failed`, `non_image_content_type`)
- `error_message` — from the result blob
- `http_status` — from the result blob request section

### 2. Log individual failures

After `download_jobs` returns, log each error row at WARN level:
```python
for r in results:
    if r.get("status") == "error":
        logger.warning("Download error pk=%s reason=%s http=%s msg=%s",
            r.get("job", {}).get("primary_key"),
            r.get("reason"),
            r.get("request", {}).get("http_status"),
            r.get("error_message"),
        )
```

### 3. Audit what `_result_blob` actually emits

Check that all error paths in `download_one_job` pass `reason=` and `error_message=` correctly — some callers omit one or both.

## Acceptance criteria

- `data.jsonl.gz` error rows contain `reason`, `error_message`, and `http_status`
- ECS logs show at least one line per failed image with enough detail to diagnose without downloading the log file
- Re-run today's failed batch and confirm root cause is visible in both surfaces
