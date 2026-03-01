import json
from pathlib import Path

from ecommercecrawl import image_downloader as downloader


class _MockResponse:
    def __init__(self, content=b"abc", content_type="image/jpeg", status_code=200):
        self.content = content
        self.headers = {"Content-Type": content_type}
        self.status_code = status_code

    def raise_for_status(self):
        return None


def test_normalize_site_level_alias():
    assert downloader.normalize_site("level_shoes") == "level-shoes"
    assert downloader.normalize_site("level") == "level-shoes"
    assert downloader.normalize_site("ounass") == "ounass"


def test_normalize_image_url_for_ounass_scheme_less_url():
    raw = "ounass-ae.atgcdn.ae/path/image.jpg?x=1"
    assert downloader.normalize_image_url("ounass", raw) == "https://ounass-ae.atgcdn.ae/path/image.jpg?x=1"


def test_extract_jobs_from_jsonl_reads_crawler_shape(tmp_path):
    path = tmp_path / "jobs.jsonl"
    lines = [
        {
            "site": "level_shoes",
            "primary_key": "ABC123_level-shoes",
            "image_urls": "https://assets.levelshoes.com/img.jpg",
            "run_id": "2026-02-26T14-00-00-000",
        },
        {
            "site": "ounass",
            "primary_key": "222_ounass",
            "image_url": "ounass-ae.atgcdn.ae/x.jpg",
            "run_id": "2026-02-26T14-00-00-000",
        },
        {"site": "ounass", "primary_key": "missing-image_ounass"},
    ]
    path.write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")

    jobs, skipped = downloader.extract_jobs_and_skips_from_jsonl(str(path))
    assert len(jobs) == 2
    assert len(skipped) == 1
    assert skipped[0]["status"] == downloader.STATUS_SKIPPED_INVALID
    assert skipped[0]["reason"] == "missing_required_fields"
    assert jobs[0]["primary_key"] == "ABC123_level-shoes"
    assert jobs[0]["source_run_id"] == "2026-02-26T14-00-00-000"


def test_download_one_job_writes_file(monkeypatch, tmp_path):
    calls = []

    def _fake_get(url, headers=None, timeout=None):
        calls.append((url, headers, timeout))
        return _MockResponse(content=b"image-bytes")

    monkeypatch.setattr(downloader.requests, "get", _fake_get)
    job = {
        "site": "level_shoes",
        "primary_key": "ABC123_level-shoes",
        "image_url": "https://assets.levelshoes.com/path/file.webp",
        "source_run_id": "2026-02-26T10-00-00-000",
    }
    result = downloader.download_one_job(
        job=job,
        output_dir=str(tmp_path),
        download_run_id="download-run-1",
        timeout_seconds=12,
    )

    assert result["status"] == "ok"
    assert result["reason"] == "downloaded"
    assert calls and calls[0][0] == "https://assets.levelshoes.com/path/file.webp"
    output_path = Path(result["storage"]["output_path"])
    assert output_path.exists()
    assert output_path.read_bytes() == b"image-bytes"
    assert result["storage"]["canonical_blob_key"].startswith("silver/images/by-hash/")
    assert result["storage"]["primary_key_pointer_key"].startswith("silver/images/by-primary/")
    assert result["transfer"]["bytes"] == len(b"image-bytes")
    assert result["job"]["primary_key"] == "ABC123_level-shoes"


def test_download_jobs_dedupes_same_job(monkeypatch, tmp_path):
    call_count = {"count": 0}

    def _fake_get(url, headers=None, timeout=None):
        call_count["count"] += 1
        return _MockResponse(content=b"x")

    monkeypatch.setattr(downloader.requests, "get", _fake_get)
    jobs = [
        {
            "site": "level_shoes",
            "primary_key": "A1_level-shoes",
            "image_url": "https://assets.levelshoes.com/path/file.jpg",
        },
        {
            "site": "level-shoes",
            "primary_key": "A1_level-shoes",
            "image_url": "https://assets.levelshoes.com/path/file.jpg",
        },
    ]
    results = downloader.download_jobs(jobs, output_dir=str(tmp_path), max_workers=2)

    statuses = [result["status"] for result in results]
    assert statuses.count(downloader.STATUS_OK) == 1
    assert statuses.count(downloader.STATUS_SKIPPED_DUPLICATE) == 1
    assert call_count["count"] == 1
