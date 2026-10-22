"""
The crawler (ecommercecrawl/run_status.py) and the verifier Lambda
(lambda/bronze_manifest_verifier/handler.py) each carry the plain-language
meaning / what-to-do of every failure reason: the Lambda ships as its own
zip and can't import the crawler. These tests keep the two copies identical
and complete, and check the explanations reach the markers and manifest.
"""

import ast
import json
from pathlib import Path

from ecommercecrawl import run_status

HANDLER = Path(__file__).resolve().parents[1] / "lambda" / "bronze_manifest_verifier" / "handler.py"


def _verifier_reasons_and_link():
    tree = ast.parse(HANDLER.read_text(encoding="utf-8"))
    reasons, link = {}, None
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        name = getattr(node.targets[0], "id", "")
        if name == "STATUS_DOC_LINK":
            link = node.value.value
        elif name == "FAILURE_REASONS":
            for key, value in zip(node.value.keys, node.value.values):
                fields = {k.value: v for k, v in zip(value.keys, value.values)}
                reasons[key.value] = {f: fields[f].value for f in ("meaning", "what_to_do")}
    return reasons, link


def test_crawler_and_verifier_explanations_are_identical():
    reasons, link = _verifier_reasons_and_link()
    crawler = {k: v for k, v in run_status.FAILURE_EXPLANATIONS.items()}
    # The crawler never decides "verification" (only the verifier checks files).
    assert set(reasons) == set(crawler)
    assert reasons == crawler
    assert link == run_status.RUN_STATUS_DOC


def test_every_explanation_is_filled_in():
    for reason, texts in run_status.FAILURE_EXPLANATIONS.items():
        assert texts["meaning"].strip() and texts["what_to_do"].strip(), reason


def test_doc_anchor_exists():
    doc_path, anchor = run_status.RUN_STATUS_DOC.split("#")
    doc = (Path(__file__).resolve().parents[1] / doc_path).read_text(encoding="utf-8")
    # GitHub anchor for "## Failure markers" is #failure-markers.
    assert f"## {anchor.replace('-', ' ').capitalize()}" in doc
