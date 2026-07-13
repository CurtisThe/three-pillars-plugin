"""test_skill_md_path_anchors.py — G5 pin test (plugin-mode-parity, Task 3.6).

Pins the six executable-reference sites the parity-catalog G5 row identified
as un-anchored `skills/_shared/` module invocations (module invocation / bare
import with no `$TP_ROOT`/`sys.path` anchor). Deliberately excludes the ~18
prose doc-pointer sites (catalog G5 batched-ALREADY-CORRECT note) — this test
targets only the 6 EXECUTABLE sites the catalog names.

Each site must still contain its exact locator substring (an UNEXPECTED
locator-moved failure means the site was edited in a way this pin test no
longer tracks — update the sites list, not the assertion) AND the anchor
(`$TP_ROOT` or `sys.path`) must appear within the same +/-3/+4 line window
`known_gaps.sh`'s `_g5_check` uses, so the smoke harness and this pytest
regression agree on one definition of "anchored".
"""
from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# (relpath, locator) — catalog G5's six executable-reference sites.
_SITES = [
    ("skills/tp-implementation-audit/SKILL.md", "auto_verdict.py::compute_verdict"),
    ("skills/tp-run-full-design/SKILL.md", "auto_verdict.compute_verdict"),
    ("skills/tp-spec/SKILL.md", "from validate_artifact import validate_artifact"),
    ("skills/tp-pr-iterate/SKILL.md", "result = thread_dispose.dispose_threads("),
    (
        "skills/council/SKILL.md",
        "fills `{project_context_block}` from `skills/_shared/project_context.py`",
    ),
    (
        "skills/tp-pr-fix/SKILL.md",
        "Fill `{project_context_block}` from `skills/_shared/project_context.py`",
    ),
]


def _window(text: str, locator: str) -> str:
    idx = text.find(locator)
    assert idx >= 0, f"locator moved/missing: {locator!r}"
    lines = text.splitlines()
    upto = text[:idx].count("\n")
    return "\n".join(lines[max(0, upto - 3):upto + 4])


@pytest.mark.parametrize("relpath,locator", _SITES)
def test_executable_reference_carries_anchor(relpath, locator):
    """Each G5 executable-reference site is $TP_ROOT/sys.path-anchored."""
    text = (_REPO_ROOT / relpath).read_text(encoding="utf-8")
    window = _window(text, locator)
    assert "$TP_ROOT" in window or "sys.path" in window, (
        f"{relpath}: {locator!r} has no $TP_ROOT/sys.path anchor within its "
        f"+/-3/+4 line window:\n{window}"
    )


def test_zero_unanchored_g5_sites():
    """None of the six catalog G5 sites remain unanchored (aggregate pin)."""
    unanchored = []
    for relpath, locator in _SITES:
        text = (_REPO_ROOT / relpath).read_text(encoding="utf-8")
        window = _window(text, locator)
        if "$TP_ROOT" not in window and "sys.path" not in window:
            unanchored.append(relpath)
    assert not unanchored, f"un-anchored G5 sites remain: {unanchored}"
