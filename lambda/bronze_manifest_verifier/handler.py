import boto3
import json
import gzip
import hashlib
import os
import logging
import urllib.parse
import re
from datetime import datetime, timezone


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")
glue = boto3.client("glue")

APP_ENV = os.getenv("APP_ENV", "dev")
BRONZE_DATA_PREFIX = f"bronze/{APP_ENV}/crawls/"
BRONZE_MARKERS_PREFIX = f"bronze/{APP_ENV}/crawls/markers/"
BRONZE_MANIFESTS_PREFIX = f"bronze/{APP_ENV}/crawls/manifests/"
# Kept for reading manifests written by the crawl writer (trigger path unchanged)
BRONZE_METADATA_PREFIX = f"bronze/{APP_ENV}/crawls/metadata/"

MANIFEST_TABLE = os.getenv("MANIFEST_TABLE", "crawl_manifest_raw")

MARKER_SUCCESS = "_SUCCESS"
MARKER_FAILED = "_FAILED"
MARKER_FAIL_QUALITY = "_FAIL_QUALITY"


def _s3_key_from_record(record):
    return urllib.parse.unquote_plus(record["s3"]["object"]["key"])


def _parse_metadata_key(key):
    """Return (site, dt, run_id) from a metadata/ manifest key."""
    relative = key[len(BRONZE_METADATA_PREFIX):]
    parts = relative.split("/")
    # expected: {site}/{dt}/{run_id}/manifest.json
    if len(parts) < 4:
        raise ValueError(f"Unexpected metadata key format: {key}")
    return parts[0], parts[1], parts[2]


def _register_bronze_partition(bucket, success_key):
    if not success_key.startswith(BRONZE_MARKERS_PREFIX):
        raise ValueError(f"Unexpected _SUCCESS key location: {success_key}")

    relative_key = success_key[len(BRONZE_MARKERS_PREFIX):]
    parts = relative_key.split("/")
    # expected: {site}/{dt}/{run_id}/_SUCCESS
    if len(parts) < 4:
        raise ValueError(f"Unexpected _SUCCESS key format: {success_key}")

    site, dt, _run_id = parts[0], parts[1], parts[2]
    if parts[-1] != "_SUCCESS":
        raise ValueError(f"Expected _SUCCESS marker key, got: {success_key}")

    normalized_site = re.sub(r"[^a-zA-Z0-9]+", "_", site).strip("_").lower()
    derived_table = f"bronze_{normalized_site}_raw" if normalized_site else "bronze_raw_scrape"
    table = os.getenv("ATHENA_TABLE") or derived_table
    bronze_database = os.getenv("BRONZE_DATABASE", f"price_comparison_{APP_ENV}")

    data_location = f"s3://{bucket}/{BRONZE_DATA_PREFIX}{site}/{dt}/"
    manifest_location = f"s3://{bucket}/{BRONZE_MANIFESTS_PREFIX}{site}/{dt}/"

    logger.info(
        "Registering Glue partition site=%s dt=%s table=%s database=%s",
        site, dt, table, bronze_database,
    )

    serde_descriptor = {
        "InputFormat": "org.apache.hadoop.mapred.TextInputFormat",
        "OutputFormat": "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat",
        "SerdeInfo": {
            "SerializationLibrary": "org.openx.data.jsonserde.JsonSerDe",
            "Parameters": {"serialization.format": "1"},
        },
    }

    # Register crawl data partition (site, dt)
    try:
        glue.create_partition(
            DatabaseName=bronze_database,
            TableName=table,
            PartitionInput={
                "Values": [site, dt],
                "StorageDescriptor": {**serde_descriptor, "Location": data_location},
            },
        )
        logger.info("Registered Glue partition site=%s dt=%s for table %s", site, dt, table)
    except glue.exceptions.AlreadyExistsException:
        logger.info("Glue partition site=%s dt=%s already exists for table %s", site, dt, table)

    # Register crawl_manifest_raw partition (site, dt) — env is baked into the table LOCATION prefix
    try:
        glue.create_partition(
            DatabaseName=bronze_database,
            TableName=MANIFEST_TABLE,
            PartitionInput={
                "Values": [site, dt],
                "StorageDescriptor": {**serde_descriptor, "Location": manifest_location},
            },
        )
        logger.info(
            "Registered Glue partition site=%s dt=%s for table %s",
            site, dt, MANIFEST_TABLE,
        )
    except glue.exceptions.AlreadyExistsException:
        logger.info(
            "Glue partition site=%s dt=%s already exists for table %s",
            site, dt, MANIFEST_TABLE,
        )

    return {
        "status": "ok",
        "action": "glue_create_partition",
        "table": table,
        "manifest_table": MANIFEST_TABLE,
        "database": bronze_database,
        "data_location": data_location,
        "manifest_location": manifest_location,
        "partition": {"site": site, "dt": dt},
    }


def _verify_manifest_and_write_success(bucket, key):
    manifest_key = key
    site, dt, run_id = _parse_metadata_key(key)

    marker_prefix = f"{BRONZE_MARKERS_PREFIX}{site}/{dt}/{run_id}"
    manifest_dest_key = f"{BRONZE_MANIFESTS_PREFIX}{site}/{dt}/{run_id}/data.json"

    # Derive data file prefix: bronze/{env}/crawls/{site}/{dt}/{run_id}
    run_prefix = f"{BRONZE_DATA_PREFIX}{site}/{dt}/{run_id}"

    verification_ok = False
    verification_error = None
    quality_gate_status = None
    quality_gate_reason = None
    markers_written = []
    manifest = {}

    try:
        manifest_content = s3.get_object(Bucket=bucket, Key=manifest_key)["Body"].read().decode("utf-8")
        manifest = json.loads(manifest_content)

        quality_gate = manifest.get("quality_gate", {}) if isinstance(manifest, dict) else {}
        if isinstance(quality_gate, dict):
            quality_gate_status = quality_gate.get("status")
            quality_gate_reason = quality_gate.get("reason")

        artifacts = manifest.get("artifacts", {}) if isinstance(manifest, dict) else {}
        data_filename = os.path.basename(artifacts.get("file_path", ""))
        if not data_filename:
            raise ValueError("Could not determine data filename from manifest.")

        data_key = f"{run_prefix}/{data_filename}"
        data = s3.get_object(Bucket=bucket, Key=data_key)["Body"].read()

        calculated_hash = hashlib.sha256(data).hexdigest()
        expected_hash = manifest["artifacts"]["hashes"]["sha256"]
        if calculated_hash != expected_hash:
            raise ValueError("Hash mismatch")

        raw = gzip.decompress(data)
        observed_rowcount = len(raw.splitlines())
        expected_rows = manifest["artifacts"]["rows"]
        if observed_rowcount != expected_rows:
            raise ValueError("Row count mismatch")

        verification_ok = True
    except Exception as e:
        verification_error = str(e)
        logger.exception("Error verifying manifest or data file")

    quality_gate_ok = quality_gate_status == "pass"

    # Determine outcome for the verification block
    if verification_ok and quality_gate_ok:
        outcome = "SUCCESS"
        failure_reason = None
    elif not quality_gate_ok:
        outcome = "FAIL_QUALITY"
        failure_reason = quality_gate_reason
    else:
        outcome = "FAILED"
        failure_reason = verification_error

    # Write to manifests/ as a wrapper JSON so JsonSerDe can map columns directly.
    # run_id is a top-level key for direct Athena querying; raw_json captures the
    # full verified manifest as a string for json_extract_scalar in downstream models.
    verified_manifest = {
        **manifest,
        "verification": {
            "verified_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "outcome": outcome,
            "failure_reason": failure_reason,
        },
    }
    dest_row = {
        "run_id": manifest.get("run_id"),
        "raw_json": json.dumps(verified_manifest),
    }
    try:
        s3.put_object(
            Bucket=bucket,
            Key=manifest_dest_key,
            Body=json.dumps(dest_row).encode("utf-8"),
        )
        logger.info("Wrote verified manifest to s3://%s/%s", bucket, manifest_dest_key)
    except Exception:
        logger.exception("Failed to write verified manifest to manifests/")

    if not quality_gate_ok:
        try:
            s3.put_object(
                Bucket=bucket,
                Key=f"{marker_prefix}/{MARKER_FAIL_QUALITY}",
                Body=json.dumps(
                    {
                        "quality_gate_status": quality_gate_status,
                        "quality_gate_reason": quality_gate_reason,
                        "manifest_key": manifest_key,
                    }
                ).encode("utf-8"),
            )
            markers_written.append(MARKER_FAIL_QUALITY)
        except Exception:
            logger.exception("Failed to write %s marker", MARKER_FAIL_QUALITY)

    if not verification_ok:
        try:
            s3.put_object(
                Bucket=bucket,
                Key=f"{marker_prefix}/{MARKER_FAILED}",
                Body=b"",
            )
            markers_written.append(MARKER_FAILED)
        except Exception:
            logger.exception("Failed to write %s marker", MARKER_FAILED)

    if verification_ok and quality_gate_ok:
        s3.put_object(
            Bucket=bucket,
            Key=f"{marker_prefix}/{MARKER_SUCCESS}",
            Body=b"",
        )
        markers_written.append(MARKER_SUCCESS)
        return {
            "status": "ok",
            "action": "verify_manifest",
            "manifest_key": key,
            "manifest_dest_key": manifest_dest_key,
            "quality_gate_status": quality_gate_status,
            "verification_ok": verification_ok,
            "markers_written": markers_written,
        }

    return {
        "status": "error",
        "action": "verify_manifest",
        "manifest_key": key,
        "manifest_dest_key": manifest_dest_key,
        "quality_gate_status": quality_gate_status,
        "quality_gate_ok": quality_gate_ok,
        "quality_gate_reason": quality_gate_reason,
        "verification_ok": verification_ok,
        "message": verification_error or "Quality gate status is not pass",
        "markers_written": markers_written,
    }


def handler(event, context):
    records = event.get("Records", [])
    if not records:
        return {"status": "ignored", "message": "No Records in event"}

    results = []
    for record in records:
        bucket = record["s3"]["bucket"]["name"]
        key = _s3_key_from_record(record)

        if key.endswith("manifest.json"):
            results.append(_verify_manifest_and_write_success(bucket, key))
            continue

        if key.endswith("_SUCCESS"):
            results.append(_register_bronze_partition(bucket, key))
            continue

        logger.info("Ignoring S3 event for unsupported key: s3://%s/%s", bucket, key)
        results.append({"status": "ignored", "key": key})

    return {"status": "ok", "results": results}
