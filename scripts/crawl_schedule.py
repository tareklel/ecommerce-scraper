"""
Switch the crawl flow's EventBridge schedule on or off, or show it.

    python3 scripts/crawl_schedule.py status|on|off

update-schedule replaces the whole schedule, so this reads it, changes only
State and sends everything else back unchanged. Terraform ignores State
(infra/terraform/orchestration.tf), so an apply doesn't undo the switch.
"""
import json
import os
import subprocess
import sys

SCHEDULE_NAME = os.environ.get("CRAWL_SCHEDULE_NAME", "ecommerce-scraper-crawl-flow-dev")
AWS_REGION = os.environ.get("AWS_REGION", "eu-central-1")

# Fields get-schedule returns that update-schedule accepts back.
KEPT_FIELDS = (
    "Name", "GroupName", "ScheduleExpression", "ScheduleExpressionTimezone", "Description",
    "StartDate", "EndDate", "FlexibleTimeWindow", "Target", "KmsKeyArn", "ActionAfterCompletion",
)


def _aws(args):
    result = subprocess.run(["aws", "scheduler", *args, "--region", AWS_REGION, "--output", "json"],
                            capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"aws scheduler {args[0]} failed: {result.stderr.strip()}")
    return json.loads(result.stdout or "{}")


def update_input(schedule, state):
    """The update-schedule input that keeps everything but State."""
    body = {k: schedule[k] for k in KEPT_FIELDS if schedule.get(k) is not None}
    body["State"] = state
    return body


def describe(schedule):
    return (f"{schedule['Name']}: {schedule['State']}, {schedule['ScheduleExpression']} "
            f"({schedule.get('ScheduleExpressionTimezone', 'UTC')}), "
            f"ends {schedule.get('EndDate') or 'never'}")


def main(argv):
    if len(argv) != 2 or argv[1] not in ("status", "on", "off"):
        sys.exit("usage: crawl_schedule.py status|on|off")
    schedule = _aws(["get-schedule", "--name", SCHEDULE_NAME])
    if argv[1] != "status":
        state = "ENABLED" if argv[1] == "on" else "DISABLED"
        _aws(["update-schedule", "--cli-input-json", json.dumps(update_input(schedule, state))])
        schedule = _aws(["get-schedule", "--name", SCHEDULE_NAME])
    print(describe(schedule))


if __name__ == "__main__":
    main(sys.argv)
