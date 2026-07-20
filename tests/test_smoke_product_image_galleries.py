import gzip
import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from scripts import smoke_product_image_galleries as smoke


def _write_crawl_artifact(path: Path, row: dict) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as output:
        output.write(json.dumps(row) + "\n")


@pytest.mark.parametrize(
    ("site", "row_site", "gallery"),
    [
        (
            "ounass",
            "ounass",
            [
                "https://ounass-ae.atgcdn.ae/media/catalog/product/dress_in.jpg?version=1",
                "https://ounass-ae.atgcdn.ae/media/catalog/product/dress_side.jpg?version=1",
            ],
        ),
        (
            "level",
            "level-shoes",
            [
                "https://assets.levelshoes.com/media/catalog/product/bag_1.jpg?version=1",
                "https://assets.levelshoes.com/media/catalog/product/bag_2.jpg?version=1",
            ],
        ),
    ],
)
def test_validate_crawl_artifact_accepts_ordered_product_gallery(
    tmp_path,
    site,
    row_site,
    gallery,
):
    artifact = tmp_path / "crawl.jsonl.gz"
    row = {"site": row_site, "portal_itemid": "SKU123", "image_urls": gallery}
    _write_crawl_artifact(artifact, row)

    actual_row, actual_gallery = smoke.validate_crawl_artifact(artifact, site)

    assert actual_row == row
    assert actual_gallery == gallery


@pytest.mark.parametrize(
    "gallery",
    [
        "https://assets.levelshoes.com/media/catalog/product/bag_1.jpg",
        ["https://assets.levelshoes.com/media/catalog/product/bag_1.jpg"],
        [
            "https://assets.levelshoes.com/media/catalog/product/bag_1.jpg",
            "https://assets.levelshoes.com/media/catalog/product/bag_1.jpg",
        ],
        [
            "https://assets.levelshoes.com/media/catalog/product/bag_1.jpg",
            "https://assets.levelshoes.com/static/navigation.jpg",
        ],
    ],
)
def test_validate_crawl_artifact_rejects_invalid_gallery(tmp_path, gallery):
    artifact = tmp_path / "crawl.jsonl.gz"
    _write_crawl_artifact(
        artifact,
        {"site": "level-shoes", "portal_itemid": "SKU123", "image_urls": gallery},
    )

    with pytest.raises(smoke.SmokeFailure):
        smoke.validate_crawl_artifact(artifact, "level")


def test_download_validator_checks_saved_bytes(monkeypatch, tmp_path):
    jobs_path = tmp_path / "jobs.jsonl"
    jobs_path.write_text(
        json.dumps(
            {
                "site": "level-shoes",
                "primary_key": "SKU123_level-shoes",
                "image_url": "https://assets.levelshoes.com/media/catalog/product/bag_1.jpg",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    image_path = tmp_path / "downloaded.png"
    image = Image.new("RGB", (12, 12), color="white")
    image.save(image_path)
    content_sha256 = hashlib.sha256(image_path.read_bytes()).hexdigest()

    def fake_downloader(command, **_kwargs):
        results_path = Path(command[command.index("--results-path") + 1])
        result = {
            "status": "ok",
            "reason": "downloaded",
            "storage": {"output_path": str(image_path)},
            "transfer": {"content_sha256": content_sha256},
        }
        results_path.write_text(json.dumps(result) + "\n", encoding="utf-8")

    monkeypatch.setattr(smoke.subprocess, "run", fake_downloader)

    assert smoke._download_and_validate_jobs(jobs_path, "level", tmp_path) == 1
