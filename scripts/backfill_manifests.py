"""
One-time backfill: copy historical manifest.json files from crawls/metadata/
into crawls/manifests/ as data.json, then register Glue partitions for
crawl_manifest_raw so the table has continuous history from before the cutover.

Historical manifests lack the verification block — those fields will be NULL
in Athena, which is correct. Filter with WHERE verified_at IS NOT NULL when
you need only verified rows.

Usage:
    python scripts/backfill_manifests.py --env prod --bucket price-comparison-bucket-eu-central-1
    python scripts/backfill_manifests.py --env dev  --bucket price-comparison-bucket-eu-central-1 --dry-run
"""

import argparse
import boto3
import json
import logging
import botocore.exceptions

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", required=True, help="APP_ENV value (dev/prod)")
    parser.add_argument("--bucket", required=True, help="S3 bucket name")
    parser.add_argument("--database", help="Glue database name (default: price_comparison_{env})")
    parser.add_argument("--dry-run", action="store_true", help="List what would be copied, no writes")
    return parser.parse_args()


def list_metadata_manifests(s3_client, bucket, env):
    """Yield every manifest.json key under bronze/{env}/crawls/metadata/."""
    prefix = f"bronze/{env}/crawls/metadata/"
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith("/manifest.json"):
                yield key


def parse_metadata_key(key, env):
    """
    Extract (site, dt, run_id) from:
      bronze/{env}/crawls/metadata/{site}/{dt}/{run_id}/manifest.json
    """
    prefix = f"bronze/{env}/crawls/metadata/"
    relative = key[len(prefix):]
    parts = relative.rstrip("/").split("/")
    if len(parts) < 4:
        raise ValueError(f"Unexpected key format: {key}")
    return parts[0], parts[1], parts[2]


def dest_key(env, site, dt, run_id):
    return f"bronze/{env}/crawls/manifests/{site}/{dt}/{run_id}/data.json"


def register_partition(glue_client, database, env, site, dt, bucket, dry_run):
    location = f"s3://{bucket}/bronze/{env}/crawls/manifests/{site}/{dt}/"
    if dry_run:
        logger.info("[dry-run] Would register partition site=%s dt=%s at %s", site, dt, location)
        return
    try:
        glue_client.create_partition(
            DatabaseName=database,
            TableName="crawl_manifest_raw",
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
        logger.info("Registered partition site=%s dt=%s", site, dt)
    except glue_client.exceptions.AlreadyExistsException:
        logger.info("Partition already exists site=%s dt=%s — skipped", site, dt)


def main():
    args = parse_args()
    database = args.database or f"price_comparison_{args.env}"

    s3_client = boto3.client("s3")
    glue_client = boto3.client("glue")

    partitions_seen = set()
    copied = 0
    skipped = 0

    for src_key in list_metadata_manifests(s3_client, args.bucket, args.env):
        site, dt, run_id = parse_metadata_key(src_key, args.env)
        dst_key = dest_key(args.env, site, dt, run_id)

        if args.dry_run:
            logger.info("[dry-run] Would write wrapper s3://%s/%s → s3://%s/%s", args.bucket, src_key, args.bucket, dst_key)
            copied += 1
        else:
            # Check if dest already exists to make the script idempotent
            try:
                s3_client.head_object(Bucket=args.bucket, Key=dst_key)
                logger.info("Already exists, skipping: %s", dst_key)
                skipped += 1
            except botocore.exceptions.ClientError as e:
                if e.response["Error"]["Code"] != "404":
                    raise
                # Read source manifest and write as wrapper JSON so JsonSerDe
                # can map run_id and raw_json columns directly in Athena.
                raw = s3_client.get_object(Bucket=args.bucket, Key=src_key)["Body"].read().decode("utf-8")
                manifest = json.loads(raw)
                dest_row = {
                    "run_id": manifest.get("run_id"),
                    "raw_json": raw,
                }
                s3_client.put_object(
                    Bucket=args.bucket,
                    Key=dst_key,
                    Body=json.dumps(dest_row).encode("utf-8"),
                )
                logger.info("Wrote wrapper → %s", dst_key)
                copied += 1

        partition_key = (site, dt)
        if partition_key not in partitions_seen:
            partitions_seen.add(partition_key)
            register_partition(glue_client, database, args.env, site, dt, args.bucket, args.dry_run)

    logger.info("Done. copied=%d skipped=%d partitions_registered=%d", copied, skipped, len(partitions_seen))


if __name__ == "__main__":
    main()
