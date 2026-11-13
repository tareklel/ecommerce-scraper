from scripts import crawl_schedule

SCHEDULE = {
    "Arn": "arn:aws:scheduler:eu-central-1:1:schedule/default/ecommerce-scraper-crawl-flow-dev",
    "Name": "ecommerce-scraper-crawl-flow-dev",
    "GroupName": "default",
    "State": "ENABLED",
    "ScheduleExpression": "cron(0 2 * * ? *)",
    "ScheduleExpressionTimezone": "Asia/Dubai",
    "EndDate": "2026-11-20T20:00:00+00:00",
    "FlexibleTimeWindow": {"Mode": "OFF"},
    "Target": {"Arn": "arn:sfn", "RoleArn": "arn:role", "Input": "{\"start_at\": \"crawl\"}",
               "RetryPolicy": {"MaximumRetryAttempts": 0}},
    "Description": None,
    "CreationDate": "2026-11-13T13:00:00+00:00",
    "LastModificationDate": "2026-11-13T13:00:00+00:00",
}


def test_update_input_changes_only_the_state_and_keeps_everything_else():
    body = crawl_schedule.update_input(SCHEDULE, "DISABLED")
    assert body["State"] == "DISABLED"
    for key in ("Name", "GroupName", "ScheduleExpression", "ScheduleExpressionTimezone",
                "EndDate", "FlexibleTimeWindow", "Target"):
        assert body[key] == SCHEDULE[key]


def test_update_input_leaves_out_read_only_and_empty_fields():
    body = crawl_schedule.update_input(SCHEDULE, "ENABLED")
    assert not {"Arn", "CreationDate", "LastModificationDate", "Description"} & set(body)


def test_describe_shows_state_timing_and_end():
    assert crawl_schedule.describe(SCHEDULE) == (
        "ecommerce-scraper-crawl-flow-dev: ENABLED, cron(0 2 * * ? *) (Asia/Dubai), "
        "ends 2026-11-20T20:00:00+00:00"
    )
