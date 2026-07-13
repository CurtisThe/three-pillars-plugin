"""Archive-guard invariants for skills/tp-design-complete/SKILL.md.

The design-complete-stamp-guard Phase 2 staged-blob guard pins: step 6f must
run verify_archive_staged.py between staging and the archival commit, with the
two-anchor ordering git_add < guard < commit < gh pr create, the exit-1
double-add / exit-2 immediate-abort disposition, the --json staging loop, the
unpiped / HEAD-advanced commit, and the ## Auto Mode guard inheritance.

Split out of test_design_complete_skill_md.py (inv #34 file-size cap). The
pre-existing SKILL.md pins remain in that module; this file carries only the
staged-blob archive-guard pins.

Run with: pytest skills/tp-design-complete/scripts/test_design_complete_archive_guard.py -q
"""

from __future__ import annotations

import re
from pathlib import Path

SKILL_MD = Path(__file__).resolve().parents[1] / "SKILL.md"


def _read() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def _auto_mode_block(text: str) -> str:
    """Return the text from the '## Auto Mode' heading to the next '## ' (or EOF)."""
    match = re.search(r"^## Auto Mode\b.*?(?=^## |\Z)", text, re.DOTALL | re.MULTILINE)
    assert match, "## Auto Mode section not found"
    return match.group(0)


# ---------------------------------------------------------------------------
# design-complete-stamp-guard Task 2.1: staged-blob guard on the archival commit
# ---------------------------------------------------------------------------

def test_verify_archive_staged_runs_between_staging_and_commit() -> None:
    """Two-anchor ordering pin (mirrors test_cleanup_pending_set_before_pr_open):
    git_add < verify_archive_staged.py < git commit < gh pr create.

    The guard must run strictly BEFORE the archival commit — inspecting an
    already-committed blob is inert. It must also run AFTER staging (it asserts
    the STAGED index blobs) and BEFORE PR-open.
    """
    text = _read()
    git_add_pos = text.find("git add three-pillars-docs/tp-designs/{design-name}")
    guard_pos = text.find("verify_archive_staged.py")
    commit_pos = text.find('git commit -m "Complete design:')
    pr_pos = text.find("gh pr create")
    assert git_add_pos != -1, "step 6f must stage the archival paths"
    assert guard_pos != -1, "step 6f must invoke verify_archive_staged.py"
    assert commit_pos != -1, "step 6f must contain the 'Complete design:' commit"
    assert pr_pos != -1, "step 6g must open the PR via gh pr create"
    assert git_add_pos < guard_pos < commit_pos < pr_pos, (
        "ordering must be git_add < verify_archive_staged.py < git commit < gh pr create "
        f"(git_add={git_add_pos}, guard={guard_pos}, commit={commit_pos}, pr={pr_pos})"
    )


def test_verify_archive_staged_invoked_with_repo_and_slug() -> None:
    """The guard is called with --repo $(git rev-parse --show-toplevel) --slug {design-name}."""
    text = _read()
    assert '"$TP_ROOT"/skills/tp-design-complete/scripts/verify_archive_staged.py' in text, (
        "the guard must be invoked via the $TP_ROOT anchor"
    )
    assert "git rev-parse --show-toplevel" in text, (
        "the guard --repo arg must resolve via git rev-parse --show-toplevel"
    )
    assert "--slug {design-name}" in text, "the guard must be passed --slug {design-name}"


def test_guard_exit1_double_add_exit2_immediate_abort() -> None:
    """On exit 1 the step re-runs the specific git add (double-add) then aborts if
    still failing; on exit 2 (precondition) it aborts IMMEDIATELY without the retry.
    """
    text = _read()
    # Scope to the guard sub-step: from the guard invocation to the archival commit.
    guard_pos = text.find("verify_archive_staged.py")
    commit_pos = text.find('git commit -m "Complete design:')
    span = text[guard_pos:commit_pos]
    # exit 1 -> double-add retry
    assert re.search(r"exit.{0,6}1", span), "the guard sub-step must name exit 1"
    assert re.search(r"double-add|re-`?git add`?|re-add", span, re.IGNORECASE), (
        "on exit 1 the step must re-`git add` the offending path (double-add)"
    )
    assert re.search(r"still.{0,20}(exit|fail)|abort", span, re.IGNORECASE), (
        "on a still-failing double-add the step must abort loudly"
    )
    # exit 2 -> immediate abort, no retry
    assert re.search(r"exit.{0,6}2", span), "the guard sub-step must name exit 2"
    assert re.search(r"immediate", span, re.IGNORECASE), (
        "on exit 2 the step must abort IMMEDIATELY"
    )
    assert re.search(r"no(t)?\b.{0,30}retry|without.{0,20}double-add|do not.{0,20}re-?add", span, re.IGNORECASE), (
        "on exit 2 the step must NOT run the double-add retry"
    )


def test_6f_stages_reconcile_json_list_by_loop() -> None:
    """Step 6f must LOOP over the reconcile --archive-cites --json edits[] list and
    git add each rewritten path — not rely only on a fixed hardcoded path set.
    """
    text = _read()
    # A capture of the --json output and a loop that git adds each rewritten path.
    assert "RECONCILE_JSON" in text, (
        "step 6f must capture the reconcile --json output (RECONCILE_JSON)"
    )
    assert re.search(r'edits', text), "the loop must read the --json edits[] array"
    assert re.search(r"for\s+\w+\s+in", text), "step 6f must contain a for-loop over the rewritten paths"
    assert re.search(r'git add "\$\w+"', text), (
        "the loop body must git add each rewritten path"
    )
    assert re.search(r"loop", text, re.IGNORECASE), (
        "step 6f must describe looping over the --json list (not a fixed set)"
    )


def test_archival_commit_unpiped_head_advanced() -> None:
    """The 'Complete design:' commit runs UNPIPED and the step asserts HEAD advanced
    past a pre-commit rev-parse before reporting success (a hook-blocked, HEAD-
    unchanged commit is a failure)."""
    text = _read()
    assert "PRE=$(git rev-parse HEAD)" in text, (
        "step 6f must capture PRE=$(git rev-parse HEAD) before the archival commit"
    )
    assert re.search(r"unpiped", text, re.IGNORECASE), (
        "the archival commit must be documented as running unpiped"
    )
    # After the commit, assert HEAD differs from PRE.
    pre_pos = text.find("PRE=$(git rev-parse HEAD)")
    commit_pos = text.find('git commit -m "Complete design:')
    assert pre_pos < commit_pos, "PRE must be captured before the commit"
    after = text[commit_pos:]
    assert re.search(r'\$PRE|"\$PRE"', after), (
        "after the commit the step must compare HEAD against $PRE"
    )
    assert re.search(r"HEAD.{0,40}(advanc|differ|unchanged|=)", after, re.IGNORECASE | re.DOTALL), (
        "the step must assert HEAD advanced (differs from $PRE) after the commit"
    )


def test_auto_mode_inherits_staged_blob_guard() -> None:
    """## Auto Mode must state the archival commit inherits the staged-blob guard
    (verify_archive_staged.py as its pre-commit self-check) and logs the abort to
    decisions.md under --auto."""
    block = _auto_mode_block(_read())
    assert "verify_archive_staged.py" in block, (
        "## Auto Mode must name verify_archive_staged.py as the inherited guard"
    )
    assert "decisions.md" in block, (
        "## Auto Mode must state the guard abort is logged to decisions.md"
    )
    assert re.search(r"abort|BLOCK|escalat", block, re.IGNORECASE), (
        "## Auto Mode must state the guard aborts / escalates on failure"
    )
