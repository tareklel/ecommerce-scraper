import argparse
import json
import os
from pathlib import Path

from ecommercecrawl.quality_gate import FAIL_QUALITY
from ecommercecrawl.quality_gate import QualityGateParams
from ecommercecrawl.quality_gate import evaluate_fail_quality
from ecommercecrawl.quality_gate import load_blank_field_exceptions
from ecommercecrawl.quality_gate import load_jsonl_rows


def _default_report_path(output_dir: str) -> str:
    return os.path.join(output_dir, "quality_report.json")


def _project_scoped_path(path: str) -> str:
    """
    Return a project-relative path when the file is under cwd.
    For files outside the project, return only the filename.
    """
    input_path = Path(path).resolve()
    project_root = Path.cwd().resolve()
    try:
        return input_path.relative_to(project_root).as_posix()
    except ValueError:
        return input_path.name


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local FAIL_QUALITY checks on crawler JSONL output.")
    parser.add_argument("--input-jsonl", required=True, help="Path to crawler output JSONL.")
    parser.add_argument(
        "--blank-threshold",
        type=float,
        default=0.8,
        help="Fail when a field is blank in >= this ratio of rows for a site.",
    )
    parser.add_argument(
        "--min-rows-for-blank-check",
        type=int,
        default=20,
        help="Minimum rows per site before blank-field threshold checks apply.",
    )
    parser.add_argument(
        "--blank-field-exceptions-json",
        help='JSON object mapping site to fields to ignore. Example: {"ounass":["primary_label"]}',
    )
    parser.add_argument(
        "--blank-field-exceptions-file",
        help="Path to JSON file mapping site to fields to ignore.",
    )
    parser.add_argument("--report-path", help="Optional output path for the quality report JSON.")
    parser.add_argument(
        "--report-dir",
        default="output/quality",
        help="Directory for report output when --report-path is not provided.",
    )
    args = parser.parse_args()

    if args.blank_field_exceptions_json and args.blank_field_exceptions_file:
        parser.error("Use either --blank-field-exceptions-json OR --blank-field-exceptions-file, not both.")

    rows = load_jsonl_rows(args.input_jsonl)
    exceptions = load_blank_field_exceptions(
        exceptions_json=args.blank_field_exceptions_json,
        exceptions_file=args.blank_field_exceptions_file,
    )
    report = evaluate_fail_quality(
        rows,
        params=QualityGateParams(
            blank_threshold=args.blank_threshold,
            min_rows_for_blank_check=args.min_rows_for_blank_check,
        ),
        blank_field_exceptions={k: sorted(v) for k, v in exceptions.items()},
    )
    # Keep provenance in the payload while keeping the output filename stable.
    report["input_jsonl_path"] = _project_scoped_path(args.input_jsonl)

    report_path = args.report_path or _default_report_path(args.report_dir)
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(
        f"Quality gate status={report['status']} "
        f"violations={report['violations_count']} "
        f"rows={report['total_rows']} report={report_path}"
    )
    return 1 if report["status"] == FAIL_QUALITY else 0


if __name__ == "__main__":
    raise SystemExit(main())
