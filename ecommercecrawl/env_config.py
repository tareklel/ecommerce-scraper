from pathlib import Path

import yaml

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "environments.yaml"


def load(app_env: str) -> dict:
    """Load environment config for app_env. Raises for anything other than 'dev' or 'prod'."""
    if app_env not in ("dev", "prod"):
        raise ValueError(f"Unknown app_env '{app_env}'. Must be 'dev' or 'prod'.")
    with open(_CONFIG_PATH) as f:
        raw = yaml.safe_load(f)
    return raw[app_env]


def bronze_key_prefix(config: dict) -> str:
    """Return the S3 key prefix from bronze_s3_prefix, e.g. 'bronze/dev/'."""
    uri = config["bronze_s3_prefix"]
    # strip s3://bucket-name/ to get the key portion
    return uri.split("/", 3)[3]
