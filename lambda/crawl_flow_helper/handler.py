"""Helper Lambda for the crawl flow (Step Functions state machine in
infra/terraform/orchestration.tf). One function, several actions, each called
by one step of the flow. Design: tickets/cicd_pipeline.md, step 3, and
docs/cicd_architecture.md, "What happens on each run".

Actions (event["action"]):
- start: refuse if another flow run is running; normalise the input; make the
  image pipeline's run ID.
- list_crawls: read active rows of the seeded crawl_plp_registry (Athena),
  write a --urls-source CSV per non-Ounass site, return one crawl per site.
- check_crawl: has the verifier written this crawl's markers yet?
- gate: how many crawls published (success or degraded)?
- find_image_marker: did the image pipeline write a marker for its run ID?
- summary: one result for the whole flow run.
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import boto3

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

APP_ENV = os.environ.get("APP_ENV", "dev")
BUCKET = os.environ.get("BUCKET", "price-comparison-bucket-eu-central-1")
ATHENA_WORKGROUP = os.environ.get("ATHENA_WORKGROUP", "price-comparison")
ATHENA_OUTPUT = os.environ.get("ATHENA_OUTPUT", f"s3://{BUCKET}/athena-results/crawl-flow/")
REGISTRY_TABLE = os.environ.get("REGISTRY_TABLE", f'"price_comparison_{APP_ENV}"."crawl_plp_registry"')
# Polls of the crawl's markers after its task ended (one a minute in the
# state machine): no marker by then means the crawl died without a manifest.
MAX_VERIFY_POLLS = int(os.environ.get("MAX_VERIFY_POLLS", "15"))
ATHENA_TIMEOUT_SECONDS = 120

MARKERS_PREFIX = f"bronze/{APP_ENV}/crawls/markers/"
MANIFESTS_PREFIX = f"bronze/{APP_ENV}/crawls/manifests/"
CRAWL_INPUTS_PREFIX = f"bronze/{APP_ENV}/crawl-inputs/"
IMAGE_META_PREFIX = f"bronze/{APP_ENV}/images/download_log/meta/"

# Registry site key -> how to crawl it. The site key is also the spider's
# `name`, which the verifier uses in marker paths.
SITES = {
    "ounass": {"spider": "ounass", "mode": "plp_efficient"},
    "level-shoes": {"spider": "level", "mode": "urls_source"},
    "bloomingdales": {"spider": "bloomingdales", "mode": "urls_source"},
}

PUBLISHED = ("success", "degraded")

s3 = boto3.client("s3")
athena = boto3.client("athena")
sfn = boto3.client("stepfunctions")


class FlowAlreadyRunning(Exception):
    pass


class UnknownRegistrySite(Exception):
    pass


class RegistryQueryFailed(Exception):
    pass


def _now():
    return datetime.now(timezone.utc)


def _run_id(moment):
    """Same format as MasterCrawl._generate_run_id: 2026-11-10T02-00-00-000."""
    return moment.strftime("%Y-%m-%dT%H-%M-%S") + f"-{moment.microsecond // 1000:03d}"


# ---------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------

def start(event):
    execution_arn = event["execution_arn"]
    others = [
        execution["executionArn"]
        for page in sfn.get_paginator("list_executions").paginate(
            stateMachineArn=event["state_machine_arn"], statusFilter="RUNNING"
        )
        for execution in page["executions"]
        if execution["executionArn"] != execution_arn
    ]
    if others:
        raise FlowAlreadyRunning(f"Another crawl flow run is still running: {others[0]}")

    flow_input = event.get("input") or {}
    start_at = flow_input.get("start_at", "crawl")
    if start_at not in ("crawl", "images"):
        raise ValueError(f'start_at must be "crawl" or "images", got {start_at!r}')
    # Always a string, so the state machine's Choice can read it.
    stop_after = flow_input.get("stop_after") or "none"
    if stop_after not in ("none", "crawls"):
        raise ValueError(f'stop_after must be "crawls" or unset, got {stop_after!r}')
    if stop_after == "crawls" and start_at != "crawl":
        raise ValueError('stop_after "crawls" needs start_at "crawl"')
    limit = flow_input.get("limit")
    if limit is not None and (not isinstance(limit, int) or limit < 1):
        raise ValueError(f"limit must be a positive whole number, got {limit!r}")

    now = _now()
    return {
        "flow_id": execution_arn.rsplit(":", 1)[-1],
        "execution_arn": execution_arn,
        "start_at": start_at,
        "stop_after": stop_after,
        "limit": limit,
        "started_at": now.isoformat(),
        "image_run_id": _run_id(now),
    }


# ---------------------------------------------------------------------------
# list_crawls
# ---------------------------------------------------------------------------

def _query_active_registry():
    query = (
        f"SELECT site, url FROM {REGISTRY_TABLE} "
        "WHERE is_active ORDER BY site, url"
    )
    execution_id = athena.start_query_execution(
        QueryString=query,
        WorkGroup=ATHENA_WORKGROUP,
        ResultConfiguration={"OutputLocation": ATHENA_OUTPUT},
    )["QueryExecutionId"]
    deadline = time.monotonic() + ATHENA_TIMEOUT_SECONDS
    while True:
        status = athena.get_query_execution(QueryExecutionId=execution_id)["QueryExecution"]["Status"]
        if status["State"] == "SUCCEEDED":
            break
        if status["State"] in ("FAILED", "CANCELLED"):
            raise RegistryQueryFailed(status.get("StateChangeReason", status["State"]))
        if time.monotonic() > deadline:
            raise RegistryQueryFailed(f"Registry query still {status['State']} after {ATHENA_TIMEOUT_SECONDS}s")
        time.sleep(1)

    rows = []
    for page in athena.get_paginator("get_query_results").paginate(QueryExecutionId=execution_id):
        for row in page["ResultSet"]["Rows"]:
            rows.append([column.get("VarCharValue") for column in row["Data"]])
    # The first row of the first page is the header.
    return [(site, url) for site, url in rows[1:] if site and url]


def list_crawls(event):
    flow = event["flow"]
    urls_by_site = {}
    for site, url in _query_active_registry():
        urls_by_site.setdefault(site.strip().lower(), []).append(url.strip())

    unknown = sorted(set(urls_by_site) - set(SITES))
    if unknown:
        raise UnknownRegistrySite(
            f"Registry has active rows for sites the flow can't crawl: {unknown}. "
            "Add them to SITES in lambda/crawl_flow_helper/handler.py."
        )

    base = _now()
    crawls = []
    for index, site in enumerate(sorted(urls_by_site)):
        config = SITES[site]
        run_id = _run_id(base + timedelta(milliseconds=index))
        parts = ["python3 run_crawler.py", config["spider"], f"--env {APP_ENV}"]
        if config["mode"] == "plp_efficient":
            # Its export reads the seeded registry table itself.
            parts.append("--plp-efficient")
            urls_source = None
        else:
            key = f"{CRAWL_INPUTS_PREFIX}{flow['flow_id']}/{site}.csv"
            body = "url\n" + "".join(f"{url}\n" for url in urls_by_site[site])
            s3.put_object(Bucket=BUCKET, Key=key, Body=body.encode("utf-8"), ContentType="text/csv")
            urls_source = f"s3://{BUCKET}/{key}"
            parts.append(f"--urls-source {urls_source}")
        if flow.get("limit"):
            parts.append(f"--limit {int(flow['limit'])}")
        crawls.append({
            "site": site,
            "spider": config["spider"],
            "run_id": run_id,
            "url_count": len(urls_by_site[site]),
            "urls_source": urls_source,
            "command": " ".join(parts),
        })
    logger.info("Crawls for flow %s: %s", flow["flow_id"], json.dumps(crawls))
    return {"crawls": crawls}


# ---------------------------------------------------------------------------
# check_crawl
# ---------------------------------------------------------------------------

def _list_keys(prefix):
    keys = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=prefix):
        keys.extend(item["Key"] for item in page.get("Contents", []))
    return keys


def _read_json(key):
    try:
        return json.loads(s3.get_object(Bucket=BUCKET, Key=key)["Body"].read() or b"{}")
    except Exception:  # a marker we can't read still counts; its name says enough
        logger.exception("Could not read %s", key)
        return {}


def check_crawl(event):
    crawl = event["crawl"]
    polls = int(event.get("polls", 0)) + 1
    site, run_id = crawl["site"], crawl["run_id"]
    dt = run_id.split("T")[0]
    markers = {key.rsplit("/", 1)[-1]: key for key in _list_keys(f"{MARKERS_PREFIX}{site}/{dt}/{run_id}/")}
    result = {"site": site, "run_id": run_id, "polls": polls, "done": True,
              "run_status": None, "failure_reasons": [], "degradations": None}

    failures = sorted(name for name in markers if name.startswith("_FAIL"))
    if failures:
        result["run_status"] = "failed"
        for name in failures:
            body = _read_json(markers[name])
            reason = body.get("failure_reason") or name
            if reason == "crash" and body.get("first_error"):
                reason = f"crash: {body['first_error']}"
            result["failure_reasons"].append(reason)
        return result
    if "_SUCCESS" in markers:
        manifest = _read_json(f"{MANIFESTS_PREFIX}{site}/{dt}/{run_id}/data.json")
        result["run_status"] = manifest.get("run_status") or "success"
        result["degradations"] = manifest.get("degradations")
        return result
    if polls >= MAX_VERIFY_POLLS:
        # Task ended MAX_VERIFY_POLLS minutes ago and the verifier wrote nothing:
        # the crawl never uploaded a manifest.
        result["run_status"] = "killed"
        return result
    result["done"] = False
    return result


# ---------------------------------------------------------------------------
# gate, find_image_marker, summary
# ---------------------------------------------------------------------------

def gate(event):
    crawls = event.get("crawls") or []
    published = [c for c in crawls if (c.get("result") or {}).get("run_status") in PUBLISHED]
    return {"published": len(published), "total": len(crawls)}


def find_image_marker(event):
    flow = event["flow"]
    run_id = flow["image_run_id"]
    first = datetime.fromisoformat(flow["started_at"]).date()
    last = _now().date()
    day = first
    while day <= last:
        keys = _list_keys(f"{IMAGE_META_PREFIX}{day.isoformat()}/{run_id}/")
        names = {key.rsplit("/", 1)[-1] for key in keys}
        for marker in ("_SUCCESS", "_FAILED"):
            if marker in names:
                return {"found": True, "dt": day.isoformat(), "marker": marker, "run_id": run_id}
        day += timedelta(days=1)
    # No marker: the pipeline found nothing to download.
    return {"found": False, "dt": None, "marker": None, "run_id": run_id}


STEP_NAMES = {
    "seed_registry": "registry seed or its tests",
    "list_crawls": "reading the registry",
    "crawls": "the crawl step",
    "dbt_run": "dbt run (full)",
    "image_pipeline": "image pipeline",
    "image_marker": "finding the image pipeline's marker",
    "quality_checker": "quality checker",
    "dbt_run_images": "dbt run (image models)",
    "dbt_test": "dbt test",
    "refresh_cache": "API cache refresh",
}


def _describe_error(failure):
    """Turn a caught Step Functions error into one line.

    A runTask.sync failure carries the whole stopped ECS task as JSON in
    Cause; show its exit code and stop reason instead of the raw JSON.
    """
    cause = failure.get("Cause") or ""
    try:
        task = json.loads(cause)
    except (TypeError, ValueError):
        task = None
    if isinstance(task, dict) and isinstance(task.get("Containers"), list):
        container = task["Containers"][0] if task["Containers"] else {}
        parts = [f"exit code {container.get('ExitCode', 'unknown')}"]
        reason = container.get("Reason") or task.get("StoppedReason")
        if reason:
            parts.append(f"({reason})")
        if task.get("TaskArn"):
            parts.append(f"task {task['TaskArn'].rsplit('/', 1)[-1]}")
        return " ".join(parts)
    return f"{failure.get('Error')} {str(cause)[:500]}".strip()


def _degradation_line(degradation):
    if isinstance(degradation, dict) and degradation.get("message"):
        return f"{degradation.get('kind', '?')} {degradation.get('scope', '?')}: {degradation['message']}"
    return json.dumps(degradation)


def _is_access(degradation):
    return isinstance(degradation, dict) and degradation.get("kind") == "access"


def _console_url(execution_arn):
    region = execution_arn.split(":")[3]
    return (f"https://{region}.console.aws.amazon.com/states/home?region={region}"
            f"#/v2/executions/details/{execution_arn}")


def summary(event):
    state = event.get("state") or {}
    flow = state.get("flow") or {}
    crawls = state.get("crawls") or []
    failed_step = state.get("failed_step")
    failure = state.get("failure")
    gate_result = state.get("gate") or {}
    image_marker = state.get("image_marker")

    lines = [f"Crawl flow {flow.get('flow_id', '?')} (start_at={flow.get('start_at', '?')})"]
    # Blocking needs a different response from bad data, so it gets its own
    # section (access failures and access degradations).
    blocked = []
    for crawl in crawls:
        result = crawl.get("result") or {}
        line = f"- {crawl.get('site')} {crawl.get('run_id')}: {result.get('run_status') or 'unknown'}"
        if result.get("failure_reasons"):
            line += f" ({', '.join(result['failure_reasons'])})"
            if "access" in result["failure_reasons"]:
                blocked.append(f"- {crawl.get('site')}: crawl failed, nothing written")
        if crawl.get("task_error"):
            line += f" task error: {crawl['task_error'].get('Error')}"
        lines.append(line)
        for degradation in result.get("degradations") or []:
            lines.append(f"    {_degradation_line(degradation)}")
            if _is_access(degradation):
                blocked.append(f"- {crawl.get('site')} {_degradation_line(degradation)}")
    if blocked:
        lines.append("Blocked by the site:")
        lines.extend(blocked)
    if image_marker is not None:
        if image_marker.get("found"):
            lines.append(f"- images: {image_marker['marker']} dt={image_marker['dt']} run={image_marker['run_id']}")
        else:
            lines.append("- images: nothing to download")

    if failed_step:
        status = "failed"
        detail = STEP_NAMES.get(failed_step, failed_step)
        if isinstance(failure, dict) and failure.get("Error"):
            detail += f": {_describe_error(failure)}"
        elif isinstance(failure, dict) and failure.get("exit_code") is not None:
            detail += f": exit code {failure['exit_code']}"
        else:
            # The task ran but exited non-zero: its containers are in last_task.
            containers = (state.get("last_task") or {}).get("containers") or [{}]
            detail += f": exit code {containers[0].get('ExitCode', 'unknown')}"
        lines.append(f"FAILED at {detail}")
        if failed_step == "refresh_cache":
            lines.append("API cache refresh failed: the API keeps the previous data")
        else:
            lines.append("API cache not refreshed: the API keeps the last tested data")
        subject = f"FAILED at {STEP_NAMES.get(failed_step, failed_step)}"
    elif flow.get("start_at") == "crawl" and gate_result.get("published", 0) == 0:
        status = "failed"
        lines.append("FAILED: no crawl published, so dbt and images were skipped")
        lines.append("API cache not refreshed: the API keeps the last tested data")
        subject = "FAILED: no crawl published"
    elif flow.get("stop_after") == "crawls":
        status = "succeeded"
        lines.append("Stopped after the crawls (stop_after=crawls): no dbt, images or cache refresh")
        subject = f"SUCCEEDED (crawls only): {gate_result.get('published', 0)}/{len(crawls)} crawls published"
    else:
        status = "succeeded"
        lines.append("API cache refreshed")
        bad = [c for c in crawls if (c.get("result") or {}).get("run_status") not in PUBLISHED]
        if bad:
            lines.append(f"Succeeded with {len(bad)} crawl(s) not published")
        else:
            lines.append("Succeeded")
        if flow.get("start_at") == "crawl":
            subject = f"SUCCEEDED: {len(crawls) - len(bad)}/{len(crawls)} crawls published"
        else:
            subject = "SUCCEEDED (images only)"
    if flow.get("execution_arn"):
        lines.append(f"Console: {_console_url(flow['execution_arn'])}")
    text = "\n".join(lines)
    logger.info(text)
    # SNS subjects: one line, at most 100 characters.
    subject = f"Crawl flow {APP_ENV} {subject}"[:100]
    return {"status": status, "subject": subject, "text": text}


ACTIONS = {
    "start": start,
    "list_crawls": list_crawls,
    "check_crawl": check_crawl,
    "gate": gate,
    "find_image_marker": find_image_marker,
    "summary": summary,
}


def handler(event, context):
    action = event.get("action")
    if action not in ACTIONS:
        raise ValueError(f"Unknown action {action!r}; expected one of {sorted(ACTIONS)}")
    return ACTIONS[action](event)
