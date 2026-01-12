import json
import os


def main() -> None:
    cmd = os.environ.get("ECS_RUN_COMMAND", "").strip()
    if not cmd:
        print("")
        return

    overrides = {
        "containerOverrides": [
            {
                "name": "scraper",
                "command": [cmd],
            }
        ]
    }
    print(json.dumps(overrides))


if __name__ == "__main__":
    main()
