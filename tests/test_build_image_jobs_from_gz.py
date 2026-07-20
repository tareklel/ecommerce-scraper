import gzip
import json

from scripts.backfill.build_image_jobs_from_gz import build_jobs


def test_build_jobs_fans_out_ordered_gallery_to_scalar_jobs(tmp_path):
    input_gz = tmp_path / "crawl.jsonl.gz"
    output_jsonl = tmp_path / "jobs.jsonl"
    gallery = [
        "https://cdn.example.com/hero.jpg",
        "https://cdn.example.com/side.jpg",
        "https://cdn.example.com/detail.jpg",
        "https://cdn.example.com/back.jpg",
    ]
    crawler_row = {
        "site": "ounass",
        "portal_itemid": "SKU123",
        "run_id": "2026-07-20T08-00-00-000",
        "image_urls": gallery,
    }
    with gzip.open(input_gz, "wt", encoding="utf-8") as output:
        output.write(json.dumps(crawler_row) + "\n")

    counts, jobs_written = build_jobs(str(input_gz), str(output_jsonl))
    jobs = [json.loads(line) for line in output_jsonl.read_text().splitlines()]

    assert jobs_written == 4
    assert counts["jobs_written"] == 4
    assert [job["image_url"] for job in jobs] == gallery
    assert {job["primary_key"] for job in jobs} == {"SKU123_ounass"}
    assert {job["source_run_id"] for job in jobs} == {
        "2026-07-20T08-00-00-000",
    }


def test_build_jobs_ignores_non_string_gallery_members(tmp_path):
    input_gz = tmp_path / "crawl.jsonl.gz"
    output_jsonl = tmp_path / "jobs.jsonl"
    crawler_row = {
        "site": "level-shoes",
        "portal_itemid": "SKU456",
        "image_urls": [
            " https://cdn.example.com/hero.jpg ",
            None,
            {"url": "https://cdn.example.com/not-a-scalar.jpg"},
        ],
    }
    with gzip.open(input_gz, "wt", encoding="utf-8") as output:
        output.write(json.dumps(crawler_row) + "\n")

    _, jobs_written = build_jobs(str(input_gz), str(output_jsonl))
    jobs = [json.loads(line) for line in output_jsonl.read_text().splitlines()]

    assert jobs_written == 1
    assert jobs[0]["image_url"] == "https://cdn.example.com/hero.jpg"
