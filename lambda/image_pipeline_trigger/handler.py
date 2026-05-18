import json
import logging
import os
import urllib.parse

import boto3

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

ecs = boto3.client("ecs")

ECS_CLUSTER          = os.environ["ECS_CLUSTER"]
ECS_TASK_DEFINITION  = os.environ["ECS_TASK_DEFINITION"]
ECS_CONTAINER_NAME   = os.environ.get("ECS_CONTAINER_NAME", "image-quality-checker")
ECS_SUBNET_IDS       = os.environ["ECS_SUBNET_IDS"].split(",")
ECS_SECURITY_GROUP   = os.environ["ECS_SECURITY_GROUP_ID"]
GLUE_DATABASE        = os.environ["GLUE_DATABASE"]

# Expected key pattern: bronze/images/download_log/meta/{dt}/{run_id}/_SUCCESS
_META_PREFIX = "bronze/images/download_log/meta/"


def _extract_dt_run_id(key: str) -> tuple:
    if not key.startswith(_META_PREFIX):
        raise ValueError(f"Unexpected key: {key}")
    # key = bronze/images/download_log/meta/2026-05-15/2026-05-15T07-53-07-848/_SUCCESS
    remainder = key[len(_META_PREFIX):]       # "2026-05-15/2026-05-15T07-53-07-848/_SUCCESS"
    parts = remainder.split("/")
    if len(parts) < 3:
        raise ValueError(f"Could not extract dt/run_id from key: {key}")
    return parts[0], parts[1]  # dt, run_id


def _trigger_quality_checker(dt: str, run_id: str) -> dict:
    cmd = (
        f"python scripts/image_quality_checker.py"
        f" --dt {dt}"
        f" --run-id {run_id}"
        f" --glue-database {GLUE_DATABASE}"
    )
    command = [cmd]
    response = ecs.run_task(
        cluster=ECS_CLUSTER,
        taskDefinition=ECS_TASK_DEFINITION,
        launchType="FARGATE",
        networkConfiguration={
            "awsvpcConfiguration": {
                "subnets": ECS_SUBNET_IDS,
                "securityGroups": [ECS_SECURITY_GROUP],
                "assignPublicIp": "ENABLED",
            }
        },
        overrides={
            "containerOverrides": [{
                "name": ECS_CONTAINER_NAME,
                "command": command,
            }]
        },
    )
    task_arns = [t["taskArn"] for t in response.get("tasks", [])]
    failures = response.get("failures", [])
    logger.info("Triggered image_quality_checker dt=%s tasks=%s failures=%s", dt, task_arns, failures)
    return {"task_arns": task_arns, "failures": failures}


def handler(event, context):
    records = event.get("Records", [])
    if not records:
        return {"status": "ignored", "message": "No Records in event"}

    results = []
    for record in records:
        key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])

        if not key.endswith("_SUCCESS"):
            logger.info("Ignoring non-_SUCCESS key: %s", key)
            results.append({"status": "ignored", "key": key})
            continue

        try:
            dt, run_id = _extract_dt_run_id(key)
        except ValueError as e:
            logger.error("Could not extract dt/run_id from key %s: %s", key, e)
            results.append({"status": "error", "key": key, "message": str(e)})
            continue

        result = _trigger_quality_checker(dt, run_id)
        results.append({"status": "ok", "dt": dt, "run_id": run_id, **result})

    return {"status": "ok", "results": results}
