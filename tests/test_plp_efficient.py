"""
Startup checks for the Ounass PLP-efficient crawl (ecommercecrawl/plp_efficient.py).

All data here is synthetic (made-up products/listings): real downloaded
product data must not be committed (context/AGENTS.md). Each check and each
threshold boundary from docs/ounass_plp_efficient_crawl.md section 5 is covered.
"""

import io
import json
from datetime import datetime, timedelta, timezone

import pytest

from ecommercecrawl import plp_efficient as pe

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)

VOCAB = {
    "country": ["ae", "sa"],
    "language": ["ar", "en"],
    "gender": ["men", "women"],
    "category_subcategory": [["bags", "tote_bags"], ["bags", "shoulder_bags"]],
    "brand": ["brand_a", "brand_b"],
}


def plp(**overrides):
    row = {
        "url": "https://saudi.ounass.com/api/women/bags/tote-bags",
        "site": "ounass", "country": "sa", "language": "ar", "gender": "women",
        "category": "bags", "subcategory": "tote_bags", "brand": "",
    }
    row.update(overrides)
    return row


def pdp(item_id="1001", **overrides):
    row = {
        "portal_itemid": item_id, "primary_key": f"{item_id}_ounass", "site": "ounass",
        "country": "sa", "language": "ar",
        "url": f"https://saudi.ounass.com/shop-made-up-bag-{item_id}_19.html",
        "gender": "women", "category": "bags", "subcategory": "tote_bags",
        "brand": "brand_a", "out_of_stock": "false",
        "last_available_date": "2026-10-15", "last_crawl_date": "2026-10-15",
    }
    row.update(overrides)
    return row


def manifest(gold_built_at=NOW - timedelta(hours=4)):
    return {
        "export_id": "test-export", "app_env": "dev",
        "gold_built_at": gold_built_at.isoformat() if isinstance(gold_built_at, datetime) else gold_built_at,
        "files": {
            "plp_list": {"uri": "s3://bucket/x/plp_list.csv"},
            "pdp_list": {"uri": "s3://bucket/x/pdp_list.csv"},
            "vocabulary": {"uri": "s3://bucket/x/vocabulary.json"},
        },
    }


def make_inputs(plp_rows=None, pdp_rows=None, vocabulary=None, man="default"):
    return pe.Inputs(
        plp_rows=[plp()] if plp_rows is None else plp_rows,
        pdp_rows=[pdp()] if pdp_rows is None else pdp_rows,
        vocabulary=VOCAB if vocabulary is None else vocabulary,
        manifest=manifest() if man == "default" else man,
        plp_columns=list(pe.PLP_COLUMNS),
        pdp_columns=list(pe.PDP_COLUMNS),
    )


def run(inputs, **config):
    return pe.validate(inputs, pe.Config(**config), now=NOW)


def checks(result, severity=None):
    return {(p.check, p.severity) for p in result.problems
            if severity is None or p.severity == severity}


# --- clean inputs -------------------------------------------------------------

def test_clean_inputs_have_no_problems():
    result = run(make_inputs())
    assert result.problems == []
    assert not result.stop
    assert len(result.valid_plp_rows) == 1 and len(result.valid_pdp_rows) == 1
    assert result.gold_age_days == pytest.approx(4 / 24)


def test_language_is_case_insensitive():
    result = run(make_inputs(plp_rows=[plp(language="AR")], pdp_rows=[pdp(language="AR")]))
    assert result.problems == []


# --- G2: files and columns ----------------------------------------------------

def test_g2_missing_input_stops_and_skips_other_checks():
    inputs = make_inputs()
    inputs.pdp_rows = None
    inputs.load_errors["pdp_list"] = "NoSuchKey"
    result = run(inputs)
    assert result.stop
    assert checks(result) == {("G2", pe.STOP)}


def test_g2_missing_column_stops():
    inputs = make_inputs()
    inputs.pdp_columns = [c for c in pe.PDP_COLUMNS if c != "subcategory"]
    assert ("G2", pe.STOP) in checks(run(inputs))


def test_g2_vocabulary_missing_key_stops():
    vocab = {k: v for k, v in VOCAB.items() if k != "brand"}
    assert ("G2", pe.STOP) in checks(run(make_inputs(vocabulary=vocab)))


# --- G1: listing rows ---------------------------------------------------------

@pytest.mark.parametrize("override", [
    {"subcategory": "tote-bags"},     # not canonical
    {"subcategory": ""},              # required
    {"gender": ""},                   # required
    {"brand": "unknown_brand"},       # brand not allowed (and not canonical)
    {"site": "level-shoes"},          # wrong site
])
def test_g1_invalid_listing_row_is_skipped(override):
    rows = [plp(), plp(url="https://saudi.ounass.com/api/women/bags/shoulder-bags",
                       subcategory="shoulder_bags"),
            plp(url="https://saudi.ounass.com/api/x", **override),
            plp(url="https://saudi.ounass.com/api/y", subcategory="shoulder_bags")]
    result = run(make_inputs(plp_rows=rows))
    assert ("G1", pe.SKIP) in checks(result)
    assert len(result.skipped_plp_rows) == 1
    assert not result.stop  # 1 of 4 = 25%, not above the limit


def test_g1_too_many_bad_rows_stops():
    rows = [plp(), plp(url="https://saudi.ounass.com/api/a", subcategory="shoulder_bags"),
            plp(url="https://saudi.ounass.com/api/b", subcategory="nope")]
    result = run(make_inputs(plp_rows=rows))  # 1 of 3 = 33% > 25%
    assert ("G1", pe.STOP) in checks(result)


def test_g1_duplicate_url_is_skipped():
    result = run(make_inputs(plp_rows=[plp(), plp(), plp(url="https://saudi.ounass.com/api/c"),
                                       plp(url="https://saudi.ounass.com/api/d")]))
    assert any("duplicate url" in p.message for p in result.problems)
    assert len(result.skipped_plp_rows) == 1


def test_g1_no_valid_listing_rows_stops():
    result = run(make_inputs(plp_rows=[]))
    assert ("G1", pe.STOP) in checks(result)


# --- G7: listing URL vs country/language --------------------------------------

@pytest.mark.parametrize("override", [
    {"url": "https://www.ounass.ae/api/women/bags/tote-bags"},     # UAE host tagged sa
    {"url": "https://en-saudi.ounass.com/api/women/bags/tote-bags"},  # English host tagged ar
    {"url": "https://saudi.ounass.com/women/bags/tote-bags"},     # not the /api/ endpoint
    {"url": "https://example.com/api/women/bags"},                # unknown host
    {"url": "http://saudi.ounass.com/api/women/bags/tote-bags"},  # not https
])
def test_g7_host_mismatch_is_skipped(override):
    rows = [plp(**override)] + [plp(url=f"https://saudi.ounass.com/api/ok{i}") for i in range(4)]
    result = run(make_inputs(plp_rows=rows))
    assert ("G7", pe.SKIP) in checks(result)
    assert len(result.skipped_plp_rows) == 1


# --- G10: product rows --------------------------------------------------------

def test_g10_invalid_product_is_quarantined():
    rows = [pdp(str(1000 + i)) for i in range(19)] + [pdp("2000", brand="unknown_brand")]
    result = run(make_inputs(pdp_rows=rows))  # 1 of 20 = 5%, not above
    assert ("G10", pe.QUARANTINE) in checks(result)
    assert len(result.quarantined_pdp_rows) == 1
    assert not result.stop


def test_g10_too_many_bad_products_stops():
    rows = [pdp(str(1000 + i)) for i in range(18)] + \
           [pdp("2000", brand="x"), pdp("2001", subcategory="totes")]
    result = run(make_inputs(pdp_rows=rows))  # 2 of 20 = 10% > 5%
    assert ("G10", pe.STOP) in checks(result)


def test_g10_duplicate_product_is_quarantined():
    result = run(make_inputs(pdp_rows=[pdp("1001")] * 2 + [pdp(str(i)) for i in range(2, 40)]))
    assert any("duplicate product" in p.message for p in result.problems)


def test_g10_empty_product_list_only_warns():
    result = run(make_inputs(pdp_rows=[]))
    assert ("G10", pe.WARN) in checks(result)
    assert not result.stop


# --- G8: gold age -------------------------------------------------------------

@pytest.mark.parametrize("age_days, expected", [
    (1.0, None),
    (2.5, pe.WARN),
    (30.0, pe.WARN),     # warn only, however old: stale gold costs money, not correctness
])
def test_g8_gold_age(age_days, expected):
    result = run(make_inputs(man=manifest(NOW - timedelta(days=age_days))))
    g8 = {p.severity for p in result.problems if p.check == "G8"}
    assert g8 == ({expected} if expected else set())
    assert not result.stop


def test_g8_missing_gold_built_at_warns():
    result = run(make_inputs(man=manifest(gold_built_at=None)))
    assert ("G8", pe.WARN) in checks(result) and not result.stop


def test_g8_no_manifest_warns():
    result = run(make_inputs(man=None))
    assert checks(result) == {("G8", pe.WARN)}


# --- Stale crawls (warn only) -------------------------------------------------

def test_stale_crawl_warns_with_oldest_date_and_never_stops():
    rows = [pdp("1", last_crawl_date="2026-08-08"), pdp("2", last_crawl_date="2026-10-01"),
            pdp("3", last_crawl_date="2026-10-15")]
    result = run(make_inputs(pdp_rows=rows))
    stale = [p for p in result.problems if p.check == "STALE"]
    assert len(stale) == 1 and stale[0].severity == pe.WARN
    assert "2 products" in stale[0].message and "2026-08-08" in stale[0].message
    assert not result.stop


def test_stale_crawl_threshold_is_exclusive():
    result = run(make_inputs(pdp_rows=[pdp(last_crawl_date="2026-10-09")]))  # exactly 7 days
    assert not any(p.check == "STALE" for p in result.problems)


def test_stale_crawl_missing_date_warns():
    result = run(make_inputs(pdp_rows=[pdp(last_crawl_date="")]))
    assert any("no last_crawl_date" in p.message for p in result.problems)


# --- Coverage: held back / uncovered ------------------------------------------

def test_product_only_covered_by_skipped_listing_is_held_back():
    rows = [plp(), plp(url="https://saudi.ounass.com/api/a"), plp(url="https://saudi.ounass.com/api/b"),
            plp(url="https://www.ounass.ae/api/women/bags/shoulder-bags", subcategory="shoulder_bags")]
    result = run(make_inputs(plp_rows=rows, pdp_rows=[pdp("9", subcategory="shoulder_bags")]))
    assert len(result.held_back_pdp_rows) == 1
    assert result.uncovered_pdp_rows == []


def test_product_covered_by_no_listing_goes_to_phase2():
    result = run(make_inputs(pdp_rows=[pdp(), pdp("9", country="ae")]))
    assert [p["portal_itemid"] for p in result.uncovered_pdp_rows] == ["9"]


@pytest.mark.parametrize("override, message", [
    ({"brand": "brand_a"}, "brand must be blank"),
    ({"url": "https://saudi.ounass.com/api/women/designers/acler"}, "/designers/"),
])
def test_g1_rejects_brand_rows_and_brand_pages(override, message):
    # A listing returns what its URL contains; only category pages with no
    # brand match what a row claims (otherwise: Phase 2 flood or G11).
    rows = [plp(), plp(url="https://saudi.ounass.com/api/women/bags/shoulder-bags",
                       subcategory="shoulder_bags"),
            plp(**{"url": "https://saudi.ounass.com/api/z", **override}),
            plp(url="https://saudi.ounass.com/api/y", subcategory="shoulder_bags")]
    result = run(make_inputs(plp_rows=rows))
    g1 = [p for p in result.problems if p.check == "G1" and p.severity == pe.SKIP]
    assert any(message in p.message for p in g1)
    assert len(result.skipped_plp_rows) == 1


def test_brand_matching_rule_kept_for_future_brand_pages():
    # Dormant while the guard rejects brand rows; kept for brand-page support.
    listing = pe.normalize_row(plp(brand="brand_a"))
    assert pe.plp_covers_pdp(listing, pe.normalize_row(pdp("1")))
    assert not pe.plp_covers_pdp(listing, pe.normalize_row(pdp("2", brand="brand_b")))


def test_too_many_uncovered_products_warns_about_phase2_ceiling():
    result = run(make_inputs(pdp_rows=[pdp(str(i), country="ae") for i in range(3)]),
                 max_phase2_pdps=2)
    assert ("COVERAGE", pe.WARN) in checks(result)


# --- Loading ------------------------------------------------------------------

class FakeS3:
    def __init__(self, objects):
        self.objects = objects

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[f"{Bucket}/{Key}"].encode("utf-8"))}


def _csv(columns, rows):
    lines = [",".join(columns)] + [",".join(str(r.get(c, "")) for c in columns) for r in rows]
    return "\n".join(lines) + "\n"


def test_load_inputs_from_manifest_reads_all_three_files():
    s3 = FakeS3({
        "bucket/x/plp_list.csv": _csv(pe.PLP_COLUMNS, [plp()]),
        "bucket/x/pdp_list.csv": _csv(pe.PDP_COLUMNS, [pdp()]),
        "bucket/x/vocabulary.json": json.dumps(VOCAB),
    })
    inputs = pe.load_inputs_from_manifest(manifest(), s3_client=s3)
    assert inputs.load_errors == {}
    result = pe.validate(inputs, now=NOW)
    assert result.problems == [] and len(result.valid_pdp_rows) == 1


def test_load_inputs_records_unreadable_file_for_g2(tmp_path):
    plp_path = tmp_path / "plp.csv"
    plp_path.write_text(_csv(pe.PLP_COLUMNS, [plp()]))
    inputs = pe.load_inputs(str(plp_path), str(tmp_path / "missing.csv"), str(tmp_path / "v.json"))
    assert set(inputs.load_errors) == {"pdp_list", "vocabulary"}
    assert pe.validate(inputs, now=NOW).stop


# --- Export invocation --------------------------------------------------------

class FakeLambda:
    def __init__(self, payload, function_error=None, status=200, raises=None):
        self.payload, self.function_error, self.status, self.raises = payload, function_error, status, raises
        self.calls = []

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        if self.raises:
            raise self.raises
        response = {"StatusCode": self.status,
                    "Payload": io.BytesIO(json.dumps(self.payload).encode("utf-8"))}
        if self.function_error:
            response["FunctionError"] = self.function_error
        return response


def test_invoke_export_returns_manifest_and_sends_site():
    client = FakeLambda(manifest())
    assert pe.invoke_export("export-dev", site="ounass", lambda_client=client)["export_id"] == "test-export"
    call = client.calls[0]
    assert call["FunctionName"] == "export-dev" and call["InvocationType"] == "RequestResponse"
    assert json.loads(call["Payload"])["site"] == "ounass"


@pytest.mark.parametrize("client", [
    FakeLambda({"errorMessage": "boom"}, function_error="Unhandled"),
    FakeLambda(manifest(), status=500),
    FakeLambda({"no": "files"}),
    FakeLambda(None, raises=RuntimeError("network")),
])
def test_invoke_export_failures_raise_export_error(client):
    with pytest.raises(pe.ExportError):
        pe.invoke_export("export-dev", lambda_client=client)


# --- Config and preflight -----------------------------------------------------

def test_config_from_settings_mapping():
    config = pe.Config.from_settings({"OUNASS_PLP_EFFICIENT_STALE_CRAWL_DAYS": "14",
                                      "OUNASS_PLP_EFFICIENT_GOLD_WARN_AGE_DAYS": "5"})
    assert config.stale_crawl_days == 14 and config.gold_warn_age_days == 5.0
    assert config.max_bad_plp_rows_ratio == 0.25  # default


def _write_local_inputs(tmp_path, plp_rows, pdp_rows):
    paths = {
        "plp": tmp_path / "plp.csv", "pdp": tmp_path / "pdp.csv",
        "vocab": tmp_path / "vocabulary.json", "manifest": tmp_path / "manifest.json",
    }
    paths["plp"].write_text(_csv(pe.PLP_COLUMNS, plp_rows))
    paths["pdp"].write_text(_csv(pe.PDP_COLUMNS, pdp_rows))
    paths["vocab"].write_text(json.dumps(VOCAB))
    paths["manifest"].write_text(json.dumps(manifest(datetime.now(timezone.utc))))
    return paths


def _preflight(paths):
    from scripts import preflight_ounass_plp_efficient as preflight

    return preflight.main(["--env", "dev", "--plp-list", str(paths["plp"]),
                           "--pdp-list", str(paths["pdp"]), "--vocabulary", str(paths["vocab"]),
                           "--manifest", str(paths["manifest"])])


def test_preflight_exits_0_when_crawl_would_start(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("APP_ENV", "dev")
    today = datetime.now(timezone.utc).date().isoformat()
    paths = _write_local_inputs(tmp_path, [plp()], [pdp(last_crawl_date=today)])
    assert _preflight(paths) == 0
    assert "OK: the crawl would start" in capsys.readouterr().out


def test_preflight_exits_1_and_lists_problems_when_crawl_would_stop(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("APP_ENV", "dev")
    paths = _write_local_inputs(tmp_path, [plp(subcategory="nope")], [pdp()])
    assert _preflight(paths) == 1
    out = capsys.readouterr().out
    assert "WOULD STOP" in out and "not in vocabulary" in out
