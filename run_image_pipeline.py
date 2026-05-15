import argparse
import csv
import gzip
import io
import json
import logging
import os
import time
from collections import Counter
from datetime import datetime, timezone

import boto3

from ecommercecrawl.image_downloader import download_jobs, generate_run_id

logger = logging.getLogger(__name__)

S3_BUCKET = os.environ.get("S3_BUCKET", "price-comparison-bucket-eu-central-1")
STATUS_PARTITION_PREFIX = "bronze/images/download_status"
MARKER_SUCCESS = "_SUCCESS"
MARKER_FAILED = "_FAILED"


# ---------------------------------------------------------------------------
# Athena helpers
# ---------------------------------------------------------------------------

def _start_athena_query(athena, database, sql, output_location, workgroup):
    kwargs = {
        "QueryString": sql,
        "WorkGroup": workgroup,
        "QueryExecutionContext": {"Database": database},
    }
    if output_location:
        kwargs["ResultConfiguration"] = {"OutputLocation": output_location}
    response = athena.start_query_execution(**kwargs)
    return response["QueryExecutionId"]


def _wait_athena(athena, execution_id, timeout_seconds=120):
    deadline = time.time() + timeout_seconds
    while True:
        resp = athena.get_query_execution(QueryExecutionId=execution_id)
        state = resp["QueryExecution"]["Status"]["State"]
        if state == "SUCCEEDED":
            return resp["QueryExecution"]["ResultConfiguration"]["OutputLocation"]
        if state in ("FAILED", "CANCELLED"):
            reason = resp["QueryExecution"]["Status"].get("StateChangeReason", "")
            raise RuntimeError(f"Athena query {execution_id} ended as {state}: {reason}")
        if time.time() >= deadline:
            raise TimeoutError(f"Athena query {execution_id} timed out after {timeout_seconds}s")
        time.sleep(2)


def _parse_s3_uri(uri):
    without_scheme = uri[len("s3://"):]
    bucket, _, key = without_scheme.partition("/")
    return bucket, key


def _read_athena_csv(s3, result_uri):
    bucket, key = _parse_s3_uri(result_uri)
    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")
    reader = csv.DictReader(io.StringIO(body))
    return list(reader)


def _query_pending_images(athena, s3, database, table, output_location, workgroup,
                          status_table, limit, timeout_seconds):
    limit_clause = f"LIMIT {limit}" if limit else ""
    sql = f"""
SELECT c.site, c.primary_key, c.url
FROM {table} c
LEFT JOIN (
    SELECT site, primary_key, status,
           ROW_NUMBER() OVER (PARTITION BY site, primary_key ORDER BY dt DESC) AS rn
    FROM {status_table}
) s ON c.site = s.site AND c.primary_key = s.primary_key AND s.rn = 1
WHERE s.status IS NULL OR s.status = 'error'
{limit_clause}
""".strip()
    logger.info("Running Athena query:\n%s", sql)
    execution_id = _start_athena_query(athena, database, sql, output_location, workgroup)
    result_uri = _wait_athena(athena, execution_id, timeout_seconds=timeout_seconds)
    rows = _read_athena_csv(s3, result_uri)
    logger.info("Athena returned %d pending images", len(rows))
    return rows


# ---------------------------------------------------------------------------
# Status partition helpers
# ---------------------------------------------------------------------------

def _build_status_rows(results, dt, run_id):
    rows = []
    for r in results:
        job = r.get("job", {})
        request = r.get("request", {})
        storage = r.get("storage", {})
        rows.append({
            "site": job.get("site"),
            "primary_key": job.get("primary_key"),
            "url": request.get("image_url"),
            "run_id": run_id,
            "status": r.get("status"),
            "s3_blob_key": storage.get("canonical_blob_key"),
            "dt": dt,
        })
    return rows


def _write_status_partition(s3, bucket, dt, status_rows):
    key = f"{STATUS_PARTITION_PREFIX}/dt={dt}/data.jsonl.gz"
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        for row in status_rows:
            gz.write((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))
    buf.seek(0)
    s3.put_object(Bucket=bucket, Key=key, Body=buf.read())
    logger.info("Wrote status partition to s3://%s/%s (%d rows)", bucket, key, len(status_rows))
    return key


def _register_glue_partition(athena, database, table, dt, bucket, workgroup, output_location, timeout_seconds):
    location = f"s3://{bucket}/{STATUS_PARTITION_PREFIX}/dt={dt}/"
    sql = f"ALTER TABLE {table} ADD IF NOT EXISTS PARTITION (dt='{dt}') LOCATION '{location}'"
    execution_id = _start_athena_query(athena, database, sql, output_location, workgroup)
    _wait_athena(athena, execution_id, timeout_seconds=timeout_seconds)
    logger.info("Registered Glue partition dt=%s for table %s", dt, table)


def _write_marker(s3, bucket, dt, marker):
    key = f"{STATUS_PARTITION_PREFIX}/meta/{dt}/{marker}"
    s3.put_object(Bucket=bucket, Key=key, Body=b"")
    logger.info("Wrote marker s3://%s/%s", bucket, key)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Image download pipeline — Athena-driven.")
    parser.add_argument("--run-id", default=None, help="Trace ID for this batch (auto-generated if omitted).")
    parser.add_argument("--athena-database", required=True, help="Glue/Athena database name.")
    parser.add_argument("--athena-table", default="stg_product_image_download_status",
                        help="Image catalog table or view name.")
    parser.add_argument("--athena-status-table", default="image_download_status",
                        help="Download status table name (used for pending query + partition registration).")
    parser.add_argument("--athena-output-loc", default=None,
                        help="s3://... prefix for Athena query result CSVs.")
    parser.add_argument("--athena-workgroup", default="primary", help="Athena workgroup.")
    parser.add_argument("--athena-timeout", type=int, default=120,
                        help="Seconds to wait for each Athena query.")
    parser.add_argument("--storage-mode", choices=["local", "s3", "both"], default="s3",
                        help="Where to store downloaded images.")
    parser.add_argument("--output-dir", default="output/images",
                        help="Local output dir (used when storage-mode is local or both).")
    parser.add_argument("--max-workers", type=int, default=10,
                        help="Concurrent download threads.")
    parser.add_argument("--timeout-seconds", type=int, default=20,
                        help="HTTP timeout per image request.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Cap number of images to download (for testing).")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    run_id = args.run_id or generate_run_id()
    dt = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    bucket = S3_BUCKET

    athena = boto3.client("athena")
    s3 = boto3.client("s3")

    logger.info("Starting image pipeline run_id=%s dt=%s bucket=%s", run_id, dt, bucket)

    # 1. Query Athena for pending images
    try:
        rows = _query_pending_images(
            athena=athena,
            s3=s3,
            database=args.athena_database,
            table=args.athena_table,
            output_location=args.athena_output_loc,
            workgroup=args.athena_workgroup,
            status_table=args.athena_status_table,
            limit=args.limit,
            timeout_seconds=args.athena_timeout,
        )
    except Exception as e:
        logger.error("Athena query failed: %s", e)
        raise

    if not rows:
        logger.info("No pending images found — nothing to do.")
        return

    # 2. Build download jobs from Athena rows
    jobs = [
        {
            "site": row["site"],
            "primary_key": row["primary_key"],
            "image_url": row["url"],
        }
        for row in rows
        if row.get("site") and row.get("primary_key") and row.get("url")
    ]
    logger.info("Built %d download jobs from %d Athena rows", len(jobs), len(rows))

    # 3. Run downloads
    results = download_jobs(
        jobs=jobs,
        output_dir=args.output_dir,
        max_workers=args.max_workers,
        timeout_seconds=args.timeout_seconds,
        download_run_id=run_id,
        storage_mode=args.storage_mode,
        s3_bucket=bucket,
    )

    counts = Counter(r.get("status", "unknown") for r in results)
    logger.info("Download complete: %s", dict(counts))

    # 4. Write status partition to S3
    status_rows = _build_status_rows(results, dt, run_id)
    _write_status_partition(s3, bucket, dt, status_rows)

    # 5. Register Glue partition
    try:
        _register_glue_partition(
            athena=athena,
            database=args.athena_database,
            table=args.athena_status_table,
            dt=dt,
            bucket=bucket,
            workgroup=args.athena_workgroup,
            output_location=args.athena_output_loc,
            timeout_seconds=args.athena_timeout,
        )
    except Exception as e:
        logger.warning("Glue partition registration failed (non-fatal): %s", e)

    # 6. Write marker
    all_ok = counts.get("error", 0) == 0
    marker = MARKER_SUCCESS if all_ok else MARKER_FAILED
    _write_marker(s3, bucket, dt, marker)

    summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    print(f"run_id={run_id} dt={dt} results={summary} marker={marker}")


if __name__ == "__main__":
    main()
