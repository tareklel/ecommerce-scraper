from ecommercecrawl.quality_gate import FAIL_QUALITY
from ecommercecrawl.quality_gate import PASS
from ecommercecrawl.quality_gate import QualityGateParams
from ecommercecrawl.quality_gate import evaluate_fail_quality


def _find_site_violation(report: dict, site: str, field: str) -> dict | None:
    for violation in report["sites"][site]["violations"]:
        if violation["field"] == field:
            return violation
    return None


def test_fail_quality_when_field_blank_ratio_is_80_percent_or_more():
    rows = []
    for idx in range(10):
        rows.append(
            {
                "site": "ounass",
                "primary_key": f"PK{idx}_ounass",
                "url": f"https://www.ounass.ae/pdp-{idx}",
                "primary_label": None if idx < 8 else "NEW SEASON",
            }
        )

    report = evaluate_fail_quality(
        rows,
        params=QualityGateParams(blank_threshold=0.8, min_rows_for_blank_check=5),
    )
    assert report["status"] == FAIL_QUALITY
    violation = _find_site_violation(report, "ounass", "primary_label")
    assert violation is not None
    assert violation["blank_ratio"] == 0.8


def test_site_exception_skips_blank_field_violation():
    rows = []
    for idx in range(10):
        rows.append(
            {
                "site": "ounass",
                "primary_key": f"PK{idx}_ounass",
                "url": f"https://www.ounass.ae/pdp-{idx}",
                "primary_label": None if idx < 9 else "NEW",
            }
        )

    report = evaluate_fail_quality(
        rows,
        params=QualityGateParams(blank_threshold=0.8, min_rows_for_blank_check=5),
        blank_field_exceptions={"ounass": ["primary_label"]},
    )
    assert report["status"] == PASS
    assert _find_site_violation(report, "ounass", "primary_label") is None


def test_blank_rule_is_skipped_when_site_rows_below_minimum():
    rows = [
        {"site": "level-shoes", "primary_key": "a", "url": "https://www.levelshoes.com/p/1", "color": None},
        {"site": "level-shoes", "primary_key": "b", "url": "https://www.levelshoes.com/p/2", "color": None},
        {"site": "level-shoes", "primary_key": "c", "url": "https://www.levelshoes.com/p/3", "color": None},
    ]

    report = evaluate_fail_quality(
        rows,
        params=QualityGateParams(blank_threshold=0.8, min_rows_for_blank_check=10),
    )

    assert report["status"] == PASS
    assert report["sites"]["level-shoes"]["blank_rule_checked"] is False
    assert report["sites"]["level-shoes"]["blank_rule_skipped_reason"] is not None


def test_missing_field_counts_as_blank():
    rows = []
    for idx in range(10):
        row = {
            "site": "level",
            "primary_key": f"PK{idx}_level-shoes",
            "url": f"https://www.levelshoes.com/p/{idx}",
        }
        if idx == 0:
            row["color"] = "black"
        rows.append(row)

    report = evaluate_fail_quality(
        rows,
        params=QualityGateParams(blank_threshold=0.8, min_rows_for_blank_check=5),
    )

    assert report["status"] == FAIL_QUALITY
    violation = _find_site_violation(report, "level-shoes", "color")
    assert violation is not None
    assert violation["blank_count"] == 9
