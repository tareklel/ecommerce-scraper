import json
import os


def main() -> None:
    cmd = os.environ.get("ECS_RUN_COMMAND", "").strip()
    app_env = os.environ.get("APP_ENV", "dev")

    if not cmd:
        print("")
        return

    overrides = {
        "containerOverrides": [
            {
                "name": "scraper",
                "command": [cmd],
                "environment": [{"name": "APP_ENV", "value": app_env}],
            }
        ]
    }
    print(json.dumps(overrides))


if __name__ == "__main__":
    main()
