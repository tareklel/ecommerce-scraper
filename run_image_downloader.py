import argparse
import json
import logging
import os
from collections import Counter
from datetime import datetime, timezone

from ecommercecrawl.image_downloader import download_jobs
from ecommercecrawl.image_downloader import extract_jobs_and_skips_from_jsonl
from ecommercecrawl.image_downloader import generate_run_id


def _default_results_path(output_dir: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return os.path.join(output_dir, f"download_results_{timestamp}.jsonl")


def main():
    parser = argparse.ArgumentParser(description="Image downloader for crawler outputs.")
    parser.add_argument("--input-jsonl", help="Path to JSONL records with site/primary_key/image_urls.")
    parser.add_argument("--site", help="Site name (e.g. ounass, level_shoes, farfetch).")
    parser.add_argument("--primary-key", help="Canonical primary key (e.g. 218511926_ounass).")
    parser.add_argument("--image-url", help="Image URL for single-job download.")
    parser.add_argument("--source-run-id", help="Optional source run id for output partitioning.")
    parser.add_argument("--output-dir", default="output/images", help="Local output directory root.")
    parser.add_argument("--max-workers", type=int, default=10, help="Max parallel download workers.")
    parser.add_argument("--timeout-seconds", type=int, default=20, help="HTTP timeout per request.")
    parser.add_argument("--results-path", help="Optional path to write JSONL download results.")
    parser.add_argument("--log-level", default="INFO", help="Logging level (DEBUG, INFO, WARNING, ERROR).")

    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    using_jsonl = bool(args.input_jsonl)
    using_inline = any([args.site, args.primary_key, args.image_url, args.source_run_id])
    download_run_id = generate_run_id()

    if using_jsonl and using_inline:
        parser.error(
            "Use either --input-jsonl OR inline --site --primary-key --image-url, not both."
        )
    if not using_jsonl and not using_inline:
        parser.error(
            "No input mode selected. Provide --input-jsonl OR inline --site --primary-key --image-url."
        )

    jobs = []
    pre_results = []
    if using_jsonl:
        try:
            jobs, pre_results = extract_jobs_and_skips_from_jsonl(
                args.input_jsonl,
                download_run_id=download_run_id,
            )
        except OSError as e:
            parser.error(f"Failed to read --input-jsonl file: {e}")

        if not jobs and not pre_results:
            parser.error(f"No valid jobs found in {args.input_jsonl}")

    if using_inline:
        if not (args.site and args.primary_key and args.image_url):
            parser.error(
                "Inline mode requires all of --site, --primary-key, and --image-url."
            )
        jobs.append(
            {
                "site": args.site,
                "primary_key": args.primary_key,
                "image_url": args.image_url,
                "source_run_id": args.source_run_id,
            }
        )

    results = list(pre_results)
    if jobs:
        results.extend(
            download_jobs(
                jobs=jobs,
                output_dir=args.output_dir,
                max_workers=max(1, args.max_workers),
                timeout_seconds=max(1, args.timeout_seconds),
                download_run_id=download_run_id,
            )
        )

    result_path = args.results_path or _default_results_path(args.output_dir)
    os.makedirs(os.path.dirname(result_path), exist_ok=True)
    with open(result_path, "w", encoding="utf-8") as f:
        for result in results:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")

    counts = Counter((r.get("status") or "unknown") for r in results)
    summary = ", ".join(f"{status}={count}" for status, count in sorted(counts.items()))
    print(f"Results: {summary}, output={result_path}")


if __name__ == "__main__":
    main()
