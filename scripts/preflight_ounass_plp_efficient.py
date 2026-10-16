"""
Preflight for the Ounass PLP-efficient crawl: a dry run of the crawler's
startup (docs/ounass_plp_efficient_crawl.md, section 8 "Preflight").

It gets the inputs exactly as a crawl would (invokes scraper-pipeline's
export Lambda), runs every startup check with the same code the crawler uses
(ecommercecrawl/plp_efficient.py), prints all problems plus a summary, and
exits 0 if the crawl would start, 1 if it would stop.

No Zyte requests and no writes, except --probe-one-page (1 Zyte request).

Usage:
    poetry run python3 scripts/preflight_ounass_plp_efficient.py --env dev
    # local files instead of invoking the export (e.g. hand-made CSVs):
    poetry run python3 scripts/preflight_ounass_plp_efficient.py \
        --plp-list plp.csv --pdp-list pdp.csv --vocabulary vocabulary.json [--manifest manifest.json]
"""

import argparse
import base64
import json
import os
import sys
from pathlib import Path

# Allow running as `python scripts/...` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ZYTE_API_URL = "https://api.zyte.com/v1/extract"


def _settings_for(env):
    # Same settings a crawl gets (run_crawler.py sets APP_ENV the same way).
    os.environ["APP_ENV"] = env
    from scrapy.utils.project import get_project_settings

    return get_project_settings()


def _probe_one_page(url):
    """Fetch page 0 of one listing through Zyte (1 request) to check Ounass isn't blocking us."""
    import requests

    api_key = os.environ.get("ZYTE_API_KEY", "").strip()
    if not api_key:
        return "probe skipped: ZYTE_API_KEY is not set"
    try:
        resp = requests.post(ZYTE_API_URL, auth=(api_key, ""), timeout=90,
                             json={"url": url, "httpResponseBody": True})
    except requests.RequestException as exc:
        return f"probe failed: {exc}"
    if not resp.ok:
        try:
            detail = resp.json().get("title")
        except ValueError:
            detail = resp.text[:100]
        return f"probe failed: Zyte {resp.status_code} {detail} for {url}"
    try:
        page = json.loads(base64.b64decode(resp.json()["httpResponseBody"]))
    except (KeyError, ValueError) as exc:
        return f"probe failed: response is not listing JSON ({exc})"
    return (f"probe OK: {url} -> routeType={page.get('routeType')}, "
            f"{len(page.get('hits') or [])} products on page 0, "
            f"{(page.get('pagination') or {}).get('totalPages')} pages")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--env", choices=["dev", "prod"], default="dev")
    parser.add_argument("--site", default="ounass")
    parser.add_argument("--lambda-name", help="override OUNASS_PLP_EFFICIENT_EXPORT_LAMBDA")
    parser.add_argument("--plp-list", help="local/s3 PLP list instead of invoking the export")
    parser.add_argument("--pdp-list", help="local/s3 PDP list instead of invoking the export")
    parser.add_argument("--vocabulary", help="local/s3 vocabulary instead of invoking the export")
    parser.add_argument("--manifest", help="optional local manifest.json to go with local files (for G8)")
    parser.add_argument("--probe-one-page", action="store_true",
                        help="also fetch page 0 of the first valid listing via Zyte (1 request)")
    args = parser.parse_args(argv)

    from ecommercecrawl import plp_efficient as pe

    settings = _settings_for(args.env)
    config = pe.Config.from_settings(settings)

    local = [args.plp_list, args.pdp_list, args.vocabulary]
    if any(local):
        if not all(local):
            parser.error("--plp-list, --pdp-list and --vocabulary must be given together")
        manifest = json.loads(Path(args.manifest).read_text()) if args.manifest else None
        inputs = pe.load_inputs(*local, manifest=manifest)
    else:
        lambda_name = args.lambda_name or settings.get("OUNASS_PLP_EFFICIENT_EXPORT_LAMBDA")
        print(f"Invoking export {lambda_name} ...", flush=True)
        try:
            manifest = pe.invoke_export(lambda_name, site=args.site)
        except pe.ExportError as exc:
            print(f"PLP-efficient startup checks: WOULD STOP\n\n[STOP] EXPORT: {exc}")
            return 1
        inputs = pe.load_inputs_from_manifest(manifest)

    result = pe.validate(inputs, config)
    print(pe.format_report(inputs, result))

    if args.probe_one_page:
        print()
        if result.valid_plp_rows:
            print(_probe_one_page(result.valid_plp_rows[0]["url"]))
        else:
            print("probe skipped: no valid listing rows")

    return 1 if result.stop else 0


if __name__ == "__main__":
    sys.exit(main())
