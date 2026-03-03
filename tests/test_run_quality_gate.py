import json

import run_quality_gate


def _write_jsonl(path, rows):
    path.write_text("\n".join(json.dumps(x) for x in rows), encoding="utf-8")


def test_main_returns_non_zero_on_fail_quality(monkeypatch, tmp_path):
    input_path = tmp_path / "rows.jsonl"
    report_path = tmp_path / "quality_report.json"
    rows = [
        {"site": "ounass", "primary_key": "a_ounass", "url": "https://www.ounass.ae/pdp-1", "primary_label": None},
        {"site": "ounass", "primary_key": "b_ounass", "url": "https://www.ounass.ae/pdp-2", "primary_label": None},
        {"site": "ounass", "primary_key": "c_ounass", "url": "https://www.ounass.ae/pdp-3", "primary_label": None},
        {"site": "ounass", "primary_key": "d_ounass", "url": "https://www.ounass.ae/pdp-4", "primary_label": "NEW"},
        {"site": "ounass", "primary_key": "e_ounass", "url": "https://www.ounass.ae/pdp-5", "primary_label": None},
    ]
    _write_jsonl(input_path, rows)

    monkeypatch.setattr(
        "sys.argv",
        [
            "run_quality_gate.py",
            "--input-jsonl",
            str(input_path),
            "--blank-threshold",
            "0.8",
            "--min-rows-for-blank-check",
            "5",
            "--report-path",
            str(report_path),
        ],
    )

    exit_code = run_quality_gate.main()
    assert exit_code == 1
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "fail_quality"
    assert report["rule_set"] == "default"
    assert report["input_jsonl_path"] == "rows.jsonl"


def test_main_returns_zero_when_exception_whitelists_field(monkeypatch, tmp_path):
    input_path = tmp_path / "rows.jsonl"
    report_path = tmp_path / "quality_report.json"
    rows = [
        {"site": "ounass", "primary_key": "a_ounass", "url": "https://www.ounass.ae/pdp-1", "primary_label": None},
        {"site": "ounass", "primary_key": "b_ounass", "url": "https://www.ounass.ae/pdp-2", "primary_label": None},
        {"site": "ounass", "primary_key": "c_ounass", "url": "https://www.ounass.ae/pdp-3", "primary_label": None},
        {"site": "ounass", "primary_key": "d_ounass", "url": "https://www.ounass.ae/pdp-4", "primary_label": "NEW"},
        {"site": "ounass", "primary_key": "e_ounass", "url": "https://www.ounass.ae/pdp-5", "primary_label": None},
    ]
    _write_jsonl(input_path, rows)

    monkeypatch.setattr(
        "sys.argv",
        [
            "run_quality_gate.py",
            "--input-jsonl",
            str(input_path),
            "--blank-threshold",
            "0.8",
            "--min-rows-for-blank-check",
            "5",
            "--blank-field-exceptions-json",
            '{"ounass":["primary_label"]}',
            "--report-path",
            str(report_path),
        ],
    )

    exit_code = run_quality_gate.main()
    assert exit_code == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "pass"
    assert report["rule_set"] == "default"
    assert report["input_jsonl_path"] == "rows.jsonl"
