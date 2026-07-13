"""Invariants for skills/tp-merge/SKILL.md — the land skill (Task 4.4, D7).

Asserts:
  - frontmatter name is exactly `tp-merge` (the retained land name).
  - the description is the LAND half (irreversible gh pr merge), NOT base-sync.
  - the body states it calls require_merge_gate_pass (5 preds incl. human approval),
    runs gh pr merge ONLY on PASS, and REFUSES on MergeGateBlocked.
  - it references the howto guide (skills/_shared/human-approval-howto.md).
  - it carries design-name validation (framework-check invariant #2).
  - it never says "safe to merge".

Run with: pytest skills/tp-merge/scripts/test_land_skill_md.py -q
"""

from __future__ import annotations

import re
from pathlib import Path

SKILL_MD = Path(__file__).resolve().parents[1] / "SKILL.md"


def _read() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def test_frontmatter_name_is_tp_merge() -> None:
    text = _read()
    assert re.search(r"^name:\s*tp-merge\s*$", text, re.MULTILINE), (
        "land SKILL.md frontmatter name must be exactly tp-merge"
    )


def test_description_is_the_land_half() -> None:
    text = _read()
    desc = re.search(r"^description:.*$", text, re.MULTILINE).group(0)
    assert "gh pr merge" in desc, (
        "land description must reference the irreversible gh pr merge"
    )
    assert re.search(r"require_merge_gate_pass|merge gate", desc, re.IGNORECASE), (
        "land description must reference the merge gate enforcement"
    )


def test_calls_require_merge_gate_pass() -> None:
    text = _read()
    assert "require_merge_gate_pass" in text, (
        "land skill must call require_merge_gate_pass"
    )
    # The six-predicate gate including human approval and ci_local_stamp.
    assert re.search(r"human.approv|pred_human_approved", text, re.IGNORECASE), (
        "land skill must mention the human-approval predicate"
    )


def test_runs_gh_pr_merge_only_on_pass() -> None:
    text = _read()
    assert "gh pr merge" in text
    assert re.search(r"only on PASS|on PASS.*merge|merge.*on PASS|ONLY on PASS", text, re.IGNORECASE), (
        "land skill must run gh pr merge ONLY on a PASS gate"
    )


def test_refuses_on_merge_gate_blocked() -> None:
    text = _read()
    assert "MergeGateBlocked" in text, (
        "land skill must name MergeGateBlocked as the refusal trigger"
    )
    assert re.search(r"refuse|REFUSED", text, re.IGNORECASE), (
        "land skill must REFUSE on a blocked gate"
    )
    # Refusal must NOT run gh pr merge.
    assert re.search(r"NOT.*gh pr merge|does NOT run|never.*gh pr merge|not invoked", text, re.IGNORECASE), (
        "land skill refusal must explicitly NOT cross the gh pr merge boundary"
    )


def test_references_howto() -> None:
    text = _read()
    assert "skills/_shared/human-approval-howto.md" in text, (
        "land skill refusal must reference the human-approval howto guide"
    )


def test_carries_design_name_validation() -> None:
    """framework-check invariant #2: a tp-* skill taking a name argument must
    validate design-name (inline a-z0-9- pattern or validate-name reference)."""
    text = _read()
    assert "a-z0-9-" in text or "validate-name" in text, (
        "land SKILL.md must carry design-name validation"
    )


def test_never_says_safe_to_merge() -> None:
    text = _read()
    assert "safe to merge" not in text.lower(), (
        "land SKILL.md must NEVER say 'safe to merge' — use the UNVERIFIED label language"
    )
    assert "UNVERIFIED" in text, (
        "land SKILL.md must surface the UNVERIFIED gate label"
    )


# ---------------------------------------------------------------------------
# Task 8.4: dispatch-from-seat invocation (Phase 8 activation mechanism)
# ---------------------------------------------------------------------------


def test_step_2_documents_dispatch_from_seat_two_hop_recipe() -> None:
    """Step 2 must document the NON-CIRCULAR two-hop $TP_SEAT_ROOT recipe: seat_resolve.sh
    --where, then resolve_root.sh --skill-dir anchored at the SEAT's own skill directory
    (NOT the worktree's, and NOT probe-4's cwd-derived fallback)."""
    text = _read()

    assert "seat_resolve.sh --where" in text, (
        "step 2 must resolve the seat via `seat_resolve.sh --where`"
    )
    assert re.search(r'resolve_root\.sh.*--skill-dir.*"\$SEAT"/skills/tp-merge\b', text), (
        "step 2 must resolve TP_SEAT_ROOT via resolve_root.sh --skill-dir anchored at "
        "the SEAT's own skill directory (skills/tp-merge, NOT .../scripts)"
    )
    assert "TP_SEAT_ROOT" in text, (
        "step 2 must name the resolved seat root as TP_SEAT_ROOT"
    )
    assert re.search(r"not.{0,6}probe-4", text, re.IGNORECASE), (
        "step 2 must explicitly rule out probe-4 (cwd-derived dev-checkout fallback)"
    )


def test_step_2_documents_repo_flag_invocation() -> None:
    """Step 2 must invoke land.py from $TP_SEAT_ROOT with --repo "$(git rev-parse
    --show-toplevel)" — the documented dispatch-from-seat carry-capable invocation."""
    text = _read()

    assert '"$TP_SEAT_ROOT"/skills/tp-merge/scripts/land.py' in text, (
        "step 2 must invoke land.py from $TP_SEAT_ROOT (the seat's copy)"
    )
    assert '--repo "$(git rev-parse --show-toplevel)"' in text, (
        "step 2 must pass --repo \"$(git rev-parse --show-toplevel)\" (the worktree "
        "as the explicit subject repo)"
    )


def test_step_2_documents_why_disjoint_code_and_fail_closed_consequence() -> None:
    """Step 2 must name WHY (the oracle's DISJOINT-CODE guard) and the fail-closed
    consequence of skipping the two-hop recipe (carry lost, never an unsound PASS)."""
    text = _read()

    assert re.search(r"DISJOINT.CODE", text), (
        "step 2 must name the oracle's DISJOINT-CODE guard as the WHY"
    )
    assert re.search(r"oracle_independent|independent.oracle", text, re.IGNORECASE), (
        "step 2 must reference the independent-oracle guard by name"
    )
    assert re.search(r"fail.?s?\s*CLOSED|fails closed", text, re.IGNORECASE), (
        "step 2 must state the guard fails CLOSED (never an unsound certificate)"
    )
    assert re.search(r"worktree.resolved.*(refused|detected)|detected and refused", text, re.IGNORECASE), (
        "step 2 must state a worktree-resolved root is detected/refused by the guard"
    )


# ---------------------------------------------------------------------------
# Task 5.1: Serial landings and the depth-1 revert window section
# ---------------------------------------------------------------------------

def _revert_window_section(text: str) -> str:
    """Return the 'Serial landings and the depth-1 revert window' section."""
    match = re.search(
        r"^##\s+Serial landings and the depth-1 revert window\b.*?(?=^##\s|\Z)",
        text, re.DOTALL | re.MULTILINE,
    )
    assert match, (
        "SKILL.md must contain a '## Serial landings and the depth-1 revert window' section"
    )
    return match.group(0)


def test_revert_window_section_exists_after_rules() -> None:
    """The revert-window section must exist after ## Rules."""
    text = _read()
    rules_pos = re.search(r"^## Rules\b", text, re.MULTILINE)
    section_pos = re.search(
        r"^## Serial landings and the depth-1 revert window\b",
        text, re.MULTILINE,
    )
    assert rules_pos, "## Rules section must exist in SKILL.md"
    assert section_pos, (
        "## Serial landings and the depth-1 revert window section must exist"
    )
    assert rules_pos.start() < section_pos.start(), (
        "The revert-window section must appear after ## Rules"
    )


def test_revert_window_serial_landings() -> None:
    """Section must state landings are serial and document it as load-bearing."""
    text = _read()
    block = _revert_window_section(text)
    assert re.search(r"\bserial\b", block, re.IGNORECASE), (
        "The section must use 'serial' to describe the landing model"
    )


def test_revert_window_probe_stat() -> None:
    """Section must contain the 1/12 probe stat."""
    text = _read()
    block = _revert_window_section(text)
    assert "1/12" in block, (
        "The section must cite the '1/12' probe stat"
    )


def test_revert_window_newest_landing_phrase() -> None:
    """Section must state only the newest landing reverts clean."""
    text = _read()
    block = _revert_window_section(text)
    assert "only the newest landing reverts clean" in block, (
        "The section must state 'only the newest landing reverts clean'"
    )


def test_revert_window_run_post_merge_before_next() -> None:
    """Section must instruct running /tp-post-merge before the next merge gesture."""
    text = _read()
    block = _revert_window_section(text)
    assert "/tp-post-merge" in block, (
        "The section must reference /tp-post-merge"
    )
    assert "/tp-merge" in block, (
        "The section must reference /tp-merge"
    )
    assert "before the next merge gesture" in block, (
        "The section must contain the literal 'before the next merge gesture'"
    )


def test_revert_window_event_denominated_budget() -> None:
    """Section must state the budget is event-denominated (inter-merge gap), not minutes."""
    text = _read()
    block = _revert_window_section(text)
    assert re.search(r"inter.merge gap|budget.*event|event.*budget", block, re.IGNORECASE), (
        "The section must state the budget is event-denominated "
        "(the inter-merge gap IS the tripwire latency budget)"
    )
