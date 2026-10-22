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
# Published crawl data: the Glue day partitions point here, so everything under
# it is read by Athena and dbt. Only verified, passing runs are copied in.
BRONZE_DATA_PREFIX = f"bronze/{APP_ENV}/crawls/"
# Where the crawler uploads a run's data file. Nothing reads it; a run that
# fails stays here (for inspection) and never reaches BRONZE_DATA_PREFIX.
BRONZE_UNVERIFIED_PREFIX = f"bronze/{APP_ENV}/crawl-unverified/"
BRONZE_MARKERS_PREFIX = f"bronze/{APP_ENV}/crawls/markers/"
BRONZE_MANIFESTS_PREFIX = f"bronze/{APP_ENV}/crawls/manifests/"
# Kept for reading manifests written by the crawl writer (trigger path unchanged)
BRONZE_METADATA_PREFIX = f"bronze/{APP_ENV}/crawls/metadata/"

MANIFEST_TABLE = os.getenv("MANIFEST_TABLE", "crawl_manifest_raw")

MARKER_SUCCESS = "_SUCCESS"
MARKER_FAILED = "_FAILED"
MARKER_FAIL_QUALITY = "_FAIL_QUALITY"
MARKER_FAIL_ABORTED = "_FAIL_ABORTED"
MARKER_FAIL_STARTUP_CHECK = "_FAIL_STARTUP_CHECK"
MARKER_FAIL_ACCESS = "_FAIL_ACCESS"

# Run status (docs/ounass_plp_efficient_crawl.md, "Run status"; applies to all
# crawls). One question decides it: did the crawler reach its own end, and did
# it skip anything on purpose?
RUN_SUCCESS = "success"     # reached its end, nothing skipped -> _SUCCESS
RUN_DEGRADED = "degraded"   # reached its end, a guardrail skipped work -> _SUCCESS
RUN_FAILED = "failed"       # rows never reach dbt; see failure_reason

# failure_reason -> marker, verification.outcome, and a plain-language
# meaning + what to do, in precedence order: the first that applies is the
# run's failure_reason. An aborted run is failed even when its rows are fine:
# a half-finished day is misleading data.
# The explanations are written into every marker and verified manifest, so a
# failure explains itself wherever it's met. They must match the crawler's
# copy in ecommercecrawl/run_status.py (tests/test_run_status_explanations.py).
STATUS_DOC_LINK = "docs/crawl_run_status.md#failure-markers"
FAILURE_REASONS = {
    "aborted": {
        "marker": MARKER_FAIL_ABORTED,
        "outcome": "FAIL_ABORTED",
        "meaning": "The crawl was stopped before it finished (Ctrl+C, ECS task stopped, timeout); its rows are not published.",
        "what_to_do": "Re-run the crawl. If it keeps happening, check why the task was stopped.",
    },
    "startup_check": {
        "marker": MARKER_FAIL_STARTUP_CHECK,
        "outcome": "FAIL_STARTUP_CHECK",
        "meaning": "The PLP-efficient crawl stopped before making any request because a startup check failed.",
        "what_to_do": "Run `make preflight-ounass-plp-efficient` to list every failed check.",
    },
    # Nothing written because the site refused us (blocking): never a
    # content failure. Same rule as the crawler's crawler_run_status.
    "access": {
        "marker": MARKER_FAIL_ACCESS,
        "outcome": "FAIL_ACCESS",
        "meaning": "Nothing was written because the site blocked our requests through every retry round.",
        "what_to_do": "See the manifest's access block for which hostnames and errors; check Zyte routing (CRAWLER_API_ZYTE_GEOLOCATION_BY_HOST); re-run later.",
    },
    "quality": {
        "marker": MARKER_FAIL_QUALITY,
        "outcome": "FAIL_QUALITY",
        "meaning": "The rows failed the quality gate, or nothing was written for a reason other than blocking.",
        "what_to_do": "Read metadata/quality_report.json; check the seed URLs still exist and the page format hasn't changed.",
    },
    "verification": {
        "marker": MARKER_FAILED,
        "outcome": "FAILED",
        "meaning": "The data file failed verification (missing, hash or row-count mismatch, unreadable manifest, or the publish copy failed).",
        "what_to_do": "Check the verifier Lambda's logs, then re-run the crawl.",
    },
}


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

    _register_manifest_partition(site, dt, bucket)

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


def _register_manifest_partition(site, dt, bucket):
    """
    Register the crawl_manifest_raw (site, dt) partition. Done for every
    verified run, failed ones included, so a day where every run failed is
    still queryable. Env is baked into the table LOCATION prefix.
    """
    bronze_database = os.getenv("BRONZE_DATABASE", f"price_comparison_{APP_ENV}")
    manifest_location = f"s3://{bucket}/{BRONZE_MANIFESTS_PREFIX}{site}/{dt}/"
    serde_descriptor = {
        "InputFormat": "org.apache.hadoop.mapred.TextInputFormat",
        "OutputFormat": "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat",
        "SerdeInfo": {
            "SerializationLibrary": "org.openx.data.jsonserde.JsonSerDe",
            "Parameters": {"serialization.format": "1"},
        },
    }
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


def _crawler_failure_reason(manifest):
    """
    Failures the crawler's own manifest already shows; checking the file can't
    change them. Read from exit_reason (not the crawler's run_status) so
    manifests written before run_status existed are classified the same way.
    """
    exit_reason = manifest.get("exit_reason")
    if exit_reason and exit_reason != "finished":
        return "aborted"
    plp_efficient = manifest.get("plp_efficient")
    if isinstance(plp_efficient, dict) and plp_efficient.get("startup_stopped"):
        return "startup_check"
    rows = (manifest.get("artifacts") or {}).get("rows")
    if not rows and _access_gave_up(manifest):
        return "access"
    return None


def _access_gave_up(manifest):
    access = manifest.get("access")
    hosts = access.get("hosts") if isinstance(access, dict) else None
    if not isinstance(hosts, dict):
        return 0
    return sum(int((h or {}).get("gave_up") or 0) for h in hosts.values())


def _blocked_hosts(manifest):
    hosts = ((manifest.get("access") or {}).get("hosts") or {})
    return sorted(h for h, stats in hosts.items() if (stats or {}).get("gave_up"))


def _read_data_file(bucket, unverified_key, published_key):
    """
    Return (bytes, source). New crawler images upload to crawl-unverified/;
    images from before that change uploaded straight to crawls/ ("legacy"),
    where the file is already published.
    """
    try:
        return s3.get_object(Bucket=bucket, Key=unverified_key)["Body"].read(), "unverified"
    except Exception:
        return s3.get_object(Bucket=bucket, Key=published_key)["Body"].read(), "legacy"


def _verify_manifest_and_write_success(bucket, key):
    manifest_key = key
    site, dt, run_id = _parse_metadata_key(key)

    marker_prefix = f"{BRONZE_MARKERS_PREFIX}{site}/{dt}/{run_id}"
    manifest_dest_key = f"{BRONZE_MANIFESTS_PREFIX}{site}/{dt}/{run_id}/data.json"

    # Published data prefix: bronze/{env}/crawls/{site}/{dt}/{run_id}
    run_prefix = f"{BRONZE_DATA_PREFIX}{site}/{dt}/{run_id}"
    unverified_prefix = f"{BRONZE_UNVERIFIED_PREFIX}{site}/{dt}/{run_id}"

    manifest_ok = False
    verification_ok = False
    verification_error = None
    quality_gate_status = None
    quality_gate_reason = None
    data_source = None
    data_key = None
    published_key = None
    markers_written = []
    manifest = {}

    try:
        manifest_content = s3.get_object(Bucket=bucket, Key=manifest_key)["Body"].read().decode("utf-8")
        manifest = json.loads(manifest_content)
        if not isinstance(manifest, dict):
            raise ValueError("Manifest is not a JSON object.")
        manifest_ok = True

        quality_gate = manifest.get("quality_gate") or {}
        if isinstance(quality_gate, dict):
            quality_gate_status = quality_gate.get("status")
            quality_gate_reason = quality_gate.get("reason")

        artifacts = manifest.get("artifacts", {})
        data_filename = os.path.basename(artifacts.get("file_path", ""))
        if not data_filename:
            raise ValueError("Could not determine data filename from manifest.")

        published_key = f"{run_prefix}/{data_filename}"
        data, data_source = _read_data_file(bucket, f"{unverified_prefix}/{data_filename}", published_key)
        data_key = f"{unverified_prefix}/{data_filename}" if data_source == "unverified" else published_key

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
    crawler_reason = _crawler_failure_reason(manifest) if manifest_ok else None

    # Every reason that applies gets its marker; the first is the run's
    # failure_reason. A startup-stopped or fully blocked run has no data file
    # by design, so the missing file isn't also reported as quality/verification.
    reasons = []
    if crawler_reason:
        reasons.append(crawler_reason)
    if crawler_reason not in ("startup_check", "access"):
        if manifest_ok and not quality_gate_ok:
            reasons.append("quality")
        if not verification_ok:
            reasons.append("verification")

    # Publish: copy the verified file into the day folder Athena reads. Only
    # then is _SUCCESS written, which registers the partition for dbt.
    if not reasons and data_source == "unverified":
        try:
            s3.copy_object(
                Bucket=bucket,
                Key=published_key,
                CopySource={"Bucket": bucket, "Key": data_key},
            )
            logger.info("Published s3://%s/%s -> %s", bucket, data_key, published_key)
        except Exception as e:
            verification_error = f"Publish failed: {e}"
            logger.exception("Failed to publish verified data file")
            reasons.append("verification")

    degradations = manifest.get("degradations") if manifest_ok else None
    if reasons:
        run_status = RUN_FAILED
        failure_reason = reasons[0]
        outcome = FAILURE_REASONS[failure_reason]["outcome"]
        detail = {
            "aborted": f"exit_reason={manifest.get('exit_reason')}",
            "startup_check": (manifest.get("plp_efficient") or {}).get("startup_error")
            or "stopped by startup checks",
            "access": f"no rows; requests lost to blocking on {', '.join(_blocked_hosts(manifest))}",
            "quality": quality_gate_reason,
            "verification": verification_error,
        }[failure_reason]
    else:
        run_status = RUN_DEGRADED if degradations else RUN_SUCCESS
        failure_reason = None
        outcome = "SUCCESS"
        detail = None

    # Write to manifests/ as a wrapper JSON so JsonSerDe can map columns directly.
    # run_id is a top-level key for direct Athena querying; raw_json captures the
    # full verified manifest as a string for json_extract_scalar in downstream models.
    # run_status / failure_reason here are final (the crawler's own values,
    # written before verification, are overwritten).
    verified_manifest = {
        **manifest,
        "run_status": run_status,
        "failure_reason": failure_reason,
        "failure_explanation": (
            {"meaning": FAILURE_REASONS[failure_reason]["meaning"],
             "what_to_do": FAILURE_REASONS[failure_reason]["what_to_do"],
             "doc": STATUS_DOC_LINK}
            if failure_reason else None
        ),
        "verification": {
            "verified_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "outcome": outcome,
            "failure_reason": detail,
            "data_source": data_source,
            "published_key": published_key if run_status != RUN_FAILED else None,
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

    try:
        _register_manifest_partition(site, dt, bucket)
    except Exception:
        logger.exception("Failed to register %s partition", MANIFEST_TABLE)

    for reason in reasons:
        marker = FAILURE_REASONS[reason]["marker"]
        try:
            s3.put_object(
                Bucket=bucket,
                Key=f"{marker_prefix}/{marker}",
                Body=json.dumps(
                    {
                        "run_status": run_status,
                        "failure_reason": reason,
                        # Self-explaining: what this marker means and what to do.
                        "meaning": FAILURE_REASONS[reason]["meaning"],
                        "what_to_do": FAILURE_REASONS[reason]["what_to_do"],
                        "doc": STATUS_DOC_LINK,
                        "quality_gate_status": quality_gate_status,
                        "quality_gate_reason": quality_gate_reason,
                        "exit_reason": manifest.get("exit_reason"),
                        "verification_error": verification_error,
                        "manifest_key": manifest_key,
                    }
                ).encode("utf-8"),
            )
            markers_written.append(marker)
        except Exception:
            logger.exception("Failed to write %s marker", marker)

    if not reasons:
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
            "run_status": run_status,
            "quality_gate_status": quality_gate_status,
            "verification_ok": verification_ok,
            "markers_written": markers_written,
        }

    return {
        "status": "error",
        "action": "verify_manifest",
        "manifest_key": key,
        "manifest_dest_key": manifest_dest_key,
        "run_status": run_status,
        "failure_reason": failure_reason,
        "quality_gate_status": quality_gate_status,
        "quality_gate_ok": quality_gate_ok,
        "quality_gate_reason": quality_gate_reason,
        "verification_ok": verification_ok,
        "message": detail or "Run failed",
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
