"""Prose invariants for skills/tp-revert/SKILL.md — landing / bookkeeping / re-land (Task 2.3).

Recipe / depth / flow prose tests are in test_revert_skill_md.py (Tasks 2.1-2.2).

Run with: pytest skills/tp-revert/scripts/test_revert_skill_md_landing.py -q
"""

from __future__ import annotations

import re
from pathlib import Path

SKILL_MD = Path(__file__).resolve().parents[1] / "SKILL.md"


def _read() -> str:
    return SKILL_MD.read_text()


# ---------------------------------------------------------------------------
# Task 2.3 — landing shape
# ---------------------------------------------------------------------------

def test_landing_commit_message_shape() -> None:
    text = _read()
    assert re.search(r"Revert:.*{slug}.*PR #NN|Revert:.*slug.*PR", text), (
        "SKILL.md must specify commit message shape 'Revert: {slug} (PR #NN)'"
    )


def test_landing_single_commit_pr() -> None:
    text = _read()
    assert "single-commit PR" in text, (
        "SKILL.md must contain 'single-commit PR'"
    )


def test_landing_standard_gate() -> None:
    text = _read()
    assert "standard gate" in text, (
        "SKILL.md must say the revert lands through the 'standard gate'"
    )


def test_landing_no_direct_master_commit() -> None:
    text = _read()
    assert re.search(r"no direct.*master|no direct master|never.*direct.*master", text, re.IGNORECASE), (
        "SKILL.md must explicitly say no direct master commit"
    )


def test_landing_gate_untouched_named() -> None:
    text = _read()
    assert "deterministic_gate.py" in text, (
        "SKILL.md must name deterministic_gate.py and say it is never edited"
    )


# ---------------------------------------------------------------------------
# Task 2.3 — bookkeeping
# ---------------------------------------------------------------------------

def test_bookkeeping_annotate_and_link() -> None:
    text = _read()
    assert re.search(r"comment.*both PRs|annotate.and.link|comment on.*original PR", text, re.IGNORECASE), (
        "SKILL.md must describe annotate-and-link bookkeeping (comment both PRs)"
    )


def test_bookkeeping_merged_cannot_reopen() -> None:
    text = _read()
    assert re.search(r"cannot be reopened|merged PRs.*cannot", text, re.IGNORECASE), (
        "SKILL.md must state merged PRs cannot be reopened"
    )


def test_bookkeeping_tp_reverted_label() -> None:
    text = _read()
    assert "tp:reverted" in text, (
        "SKILL.md must mention the tp:reverted label"
    )


def test_bookkeeping_rest_labels_api() -> None:
    text = _read()
    assert re.search(r"REST labels API|gh api.*labels|labels.*gh api", text, re.IGNORECASE), (
        "SKILL.md must say the label is applied via the REST labels API (gh api)"
    )


def test_bookkeeping_add_label_noop_caveat() -> None:
    text = _read()
    assert "`gh pr edit --add-label` silently no-ops" in text, (
        "SKILL.md must contain the exact caveat: '`gh pr edit --add-label` silently no-ops'"
    )


def test_bookkeeping_design_stays_archived() -> None:
    text = _read()
    assert re.search(r"design stays archived|archive.*not resurrected|lock.*not resurrected", text, re.IGNORECASE), (
        "SKILL.md must say design stays archived and lock/branch not resurrected"
    )


# ---------------------------------------------------------------------------
# Task 2.3 — re-land path
# ---------------------------------------------------------------------------

def test_reland_revert_pr_is_landing() -> None:
    text = _read()
    assert re.search(r"revert PR.*landing|revert.*is.*landing|re.land.*revert", text, re.IGNORECASE), (
        "SKILL.md must say the revert PR is itself a landing"
    )


def test_reland_depth_1_revert_of_revert() -> None:
    text = _read()
    assert re.search(r"/tp-revert.*revert.pr|revert.of.a.revert|revert.*depth.1", text, re.IGNORECASE), (
        "SKILL.md must describe /tp-revert <revert-pr#> re-landing while depth-1"
    )


def test_reland_past_depth_1_new_design_cycle() -> None:
    text = _read()
    assert re.search(r"new design cycle|past depth.1.*new design|past.*depth.1.*new", text, re.IGNORECASE), (
        "SKILL.md must say past depth-1 re-landing is a new design cycle"
    )
