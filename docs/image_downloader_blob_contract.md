# Image Downloader Blob Contract

This document defines the JSONL result blob contract produced by:
- `run_image_downloader.py`
- `ecommercecrawl/image_downloader.py` (`_result_blob`)

Each line in a results file is one JSON object with this schema version:
- `schema_version: "image_download_result_v1"`

## Input contract

The downloader supports exactly one input mode per run.

### Mode 1: JSONL batch mode

Use:

```bash
python3 run_image_downloader.py --input-jsonl <path>
```

Each line must be a JSON object. Required fields per row:
- `site`
- `primary_key` (alias accepted: `unique_id`)
- image URL as `image_url` or `image_urls`

Optional per row:
- `source_run_id` (alias accepted: `run_id`)

Transitional fallback:
- If `primary_key` is missing but `portal_itemid` and `site` exist, downloader derives `primary_key` as `<portal_itemid>_<site>`.

Supported `site` values:
- `farfetch`
- `ounass`
- `level-shoes`
- `level_shoes` (alias)
- `level` (alias)

Example JSONL lines:

```json
{"site":"level-shoes","primary_key":"8119826_level-shoes","image_urls":"https://assets.levelshoes.com/...jpg?ts=20251120165020","run_id":"2026-02-23T14-09-16-758"}
{"site":"ounass","primary_key":"218511926_ounass","image_urls":"ounass-ae.atgcdn.ae/.../218511841_beige_in.jpg?ts=1752483038.634","run_id":"2026-02-26T14-26-22-999"}
```

### Mode 2: Inline single-job mode

Use:

```bash
python3 run_image_downloader.py \
  --site <site> \
  --primary-key <primary_key> \
  --image-url <image_url> \
  [--source-run-id <source_run_id>]
```

Required flags:
- `--site`
- `--primary-key`
- `--image-url`

Optional flag:
- `--source-run-id`

### Validation behavior

- `--input-jsonl` cannot be combined with inline flags.
- Missing required fields are emitted as `skipped_invalid` in output results.
- Unsupported `site` values are emitted as invalid job input.

## Top-level fields

- `schema_version` (`string`): contract version.
- `status` (`string`): one of `ok`, `error`, `skipped_invalid`, `skipped_duplicate`.
- `reason` (`string`): machine-readable reason within a status.
- `event_time_utc` (`string`): ISO-8601 UTC timestamp when blob was emitted.
- `download_run_id` (`string`): run id generated once per downloader execution.
- `job` (`object`):
  - `job_id` (`string|null`): SHA1 of `site|primary_key|normalized_image_url`.
  - `site` (`string|null`): normalized site (`farfetch`, `level-shoes`, `ounass`).
  - `primary_key` (`string|null`): canonical product key for image handler.
  - `source_run_id` (`string|null`): source crawl run id, if provided.
  - `input_source` (`object|null`): source location metadata (example: JSONL path + line number).
- `request` (`object`):
  - `image_url` (`string|null`): raw input URL.
  - `normalized_image_url` (`string|null`): normalized URL actually requested.
- `storage` (`object`):
  - `output_path` (`string|null`): local image path for `ok`.
  - `canonical_blob_key` (`string|null`): content-addressed key.
  - `primary_key_pointer_key` (`string|null`): primary-key pointer key.
- `transfer` (`object`):
  - `bytes` (`number|null`): bytes written for `ok`.
  - `content_sha256` (`string|null`): content hash for `ok`.
  - `content_type` (`string|null`): response content type when known.
  - `http_status` (`number|null`): HTTP status when known.
- `error` (`object|null`):
  - `type` (`string|null`): exception type.
  - `message` (`string`): error message.
- `details` (`object`): status-specific metadata (always present, may be empty).

## Status and reason matrix

- `ok`
  - `downloaded`
- `error`
  - `invalid_job_input`
  - `request_failed`
  - `non_image_content_type`
- `skipped_invalid`
  - `invalid_json`
  - `missing_required_fields`
  - `invalid_job_input`
- `skipped_duplicate`
  - `duplicate_job`

## Path/key conventions

- Local output path:
  - `<output_dir>/<site>/<source_run_id_or_download_run_id>/<primary_key>_<url_sha10><ext>`
- Canonical blob key:
  - `silver/images/by-hash/<content_sha256><ext>`
- Primary-key pointer key:
  - `silver/images/by-primary/<site>/<primary_key>/<content_sha256><ext>`

## Minimal examples

```json
{"schema_version":"image_download_result_v1","status":"ok","reason":"downloaded","event_time_utc":"2026-02-28T12:00:00.000000+00:00","download_run_id":"2026-02-28T12-00-00-000","job":{"job_id":"...","site":"level-shoes","primary_key":"8119826_level-shoes","source_run_id":"2026-02-23T14-09-16-758","input_source":{"jsonl_path":"resources/image_download_test_jobs.jsonl","line_no":1}},"request":{"image_url":"https://...jpg","normalized_image_url":"https://...jpg"},"storage":{"output_path":"output/images/level-shoes/2026-02-23T14-09-16-758/8119826_level-shoes_abc123.jpg","canonical_blob_key":"silver/images/by-hash/<sha>.jpg","primary_key_pointer_key":"silver/images/by-primary/level-shoes/8119826_level-shoes/<sha>.jpg"},"transfer":{"bytes":19150,"content_sha256":"<sha256>","content_type":"image/jpeg","http_status":200},"error":null,"details":{}}
{"schema_version":"image_download_result_v1","status":"skipped_duplicate","reason":"duplicate_job","event_time_utc":"2026-02-28T12:00:00.000000+00:00","download_run_id":"2026-02-28T12-00-00-000","job":{"job_id":"...","site":"level-shoes","primary_key":"8119826_level-shoes","source_run_id":"2026-02-23T14-09-16-758","input_source":{"jsonl_path":"resources/image_download_test_jobs.jsonl","line_no":2}},"request":{"image_url":"https://...jpg","normalized_image_url":"https://...jpg"},"storage":{"output_path":null,"canonical_blob_key":null,"primary_key_pointer_key":null},"transfer":{"bytes":null,"content_sha256":null,"content_type":null,"http_status":null},"error":null,"details":{}}
{"schema_version":"image_download_result_v1","status":"skipped_invalid","reason":"missing_required_fields","event_time_utc":"2026-02-28T12:00:00.000000+00:00","download_run_id":"2026-02-28T12-00-00-000","job":{"job_id":null,"site":null,"primary_key":null,"source_run_id":null,"input_source":{"jsonl_path":"resources/image_download_test_jobs.jsonl","line_no":7}},"request":{"image_url":null,"normalized_image_url":null},"storage":{"output_path":null,"canonical_blob_key":null,"primary_key_pointer_key":null},"transfer":{"bytes":null,"content_sha256":null,"content_type":null,"http_status":null},"error":null,"details":{"missing_fields":["primary_key"]}}
{"schema_version":"image_download_result_v1","status":"error","reason":"request_failed","event_time_utc":"2026-02-28T12:00:00.000000+00:00","download_run_id":"2026-02-28T12-00-00-000","job":{"job_id":"...","site":"farfetch","primary_key":"faulty-url-1_farfetch","source_run_id":"2026-02-23T14-09-16-758","input_source":{"jsonl_path":"resources/image_download_test_jobs.jsonl","line_no":5}},"request":{"image_url":"https://this-domain-should-not-exist-12345.invalid/image.jpg","normalized_image_url":"https://this-domain-should-not-exist-12345.invalid/image.jpg"},"storage":{"output_path":null,"canonical_blob_key":null,"primary_key_pointer_key":null},"transfer":{"bytes":null,"content_sha256":null,"content_type":null,"http_status":null},"error":{"type":"ConnectionError","message":"..."},"details":{}}
```
