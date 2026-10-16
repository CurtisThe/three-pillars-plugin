"""test_certify_ledger_heading.py — `open_pending_heading` matches the slug by exact token.

design: fragile-test-prevention (Task 15.6, #162; carried from the PR 162 review).

A slug matches only its own heading token: a slug never matches a heading
written for a longer slug that merely contains it, and a longer slug never
matches a heading written for a shorter one.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

import certify_ledger  # noqa: E402

DOCS = Path("three-pillars-docs")
SHORT_SLUG = "audit-pass"
LONG_SLUG = "audit-pass-does-not-bind"
LONG_HEADING = f"### M7: sweep ledger pending — {LONG_SLUG} B13/B15 await post-merge certify-sweep"
SHORT_HEADING = f"### M8: sweep ledger pending — {SHORT_SLUG} awaits post-merge certify-sweep"


def _issues(root: Path, heading: str) -> None:
    (root / DOCS).mkdir(parents=True, exist_ok=True)
    (root / DOCS / "known_issues.md").write_text(
        f"# Known issues\n\n## Medium\n\n{heading}\n\n## Low\n", encoding="utf-8")


def test_short_slug_does_not_match_a_longer_slug_heading(tmp_path):
    _issues(tmp_path, LONG_HEADING)
    assert certify_ledger.open_pending_heading(tmp_path, SHORT_SLUG) is None


def test_own_slug_matches_its_heading_exactly(tmp_path):
    _issues(tmp_path, LONG_HEADING)
    assert certify_ledger.open_pending_heading(tmp_path, LONG_SLUG) == LONG_HEADING.lstrip("# ")


def test_longer_slug_does_not_match_a_shorter_heading(tmp_path):
    _issues(tmp_path, SHORT_HEADING)
    assert certify_ledger.open_pending_heading(tmp_path, LONG_SLUG) is None
