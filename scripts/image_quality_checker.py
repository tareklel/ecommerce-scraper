"""
image_quality_checker.py

Triggered by _SUCCESS marker written by run_image_pipeline.py.
Reads the download status partition for a given dt, validates each ok image
from S3, and appends passing rows to the raw_image Athena table.

Usage:
  python scripts/image_quality_checker.py --dt 2026-05-15 --athena-database price_comparison
"""
import argparse
import gzip
import hashlib
import io
import json
import logging
import os
import time
from collections import Counter
from datetime import datetime, timezone

import boto3
from PIL import Image, UnidentifiedImageError

logger = logging.getLogger(__name__)

S3_BUCKET = os.environ.get("S3_BUCKET", "price-comparison-bucket-eu-central-1")
STATUS_PREFIX = "bronze/images/download_status"
RAW_IMAGE_PREFIX = "bronze/images/raw"
MIN_DIMENSION = 10  # reject images smaller than 10px in either dimension


# ---------------------------------------------------------------------------
# S3 helpers
# ---------------------------------------------------------------------------

def _read_status_partition(s3, bucket, dt):
    key = f"{STATUS_PREFIX}/dt={dt}/data.jsonl.gz"
    logger.info("Reading status partition s3://%s/%s", bucket, key)
    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    rows = []
    with gzip.GzipFile(fileobj=io.BytesIO(body)) as gz:
        for line in gz:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _fetch_blob(s3, bucket, s3_blob_key):
    return s3.get_object(Bucket=bucket, Key=s3_blob_key)["Body"].read()


def _write_raw_partition(s3, bucket, dt, raw_rows):
    key = f"{RAW_IMAGE_PREFIX}/dt={dt}/data.jsonl.gz"
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        for row in raw_rows:
            gz.write((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))
    buf.seek(0)
    s3.put_object(Bucket=bucket, Key=key, Body=buf.read())
    logger.info("Wrote raw_image partition s3://%s/%s (%d rows)", bucket, key, len(raw_rows))


# ---------------------------------------------------------------------------
# Athena / Glue helpers
# ---------------------------------------------------------------------------

def _start_athena_query(athena, database, sql, output_location, workgroup):
    kwargs = {
        "QueryString": sql,
        "WorkGroup": workgroup,
        "QueryExecutionContext": {"Database": database},
    }
    if output_location:
        kwargs["ResultConfiguration"] = {"OutputLocation": output_location}
    return athena.start_query_execution(**kwargs)["QueryExecutionId"]


def _wait_athena(athena, execution_id, timeout_seconds=60):
    deadline = time.time() + timeout_seconds
    while True:
        resp = athena.get_query_execution(QueryExecutionId=execution_id)
        state = resp["QueryExecution"]["Status"]["State"]
        if state == "SUCCEEDED":
            return
        if state in ("FAILED", "CANCELLED"):
            reason = resp["QueryExecution"]["Status"].get("StateChangeReason", "")
            raise RuntimeError(f"Athena query {execution_id} ended as {state}: {reason}")
        if time.time() >= deadline:
            raise TimeoutError(f"Athena query {execution_id} timed out")
        time.sleep(2)


def _register_glue_partition(athena, database, table, dt, bucket, workgroup, output_location, timeout_seconds):
    location = f"s3://{bucket}/{RAW_IMAGE_PREFIX}/dt={dt}/"
    sql = f"ALTER TABLE {table} ADD IF NOT EXISTS PARTITION (dt='{dt}') LOCATION '{location}'"
    eid = _start_athena_query(athena, database, sql, output_location, workgroup)
    _wait_athena(athena, eid, timeout_seconds=timeout_seconds)
    logger.info("Registered Glue partition dt=%s for table %s", dt, table)


# ---------------------------------------------------------------------------
# Image validation
# ---------------------------------------------------------------------------

def _validate_image(content: bytes, expected_sha256: str):
    """
    Returns (ok: bool, reason: str, width: int, height: int, format: str).
    """
    actual_sha256 = hashlib.sha256(content).hexdigest()
    if actual_sha256 != expected_sha256:
        return False, "sha256_mismatch", None, None, None

    try:
        img = Image.open(io.BytesIO(content))
        img.verify()
        img = Image.open(io.BytesIO(content))  # reopen after verify
        width, height = img.size
        fmt = (img.format or "").lower()
    except (UnidentifiedImageError, Exception) as e:
        return False, f"invalid_image: {e}", None, None, None

    if width < MIN_DIMENSION or height < MIN_DIMENSION:
        return False, f"too_small: {width}x{height}", width, height, fmt

    return True, "ok", width, height, fmt


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Validate downloaded images and write raw_image partition.")
    parser.add_argument("--dt", required=True, help="Partition date (YYYY-MM-DD) to process.")
    parser.add_argument("--athena-database", required=True, help="Glue/Athena database name.")
    parser.add_argument("--athena-raw-table", default="raw_image",
                        help="raw_image Athena table name.")
    parser.add_argument("--athena-output-loc", default=None,
                        help="s3://... prefix for Athena query results.")
    parser.add_argument("--athena-workgroup", default="primary")
    parser.add_argument("--athena-timeout", type=int, default=60)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    bucket = S3_BUCKET
    s3 = boto3.client("s3")
    athena = boto3.client("athena")

    logger.info("Starting quality check for dt=%s", args.dt)

    # 1. Read status partition
    status_rows = _read_status_partition(s3, bucket, args.dt)
    ok_rows = [r for r in status_rows if r.get("status") == "ok" and r.get("s3_blob_key")]
    logger.info("Status partition: %d total rows, %d ok to validate", len(status_rows), len(ok_rows))

    if not ok_rows:
        logger.info("No ok rows to validate — exiting.")
        return

    # 2. Validate each image
    raw_rows = []
    counts = Counter()

    for row in ok_rows:
        s3_blob_key = row["s3_blob_key"]
        sha256 = s3_blob_key.split("/")[-1].rsplit(".", 1)[0]  # derived from key pattern

        try:
            content = _fetch_blob(s3, bucket, s3_blob_key)
        except Exception as e:
            logger.warning("Failed to fetch %s: %s", s3_blob_key, e)
            counts["fetch_error"] += 1
            continue

        valid, reason, width, height, fmt = _validate_image(content, sha256)
        if not valid:
            logger.info("Rejected %s: %s", s3_blob_key, reason)
            counts["rejected"] += 1
            continue

        raw_rows.append({
            "site": row.get("site"),
            "primary_key": row.get("primary_key"),
            "image_url": row.get("url"),
            "s3_blob_key": s3_blob_key,
            "sha256": sha256,
            "width": width,
            "height": height,
            "format": fmt,
            "run_id": row.get("run_id"),
            "dt": args.dt,
        })
        counts["ok"] += 1

    logger.info("Validation complete: %s", dict(counts))

    if not raw_rows:
        logger.warning("No images passed validation — skipping partition write.")
        return

    # 3. Write raw_image partition
    _write_raw_partition(s3, bucket, args.dt, raw_rows)

    # 4. Register Glue partition
    try:
        _register_glue_partition(
            athena=athena,
            database=args.athena_database,
            table=args.athena_raw_table,
            dt=args.dt,
            bucket=bucket,
            workgroup=args.athena_workgroup,
            output_location=args.athena_output_loc,
            timeout_seconds=args.athena_timeout,
        )
    except Exception as e:
        logger.warning("Glue partition registration failed (non-fatal): %s", e)

    summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    print(f"dt={args.dt} {summary} raw_rows={len(raw_rows)}")


if __name__ == "__main__":
    main()
