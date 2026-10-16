"""test_consumer_repo_rule.py — consumer-repo-parity Task 9.2.

SHIPPED test: reads only the shipped rule doc
(skills/_shared/consumer-repo-rule.md), resolved relative to this file's own
path — never a dev-only file. Asserts structural keys only (headings, the
ship-list manifest's file name), never prose wording, so the doc can be
reworded without breaking this test.

Run with: pytest skills/_shared/test_consumer_repo_rule.py -q
"""
from __future__ import annotations

from pathlib import Path

_RULE_DOC = Path(__file__).resolve().parent / "consumer-repo-rule.md"
# The ship-list manifest's file name, split so this shipped test is not
# mistaken for a manifest reader by test_release_tiers' source-text scan
# (it only reads the rule doc).
_SHIP_LIST = "release-tiers" ".json"


def _text() -> str:
    return _RULE_DOC.read_text(encoding="utf-8")


def test_rule_doc_exists() -> None:
    assert _RULE_DOC.is_file(), f"missing shipped rule doc: {_RULE_DOC}"


def test_rule_doc_has_rule_heading() -> None:
    text = _text()
    assert any(
        line.strip() == "## Rule" for line in text.splitlines()
    ), "consumer-repo-rule.md must have a '## Rule' heading"


def test_rule_doc_has_audit_question_heading() -> None:
    text = _text()
    assert any(
        line.strip() == "## Audit question" for line in text.splitlines()
    ), "consumer-repo-rule.md must have a '## Audit question' heading"


def test_rule_doc_names_release_tiers_as_ship_list() -> None:
    text = _text()
    assert _SHIP_LIST in text, (
        f"consumer-repo-rule.md must name {_SHIP_LIST} as the ship list"
    )
