import boto3
import json
import gzip
import hashlib
import os
import logging
import urllib.parse
import re


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")
glue = boto3.client("glue")

APP_ENV = os.getenv("APP_ENV", "dev")
BRONZE_METADATA_PREFIX = f"bronze/{APP_ENV}/crawls/metadata/"
BRONZE_DATA_PREFIX = f"bronze/{APP_ENV}/crawls/"

MARKER_SUCCESS = "_SUCCESS"
MARKER_FAILED = "_FAILED"
MARKER_FAIL_QUALITY = "_FAIL_QUALITY"


def _s3_key_from_record(record):
    return urllib.parse.unquote_plus(record["s3"]["object"]["key"])


def _register_bronze_partition(bucket, success_key):
    if not success_key.startswith(BRONZE_METADATA_PREFIX):
        raise ValueError(f"Unexpected _SUCCESS key location: {success_key}")

    relative_key = success_key[len(BRONZE_METADATA_PREFIX):]
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

    location = f"s3://{bucket}/{BRONZE_DATA_PREFIX}{site}/{dt}/"

    logger.info(
        "Registering Glue partition site=%s dt=%s table=%s database=%s location=%s",
        site, dt, table, bronze_database, location,
    )

    try:
        glue.create_partition(
            DatabaseName=bronze_database,
            TableName=table,
            PartitionInput={
                "Values": [site, dt],
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
        logger.info("Registered Glue partition site=%s dt=%s for table %s", site, dt, table)
    except glue.exceptions.AlreadyExistsException:
        logger.info("Glue partition site=%s dt=%s already exists for table %s", site, dt, table)

    return {
        "status": "ok",
        "action": "glue_create_partition",
        "table": table,
        "database": bronze_database,
        "location": location,
        "partition": {"site": site, "dt": dt},
    }


def _verify_manifest_and_write_success(bucket, key):
    manifest_key = key
    manifest_parent = "/".join(key.split("/")[:-1])
    # Derive data prefix: bronze/{env}/crawls/metadata/... → bronze/{env}/crawls/...
    run_prefix = manifest_parent.replace("/crawls/metadata/", "/crawls/", 1)
    if run_prefix == manifest_parent:
        logger.error("Unexpected manifest key location: %s", key)
        return {
            "status": "error",
            "message": f"Manifest key not under {BRONZE_METADATA_PREFIX}"
        }

    verification_ok = False
    verification_error = None
    quality_gate_status = None
    quality_gate_reason = None
    markers_written = []

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

    if not quality_gate_ok:
        try:
            s3.put_object(
                Bucket=bucket,
                Key=f"{manifest_parent}/{MARKER_FAIL_QUALITY}",
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
                Key=f"{manifest_parent}/{MARKER_FAILED}",
                Body=b"",
            )
            markers_written.append(MARKER_FAILED)
        except Exception:
            logger.exception("Failed to write %s marker", MARKER_FAILED)

    if verification_ok and quality_gate_ok:
        s3.put_object(
            Bucket=bucket,
            Key=f"{manifest_parent}/{MARKER_SUCCESS}",
            Body=b"",
        )
        markers_written.append(MARKER_SUCCESS)
        return {
            "status": "ok",
            "action": "verify_manifest",
            "manifest_key": key,
            "quality_gate_status": quality_gate_status,
            "verification_ok": verification_ok,
            "markers_written": markers_written,
        }

    return {
        "status": "error",
        "action": "verify_manifest",
        "manifest_key": key,
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
