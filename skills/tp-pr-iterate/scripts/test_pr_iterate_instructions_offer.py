"""test_pr_iterate_instructions_offer — Task 8.4: the `/tp-pr-iterate` first-run offer.

`tp-pr-iterate/SKILL.md` must name the shipped entry points — `review_instructions.py
status`, `review_instructions.py scaffold`, and `repo_config_load.py set` with
`review.instructions_declined` — and its `--auto` line must name the offer as
logged-not-scaffolded (`decisions.md` next to `review_instructions`). Token pins, not
sentences. Also holds the file to the Task 8.4 line cap.

Run with: python3 -m pytest skills/tp-pr-iterate/scripts/test_pr_iterate_instructions_offer.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "skills" / "_shared"))
SKILL_MD = Path(__file__).resolve().parents[1] / "SKILL.md"
# Task 8.4 "Done when": the file is ≤ 476 after Phase 7 (the edit is net-neutral).
# cheap-tier-review-prep (Task 6.6, plan-audit #2): the --cheap-tier flag bullet, the step 2.5
# pointer and the classifier_judge stub add 7 lines; the cap rises to 485 (the plan's +9 budget).
MAX_LINES = 485


def _body() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def test_entry_points_named(tmp_path):
    """The offer's entry points resolve (invariant 46) and the decline key is in the schema."""
    skill_refs = pytest.importorskip("skill_refs")
    assert skill_refs.check(REPO_ROOT, [SKILL_MD], cache_dir=tmp_path).issues == []
    import json
    import repo_config_load
    schema = json.loads(repo_config_load.SCHEMA_PATH.read_text(encoding="utf-8"))
    review = schema["properties"]["review"]["properties"]
    assert review["instructions_declined"]["type"] == "boolean"


def test_auto_line_logs_not_scaffolds():
    """The unattended case: a `--auto` line must say the offer is LOGGED (not
    scaffolded) — `decisions.md` on the same line as `review_instructions`."""
    auto_lines = [ln for ln in _body().splitlines() if "--auto" in ln]
    assert any(
        "decisions.md" in ln and "review_instructions" in ln for ln in auto_lines
    ), ("no `--auto` line says the review-instructions offer is logged-not-scaffolded "
        "(needs `decisions.md` + `review_instructions` on the same line)")


def test_under_line_cap():
    lines = len(_body().splitlines())
    assert lines <= MAX_LINES, (
        f"tp-pr-iterate/SKILL.md is {lines} lines — must be ≤ {MAX_LINES} (Task 8.4 cap)")
