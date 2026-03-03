import argparse
import gzip
import json
import os
from collections import Counter
from datetime import datetime, timezone


def _default_output_path() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return os.path.join("output", "backfill", f"image_jobs_{timestamp}.jsonl")


def _extract_image_urls(payload: dict):
    value = payload.get("image_url")
    if value is None:
        value = payload.get("image_urls")

    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []

    # Unsupported type (example: dict)
    return []


def _derive_primary_key(payload: dict, site: str):
    primary_key = payload.get("primary_key") or payload.get("unique_id")
    if primary_key:
        return str(primary_key).strip()

    portal_itemid = payload.get("portal_itemid")
    if portal_itemid and site:
        return f"{portal_itemid}_{site}"
    return None


def build_jobs(input_gz: str, output_jsonl: str, site_override: str | None = None, dedupe: bool = True):
    counts = Counter()
    seen = set()
    jobs_written = 0

    output_parent = os.path.dirname(output_jsonl)
    if output_parent:
        os.makedirs(output_parent, exist_ok=True)
    with gzip.open(input_gz, "rt", encoding="utf-8") as source, open(
        output_jsonl, "w", encoding="utf-8"
    ) as target:
        for line_no, raw_line in enumerate(source, start=1):
            counts["rows_total"] += 1
            row = raw_line.strip()
            if not row:
                counts["skipped_empty_line"] += 1
                continue

            try:
                payload = json.loads(row)
            except json.JSONDecodeError:
                counts["skipped_invalid_json"] += 1
                continue

            if not isinstance(payload, dict):
                counts["skipped_invalid_shape"] += 1
                continue

            site = (site_override or payload.get("site") or "").strip()
            if not site:
                counts["skipped_missing_site"] += 1
                continue

            primary_key = _derive_primary_key(payload, site)
            if not primary_key:
                counts["skipped_missing_primary_key"] += 1
                continue

            image_urls = _extract_image_urls(payload)
            if not image_urls:
                counts["skipped_missing_image_url"] += 1
                continue

            source_run_id = payload.get("source_run_id") or payload.get("run_id")
            for image_url in image_urls:
                job_tuple = (site, primary_key, image_url)
                if dedupe and job_tuple in seen:
                    counts["skipped_duplicate_job"] += 1
                    continue
                seen.add(job_tuple)

                job = {
                    "site": site,
                    "primary_key": primary_key,
                    "image_url": image_url,
                    "source_run_id": source_run_id,
                    "_source": {
                        "input_file": input_gz,
                        "line_no": line_no,
                    },
                }
                target.write(json.dumps(job, ensure_ascii=False) + "\n")
                jobs_written += 1
                counts["jobs_written"] += 1

    return counts, jobs_written


def main():
    parser = argparse.ArgumentParser(
        description="Build image downloader jobs JSONL from crawler jsonl.gz output."
    )
    parser.add_argument("--input-gz", required=True, help="Path to input crawler jsonl.gz file.")
    parser.add_argument(
        "--output-jsonl",
        default=_default_output_path(),
        help="Output jobs JSONL path. Default is output/backfill/image_jobs_<timestamp>.jsonl",
    )
    parser.add_argument("--site-override", help="Optional site override for all rows.")
    parser.add_argument(
        "--no-dedupe",
        action="store_true",
        help="Disable in-file dedupe of (site, primary_key, image_url).",
    )
    args = parser.parse_args()

    counts, jobs_written = build_jobs(
        input_gz=args.input_gz,
        output_jsonl=args.output_jsonl,
        site_override=args.site_override,
        dedupe=not args.no_dedupe,
    )

    summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    print(f"Generated jobs: {jobs_written}, output={args.output_jsonl}")
    print(f"Stats: {summary}")


if __name__ == "__main__":
    main()
