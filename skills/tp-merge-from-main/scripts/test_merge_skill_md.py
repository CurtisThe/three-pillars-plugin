"""Invariants for skills/tp-merge-from-main/SKILL.md (the base-sync half).

Enforces:
  - Phase 5 (post-merge-cleanup): step-8 auto-chain to /tp-post-merge.
  - human-approval-merge-gate Task 4.2: frontmatter name is `tp-merge-from-main`
    and the description is the base-sync (merge-driver) one.
  - human-approval-merge-gate Task 4.3: step-7 auto-strip wiring + step-6.7 human
    approval predicate note.

Run with: pytest skills/tp-merge-from-main/scripts/test_merge_skill_md.py -q
"""

from __future__ import annotations

import re
from pathlib import Path

SKILL_MD = Path(__file__).resolve().parents[1] / "SKILL.md"


def _read() -> str:
    return SKILL_MD.read_text()


def test_frontmatter_name_is_tp_merge_from_main() -> None:
    """Task 4.2 — the base-sync skill's frontmatter name is `tp-merge-from-main`
    (the rename target) and its description is the base-sync (merge-driver) one,
    NOT the irreversible land description."""
    text = _read()

    assert re.search(r"^name:\s*tp-merge-from-main\s*$", text, re.MULTILINE), (
        "base-sync SKILL.md frontmatter name must be exactly tp-merge-from-main"
    )
    # The description must read as base-sync (merge a base INTO a branch), not land.
    assert re.search(r"^description:.*(base.sync|base branch into|INTO a design)", text,
                      re.MULTILINE | re.IGNORECASE), (
        "base-sync SKILL.md description must describe the base-into-branch operation"
    )
    # It must NOT claim to run the irreversible gh pr merge land.
    assert "gh pr merge" not in re.search(r"^description:.*$", text, re.MULTILINE).group(0), (
        "base-sync description must not be the land (gh pr merge) description"
    )


def test_step_7_auto_strip() -> None:
    """Task 4.3 — the push step (step 7, 'push only when green') must document
    calling auto_strip_hook.run(pr_url, new_head_oid) AFTER the push lands, and it
    must be fail-open."""
    text = _read()

    assert "auto_strip_hook.run" in text, (
        "step 7 must document calling auto_strip_hook.run(pr_url, new_head_oid)"
    )
    assert re.search(r"after the push|push lands|after.*push", text, re.IGNORECASE), (
        "auto-strip must run AFTER the push lands"
    )
    assert re.search(r"fail.open|never block|swallow", text, re.IGNORECASE), (
        "step 7 auto-strip must be fail-open (never blocks a push)"
    )
    # It must reference the hook's home under tp-merge-from-main/scripts.
    assert "skills/tp-merge-from-main/scripts/auto_strip_hook.py" in text, (
        "step 7 must reference the hook at its tp-merge-from-main home"
    )


def test_step_6_7_enforces_human_approval() -> None:
    """Task 4.3 — the mandatory blocking pre-merge gate step (6.7) prose must note
    it now also enforces the human-approval predicate transparently via evaluate_gate."""
    text = _read()

    assert re.search(r"human.approved|human approval|pred_human_approved|tp:human-approved",
                     text, re.IGNORECASE), (
        "step 6.7 must mention the human-approval predicate (pred_human_approved)"
    )
    # It must reference the howto guide.
    assert "skills/_shared/human-approval-howto.md" in text, (
        "step 6.7 must reference the human-approval howto guide"
    )


def test_step_6_6_readiness_warning() -> None:
    """Phase 3.2 — tp-merge must have a step 6.6 calling merge_gate.merge_readiness_warning,
    printing the warning when non-None and PROCEEDING regardless (warn-never-block),
    slotted beside the step-6.5 detect_unarchived precedent."""
    text = _read()

    # Step 6.6 must be present
    assert re.search(r"^6\.6\.", text, re.MULTILINE), (
        "tp-merge SKILL.md must have a step 6.6 (readiness advisory check)"
    )

    # Must call merge_readiness_warning
    assert "merge_readiness_warning" in text, (
        "step 6.6 must call merge_gate.merge_readiness_warning(pr_url)"
    )

    # Must print the warning when non-None
    assert re.search(r"warn|print|warning", text, re.IGNORECASE), (
        "step 6.6 must print the warning when non-None"
    )

    # Must proceed regardless (warn-never-block)
    assert re.search(r"never.block|warn.*proceed|proceed.*warn|warn.never", text, re.IGNORECASE), (
        "step 6.6 must proceed regardless (warn-never-block, not a gate)"
    )


def test_step_8_post_merge_chain_present() -> None:
    """Phase 5 Task 5.1 — tp-merge must have a step 8 that auto-chains /tp-post-merge.

    After a successful merge of a completion PR (archive present on base),
    step 8 must:
      - auto-chain /tp-post-merge {design-name}
      - be fail-open (teardown error never undoes the merge)
      - be skipped under --dry-run / --no-push
    """
    text = _read()

    # Step 8 must be present (after step 7)
    assert re.search(r"^8\.", text, re.MULTILINE), (
        "tp-merge SKILL.md must have a step 8 (auto-chain to /tp-post-merge)"
    )

    # Must reference /tp-post-merge
    assert re.search(r"/tp-post-merge|tp-post-merge", text), (
        "tp-merge SKILL.md step 8 must reference /tp-post-merge"
    )

    # Must be fail-open
    assert re.search(r"fail.open|teardown error.*never|never.*undo.*merge", text, re.IGNORECASE), (
        "tp-merge SKILL.md step 8 must be fail-open (teardown error never undoes the merge)"
    )

    # Must be skipped under --dry-run or --no-push
    assert re.search(r"dry.run.*skip|no.push.*skip|skip.*dry.run|skip.*no.push", text, re.IGNORECASE), (
        "tp-merge SKILL.md step 8 must be skipped under --dry-run / --no-push"
    )

    # Must guard on completion PR (verify_merged or archive-on-base)
    assert re.search(r"verify_merged|completion.PR|archive.*base|completion.*merge", text, re.IGNORECASE), (
        "tp-merge SKILL.md step 8 must guard on a completion PR (verify_merged.py or archive check)"
    )


def test_blocking_gate_step_documented() -> None:
    """Task 5.2 — tp-merge SKILL.md must document the mandatory blocking pre-merge gate step.

    Asserts:
    (a) A mandatory blocking pre-merge gate step that invokes gate_cli.py /
        merge_gate_blocking and refuses to merge on non-zero exit.
    (b) The honest note that a GitHub-UI merge done outside the tooling bypasses
        the gate, with branch-protection deferred to self-hosted-ci-runner.
    (c) The UNVERIFIED label language (never "safe to merge").
    """
    text = _read()

    # (a) Mandatory blocking pre-merge step must be present
    # Must reference gate_cli.py or merge_gate_blocking
    assert re.search(r"gate_cli\.py|merge_gate_blocking", text), (
        "SKILL.md must document the mandatory blocking pre-merge gate step "
        "invoking gate_cli.py or merge_gate_blocking"
    )

    # Must indicate it is mandatory / blocking (refuses on non-zero exit)
    assert re.search(
        r"mandatory|must.*exit.*0|exit.*0.*required|refuse.*merge|non.zero.*exit|blocking.*gate|gate.*blocking",
        text, re.IGNORECASE
    ), (
        "SKILL.md mandatory pre-merge gate step must indicate it refuses to merge on non-zero exit"
    )

    # (b) Honest GitHub-UI bypass note
    # Must mention that GitHub-UI merge bypasses the gate
    assert re.search(
        r"GitHub.UI.*bypass|bypass.*GitHub.UI|UI.*bypass|outside.*tooling.*bypass|bypass.*outside.*tooling",
        text, re.IGNORECASE
    ), (
        "SKILL.md must document the honest GitHub-UI bypass note: "
        "a UI merge outside the tooling bypasses the gate"
    )

    # Must reference branch-protection backstop deferred to self-hosted-ci-runner
    assert re.search(
        r"self.hosted.ci.runner|branch.protection.*deferred|deferred.*branch.protection",
        text, re.IGNORECASE
    ), (
        "SKILL.md must note that branch-protection backstop is deferred to self-hosted-ci-runner"
    )

    # (c) UNVERIFIED label language must appear (never "safe to merge")
    assert re.search(r"UNVERIFIED", text), (
        "SKILL.md must use UNVERIFIED label language (from GATE_LABEL)"
    )

    # Must NOT say "safe to merge" (the design's explicit prohibition)
    assert "safe to merge" not in text.lower(), (
        "SKILL.md must NEVER say 'safe to merge' — use UNVERIFIED label language"
    )
