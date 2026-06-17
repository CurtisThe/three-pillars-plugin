"""Prose invariants for skills/tp-revert/SKILL.md — recipe / depth / flow (Tasks 2.1-2.2).

Landing / bookkeeping / re-land prose tests are in test_revert_skill_md_landing.py (Task 2.3).

Run with: pytest skills/tp-revert/scripts/test_revert_skill_md.py -q
"""

from __future__ import annotations

import re
from pathlib import Path

SKILL_MD = Path(__file__).resolve().parents[1] / "SKILL.md"


def _read() -> str:
    return SKILL_MD.read_text()


# ---------------------------------------------------------------------------
# Task 2.1 — recipe + depth-honesty prose
# ---------------------------------------------------------------------------

def test_recipe_git_revert_m1_present() -> None:
    text = _read()
    assert "git revert -m 1" in text, (
        "SKILL.md must contain the copy-pasteable 'git revert -m 1' recipe"
    )


def test_recipe_mainline_parent_explanation() -> None:
    text = _read()
    assert re.search(r"mainline.parent|mainline parent|-m 1", text, re.IGNORECASE), (
        "SKILL.md must explain the -m 1 mainline-parent selection"
    )


def test_recipe_naive_failure_note() -> None:
    text = _read()
    assert "is a merge but no -m option was given" in text, (
        "SKILL.md must contain the naive-failure error string"
    )


def test_recipe_documented_section_present() -> None:
    text = _read()
    assert "## Documented recipe" in text, (
        "SKILL.md must have a '## Documented recipe' section"
    )


def test_depth_caveat_clean_only_while_newest() -> None:
    text = _read()
    assert "clean only while newest (probe depth 0)" in text, (
        "SKILL.md must contain the exact depth caveat: "
        "'clean only while newest (probe depth 0)'"
    )


def test_depth_gate_refuses_depth_gt_0() -> None:
    text = _read()
    assert re.search(r"depth.*>.*0|depth > 0|depth\s*>\s*0", text), (
        "SKILL.md must name the depth > 0 refusal condition"
    )


def test_depth_gate_refuse_with_reality_prose() -> None:
    text = _read()
    assert re.search(r"refuse|REFUSE", text), (
        "SKILL.md must contain refuse/REFUSE in the depth-gate section"
    )


def test_depth_gate_conflicted_set_printed() -> None:
    text = _read()
    assert re.search(r"conflicted\[\]|conflict.set|conflicted set|conflicted\b", text, re.IGNORECASE), (
        "SKILL.md must state the conflicted[] set is printed in the refusal"
    )


def test_depth_gate_manual_only_continuation() -> None:
    text = _read()
    assert re.search(r"manual.only|operator.*recipe|proceed.*manual", text, re.IGNORECASE), (
        "SKILL.md must say proceeding past depth-1 is manual-only"
    )


def test_depth_gate_never_automates_past_depth_1() -> None:
    text = _read()
    assert re.search(r"never automate|never.*past depth.1|skill never automates", text, re.IGNORECASE), (
        "SKILL.md must state the skill never automates past depth-1"
    )


def test_depth_0_clean_false_same_refusal() -> None:
    text = _read()
    assert re.search(r"depth.*==.*0.*clean.*false|clean.*==.*false.*depth|unexpected|same refusal", text, re.IGNORECASE), (
        "SKILL.md must route 'depth==0 but clean==false' to the same refusal path"
    )


# ---------------------------------------------------------------------------
# Task 2.2 — flow core
# ---------------------------------------------------------------------------

def test_flow_workspace_path() -> None:
    text = _read()
    assert ".claude/worktrees/revert-{slug}" in text, (
        "SKILL.md must name the workspace path .claude/worktrees/revert-{slug}"
    )


def test_flow_branch_name() -> None:
    text = _read()
    assert "revert/{slug}" in text, (
        "SKILL.md must name the branch revert/{slug}"
    )


def test_flow_revert_command() -> None:
    text = _read()
    assert "git revert -m 1 --no-commit" in text, (
        "SKILL.md must contain 'git revert -m 1 --no-commit' in the flow"
    )


def test_flow_abort_refuse_on_conflict() -> None:
    text = _read()
    assert re.search(r"abort.*refuse|abort.*conflict|conflict.*abort", text, re.IGNORECASE), (
        "SKILL.md must say abort + refuse loudly on conflict"
    )


def test_carveout_whole_tree_commands() -> None:
    """Step 5 must contain the three-command whole-tree carve-out in the correct order."""
    text = _read()
    reset_cmd = "git reset -q HEAD -- three-pillars-docs/"
    restore_cmd = "git restore --worktree --source=HEAD -- three-pillars-docs/"
    clean_cmd = "git clean -fdq three-pillars-docs/"
    assert reset_cmd in text, (
        "SKILL.md step 5 must contain: git reset -q HEAD -- three-pillars-docs/"
    )
    assert restore_cmd in text, (
        "SKILL.md step 5 must contain: "
        "git restore --worktree --source=HEAD -- three-pillars-docs/"
    )
    assert clean_cmd in text, (
        "SKILL.md step 5 must contain: git clean -fdq three-pillars-docs/"
    )
    # Order is load-bearing: reset → restore → clean (clean-first skips index-tracked
    # resurrected files; they survive as untracked after reset and restore cannot remove
    # paths absent from HEAD).
    assert text.index(reset_cmd) < text.index(restore_cmd), (
        "SKILL.md carve-out: 'git reset' must appear before 'git restore'"
    )
    assert text.index(restore_cmd) < text.index(clean_cmd), (
        "SKILL.md carve-out: 'git restore' must appear before 'git clean'"
    )


def test_carveout_never_textually_unwound() -> None:
    text = _read()
    assert re.search(r"never textually unwound|never.*unwind|docs.*not.*reverted", text, re.IGNORECASE), (
        "SKILL.md must say living docs are never textually unwound"
    )


def test_carveout_archive_kept() -> None:
    text = _read()
    assert re.search(r"archive.*kept|archive is kept|paper trail.*kept", text, re.IGNORECASE), (
        "SKILL.md must say the design archive is kept"
    )


def test_reconcile_protocol_cited() -> None:
    text = _read()
    assert "skills/_shared/reconcile-protocol.md" in text, (
        "SKILL.md must cite skills/_shared/reconcile-protocol.md"
    )


def test_reconcile_amendment_template_fields() -> None:
    text = _read()
    for field in ("Supersedes", "Change", "Commit", "Why"):
        assert field in text, f"SKILL.md must include the amendment template field '{field}'"


def test_living_doc_format_cited() -> None:
    text = _read()
    assert "skills/_shared/living-doc-format.md" in text, (
        "SKILL.md must cite skills/_shared/living-doc-format.md"
    )


def test_roadmap_status_flip_prose() -> None:
    text = _read()
    assert re.search(r"Reverted.*PR.*revert PR|roadmap.*flip|status.*flip", text, re.IGNORECASE), (
        "SKILL.md must document the roadmap status-cell flip to 'Reverted — PR #NN → revert PR #RR'"
    )


def test_known_issues_revert_ledger() -> None:
    text = _read()
    assert re.search(r"known_issues.*revert|revert.*ledger|known_issues\.md", text, re.IGNORECASE), (
        "SKILL.md must mention the known_issues.md revert-ledger entry"
    )


def test_reconcile_reporter_only_never_apply() -> None:
    text = _read()
    assert "reconcile_docs.py" in text, "SKILL.md must invoke reconcile_docs.py"
    assert re.search(r'never.*--apply|never `--apply`', text, re.IGNORECASE), (
        "SKILL.md must say 'never --apply' or equivalent in the revert path"
    )
