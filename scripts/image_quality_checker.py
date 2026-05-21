"""
image_quality_checker.py

Triggered by _SUCCESS marker written by run_image_pipeline.py.
Reads the download status partition for a given dt, validates each ok image
from S3, and appends passing rows to the image_validated Athena table.

Usage:
  python scripts/image_quality_checker.py --dt 2026-05-15 --run-id <run_id> --app-env dev
"""
import argparse
import gzip
import hashlib
import io
import json
import logging
import os
from collections import Counter

import boto3
from PIL import Image, UnidentifiedImageError

from ecommercecrawl import env_config

logger = logging.getLogger(__name__)

S3_BUCKET = os.environ.get("S3_BUCKET", "price-comparison-bucket-eu-central-1")
MIN_DIMENSION = 10  # reject images smaller than 10px in either dimension


# ---------------------------------------------------------------------------
# S3 helpers
# ---------------------------------------------------------------------------

def _read_status_partition(s3, bucket, status_prefix, dt, run_id):
    key = f"{status_prefix}/dt={dt}/run={run_id}/data.jsonl.gz"
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


def _write_validated_partition(s3, bucket, validated_prefix, dt, run_id, rows):
    key = f"{validated_prefix}/dt={dt}/run={run_id}/data.jsonl.gz"
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        for row in rows:
            gz.write((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))
    buf.seek(0)
    s3.put_object(Bucket=bucket, Key=key, Body=buf.read())
    logger.info("Wrote validated partition s3://%s/%s (%d rows)", bucket, key, len(rows))


# ---------------------------------------------------------------------------
# Glue helpers
# ---------------------------------------------------------------------------

def _register_glue_partition(glue, database, table, validated_prefix, dt, bucket):
    location = f"s3://{bucket}/{validated_prefix}/dt={dt}/"
    try:
        glue.create_partition(
            DatabaseName=database,
            TableName=table,
            PartitionInput={
                "Values": [dt],
                "StorageDescriptor": {
                    "Location": location,
                    "InputFormat": "org.apache.hadoop.mapred.TextInputFormat",
                    "OutputFormat": "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat",
                    "SerdeInfo": {
                        "SerializationLibrary": "org.openx.data.jsonserde.JsonSerDe",
                        "Parameters": {"serialization.format": "1"},
                    },
                },
            },
        )
        logger.info("Registered Glue partition dt=%s for table %s", dt, table)
    except glue.exceptions.AlreadyExistsException:
        logger.info("Glue partition dt=%s already exists for table %s", dt, table)


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
    parser = argparse.ArgumentParser(description="Validate downloaded images and write image_validated partition.")
    parser.add_argument("--dt", required=True, help="Partition date (YYYY-MM-DD) to process.")
    parser.add_argument("--run-id", required=True, help="Run ID from the pipeline run to validate.")
    parser.add_argument("--app-env", default="dev",
                        help="Environment to run against: dev or prod. Defaults to dev.")
    parser.add_argument("--glue-validated-table", default="image_validated",
                        help="Validated image Glue table name.")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = env_config.load(args.app_env)
    bronze_database = config["bronze_database"]
    bronze_prefix = env_config.bronze_key_prefix(config)
    status_prefix = f"{bronze_prefix}images/download_log"
    validated_prefix = f"{bronze_prefix}images/validated"

    bucket = S3_BUCKET
    s3 = boto3.client("s3")
    glue = boto3.client("glue")

    logger.info("Starting quality check app_env=%s dt=%s", args.app_env, args.dt)

    # 1. Read status partition
    status_rows = _read_status_partition(s3, bucket, status_prefix, args.dt, args.run_id)
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

    # 3. Write validated partition
    _write_validated_partition(s3, bucket, validated_prefix, args.dt, args.run_id, raw_rows)

    # 4. Register Glue partition
    _register_glue_partition(glue, bronze_database, args.glue_validated_table, validated_prefix, args.dt, bucket)

    summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    print(f"dt={args.dt} {summary} validated_rows={len(raw_rows)}")


if __name__ == "__main__":
    main()
