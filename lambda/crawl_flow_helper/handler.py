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
import re
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
MAPPING_GAPS_TABLE = os.environ.get("MAPPING_GAPS_TABLE", f'"price_comparison_{APP_ENV}"."silver_mapping_gaps"')
GOLD_TABLE = os.environ.get("GOLD_TABLE", f'"price_comparison_{APP_ENV}"."gold_product_serving_latest"')
# Polls of the crawl's markers after its task ended (one a minute in the
# state machine): no marker by then means the crawl died without a manifest.
MAX_VERIFY_POLLS = int(os.environ.get("MAX_VERIFY_POLLS", "15"))
ATHENA_TIMEOUT_SECONDS = 120
# The dbt task's log (scraper-pipeline terraform/dbt_job.tf: awslogs prefix
# "dbt", container "dbt"), read to say why a dbt step failed.
DBT_LOG_GROUP = os.environ.get("DBT_LOG_GROUP", f"/ecs/price-comparison-dbt-{APP_ENV}")
DBT_LOG_STREAM_PREFIX = "dbt/dbt/"

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
    # One registry row per listing (English only, user decision 2026-11-15):
    # each Cettire listing URL serves both languages through its search
    # service, so the spider writes EN and AR rows from one URL.
    "cettire": {"spider": "cettire", "mode": "urls_source"},
}

PUBLISHED = ("success", "degraded")

s3 = boto3.client("s3")
athena = boto3.client("athena")
sfn = boto3.client("stepfunctions")
logs = boto3.client("logs")


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

def _athena_rows(query):
    """Run one Athena query; return its rows without the header."""
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
            raise RegistryQueryFailed(f"Query still {status['State']} after {ATHENA_TIMEOUT_SECONDS}s")
        time.sleep(1)

    rows = []
    for page in athena.get_paginator("get_query_results").paginate(QueryExecutionId=execution_id):
        for row in page["ResultSet"]["Rows"]:
            rows.append([column.get("VarCharValue") for column in row["Data"]])
    # The first row of the first page is the header.
    return rows[1:]


def _query_active_registry():
    rows = _athena_rows(f"SELECT site, url FROM {REGISTRY_TABLE} WHERE is_active ORDER BY site, url")
    return [(site, url) for site, url in rows if site and url]


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
        # The verifier writes {run_id, raw_json}: the manifest is a JSON
        # string inside raw_json (lambda/bronze_manifest_verifier/handler.py).
        if isinstance(manifest.get("raw_json"), str):
            manifest = json.loads(manifest["raw_json"])
        result["run_status"] = manifest.get("run_status") or "success"
        result["degradations"] = manifest.get("degradations")
        # Language rows written (Arabic and English counted separately).
        result["rows"] = (manifest.get("artifacts") or {}).get("rows")
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


# Steps that run the dbt task, so their log says why they failed.
DBT_STEPS = ("seed_registry", "dbt_run", "dbt_run_images", "dbt_test", "refresh_cache")
MAX_DBT_PROBLEMS = 10
# Each log line starts with an ANSI reset and an HH:MM:SS timestamp.
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_TIMESTAMP = re.compile(r"^\d\d:\d\d:\d\d  ")


def _failed_task_id(failure, state):
    """The ECS task ID of the failed step, from the caught error or last_task."""
    try:
        task = json.loads((failure or {}).get("Cause") or "")
    except (TypeError, ValueError, AttributeError):
        task = None
    arn = task.get("TaskArn") if isinstance(task, dict) else None
    if not arn:
        containers = (state.get("last_task") or {}).get("containers") or [{}]
        arn = containers[0].get("TaskArn")
    return arn.rsplit("/", 1)[-1] if arn else None


def _read_dbt_log(task_id):
    """All messages of one dbt task's log stream, ANSI codes and timestamps removed."""
    messages, token = [], None
    for _ in range(20):  # a full dbt run is a few hundred lines; this is a guard
        kwargs = {"logGroupName": DBT_LOG_GROUP, "logStreamName": DBT_LOG_STREAM_PREFIX + task_id,
                  "startFromHead": True}
        if token:
            kwargs["nextToken"] = token
        response = logs.get_log_events(**kwargs)
        messages.extend(_TIMESTAMP.sub("", _ANSI.sub("", e["message"])) for e in response["events"])
        if not response["events"] or response.get("nextForwardToken") == token:
            break
        token = response.get("nextForwardToken")
    return messages


def _dbt_problems(messages):
    """
    dbt's own explanation of a failed command (dbt 1.12 format, seen 2026-11-17):
    after "Completed with N error(s)", each problem is a block of lines between
    blank lines, e.g. "[ERROR]: in test X (path)" then "Got 30673 results, ...".
    Warnings are left out (they don't fail the step); the "Done. PASS=..." line
    gives their count. Returns (problems, done_line).
    """
    done = next((m.strip() for m in reversed(messages) if m.strip().startswith("Done. PASS=")), None)
    start = next((i for i, m in enumerate(messages) if m.strip().startswith("Completed with")), None)
    if start is None:
        return [], done
    blocks, block = [], []
    for message in messages[start + 1:] + [""]:
        text = message.strip()
        if text.startswith("Done. PASS="):
            break
        if text:
            block.append(text)
        elif block:
            blocks.append(block)
            block = []
    if block:
        blocks.append(block)
    problems = []
    for block in blocks:
        kept = [line for line in block if not line.startswith("compiled code at")]
        if kept and not kept[0].startswith("[WARNING]"):
            problems.append(": ".join(kept).replace("[ERROR]: ", ""))
    return problems, done


def _dbt_log_url(task_id):
    region = os.environ.get("AWS_REGION", "eu-central-1")
    group = DBT_LOG_GROUP.replace("/", "$252F")
    stream = (DBT_LOG_STREAM_PREFIX + task_id).replace("/", "$252F")
    return (f"https://{region}.console.aws.amazon.com/cloudwatch/home?region={region}"
            f"#logsV2:log-groups/log-group/{group}/log-events/{stream}")


def _dbt_failure_lines(failure, state):
    """
    Why a dbt step failed, from its task's log: dbt's error blocks, or the
    log's last lines when dbt printed none (e.g. the dbt lock timed out).
    Never fails the summary: a problem reading the log becomes the line itself.
    """
    task_id = _failed_task_id(failure, state)
    if not task_id:
        return ["dbt said: not available (no task ID in the failure)"]
    try:
        messages = _read_dbt_log(task_id)
        problems, done = _dbt_problems(messages)
        lines = ["dbt said:"]
        if problems:
            lines.extend(f"- {p[:500]}" for p in problems[:MAX_DBT_PROBLEMS])
            if len(problems) > MAX_DBT_PROBLEMS:
                lines.append(f"- ...and {len(problems) - MAX_DBT_PROBLEMS} more (see the log)")
        else:
            tail = [m.strip() for m in messages if m.strip()][-5:] or ["(the log is empty)"]
            lines.extend(f"  {m[:500]}" for m in tail)
        if done:
            lines.append(f"- {done}")
    except Exception as e:
        logger.warning("dbt log read failed: %s", e)
        lines = [f"dbt said: not available ({str(e)[:200]})"]
    lines.append(f"dbt log: {_dbt_log_url(task_id)}")
    return lines


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


# Steps after the full dbt run, which builds silver_mapping_gaps.
AFTER_DBT_RUN = ("image_pipeline", "image_marker", "quality_checker", "dbt_run_images", "dbt_test", "refresh_cache")


def _mapping_gaps_line():
    """
    Seed work left for scraper-pipeline, from its silver_mapping_gaps table.
    Never fails the summary: a query problem becomes the line itself.
    """
    try:
        rows = _athena_rows(
            "SELECT count_if(gap_type = 'brand' AND suggested_value IS NOT NULL), "
            f"coalesce(sum(products_dropped_from_gold), 0) FROM {MAPPING_GAPS_TABLE}"
        )
        to_review, dropped = (rows[0] if rows else [None, None])
        return (f"Mapping gaps: {to_review or 0} brand spelling(s) to review (scraper-pipeline: "
                f"make seed-suggestions); {dropped or 0} product drop(s) from gold "
                "(a product missing two mappings counts twice)")
    except Exception as e:
        logger.warning("Mapping gaps query failed: %s", e)
        return f"Mapping gaps: not available ({str(e)[:200]})"


def _count(value):
    return f"{int(value):,}" if value not in (None, "") else "?"


def _count_lines(crawls):
    """
    Per site: language rows this run crawled -> rows in gold -> rows with a
    served image (what the website shows). Gold keeps products from earlier
    runs, so it can exceed one run's crawl; a sudden gap is what to look for.
    """
    crawled = {c.get("site"): (c.get("result") or {}).get("rows") for c in crawls}
    try:
        rows = _athena_rows(
            "SELECT site, count(*), count_if(coalesce(cardinality(image_s3_blob_keys), 0) > 0) "
            f"FROM {GOLD_TABLE} GROUP BY site ORDER BY site"
        )
        gold = {site: (total, with_images) for site, total, with_images in rows if site}
    except Exception as e:
        logger.warning("Gold count query failed: %s", e)
        return [f"Counts: not available ({str(e)[:200]})"]
    lines = ["Counts (language rows): crawled this run -> in gold -> with images"]
    for site in sorted(set(crawled) | set(gold)):
        total, with_images = gold.get(site, (0, 0))
        ran = f"{_count(crawled[site])} crawled" if site in crawled else "not crawled this run"
        lines.append(f"- {site}: {ran} -> {_count(total)} in gold -> {_count(with_images)} with images")
    return lines


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
        if result.get("rows") is not None:
            line += f", {_count(result['rows'])} rows"
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
        if failed_step in DBT_STEPS:
            lines.extend(_dbt_failure_lines(failure, state))
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
    dbt_ran = (flow.get("stop_after") != "crawls"
               and (failed_step in AFTER_DBT_RUN
                    or (not failed_step and (flow.get("start_at") != "crawl" or gate_result.get("published", 0) > 0))))
    if dbt_ran:
        lines.extend(_count_lines(crawls))
        lines.append(_mapping_gaps_line())
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
