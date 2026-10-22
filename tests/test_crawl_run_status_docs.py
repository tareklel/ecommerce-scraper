"""
Drift check between the verifier's run statuses/markers and their reference
doc (docs/crawl_run_status.md, see context/AGENTS.md). Fails when a marker or
failure reason is added or renamed in the verifier without updating the doc.
"""

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HANDLER = REPO_ROOT / "lambda" / "bronze_manifest_verifier" / "handler.py"
DOC = REPO_ROOT / "docs" / "crawl_run_status.md"


def _handler_constants():
    """MARKER_* string values, RUN_* statuses and FAILURE_REASONS keys, read without importing (boto3 clients)."""
    tree = ast.parse(HANDLER.read_text(encoding="utf-8"))
    markers, statuses, reasons = set(), set(), set()
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        name = getattr(node.targets[0], "id", "")
        if name.startswith("MARKER_") and isinstance(node.value, ast.Constant):
            markers.add(node.value.value)
        elif name.startswith("RUN_") and isinstance(node.value, ast.Constant):
            statuses.add(node.value.value)
        elif name == "FAILURE_REASONS" and isinstance(node.value, ast.Dict):
            reasons |= {k.value for k in node.value.keys}
    return markers, statuses, reasons


def test_every_marker_status_and_reason_is_documented():
    doc = DOC.read_text(encoding="utf-8")
    markers, statuses, reasons = _handler_constants()
    missing = sorted(f"`{v}`" for v in markers | statuses | reasons if f"`{v}`" not in doc)
    assert not missing, f"Missing from {DOC.name}: {missing}. Update the doc's tables."


def test_constants_were_found():
    # Guards the parser itself, so a refactor can't make the check silently pass.
    markers, statuses, reasons = _handler_constants()
    assert "_SUCCESS" in markers and "_FAIL_ACCESS" in markers
    assert {"success", "degraded", "failed"} <= statuses
    assert {"aborted", "access", "quality", "verification"} <= reasons
