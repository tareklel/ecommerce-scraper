import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path


class _FakeGlue:
    def __init__(self):
        self.create_calls = []

    def create_partition(self, **kwargs):
        self.create_calls.append(kwargs)

    @property
    def exceptions(self):
        class _Exc:
            class AlreadyExistsException(Exception):
                pass
        return _Exc()


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
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    os.environ.setdefault("APP_ENV", "dev")
    module_path = Path("lambda/bronze_manifest_verifier/handler.py")
    spec = importlib.util.spec_from_file_location("bronze_manifest_verifier_handler", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _build_fixture(quality_status="pass", hash_override=None):
    bucket = "test-bucket"
    manifest_key = "bronze/dev/crawls/metadata/ounass/2026-03-03/run123/manifest.json"
    data_key = "bronze/dev/crawls/ounass/2026-03-03/run123/ounass.jsonl.gz"

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


# ---- marker path tests ----

def test_verify_manifest_writes_success_marker_under_markers_prefix():
    handler = _load_handler_module()
    bucket, manifest_key, objects = _build_fixture(quality_status="pass")
    fake_s3 = _FakeS3(objects)
    handler.s3 = fake_s3

    result = handler._verify_manifest_and_write_success(bucket, manifest_key)

    keys = _put_keys(fake_s3)
    assert result["status"] == "ok"
    assert "bronze/dev/crawls/markers/ounass/2026-03-03/run123/_SUCCESS" in keys
    assert "bronze/dev/crawls/markers/ounass/2026-03-03/run123/_FAIL_QUALITY" not in keys
    assert "bronze/dev/crawls/markers/ounass/2026-03-03/run123/_FAILED" not in keys


def test_verify_manifest_writes_fail_quality_marker_under_markers_prefix():
    handler = _load_handler_module()
    bucket, manifest_key, objects = _build_fixture(quality_status="fail_quality")
    fake_s3 = _FakeS3(objects)
    handler.s3 = fake_s3

    result = handler._verify_manifest_and_write_success(bucket, manifest_key)

    keys = _put_keys(fake_s3)
    assert result["status"] == "error"
    assert "bronze/dev/crawls/markers/ounass/2026-03-03/run123/_FAIL_QUALITY" in keys
    assert "bronze/dev/crawls/markers/ounass/2026-03-03/run123/_SUCCESS" not in keys
    assert "bronze/dev/crawls/markers/ounass/2026-03-03/run123/_FAILED" not in keys


def test_verify_manifest_writes_fail_quality_and_failed_markers_when_both_fail():
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
    assert "bronze/dev/crawls/markers/ounass/2026-03-03/run123/_FAIL_QUALITY" in keys
    assert "bronze/dev/crawls/markers/ounass/2026-03-03/run123/_FAILED" in keys
    assert "bronze/dev/crawls/markers/ounass/2026-03-03/run123/_SUCCESS" not in keys


# ---- verified manifest write tests ----

def test_verify_manifest_writes_wrapper_json_to_manifests_prefix():
    handler = _load_handler_module()
    bucket, manifest_key, objects = _build_fixture(quality_status="pass")
    fake_s3 = _FakeS3(objects)
    handler.s3 = fake_s3

    result = handler._verify_manifest_and_write_success(bucket, manifest_key)

    dest = "bronze/dev/crawls/manifests/ounass/2026-03-03/run123/data.json"
    assert result["manifest_dest_key"] == dest
    assert (bucket, dest) in fake_s3.objects

    wrapper = json.loads(fake_s3.objects[(bucket, dest)])
    # top-level columns readable directly by Athena JsonSerDe
    assert wrapper["run_id"] is None  # fixture manifest has no run_id field
    assert "raw_json" in wrapper

    # raw_json contains the full verified manifest as a string
    inner = json.loads(wrapper["raw_json"])
    assert inner["verification"]["outcome"] == "SUCCESS"
    assert inner["verification"]["failure_reason"] is None
    assert "verified_at" in inner["verification"]


def test_verify_manifest_writes_fail_outcome_in_wrapper_raw_json():
    handler = _load_handler_module()
    bucket, manifest_key, objects = _build_fixture(quality_status="fail_quality")
    fake_s3 = _FakeS3(objects)
    handler.s3 = fake_s3

    handler._verify_manifest_and_write_success(bucket, manifest_key)

    dest = "bronze/dev/crawls/manifests/ounass/2026-03-03/run123/data.json"
    wrapper = json.loads(fake_s3.objects[(bucket, dest)])
    inner = json.loads(wrapper["raw_json"])
    assert inner["verification"]["outcome"] == "FAIL_QUALITY"
    assert inner["verification"]["failure_reason"] == "test_reason"


# ---- partition registration tests ----

def test_register_bronze_partition_reads_from_markers_prefix():
    handler = _load_handler_module()
    fake_s3 = _FakeS3()
    fake_glue = _FakeGlue()
    handler.s3 = fake_s3
    handler.glue = fake_glue

    success_key = "bronze/dev/crawls/markers/ounass/2026-03-03/run123/_SUCCESS"
    result = handler._register_bronze_partition("test-bucket", success_key)

    assert result["status"] == "ok"
    assert result["partition"] == {"site": "ounass", "dt": "2026-03-03"}


def test_register_bronze_partition_registers_both_tables():
    handler = _load_handler_module()
    fake_s3 = _FakeS3()
    fake_glue = _FakeGlue()
    handler.s3 = fake_s3
    handler.glue = fake_glue

    success_key = "bronze/dev/crawls/markers/ounass/2026-03-03/run123/_SUCCESS"
    handler._register_bronze_partition("test-bucket", success_key)

    tables = [call["TableName"] for call in fake_glue.create_calls]
    assert "bronze_ounass_raw" in tables
    assert "crawl_manifest_raw" in tables


def test_register_bronze_partition_manifest_table_uses_site_dt_values():
    handler = _load_handler_module()
    fake_s3 = _FakeS3()
    fake_glue = _FakeGlue()
    handler.s3 = fake_s3
    handler.glue = fake_glue

    success_key = "bronze/dev/crawls/markers/ounass/2026-03-03/run123/_SUCCESS"
    handler._register_bronze_partition("test-bucket", success_key)

    manifest_call = next(c for c in fake_glue.create_calls if c["TableName"] == "crawl_manifest_raw")
    assert manifest_call["PartitionInput"]["Values"] == ["ounass", "2026-03-03"]
    assert "manifests/ounass/2026-03-03" in manifest_call["PartitionInput"]["StorageDescriptor"]["Location"]
