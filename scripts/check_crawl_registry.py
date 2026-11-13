"""
Pre-flight for `make crawl-flow`: refuse to start when the dbt image is older
than the latest pushed crawl registry, and print what the run will crawl.

The flow seeds `crawl_plp_registry` from the seeds baked into the dbt image
(`latest` in ECR), so a registry commit the image doesn't contain would be
silently ignored. What's pushed to scraper-pipeline `main` is the source of
truth; local edits are never read.

Needs `gh` (logged in) and AWS credentials that can read the dbt image's tags.
Exit 0 = OK to start, 1 = stale image or lookup failed.
"""
import csv
import io
import json
import os
import subprocess
import sys
from collections import Counter

REPO = os.environ.get("REGISTRY_REPO", "tareklel/scraper-pipeline-pc")
REGISTRY_PATH = "canonical_seeds/crawl_plp_registry.csv"
DBT_ECR_REPOSITORY = os.environ.get("DBT_ECR_REPOSITORY", "price-comparison-dbt")
AWS_REGION = os.environ.get("AWS_REGION", "eu-central-1")


class CheckFailed(Exception):
    pass


def _run(args):
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise CheckFailed(f"{' '.join(args[:3])} failed: {result.stderr.strip()}")
    return result.stdout


def latest_registry_commit(run):
    out = run(["gh", "api", f"repos/{REPO}/commits?sha=main&path={REGISTRY_PATH}&per_page=1"])
    commits = json.loads(out)
    if not commits:
        raise CheckFailed(f"no commit on {REPO} main touches {REGISTRY_PATH}")
    return commits[0]["sha"]


def image_commit(run):
    out = run([
        "aws", "ecr", "describe-images", "--region", AWS_REGION,
        "--repository-name", DBT_ECR_REPOSITORY, "--image-ids", "imageTag=latest",
        "--query", "imageDetails[0].imageTags", "--output", "json",
    ])
    tags = [t for t in json.loads(out) or [] if t.startswith("sha-")]
    if not tags:
        raise CheckFailed(f"{DBT_ECR_REPOSITORY}:latest has no sha- tag")
    return tags[0][len("sha-"):]


def image_contains(run, registry_sha, image_sha):
    # "ahead" or "identical": the image's commit includes the registry commit.
    out = run(["gh", "api", f"repos/{REPO}/compare/{registry_sha}...{image_sha}", "--jq", ".status"])
    return out.strip() in ("ahead", "identical")


def active_sites(run, image_sha):
    out = run([
        "gh", "api", f"repos/{REPO}/contents/{REGISTRY_PATH}?ref={image_sha}",
        "-H", "Accept: application/vnd.github.raw",
    ])
    rows = csv.DictReader(io.StringIO(out))
    return Counter(r["site"] for r in rows if (r.get("is_active") or "").strip().lower() == "true")


def check(run=_run, out=print):
    registry_sha = latest_registry_commit(run)
    image_sha = image_commit(run)
    if not image_contains(run, registry_sha, image_sha):
        raise CheckFailed(
            f"dbt image is sha-{image_sha}, but the registry last changed in {registry_sha[:7]}: "
            f"wait for the dbt image build (scraper-pipeline Actions; if it failed, fix it first), "
            f"then start again"
        )
    sites = active_sites(run, image_sha)
    if not sites:
        raise CheckFailed(f"no active rows in {REGISTRY_PATH} at {image_sha}")
    out(f"dbt image sha-{image_sha} has the latest registry ({registry_sha[:7]}). Active sites:")
    for site, count in sorted(sites.items()):
        out(f"  {site}: {count} URL(s)")
    return sites


def main():
    try:
        check()
    except CheckFailed as e:
        print(f"Registry check failed: {e}", file=sys.stderr)
        print("Set SKIP_REGISTRY_CHECK=1 to start anyway.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
