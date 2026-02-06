import boto3
import json
import gzip
import hashlib
import os
import logging


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")

def handler(event, context):
    bucket = event["Records"][0]["s3"]["bucket"]["name"]
    key = event["Records"][0]["s3"]["object"]["key"]

    # Manifest is stored under bronze/crawls/metadata/...; derive run prefix for data.
    manifest_key = key
    manifest_parent = "/".join(key.split("/")[:-1])
    run_prefix = manifest_parent.replace("/crawls/metadata/", "/crawls/", 1)
    if run_prefix == manifest_parent:
        logger.error(f"Unexpected manifest key location: {key}")
        return {
            "status": "error",
            "message": "Manifest key not under bronze/crawls/metadata/"
        }

    # Read manifest
    manifest_content = s3.get_object(Bucket=bucket, Key=manifest_key)['Body'].read().decode('utf-8')
    manifest = json.loads(manifest_content)

    # Extract the filename from the manifest
    artifacts = manifest.get('artifacts', {})
    data_filename = os.path.basename(artifacts.get('file_path', ''))

    if not data_filename:
        logger.error("Could not determine data filename from manifest.")
        return {
            'statusCode': 400,
            'body': json.dumps('Could not determine data filename from manifest.')
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

        # ✅ Write _SUCCESS marker (metadata folder)
        s3.put_object(
            Bucket=bucket,
            Key=f"{manifest_parent}/_SUCCESS",
            Body=b""
        )

        return {"status": "ok"}
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
            "message": str(e)
        }
