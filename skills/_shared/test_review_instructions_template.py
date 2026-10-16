"""test_review_instructions_template — the generic review-instructions template.

design: consumer-repo-parity (Task 8.1)

`skills/_shared/templates/review-instructions.md` ships to user repos (scaffolded
by `review_instructions.scaffold`, Task 8.2). It must be *generic*: it carries
the five section keys, the `REVIEW_BAR` blocking bar verbatim, and none of the
framework-repo-specific tokens. This test reads the template file and asserts
each of those properties. It does not edit the template; it only reads it.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[1]
_TEMPLATE = _HERE / "templates" / "review-instructions.md"
_ANGLES_SCRIPTS = _REPO_ROOT / "skills" / "tp-pr-iterate" / "scripts"

if str(_ANGLES_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_ANGLES_SCRIPTS))

import angles  # noqa: E402

SECTION_KEYS = (
    "## Scope",
    "## Known-intentional patterns",
    "## What counts as a real defect",
    "## Blocking bar",
    "## Promises vs enforcement",
)

FORBIDDEN_TOKENS = (
    "three-pillars",
    "framework-check",
    "ci-local",
    "CurtisThe",
    "tp-",
)


def _template_text() -> str:
    return _TEMPLATE.read_text(encoding="utf-8")


def test_template_exists():
    assert _TEMPLATE.is_file(), f"template missing: {_TEMPLATE}"


def test_has_five_section_headings():
    lines = [ln.strip() for ln in _template_text().splitlines()]
    for key in SECTION_KEYS:
        assert key in lines, f"missing section heading line: {key!r}"


def test_blocking_bar_carries_review_bar_verbatim():
    assert angles.REVIEW_BAR in _template_text(), (
        f"REVIEW_BAR text not present verbatim: {angles.REVIEW_BAR!r}"
    )


def test_no_framework_repo_specific_content():
    text = _template_text()
    for token in FORBIDDEN_TOKENS:
        assert token not in text, f"forbidden token {token!r} present in template"
