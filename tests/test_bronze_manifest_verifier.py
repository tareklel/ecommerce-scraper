import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path


class _FakeS3:
    def __init__(self, objects=None):
        self.objects = dict(objects or {})
        self.put_calls = []

    def get_object(self, Bucket, Key):
        data = self.objects[(Bucket, Key)]
        return {"Body": io.BytesIO(data)}

    def put_object(self, Bucket, Key, Body):
        self.objects[(Bucket, Key)] = Body
        self.put_calls.append((Bucket, Key, Body))
        return {"ResponseMetadata": {"HTTPStatusCode": 200}}


def _load_handler_module():
    # boto3 client creation at import requires a region to be set.
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    module_path = Path("lambda/bronze_manifest_verifier/handler.py")
    spec = importlib.util.spec_from_file_location("bronze_manifest_verifier_handler", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _build_fixture(quality_status="pass", hash_override=None):
    bucket = "test-bucket"
    manifest_key = "bronze/crawls/metadata/dev/ounass/2026-03-03/run123/manifest.json"
    data_key = "bronze/crawls/dev/ounass/2026-03-03/run123/ounass.jsonl.gz"

    raw = b'{"a":1}\n{"a":2}\n'
    compressed = gzip.compress(raw)
    calculated_hash = hashlib.sha256(compressed).hexdigest()
    expected_hash = hash_override or calculated_hash

    manifest = {
        "artifacts": {
            "file_path": "output/ounass.jsonl.gz",
            "rows": 2,
            "hashes": {"sha256": expected_hash},
        },
        "quality_gate": {
            "status": quality_status,
            "reason": "test_reason",
        },
    }

    objects = {
        (bucket, manifest_key): json.dumps(manifest).encode("utf-8"),
        (bucket, data_key): compressed,
    }
    return bucket, manifest_key, objects


def _put_keys(fake_s3):
    return [call[1] for call in fake_s3.put_calls]


def test_verify_manifest_writes_success_when_verification_and_quality_pass():
    handler = _load_handler_module()
    bucket, manifest_key, objects = _build_fixture(quality_status="pass")
    fake_s3 = _FakeS3(objects)
    handler.s3 = fake_s3

    result = handler._verify_manifest_and_write_success(bucket, manifest_key)

    keys = _put_keys(fake_s3)
    assert result["status"] == "ok"
    assert f"{manifest_key.rsplit('/', 1)[0]}/_SUCCESS" in keys
    assert f"{manifest_key.rsplit('/', 1)[0]}/_FAIL_QUALITY" not in keys
    assert f"{manifest_key.rsplit('/', 1)[0]}/_FAILED" not in keys


def test_verify_manifest_writes_fail_quality_marker_when_quality_not_pass():
    handler = _load_handler_module()
    bucket, manifest_key, objects = _build_fixture(quality_status="fail_quality")
    fake_s3 = _FakeS3(objects)
    handler.s3 = fake_s3

    result = handler._verify_manifest_and_write_success(bucket, manifest_key)

    keys = _put_keys(fake_s3)
    assert result["status"] == "error"
    assert f"{manifest_key.rsplit('/', 1)[0]}/_FAIL_QUALITY" in keys
    assert f"{manifest_key.rsplit('/', 1)[0]}/_SUCCESS" not in keys
    assert f"{manifest_key.rsplit('/', 1)[0]}/_FAILED" not in keys


def test_verify_manifest_writes_fail_quality_and_failed_when_both_fail():
    handler = _load_handler_module()
    bucket, manifest_key, objects = _build_fixture(
        quality_status="fail_quality",
        hash_override="deadbeef",
    )
    fake_s3 = _FakeS3(objects)
    handler.s3 = fake_s3

    result = handler._verify_manifest_and_write_success(bucket, manifest_key)

    keys = _put_keys(fake_s3)
    assert result["status"] == "error"
    assert f"{manifest_key.rsplit('/', 1)[0]}/_FAIL_QUALITY" in keys
    assert f"{manifest_key.rsplit('/', 1)[0]}/_FAILED" in keys
    assert f"{manifest_key.rsplit('/', 1)[0]}/_SUCCESS" not in keys
