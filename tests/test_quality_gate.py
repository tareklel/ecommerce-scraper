import pytest
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


# --- PLP-extract rows (plp_extract_flag = 1) -----------------------------------

def _plp_extract_row(idx, **overrides):
    row = {
        "site": "ounass", "country": "sa", "language": "AR", "portal_itemid": str(idx),
        "url": f"https://saudi.ounass.com/shop-x-{idx}.html", "price": 1800,
        "price_discount": None, "primary_label": None, "plp_extract_flag": 1,
        "plp_source_url": "https://saudi.ounass.com/api/women/bags/tote-bags",
        # Not observed on a listing: always blank on these rows.
        "product_name": None, "image_urls": None, "category": None,
    }
    row.update(overrides)
    return row


def _page_row(idx):
    return {"site": "ounass", "url": f"https://saudi.ounass.com/p-{idx}.html",
            "product_name": f"Bag {idx}", "plp_extract_flag": 0}


def test_plp_extract_rows_with_blank_page_fields_pass():
    rows = [_plp_extract_row(i) for i in range(30)]
    report = evaluate_fail_quality(rows, params=QualityGateParams(blank_threshold=0.2, min_rows_for_blank_check=5))
    assert report["status"] == PASS
    assert report["plp_extract_rows"]["row_count"] == 30
    assert report["plp_extract_rows"]["invalid_count"] == 0
    # The blank-ratio rule only sees product-page rows (none here).
    assert report["sites"] == {}


def test_blank_ratio_rule_only_counts_product_page_rows():
    rows = [_page_row(i) for i in range(10)] + [_plp_extract_row(i) for i in range(30)]
    report = evaluate_fail_quality(rows, params=QualityGateParams(blank_threshold=0.2, min_rows_for_blank_check=5))
    assert report["status"] == PASS
    assert report["sites"]["ounass"]["row_count"] == 10
    assert report["total_rows"] == 40


@pytest.mark.parametrize("overrides, error", [
    ({"price": None}, "price blank"),
    ({"price": 0}, "price <= 0"),
    ({"url": ""}, "url blank"),
    ({"url": "https://saudi.ounass.com/api/women/bags/tote-bags"}, "url is a listing URL"),
    ({"portal_itemid": None}, "portal_itemid blank"),
])
def test_one_invalid_plp_extract_row_fails_the_run(overrides, error):
    rows = [_plp_extract_row(i) for i in range(5)] + [_plp_extract_row(99, **overrides)]
    report = evaluate_fail_quality(rows)
    assert report["status"] == FAIL_QUALITY
    assert report["reason"] == "invalid_plp_extract_rows"
    [bad] = report["plp_extract_rows"]["invalid_examples"]
    assert error in bad["errors"]


def test_normal_runs_have_no_plp_extract_section():
    report = evaluate_fail_quality([_page_row(i) for i in range(3)])
    assert "plp_extract_rows" not in report
