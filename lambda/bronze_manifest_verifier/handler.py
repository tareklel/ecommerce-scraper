import boto3
import json
import gzip
import hashlib
import os
import logging
import time
import urllib.parse
import re


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")
athena = boto3.client("athena")

BRONZE_METADATA_PREFIX = "bronze/crawls/metadata/"
BRONZE_DATA_PREFIX = "bronze/crawls/"


def _s3_key_from_record(record):
    return urllib.parse.unquote_plus(record["s3"]["object"]["key"])


def _escape_sql_literal(value):
    return value.replace("'", "''")


def _wait_for_athena_query(query_execution_id, timeout_seconds=20, poll_interval_seconds=1):
    deadline = time.time() + timeout_seconds
    while True:
        response = athena.get_query_execution(QueryExecutionId=query_execution_id)
        status = response["QueryExecution"]["Status"]
        state = status["State"]
        if state in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            return state, status.get("StateChangeReason", "")

        if time.time() >= deadline:
            raise TimeoutError(
                f"Athena query {query_execution_id} did not finish within {timeout_seconds}s"
            )

        time.sleep(poll_interval_seconds)


def _register_bronze_partition(bucket, success_key):
    if not success_key.startswith(BRONZE_METADATA_PREFIX):
        raise ValueError(f"Unexpected _SUCCESS key location: {success_key}")

    relative_key = success_key[len(BRONZE_METADATA_PREFIX):]
    parts = relative_key.split("/")
    if len(parts) < 5:
        raise ValueError(f"Unexpected _SUCCESS key format: {success_key}")

    env, site, dt, _run_id = parts[0], parts[1], parts[2], parts[3]
    if parts[-1] != "_SUCCESS":
        raise ValueError(f"Expected _SUCCESS marker key, got: {success_key}")

    normalized_site = re.sub(r"[^a-zA-Z0-9]+", "_", site).strip("_").lower()
    derived_table = f"bronze_{normalized_site}_raw" if normalized_site else "bronze_raw_scrape"
    athena_table = os.getenv("ATHENA_TABLE") or derived_table
    athena_database = os.getenv("GLUE_DATABASE") or os.getenv("ATHENA_DATABASE", "price_comparison")
    athena_workgroup = os.getenv("ATHENA_WORKGROUP", "primary")
    athena_catalog = os.getenv("ATHENA_DATA_CATALOG", "AwsDataCatalog")
    athena_output_location = os.getenv("ATHENA_OUTPUT_LOCATION")
    athena_wait_seconds = int(os.getenv("ATHENA_QUERY_WAIT_SECONDS", "20"))

    location = f"s3://{bucket}/{BRONZE_DATA_PREFIX}{env}/{site}/{dt}/"
    sql = f"""
ALTER TABLE {athena_table}
ADD IF NOT EXISTS PARTITION (
  env='{_escape_sql_literal(env)}',
  site='{_escape_sql_literal(site)}',
  dt='{_escape_sql_literal(dt)}'
)
LOCATION '{_escape_sql_literal(location)}'
""".strip()

    start_query_kwargs = {
        "QueryString": sql,
        "WorkGroup": athena_workgroup,
        "QueryExecutionContext": {
            "Database": athena_database,
            "Catalog": athena_catalog,
        },
    }
    if athena_output_location:
        start_query_kwargs["ResultConfiguration"] = {
            "OutputLocation": athena_output_location
        }

    logger.info(
        "Registering Athena partition for env=%s site=%s dt=%s table=%s location=%s",
        env,
        site,
        dt,
        athena_table,
        location,
    )
    start_response = athena.start_query_execution(**start_query_kwargs)
    query_execution_id = start_response["QueryExecutionId"]
    state, reason = _wait_for_athena_query(
        query_execution_id,
        timeout_seconds=athena_wait_seconds,
    )

    if state != "SUCCEEDED":
        raise RuntimeError(
            f"Athena partition query {query_execution_id} ended in state {state}: {reason}"
        )

    return {
        "status": "ok",
        "action": "athena_add_partition",
        "query_execution_id": query_execution_id,
        "table": athena_table,
        "database": athena_database,
        "catalog": athena_catalog,
        "workgroup": athena_workgroup,
        "location": location,
        "partition": {"env": env, "site": site, "dt": dt},
    }


def _verify_manifest_and_write_success(bucket, key):
    # Manifest is stored under bronze/crawls/metadata/...; derive run prefix for data.
    manifest_key = key
    manifest_parent = "/".join(key.split("/")[:-1])
    run_prefix = manifest_parent.replace("/crawls/metadata/", "/crawls/", 1)
    if run_prefix == manifest_parent:
        logger.error("Unexpected manifest key location: %s", key)
        return {
            "status": "error",
            "message": "Manifest key not under bronze/crawls/metadata/"
        }

    # Read manifest
    manifest_content = s3.get_object(Bucket=bucket, Key=manifest_key)["Body"].read().decode("utf-8")
    manifest = json.loads(manifest_content)

    # Extract the filename from the manifest
    artifacts = manifest.get("artifacts", {})
    data_filename = os.path.basename(artifacts.get("file_path", ""))

    if not data_filename:
        logger.error("Could not determine data filename from manifest.")
        return {
            "statusCode": 400,
            "body": json.dumps("Could not determine data filename from manifest.")
        }

    data_key = f"{run_prefix}/{data_filename}"

    try:
        # Read data
        data = s3.get_object(Bucket=bucket, Key=data_key)["Body"].read()

        # Hash check
        calculated_hash = hashlib.sha256(data).hexdigest()
        if calculated_hash != manifest["artifacts"]["hashes"]["sha256"]:
            raise Exception("Hash mismatch")

        raw = gzip.decompress(data)
        # Row count check
        observed_rowcount = len(raw.splitlines())
        if observed_rowcount != manifest["artifacts"]["rows"]:
            raise Exception("Row count mismatch")

        # Write _SUCCESS marker (metadata folder); S3 notification will trigger partition registration.
        s3.put_object(
            Bucket=bucket,
            Key=f"{manifest_parent}/_SUCCESS",
            Body=b""
        )

        return {"status": "ok", "action": "verify_manifest", "manifest_key": key}
    except Exception as e:
        logger.exception("Error verifying manifest or data file")
        # attempt to write a failure marker so downstream processes can detect the failure
        try:
            s3.put_object(
                Bucket=bucket,
                Key=f"{manifest_parent}/_FAILED",
                Body=b""
            )
        except Exception:
            logger.exception("Failed to write _FAILED marker")
        return {
            "status": "error",
            "action": "verify_manifest",
            "message": str(e)
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
