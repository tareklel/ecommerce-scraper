import pytest

import run_image_downloader


def test_main_rejects_both_jsonl_and_inline(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_image_downloader.py",
            "--input-jsonl",
            "x.jsonl",
            "--site",
            "ounass",
            "--primary-key",
            "1_ounass",
            "--image-url",
            "https://example.com/1.jpg",
        ],
    )
    with pytest.raises(SystemExit) as exc:
        run_image_downloader.main()
    assert exc.value.code == 2


def test_main_rejects_incomplete_inline_mode(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_image_downloader.py",
            "--site",
            "ounass",
            "--primary-key",
            "1_ounass",
        ],
    )
    with pytest.raises(SystemExit) as exc:
        run_image_downloader.main()
    assert exc.value.code == 2


def test_main_allows_inline_mode(monkeypatch, tmp_path):
    calls = {}

    def _fake_download_jobs(jobs, output_dir, max_workers, timeout_seconds, download_run_id=None):
        calls["jobs"] = jobs
        calls["output_dir"] = output_dir
        calls["max_workers"] = max_workers
        calls["timeout_seconds"] = timeout_seconds
        calls["download_run_id"] = download_run_id
        return [{"status": "ok"}]

    monkeypatch.setattr(run_image_downloader, "download_jobs", _fake_download_jobs)
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_image_downloader.py",
            "--site",
            "level_shoes",
            "--primary-key",
            "ABC123_level-shoes",
            "--image-url",
            "https://assets.levelshoes.com/img.jpg",
            "--output-dir",
            str(tmp_path),
        ],
    )
    run_image_downloader.main()

    assert calls["jobs"][0]["site"] == "level_shoes"
    assert calls["jobs"][0]["primary_key"] == "ABC123_level-shoes"
    assert calls["download_run_id"] is not None
