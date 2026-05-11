import json
import re
import shlex
import sys


ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _stringify_env_value(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def main() -> None:
    secret_text = sys.stdin.read().strip()
    if not secret_text:
        raise SystemExit("AWS secret payload was empty")

    try:
        secret_values = json.loads(secret_text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"AWS secret must be a JSON object: {exc}") from exc

    if not isinstance(secret_values, dict):
        raise SystemExit("AWS secret must be a JSON object")

    exports = []
    for name, raw_value in secret_values.items():
        if not ENV_NAME_RE.fullmatch(name):
            raise SystemExit(f"Invalid environment variable name in secret: {name!r}")

        value = _stringify_env_value(raw_value)
        if value is None:
            continue

        exports.append(f"export {name}={shlex.quote(value)}")

    print("; ".join(exports))


if __name__ == "__main__":
    main()
