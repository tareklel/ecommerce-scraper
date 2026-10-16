import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set


# Gate outcomes used by the CLI exit code contract.
FAIL_QUALITY = "fail_quality"
PASS = "pass"

# Stable identifiers for report metadata.
RULE_SET_ID = "default"


# PLP-extract rows (Ounass PLP-efficient crawl, docs/ounass_plp_efficient_crawl.md)
# leave name, images, category etc. blank on purpose: "not observed", kept from
# the previous crawl downstream. They're checked with their own rule instead of
# the blank-ratio rule, which would otherwise fail every such run.
PLP_EXTRACT_FLAG_FIELD = "plp_extract_flag"
PLP_EXTRACT_REQUIRED_FIELDS = ("portal_itemid", "url", "price", "site", "country", "language")
PLP_EXTRACT_MAX_EXAMPLES = 20

# Normalize known site aliases so checks are consistent per site.
SITE_ALIASES = {
    "level": "level-shoes",
    "level_shoes": "level-shoes",
}


def _utc_now_iso() -> str:
    """Return the current UTC timestamp for report metadata."""
    return datetime.now(timezone.utc).isoformat()


def normalize_site_name(site: Any) -> str:
    # Keep missing site explicit so it can be reported as its own bucket.
    if site is None:
        return "__missing_site__"
    key = str(site).strip().lower()
    if not key:
        return "__missing_site__"
    return SITE_ALIASES.get(key, key)


def is_blank(value: Any) -> bool:
    """Project-level blank semantics for quality checks."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) == 0
    return False


def load_jsonl_rows(path: str) -> List[dict]:
    """Load a JSONL file and fail fast on malformed lines."""
    rows: List[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line_no, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at line {line_no} in {path}: {exc}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"Expected JSON object at line {line_no} in {path}.")
            rows.append(payload)
    return rows


def _normalize_exception_map(blank_field_exceptions: Optional[Dict[str, List[str]]]) -> Dict[str, Set[str]]:
    # Input shape: {site_or_star: [field_a, field_b]}.
    # Output shape: normalized site key -> set(fields) for fast membership checks.
    if not blank_field_exceptions:
        return {}
    if not isinstance(blank_field_exceptions, dict):
        raise ValueError("blank_field_exceptions must be a dict in the shape {site: [fields]}.")

    normalized: Dict[str, Set[str]] = {}
    for raw_site, raw_fields in blank_field_exceptions.items():
        site_key = "*" if str(raw_site).strip() == "*" else normalize_site_name(raw_site)
        if not isinstance(raw_fields, list):
            raise ValueError(f"Exception fields for site '{raw_site}' must be a list.")

        fields = {str(field).strip() for field in raw_fields if str(field).strip()}
        normalized[site_key] = fields
    return normalized


def load_blank_field_exceptions(
    *,
    exceptions_json: Optional[str] = None,
    exceptions_file: Optional[str] = None,
) -> Dict[str, Set[str]]:
    """Load exception config from either inline JSON or a JSON file."""
    if exceptions_json and exceptions_file:
        raise ValueError("Use only one of exceptions_json or exceptions_file.")

    if exceptions_json:
        try:
            payload = json.loads(exceptions_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid exceptions_json payload: {exc}") from exc
        return _normalize_exception_map(payload)

    if exceptions_file:
        with open(exceptions_file, "r", encoding="utf-8") as f:
            payload = json.load(f)
        return _normalize_exception_map(payload)

    return {}


def is_plp_extract_row(row: dict) -> bool:
    return str(row.get(PLP_EXTRACT_FLAG_FIELD)).strip() == "1"


def _plp_extract_row_errors(row: dict) -> List[str]:
    """Why a PLP-extract row is unusable; empty when it's fine."""
    errors = [f"{field} blank" for field in PLP_EXTRACT_REQUIRED_FIELDS if is_blank(row.get(field))]
    price = row.get("price")
    if not is_blank(price):
        try:
            if float(price) <= 0:
                errors.append("price <= 0")
        except (TypeError, ValueError):
            errors.append("price not a number")
    url = row.get("url")
    if not is_blank(url):
        # URL rule (G6): the row must carry the product's own page URL. A
        # listing URL would overwrite the product's link downstream.
        if "/api/" in str(url) or url == row.get("plp_source_url"):
            errors.append("url is a listing URL")
    return errors


def evaluate_plp_extract_rows(rows: List[dict]) -> dict:
    """
    Rule for PLP-extract rows: every row must be usable on its own. The
    crawler only writes rows that pass these checks, so any violation means a
    bug, and the run fails rather than letting bad rows reach raw.
    """
    invalid = []
    for idx, row in enumerate(rows):
        errors = _plp_extract_row_errors(row)
        if errors:
            invalid.append({"row_index": idx, "portal_itemid": row.get("portal_itemid"), "errors": errors})
    return {
        "row_count": len(rows),
        "required_fields": list(PLP_EXTRACT_REQUIRED_FIELDS),
        "invalid_count": len(invalid),
        "invalid_examples": invalid[:PLP_EXTRACT_MAX_EXAMPLES],
    }


@dataclass(frozen=True)
class QualityGateParams:
    # Fail when blank ratio for a field is >= this value.
    blank_threshold: float = 0.8
    # Avoid noisy failures on very small site samples.
    min_rows_for_blank_check: int = 20


def evaluate_fail_quality(
    rows: List[dict],
    *,
    params: Optional[QualityGateParams] = None,
    blank_field_exceptions: Optional[Dict[str, List[str]]] = None,
) -> dict:
    """
    Evaluate stateless FAIL_QUALITY checks for one run.

    Current rule set:
    - field_blankness_threshold per site, on product-page rows only;
    - plp_extract_required_fields on PLP-extract rows (plp_extract_flag = 1).
    """
    params = params or QualityGateParams()
    if not (0 <= params.blank_threshold <= 1):
        raise ValueError("blank_threshold must be in [0, 1].")
    if params.min_rows_for_blank_check < 1:
        raise ValueError("min_rows_for_blank_check must be >= 1.")

    normalized_exceptions = _normalize_exception_map(blank_field_exceptions)
    plp_extract_rows = [row for row in rows if is_plp_extract_row(row)]
    page_rows = [row for row in rows if not is_plp_extract_row(row)]
    grouped_by_site: Dict[str, List[dict]] = defaultdict(list)
    for row in page_rows:
        # Rule evaluation is per normalized site.
        grouped_by_site[normalize_site_name(row.get("site"))].append(row)

    report_sites = {}
    violation_count = 0

    if not rows:
        # Empty input is considered a hard quality failure.
        return {
            "status": FAIL_QUALITY,
            "event_time_utc": _utc_now_iso(),
            "rule_set": RULE_SET_ID,
            "reason": "empty_input",
            "total_rows": 0,
            "blank_threshold": params.blank_threshold,
            "min_rows_for_blank_check": params.min_rows_for_blank_check,
            "sites": {},
            "violations_count": 1,
        }

    for site, site_rows in sorted(grouped_by_site.items()):
        # Merge global ('*') and site-specific field exemptions.
        site_exceptions = set(normalized_exceptions.get("*", set()))
        site_exceptions.update(normalized_exceptions.get(site, set()))

        # Build field universe from the site's rows. Missing fields still count as blank.
        fields = set()
        for row in site_rows:
            fields.update(row.keys())

        site_report = {
            "row_count": len(site_rows),
            "blank_rule_checked": len(site_rows) >= params.min_rows_for_blank_check,
            "blank_rule_skipped_reason": None,
            "exceptions": sorted(site_exceptions),
            "checked_fields": 0,
            "violations": [],
        }

        if len(site_rows) < params.min_rows_for_blank_check:
            # Skip threshold check when sample size is below minimum.
            site_report["blank_rule_skipped_reason"] = (
                f"row_count_below_min_rows_for_blank_check ({len(site_rows)} < {params.min_rows_for_blank_check})"
            )
            report_sites[site] = site_report
            continue

        checked_fields = 0
        for field in sorted(fields):
            if field in site_exceptions:
                continue

            checked_fields += 1
            blank_count = 0
            for row in site_rows:
                # Missing key and blank value both contribute to blank ratio.
                if field not in row or is_blank(row.get(field)):
                    blank_count += 1

            blank_ratio = blank_count / len(site_rows)
            if blank_ratio >= params.blank_threshold:
                violation_count += 1
                site_report["violations"].append(
                    {
                        "rule": "field_blankness_threshold",
                        "field": field,
                        "blank_count": blank_count,
                        "row_count": len(site_rows),
                        "blank_ratio": round(blank_ratio, 4),
                        "threshold": params.blank_threshold,
                    }
                )

        site_report["checked_fields"] = checked_fields
        report_sites[site] = site_report

    blank_violations = violation_count
    plp_extract_report = None
    if plp_extract_rows:
        plp_extract_report = evaluate_plp_extract_rows(plp_extract_rows)
        if plp_extract_report["invalid_count"]:
            violation_count += 1

    if blank_violations and violation_count > blank_violations:
        reason = "blank_field_threshold_breach_and_invalid_plp_extract_rows"
    elif blank_violations:
        reason = "blank_field_threshold_breach"
    elif violation_count:
        reason = "invalid_plp_extract_rows"
    else:
        reason = "all_rules_passed"

    report = {
        "status": FAIL_QUALITY if violation_count > 0 else PASS,
        "event_time_utc": _utc_now_iso(),
        "rule_set": RULE_SET_ID,
        "reason": reason,
        "total_rows": len(rows),
        "blank_threshold": params.blank_threshold,
        "min_rows_for_blank_check": params.min_rows_for_blank_check,
        # Product-page rows only; PLP-extract rows are reported separately.
        "sites": report_sites,
        "violations_count": violation_count,
    }
    if plp_extract_report is not None:
        report["plp_extract_rows"] = plp_extract_report
    return report
