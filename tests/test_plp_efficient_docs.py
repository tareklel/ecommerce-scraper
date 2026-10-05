"""
Drift check between PLP-efficient crawl settings and their reference doc.

docs/ounass_plp_efficient_crawl.md is the long-lived description of the mode
(see context/AGENTS.md). The most common way it goes stale is a setting being
added or renamed without the doc's guardrail table being updated, so this test
fails until every OUNASS_PLP_EFFICIENT_* setting appears in the doc.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = REPO_ROOT / "ecommercecrawl" / "settings.py"
DOC_PATH = REPO_ROOT / "docs" / "ounass_plp_efficient_crawl.md"

# Top-level assignments only, e.g. `OUNASS_PLP_EFFICIENT_CRAWL = ...`.
# Reading the file as text avoids importing settings (env lookups, side effects).
SETTING_PATTERN = re.compile(r"^(OUNASS_PLP_EFFICIENT_[A-Z0-9_]+)\s*=", re.MULTILINE)


def plp_efficient_settings():
    return sorted(set(SETTING_PATTERN.findall(SETTINGS_PATH.read_text(encoding="utf-8"))))


def test_reference_doc_exists():
    assert DOC_PATH.is_file(), f"Missing reference doc: {DOC_PATH}"


def test_every_plp_efficient_setting_is_documented():
    doc = DOC_PATH.read_text(encoding="utf-8")
    missing = [name for name in plp_efficient_settings() if name not in doc]
    assert not missing, (
        f"Settings missing from {DOC_PATH.name}: {missing}. "
        "Document them in the guardrails/settings tables and add a change-log line."
    )


def test_setting_pattern_matches_assignments():
    # Guards the regex itself, so a pattern bug can't make the check silently pass.
    sample = "OUNASS_PLP_EFFICIENT_CRAWL = False\nOTHER = 1\n  OUNASS_PLP_EFFICIENT_INDENTED = 2\n"
    assert SETTING_PATTERN.findall(sample) == ["OUNASS_PLP_EFFICIENT_CRAWL"]
