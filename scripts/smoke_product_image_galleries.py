"""Run a local-only end-to-end smoke test for product image galleries.

The command crawls one direct PDP per supported site, validates the crawler
arrays, fans them out through the backfill job builder, downloads every image,
and verifies the saved image bytes. All artifacts live in a temporary folder;
S3 upload is disabled explicitly.
"""

import argparse
import gzip
import json
import os
import re
import subprocess
import sys
import tempfile
from contextlib import nullcontext
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.backfill.build_image_jobs_from_gz import build_jobs  # noqa: E402
from scripts.image_quality_checker import _validate_image  # noqa: E402


DEFAULT_OUNASS_URL = (
    "https://saudi.ounass.com/"
    "shop-safiyaa-finley-peplum-dress-for-women-219174599_2709.html"
)
DEFAULT_LEVEL_URL = (
    "https://www.levelshoes.com/"
    "miu-miu-wander-matelass-satin-mini-bag-blue-satin-women-mini-bags-qmbhpt.html"
)
OUTPUT_NAMES = {"ounass": "ounass", "level": "level-shoes"}
EXPECTED_SITES = {"ounass": "ounass", "level": "level-shoes"}


class SmokeFailure(RuntimeError):
    """Raised when a smoke contract assertion fails."""


def _load_jsonl_gz(path: Path) -> list[dict]:
    rows = []
    with gzip.open(path, "rt", encoding="utf-8") as source:
        for line_number, raw_line in enumerate(source, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SmokeFailure(f"Invalid JSON at {path}:{line_number}: {exc}") from exc
            if not isinstance(row, dict):
                raise SmokeFailure(f"Expected object at {path}:{line_number}")
            rows.append(row)
    return rows


def _load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as source:
        for line_number, raw_line in enumerate(source, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SmokeFailure(f"Invalid JSON at {path}:{line_number}: {exc}") from exc
            if not isinstance(row, dict):
                raise SmokeFailure(f"Expected object at {path}:{line_number}")
            rows.append(row)
    return rows


def _is_expected_cdn_url(site: str, image_url: str) -> bool:
    parsed = urlsplit(image_url)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not hostname:
        return False
    if "/media/catalog/product/" not in parsed.path.lower():
        return False
    if site == "ounass":
        return hostname.endswith(".atgcdn.ae") or hostname == "atgcdn.ae"
    return hostname == "assets.levelshoes.com"


def _looks_like_source_hero(site: str, image_url: str) -> bool:
    filename = Path(urlsplit(image_url).path).name.lower()
    if site == "ounass":
        return re.search(r"_in\.(?:jpe?g|png|webp|avif)$", filename) is not None
    return re.search(r"_1\.(?:jpe?g|png|webp|avif)$", filename) is not None


def validate_crawl_artifact(path: Path, site: str) -> tuple[dict, list[str]]:
    rows = _load_jsonl_gz(path)
    if len(rows) != 1:
        raise SmokeFailure(f"{site}: expected one direct-PDP row, found {len(rows)}")

    row = rows[0]
    expected_site = EXPECTED_SITES[site]
    if row.get("site") != expected_site:
        raise SmokeFailure(
            f"{site}: expected row site={expected_site!r}, found {row.get('site')!r}"
        )

    gallery = row.get("image_urls")
    if not isinstance(gallery, list):
        raise SmokeFailure(f"{site}: image_urls is not a JSON array")
    if len(gallery) < 2:
        raise SmokeFailure(f"{site}: expected at least two gallery URLs, found {len(gallery)}")
    if any(not isinstance(url, str) or not url.strip() for url in gallery):
        raise SmokeFailure(f"{site}: gallery contains a blank or non-string URL")
    if len(gallery) != len(set(gallery)):
        raise SmokeFailure(f"{site}: gallery contains duplicate URLs")
    if any(not _is_expected_cdn_url(site, url) for url in gallery):
        raise SmokeFailure(f"{site}: gallery contains a non-product or unexpected CDN URL")
    if not _looks_like_source_hero(site, gallery[0]):
        raise SmokeFailure(f"{site}: first gallery member does not look like the source hero")

    return row, gallery


def _run_crawl(site: str, url: str, work_dir: Path) -> Path:
    crawl_dir = work_dir / f"crawl-{site}"
    crawl_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(
        {
            "APP_ENV": "dev",
            "QUALITY_GATE_ENABLED": "false",
            "S3_UPLOAD_ENABLED": "false",
            "SCRAPY_SETTINGS_MODULE": "ecommercecrawl.settings",
        }
    )
    command = [
        sys.executable,
        str(REPO_ROOT / "run_crawler.py"),
        site,
        "--env",
        "dev",
        "--urls",
        url,
    ]
    subprocess.run(command, cwd=crawl_dir, env=env, check=True)

    output_name = OUTPUT_NAMES[site]
    artifacts = sorted(
        (crawl_dir / "output").rglob(f"{output_name}.jsonl.gz"),
        key=lambda path: path.stat().st_mtime_ns,
    )
    if len(artifacts) != 1:
        raise SmokeFailure(
            f"{site}: expected one new crawler artifact, found {len(artifacts)}"
        )
    return artifacts[0]


def _build_and_validate_jobs(
    artifact: Path,
    gallery: list[str],
    site: str,
    work_dir: Path,
) -> Path:
    jobs_path = work_dir / f"{site}-image-jobs.jsonl"
    _, jobs_written = build_jobs(str(artifact), str(jobs_path))
    jobs = _load_jsonl(jobs_path)
    job_urls = [job.get("image_url") for job in jobs]
    if jobs_written != len(gallery) or job_urls != gallery:
        raise SmokeFailure(
            f"{site}: job fanout/order mismatch; gallery={len(gallery)} jobs={jobs_written}"
        )
    return jobs_path


def _download_and_validate_jobs(jobs_path: Path, site: str, work_dir: Path) -> int:
    image_dir = work_dir / f"{site}-images"
    results_path = work_dir / f"{site}-download-results.jsonl"
    command = [
        sys.executable,
        str(REPO_ROOT / "run_image_downloader.py"),
        "--input-jsonl",
        str(jobs_path),
        "--output-dir",
        str(image_dir),
        "--results-path",
        str(results_path),
        "--max-workers",
        "4",
    ]
    subprocess.run(command, cwd=REPO_ROOT, check=True)

    results = _load_jsonl(results_path)
    failures = [result for result in results if result.get("status") != "ok"]
    if failures:
        reasons = sorted({str(result.get("reason")) for result in failures})
        raise SmokeFailure(f"{site}: image downloads failed with reasons={reasons}")

    for result in results:
        storage = result.get("storage") or {}
        transfer = result.get("transfer") or {}
        output_path = storage.get("output_path")
        expected_sha256 = transfer.get("content_sha256")
        if not output_path or not expected_sha256:
            raise SmokeFailure(f"{site}: successful result omitted output path or SHA256")
        image_path = Path(output_path)
        if not image_path.is_file():
            raise SmokeFailure(f"{site}: downloaded file is missing: {image_path}")
        valid, reason, _, _, _ = _validate_image(
            image_path.read_bytes(),
            expected_sha256,
        )
        if not valid:
            raise SmokeFailure(f"{site}: downloaded file failed validation: {reason}")

    return len(results)


def _redact_url(image_url: str) -> str:
    parsed = urlsplit(image_url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def run_site_smoke(site: str, url: str, work_dir: Path) -> str:
    artifact = _run_crawl(site, url, work_dir)
    _, gallery = validate_crawl_artifact(artifact, site)
    jobs_path = _build_and_validate_jobs(artifact, gallery, site, work_dir)
    downloaded = _download_and_validate_jobs(jobs_path, site, work_dir)
    return (
        f"site={EXPECTED_SITES[site]} products=1 gallery_urls={len(gallery)} "
        f"jobs={len(gallery)} downloaded_ok={downloaded} "
        f"hero={_redact_url(gallery[0])}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Crawl and download ordered product galleries without S3 writes.",
    )
    parser.add_argument("--ounass-url", default=DEFAULT_OUNASS_URL)
    parser.add_argument("--level-url", default=DEFAULT_LEVEL_URL)
    parser.add_argument(
        "--work-dir",
        help="Optional directory to retain smoke artifacts; default uses temporary storage.",
    )
    args = parser.parse_args()

    if os.environ.get("S3_UPLOAD_ENABLED", "false").strip().lower() == "true":
        raise SmokeFailure("Refusing to run while S3_UPLOAD_ENABLED=true")
    if not os.environ.get("ZYTE_API_KEY"):
        raise SmokeFailure(
            "ZYTE_API_KEY is required for the Ounass PDP smoke; use the Make target"
        )

    if args.work_dir:
        work_path = Path(args.work_dir).resolve()
        work_path.mkdir(parents=True, exist_ok=True)
        work_context = nullcontext(str(work_path))
    else:
        work_context = tempfile.TemporaryDirectory(prefix="product-image-gallery-smoke-")

    try:
        with work_context as raw_work_dir:
            work_dir = Path(raw_work_dir)
            print(run_site_smoke("ounass", args.ounass_url, work_dir))
            print(run_site_smoke("level", args.level_url, work_dir))
    except (SmokeFailure, subprocess.CalledProcessError) as exc:
        print(f"SMOKE FAIL: {exc}", file=sys.stderr)
        return 1

    print("SMOKE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
