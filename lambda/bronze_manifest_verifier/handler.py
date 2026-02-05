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

    # Get run folder (handle manifest in metadata subfolder)
    manifest_key = key
    run_prefix = key.split("/metadata/")[0]

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

        # ✅ Write _SUCCESS marker
        s3.put_object(
            Bucket=bucket,
            Key=f"{run_prefix}/_SUCCESS",
            Body=b""
        )

        return {"status": "ok"}
    except Exception as e:
        logger.exception("Error verifying manifest or data file")
        # attempt to write a failure marker so downstream processes can detect the failure
        try:
            s3.put_object(
                Bucket=bucket,
                Key=f"{run_prefix}/_FAILED",
                Body=b""
            )
        except Exception:
            logger.exception("Failed to write _FAILED marker")
        return {
            "status": "error",
            "message": str(e)
        }
