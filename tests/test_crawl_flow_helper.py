import importlib.util
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest


BUCKET = "price-comparison-bucket-eu-central-1"


class _Paginator:
    def __init__(self, pages):
        self.pages = pages

    def paginate(self, **kwargs):
        return self.pages(**kwargs)


class _FakeS3:
    def __init__(self, objects=None):
        self.objects = dict(objects or {})

    def put_object(self, Bucket, Key, Body, ContentType=None):
        self.objects[Key] = Body

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[Key])}

    def get_paginator(self, name):
        assert name == "list_objects_v2"

        def pages(Bucket, Prefix):
            keys = sorted(key for key in self.objects if key.startswith(Prefix))
            return [{"Contents": [{"Key": key} for key in keys]}] if keys else [{}]

        return _Paginator(pages)


class _FakeAthena:
    def __init__(self, rows, state="SUCCEEDED"):
        self.rows = rows
        self.state = state
        self.queries = []

    def start_query_execution(self, QueryString, WorkGroup, ResultConfiguration):
        self.queries.append(QueryString)
        return {"QueryExecutionId": "q1"}

    def get_query_execution(self, QueryExecutionId):
        return {"QueryExecution": {"Status": {"State": self.state, "StateChangeReason": "boom"}}}

    def get_paginator(self, name):
        assert name == "get_query_results"
        # rows may be {text in the query: rows} to answer each query apart.
        answer = self.rows
        if isinstance(answer, dict):
            answer = next((v for k, v in answer.items() if k in self.queries[-1]), [])
        rows = [["site", "url"]] + answer

        def pages(QueryExecutionId):
            return [{"ResultSet": {"Rows": [
                {"Data": [{"VarCharValue": value} for value in row]} for row in rows
            ]}}]

        return _Paginator(pages)


class _FakeSfn:
    def __init__(self, running):
        self.running = running

    def get_paginator(self, name):
        assert name == "list_executions"

        def pages(stateMachineArn, statusFilter):
            return [{"executions": [{"executionArn": arn} for arn in self.running]}]

        return _Paginator(pages)


class _FakeLogs:
    """One log stream per task ID; pages of `page_size` events."""

    def __init__(self, streams=None, error=None, page_size=1000):
        self.streams = streams or {}
        self.error = error
        self.page_size = page_size
        self.calls = []

    def get_log_events(self, logGroupName, logStreamName, startFromHead, nextToken=None):
        self.calls.append((logGroupName, logStreamName))
        if self.error:
            raise self.error
        messages = self.streams.get(logStreamName.rsplit("/", 1)[-1], [])
        offset = int(nextToken or 0)
        page = messages[offset:offset + self.page_size]
        return {"events": [{"message": m} for m in page], "nextForwardToken": str(offset + len(page))}


@pytest.fixture
def helper():
    os.environ.setdefault("AWS_DEFAULT_REGION", "eu-central-1")
    os.environ["APP_ENV"] = "dev"
    spec = importlib.util.spec_from_file_location(
        "crawl_flow_helper_handler", Path("lambda/crawl_flow_helper/handler.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.s3 = _FakeS3()
    module.athena = _FakeAthena([])
    module.sfn = _FakeSfn([])
    module.logs = _FakeLogs()
    return module


EXECUTION = "arn:aws:states:eu-central-1:1:execution:crawl-flow-dev:run-1"
STATE_MACHINE = "arn:aws:states:eu-central-1:1:stateMachine:crawl-flow-dev"


def _start(helper, flow_input=None):
    return helper.handler({
        "action": "start",
        "execution_arn": EXECUTION,
        "state_machine_arn": STATE_MACHINE,
        "input": flow_input or {},
    }, None)


# -- start ------------------------------------------------------------------

def test_start_defaults_to_crawl_and_makes_image_run_id(helper):
    flow = _start(helper)
    assert flow["flow_id"] == "run-1"
    assert flow["start_at"] == "crawl"
    assert flow["limit"] is None
    from ecommercecrawl.spiders.mastercrawl import RUN_ID_PATTERN
    assert RUN_ID_PATTERN.match(flow["image_run_id"])


def test_start_ignores_itself_but_refuses_another_running_flow(helper):
    helper.sfn = _FakeSfn([EXECUTION])
    _start(helper)
    helper.sfn = _FakeSfn([EXECUTION, EXECUTION.replace("run-1", "run-0")])
    with pytest.raises(helper.FlowAlreadyRunning):
        _start(helper)


@pytest.mark.parametrize("flow_input", [{"start_at": "dbt"}, {"limit": 0}, {"limit": "5"}])
def test_start_rejects_bad_input(helper, flow_input):
    with pytest.raises(ValueError):
        _start(helper, flow_input)


# -- list_crawls ------------------------------------------------------------

REGISTRY = [
    ["bloomingdales", "https://bloomingdales.sa/womens-bags-tote-bags/"],
    ["bloomingdales", "https://en.bloomingdales.sa/womens-bags-tote-bags/"],
    ["cettire", "https://www.cettire.com/sa/collections/womens-bags/tote-bags"],
    ["level-shoes", "https://en-saudi.levelshoes.com/women/bags/tote-bags"],
    ["ounass", "https://saudi.ounass.com/api/women/bags/tote-bags"],
]


def test_list_crawls_one_crawl_per_site_from_the_registry(helper):
    helper.athena = _FakeAthena(REGISTRY)
    flow = _start(helper)
    crawls = {c["site"]: c for c in helper.handler({"action": "list_crawls", "flow": flow}, None)["crawls"]}

    assert set(crawls) == {"ounass", "level-shoes", "bloomingdales", "cettire"}
    assert "WHERE is_active" in helper.athena.queries[0]
    assert crawls["ounass"]["command"] == "python3 run_crawler.py ounass --env dev --plp-efficient"
    key = "bronze/dev/crawl-inputs/run-1/bloomingdales.csv"
    assert crawls["bloomingdales"]["command"] == (
        f"python3 run_crawler.py bloomingdales --env dev --urls-source s3://{BUCKET}/{key}"
    )
    assert helper.s3.objects[key].decode() == (
        "url\nhttps://bloomingdales.sa/womens-bags-tote-bags/\nhttps://en.bloomingdales.sa/womens-bags-tote-bags/\n"
    )
    assert crawls["level-shoes"]["spider"] == "level"
    assert crawls["level-shoes"]["url_count"] == 1
    assert crawls["cettire"]["command"] == (
        f"python3 run_crawler.py cettire --env dev --urls-source s3://{BUCKET}/bronze/dev/crawl-inputs/run-1/cettire.csv"
    )
    # Distinct run IDs, so markers can't collide.
    assert len({c["run_id"] for c in crawls.values()}) == 4


def test_list_crawls_adds_limit_to_every_crawl(helper):
    helper.athena = _FakeAthena(REGISTRY)
    flow = _start(helper, {"limit": 5})
    crawls = helper.handler({"action": "list_crawls", "flow": flow}, None)["crawls"]
    assert all(c["command"].endswith("--limit 5") for c in crawls)


def test_list_crawls_skips_sites_without_active_rows(helper):
    helper.athena = _FakeAthena([REGISTRY[-1]])
    crawls = helper.handler({"action": "list_crawls", "flow": _start(helper)}, None)["crawls"]
    assert [c["site"] for c in crawls] == ["ounass"]


def test_list_crawls_refuses_a_site_it_cannot_crawl(helper):
    helper.athena = _FakeAthena([["farfetch", "https://www.farfetch.com/x"]])
    with pytest.raises(helper.UnknownRegistrySite):
        helper.handler({"action": "list_crawls", "flow": _start(helper)}, None)


def test_list_crawls_surfaces_a_failed_query(helper):
    helper.athena = _FakeAthena(REGISTRY, state="FAILED")
    with pytest.raises(helper.RegistryQueryFailed):
        helper.handler({"action": "list_crawls", "flow": _start(helper)}, None)


# -- check_crawl ------------------------------------------------------------

CRAWL = {"site": "level-shoes", "run_id": "2026-11-10T02-00-00-001"}
MARKERS = "bronze/dev/crawls/markers/level-shoes/2026-11-10/2026-11-10T02-00-00-001/"
MANIFEST = "bronze/dev/crawls/manifests/level-shoes/2026-11-10/2026-11-10T02-00-00-001/data.json"


def _check(helper, polls=0):
    return helper.handler({"action": "check_crawl", "crawl": CRAWL, "polls": polls}, None)


def test_check_crawl_pending_until_markers_appear(helper):
    result = _check(helper)
    assert result["done"] is False and result["polls"] == 1


def test_check_crawl_killed_after_max_polls(helper):
    result = _check(helper, polls=helper.MAX_VERIFY_POLLS - 1)
    assert result["done"] is True and result["run_status"] == "killed"


def test_check_crawl_success_reads_degraded_from_manifest(helper):
    helper.s3.objects[MARKERS + "_SUCCESS"] = b""
    helper.s3.objects[MANIFEST] = json.dumps({"run_status": "degraded", "degradations": {"pdp_skipped": 3}}).encode()
    result = _check(helper)
    assert result["run_status"] == "degraded"
    assert result["degradations"] == {"pdp_skipped": 3}


def test_check_crawl_failure_markers_give_reasons(helper):
    helper.s3.objects[MARKERS + "_FAILED"] = json.dumps({"failure_reason": "access"}).encode()
    helper.s3.objects[MARKERS + "_FAIL_ACCESS"] = json.dumps({"failure_reason": "access"}).encode()
    result = _check(helper)
    assert result["run_status"] == "failed"
    assert result["failure_reasons"] == ["access", "access"]


# -- gate, find_image_marker, summary ---------------------------------------

def _crawl(status):
    return {"site": "ounass", "run_id": "r", "result": {"run_status": status}}


def test_gate_counts_success_and_degraded(helper):
    result = helper.handler({"action": "gate", "crawls": [
        _crawl("success"), _crawl("degraded"), _crawl("failed"), _crawl("killed"), {"site": "x"},
    ]}, None)
    assert result == {"published": 2, "total": 5}


def test_find_image_marker_finds_success_or_failed_or_nothing(helper):
    flow = _start(helper)
    day = datetime.now(timezone.utc).date().isoformat()
    meta = f"bronze/dev/images/download_log/meta/{day}/{flow['image_run_id']}/"

    assert helper.handler({"action": "find_image_marker", "flow": flow}, None)["found"] is False
    helper.s3.objects[meta + "_FAILED"] = b""
    found = helper.handler({"action": "find_image_marker", "flow": flow}, None)
    assert found == {"found": True, "dt": day, "marker": "_FAILED", "run_id": flow["image_run_id"]}


def test_summary_succeeds_with_a_published_crawl(helper):
    flow = _start(helper)
    result = helper.handler({"action": "summary", "state": {
        "flow": flow, "crawls": [_crawl("success"), _crawl("failed")], "gate": {"published": 1},
        "image_marker": {"found": False},
    }}, None)
    assert result["status"] == "succeeded"
    assert "1 crawl(s) not published" in result["text"]
    assert "nothing to download" in result["text"]


def test_summary_fails_when_nothing_published(helper):
    result = helper.handler({"action": "summary", "state": {
        "flow": _start(helper), "crawls": [_crawl("killed")], "gate": {"published": 0},
    }}, None)
    assert result["status"] == "failed"
    assert "no crawl published" in result["text"]


def test_summary_fails_with_the_failed_step(helper):
    result = helper.handler({"action": "summary", "state": {
        "flow": _start(helper, {"start_at": "images"}),
        "failed_step": "quality_checker", "failure": {"exit_code": 1},
    }}, None)
    assert result["status"] == "failed"
    assert "quality checker: exit code 1" in result["text"]


def test_unknown_action(helper):
    with pytest.raises(ValueError):
        helper.handler({"action": "nope"}, None)


def test_summary_reads_exit_code_of_the_last_task(helper):
    result = helper.handler({"action": "summary", "state": {
        "flow": _start(helper), "failed_step": "dbt_run",
        "last_task": {"containers": [{"Name": "dbt", "ExitCode": 77}]},
    }}, None)
    assert "dbt run (full): exit code 77" in result["text"]


def test_summary_reads_exit_code_from_an_ecs_task_failure(helper):
    cause = json.dumps({
        "StopCode": "EssentialContainerExited",
        "StoppedReason": "Essential container in task exited",
        "TaskArn": "arn:aws:ecs:eu-central-1:1:task/ecommerce-scraper/b9b73c57",
        "Containers": [{"Name": "dbt", "ExitCode": 1}],
    })
    result = helper.handler({"action": "summary", "state": {
        "flow": _start(helper), "failed_step": "dbt_test",
        "failure": {"Error": "States.TaskFailed", "Cause": cause},
    }}, None)
    assert "FAILED at dbt test: exit code 1 (Essential container in task exited) task b9b73c57" in result["text"]


def test_summary_keeps_a_plain_error_cause(helper):
    result = helper.handler({"action": "summary", "state": {
        "flow": _start(helper), "failed_step": "list_crawls",
        "failure": {"Error": "RegistryQueryFailed", "Cause": "boom"},
    }}, None)
    assert "FAILED at reading the registry: RegistryQueryFailed boom" in result["text"]


# -- summary email (step 5) -------------------------------------------------

def test_summary_subject_counts_published_crawls_and_says_the_cache_refreshed(helper):
    result = helper.handler({"action": "summary", "state": {
        "flow": _start(helper), "crawls": [_crawl("success"), _crawl("degraded"), _crawl("failed")],
        "gate": {"published": 2}, "image_marker": {"found": False},
    }}, None)
    assert result["subject"] == "Crawl flow dev SUCCEEDED: 2/3 crawls published"
    assert "API cache refreshed" in result["text"]
    assert result["text"].endswith(f"Console: https://eu-central-1.console.aws.amazon.com/states/home"
                                   f"?region=eu-central-1#/v2/executions/details/{EXECUTION}")


def test_summary_subject_for_an_images_only_run(helper):
    result = helper.handler({"action": "summary", "state": {
        "flow": _start(helper, {"start_at": "images"}), "image_marker": {"found": False},
    }}, None)
    assert result["subject"] == "Crawl flow dev SUCCEEDED (images only)"


def test_summary_failure_says_the_cache_kept_the_last_tested_data(helper):
    result = helper.handler({"action": "summary", "state": {
        "flow": _start(helper), "failed_step": "dbt_test", "failure": {"exit_code": 1},
    }}, None)
    assert result["subject"] == "Crawl flow dev FAILED at dbt test"
    assert "API cache not refreshed: the API keeps the last tested data" in result["text"]


def test_summary_failed_cache_refresh_keeps_the_previous_data(helper):
    result = helper.handler({"action": "summary", "state": {
        "flow": _start(helper), "failed_step": "refresh_cache", "failure": {"exit_code": 77},
    }}, None)
    assert result["subject"] == "Crawl flow dev FAILED at API cache refresh"
    assert "API cache refresh failed: the API keeps the previous data" in result["text"]


def test_summary_no_crawl_published_subject(helper):
    result = helper.handler({"action": "summary", "state": {
        "flow": _start(helper), "crawls": [_crawl("killed")], "gate": {"published": 0},
    }}, None)
    assert result["subject"] == "Crawl flow dev FAILED: no crawl published"


def test_summary_lists_degradations_and_puts_blocking_in_its_own_section(helper):
    blocked = {"site": "level-shoes", "run_id": "r2",
               "result": {"run_status": "failed", "failure_reasons": ["access"]}}
    degraded = {"site": "ounass", "run_id": "r1", "result": {"run_status": "degraded", "degradations": [
        {"kind": "access", "scope": "en-saudi.ounass.com", "message": "12 listing rows lost to blocking"},
        {"kind": "content", "scope": "phase2", "message": "Phase 2 skipped"},
    ]}}
    text = helper.handler({"action": "summary", "state": {
        "flow": _start(helper), "crawls": [degraded, blocked], "gate": {"published": 1},
    }}, None)["text"]
    assert "    access en-saudi.ounass.com: 12 listing rows lost to blocking" in text
    assert "    content phase2: Phase 2 skipped" in text
    section = text.split("Blocked by the site:\n", 1)[1].splitlines()
    assert section[:2] == [
        "- ounass access en-saudi.ounass.com: 12 listing rows lost to blocking",
        "- level-shoes: crawl failed, nothing written",
    ]


def test_summary_subject_is_one_line_of_at_most_100_characters(helper):
    result = helper.handler({"action": "summary", "state": {
        "flow": _start(helper), "failed_step": "x" * 200, "failure": {"exit_code": 1},
    }}, None)
    assert len(result["subject"]) == 100 and "\n" not in result["subject"]


def test_check_crawl_crash_marker_carries_the_error_into_the_summary(helper):
    helper.s3.objects[MARKERS + "_FAIL_CRASH"] = json.dumps({
        "failure_reason": "crash", "first_error": "KeyError: 'item_id' (level_rules.py:31)",
    }).encode()
    result = _check(helper)
    assert result["failure_reasons"] == ["crash: KeyError: 'item_id' (level_rules.py:31)"]
    text = helper.handler({"action": "summary", "state": {
        "flow": _start(helper), "crawls": [{"site": "level-shoes", "run_id": "r", "result": result}],
        "gate": {"published": 0},
    }}, None)["text"]
    assert "- level-shoes r: failed (crash: KeyError: 'item_id' (level_rules.py:31))" in text


# -- stop_after = crawls ----------------------------------------------------

def test_start_defaults_stop_after_to_none_so_the_choice_can_read_it(helper):
    assert _start(helper)["stop_after"] == "none"
    assert _start(helper, {"stop_after": "crawls"})["stop_after"] == "crawls"


@pytest.mark.parametrize("flow_input", [{"stop_after": "dbt"}, {"start_at": "images", "stop_after": "crawls"}])
def test_start_rejects_bad_stop_after(helper, flow_input):
    with pytest.raises(ValueError):
        _start(helper, flow_input)


def test_summary_for_a_crawls_only_run_says_nothing_else_ran(helper):
    result = helper.handler({"action": "summary", "state": {
        "flow": _start(helper, {"stop_after": "crawls"}), "crawls": [_crawl("success"), _crawl("failed")],
        "gate": {"published": 1},
    }}, None)
    assert result["status"] == "succeeded"
    assert result["subject"] == "Crawl flow dev SUCCEEDED (crawls only): 1/2 crawls published"
    assert "no dbt, images or cache refresh" in result["text"]
    assert "API cache refreshed" not in result["text"]


def test_crawls_only_run_with_nothing_published_still_fails(helper):
    result = helper.handler({"action": "summary", "state": {
        "flow": _start(helper, {"stop_after": "crawls"}), "crawls": [_crawl("failed")],
        "gate": {"published": 0},
    }}, None)
    assert result["status"] == "failed"


# -- mapping gaps line --------------------------------------------------------

def _summary_text(helper, **state):
    return helper.handler({"action": "summary", "state": {"flow": _start(helper), **state}}, None)["text"]


def test_summary_reports_mapping_gaps_after_dbt_ran(helper):
    helper.athena = _FakeAthena({"silver_mapping_gaps": [["3", "2"]]})
    text = _summary_text(helper, crawls=[_crawl("success")], gate={"published": 1})
    assert ("Mapping gaps: 3 brand spelling(s) to review (scraper-pipeline: make seed-suggestions); "
            "2 product drop(s) from gold (a product missing two mappings counts twice)") in text
    assert "silver_mapping_gaps" in helper.athena.queries[-1]


def test_summary_mapping_gaps_also_on_a_failed_dbt_test(helper):
    helper.athena = _FakeAthena({"silver_mapping_gaps": [["0", "5"]]})
    text = _summary_text(helper, failed_step="dbt_test", failure={"exit_code": 1})
    assert "5 product drop(s) from gold" in text


def test_summary_mapping_gaps_query_failure_never_fails_the_summary(helper):
    helper.athena = _FakeAthena([], state="FAILED")
    text = _summary_text(helper, crawls=[_crawl("success")], gate={"published": 1})
    assert "Mapping gaps: not available (boom)" in text


@pytest.mark.parametrize("state", [
    {"failed_step": "dbt_run", "failure": {"exit_code": 1}},          # gold not rebuilt
    {"crawls": [_crawl("failed")], "gate": {"published": 0}},         # dbt skipped
])
def test_summary_skips_mapping_gaps_when_dbt_did_not_run(helper, state):
    text = _summary_text(helper, **state)
    assert "Mapping gaps" not in text and helper.athena.queries == []


def test_crawls_only_summary_skips_mapping_gaps(helper):
    helper.handler({"action": "summary", "state": {
        "flow": _start(helper, {"stop_after": "crawls"}), "crawls": [_crawl("success")], "gate": {"published": 1},
    }}, None)
    assert helper.athena.queries == []



# -- count lines --------------------------------------------------------------

GOLD_ROWS = [["bloomingdales", "230", "228"], ["level-shoes", "4690", "4650"], ["ounass", "6400", "6390"]]


def test_check_crawl_reports_the_rows_the_crawl_wrote(helper):
    helper.s3.objects[MARKERS + "_SUCCESS"] = b""
    helper.s3.objects[MANIFEST] = json.dumps({"run_status": "success", "artifacts": {"rows": 4712}}).encode()
    assert _check(helper)["rows"] == 4712


def test_summary_counts_crawled_gold_and_with_images_per_site(helper):
    helper.athena = _FakeAthena({"gold_product_serving_latest": GOLD_ROWS, "silver_mapping_gaps": [["0", "0"]]})
    crawls = [{"site": "level-shoes", "run_id": "r1", "result": {"run_status": "success", "rows": 4712}},
              {"site": "bloomingdales", "run_id": "r2", "result": {"run_status": "failed", "failure_reasons": ["quality"]}}]
    text = _summary_text(helper, crawls=crawls, gate={"published": 1})
    assert "- level-shoes r1: success, 4,712 rows" in text
    assert "Counts (language rows): crawled this run -> in gold -> with images" in text
    assert "- level-shoes: 4,712 crawled -> 4,690 in gold -> 4,650 with images" in text
    assert "- bloomingdales: ? crawled -> 230 in gold -> 228 with images" in text
    assert "- ounass: not crawled this run -> 6,400 in gold -> 6,390 with images" in text


def test_summary_count_query_failure_never_fails_the_summary(helper):
    helper.athena = _FakeAthena([], state="FAILED")
    text = _summary_text(helper, crawls=[_crawl("success")], gate={"published": 1})
    assert "Counts: not available (boom)" in text


def test_crawls_only_summary_shows_crawled_rows_but_no_gold_counts(helper):
    text = helper.handler({"action": "summary", "state": {
        "flow": _start(helper, {"stop_after": "crawls"}),
        "crawls": [{"site": "cettire", "run_id": "r", "result": {"run_status": "success", "rows": 812}}],
        "gate": {"published": 1},
    }}, None)["text"]
    assert "- cettire r: success, 812 rows" in text and "Counts" not in text


# -- why a dbt step failed (its task's log) ------------------------------------

def _dbt_line(text):
    return f"\x1b[0m23:25:30  {text}"


# The 2026-11-16 dbt test failure, as dbt 1.12 logged it (shortened).
DBT_TEST_LOG = [
    "[dbt-job] Lock taken: s3://bucket/locks/dbt-dev.lock (cloud:root@ip)",
    _dbt_line("Running with dbt=1.12.5"),
    _dbt_line("1 of 56 PASS not_null_gold_product_serving_latest_site ... [\x1b[32mPASS\x1b[0m in 1.2s]"),
    _dbt_line("53 of 56 FAIL 30673 test_silver_product_image_download_status_gallery_contract . "
              "[\x1b[31mFAIL 30673\x1b[0m in 3.34s]"),
    _dbt_line(""),
    _dbt_line("\x1b[31mCompleted with 1 error, 0 partial successes, and 1 warning:\x1b[0m"),
    _dbt_line(""),
    _dbt_line("[\x1b[31mERROR\x1b[0m]: in test test_silver_product_image_download_status_gallery_contract "
              "(tests/test_silver_product_image_download_status_gallery_contract.sql)"),
    _dbt_line("  Got 30673 results, configured to fail if != 0"),
    _dbt_line(""),
    _dbt_line("  compiled code at target/compiled/price_comparison/tests/x.sql"),
    _dbt_line(""),
    _dbt_line("[\x1b[33mWARNING\x1b[0m]: in test test_silver_product_fact_nonpositive_price "
              "(tests/test_silver_product_fact_nonpositive_price.sql)"),
    _dbt_line("[\x1b[33mWARNING\x1b[0m]: Got 2 results, configured to warn if != 0"),
    _dbt_line(""),
    _dbt_line("  compiled code at target/compiled/price_comparison/tests/y.sql"),
    _dbt_line(""),
    _dbt_line("Done. PASS=54 WARN=1 ERROR=1 SKIP=0 NO-OP=0 REUSED=0 TOTAL=56"),
    "[dbt-job] Lock released.",
]


def _ecs_failure(task_id):
    return {"Error": "States.TaskFailed", "Cause": json.dumps({
        "StoppedReason": "Essential container in task exited",
        "TaskArn": f"arn:aws:ecs:eu-central-1:1:task/price-comparison/{task_id}",
        "Containers": [{"Name": "dbt", "ExitCode": 1}],
    })}


def test_summary_explains_a_failed_dbt_test_from_its_log(helper):
    helper.logs = _FakeLogs({"a2de91b7": DBT_TEST_LOG}, page_size=5)  # several pages
    text = _summary_text(helper, failed_step="dbt_test", failure=_ecs_failure("a2de91b7"))
    assert ("dbt said:\n"
            "- in test test_silver_product_image_download_status_gallery_contract "
            "(tests/test_silver_product_image_download_status_gallery_contract.sql): "
            "Got 30673 results, configured to fail if != 0\n"
            "- Done. PASS=54 WARN=1 ERROR=1 SKIP=0 NO-OP=0 REUSED=0 TOTAL=56\n") in text
    assert "nonpositive_price" not in text  # a warning doesn't fail the step
    assert helper.logs.calls[0] == ("/ecs/price-comparison-dbt-dev", "dbt/dbt/a2de91b7")
    assert "dbt log: https://" in text and "dbt$252Fdbt$252Fa2de91b7" in text


def test_summary_explains_a_model_error_and_caps_the_list(helper):
    log = [_dbt_line("Completed with 12 errors, 0 partial successes, and 0 warnings:"), _dbt_line("")]
    for n in range(12):
        log += [_dbt_line(f"[ERROR]: in model gold_{n} (models/gold/gold_{n}.sql)"),
                _dbt_line(f"  Database Error in model gold_{n} (models/gold/gold_{n}.sql)"),
                _dbt_line("    COLUMN_NOT_FOUND: line 3:8: Column 'brand' cannot be resolved"),
                _dbt_line("")]
    helper.logs = _FakeLogs({"t1": log + [_dbt_line("Done. PASS=0 WARN=0 ERROR=12 SKIP=0 TOTAL=12")]})
    text = _summary_text(helper, failed_step="dbt_run", failure=_ecs_failure("t1"))
    assert ("- in model gold_0 (models/gold/gold_0.sql): Database Error in model gold_0 "
            "(models/gold/gold_0.sql): COLUMN_NOT_FOUND: line 3:8: Column 'brand' cannot be resolved") in text
    assert "gold_9 " in text and "gold_10 " not in text
    assert "- ...and 2 more (see the log)" in text


def test_summary_shows_the_log_tail_when_dbt_printed_no_errors(helper):
    # The task ran but exited non-zero: the task ARN is in last_task.
    helper.logs = _FakeLogs({"t2": ["[dbt-job] Waiting for the lock", "",
                                    "[dbt-job] Lock not taken after 7200s: held by laptop"]})
    text = _summary_text(helper, failed_step="dbt_test", failure=None, last_task={"containers": [
        {"ExitCode": 75, "TaskArn": "arn:aws:ecs:eu-central-1:1:task/price-comparison/t2"}]})
    assert "dbt said:\n  [dbt-job] Waiting for the lock\n  [dbt-job] Lock not taken after 7200s" in text


def test_summary_dbt_log_read_failure_never_fails_the_summary(helper):
    helper.logs = _FakeLogs(error=RuntimeError("AccessDenied"))
    text = _summary_text(helper, failed_step="dbt_test", failure=_ecs_failure("t3"))
    assert "dbt said: not available (AccessDenied)" in text
    assert "API cache not refreshed" in text


def test_summary_reads_no_dbt_log_for_other_steps(helper):
    _summary_text(helper, failed_step="image_pipeline", failure=_ecs_failure("t4"))
    assert helper.logs.calls == []
