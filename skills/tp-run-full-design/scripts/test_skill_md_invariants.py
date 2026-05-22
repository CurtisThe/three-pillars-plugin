"""Grep-level lint tests over skills/tp-run-full-design/SKILL.md.

These assert that load-bearing literal phrases survive future edits. They
are not a substitute for end-to-end behavior tests (see detailed-design
§Test Strategy "Phase 4 known limitation") — that coverage comes from
dogfood orchestrator runs. But they catch silent prose drift on the
phrases the orchestrator's runtime interpretation depends on.
"""
from __future__ import annotations

import re
from pathlib import Path


SKILL_MD = Path(__file__).resolve().parent.parent / "SKILL.md"


def _body() -> str:
    return SKILL_MD.read_text()


def test_mode_c_documented():
    body = _body()

    # (a) Arguments section lists --skip-design as the Mode B opt-out.
    # Pin the assertion to the arguments block to avoid false positives if
    # the flag is also discussed elsewhere.
    args_section = body.split("## Prerequisites", 1)[0]
    assert "--skip-design" in args_section, (
        "## Arguments must list --skip-design (Mode B opt-out)"
    )

    # (b) Mode C label and confirmation prompt appear verbatim.
    assert "Mode C" in body, "Mode C label must appear"
    assert "Go autonomous from here?" in body, (
        "Mode C blocking yes/no prompt phrase must appear verbatim"
    )

    # (c) No-flag no-design.md default routes through /tp-design first.
    assert "/tp-design {slug}" in body, (
        "Mode C default must invoke /tp-design {slug} first"
    )

    # (d) M2 — Tier 1.5 documents the no-autonomous-run terminal state.
    assert "[tp-run-full-design/tier-1] no-autonomous-run" in body, (
        "Mode C decline must carry the decisions-log token"
    )
    # The no-branch terminal sentence references lock-owner restoration.
    assert "lock owner restored to the invoking human" in body, (
        "Mode C decline must restore the lock to the invoking human"
    )

    # (e) M3 — re-enter /tp-design on existing design.md (OQ4).
    assert "re-enter /tp-design" in body, (
        "Mode C against existing design.md must re-enter /tp-design (OQ4)"
    )
    # Mode A documentation must remain unchanged in shape.
    assert "Mode A — Pickup skill provided" in body, (
        "Mode A header must remain present (backward-compat)"
    )


def test_pr_template_about_this_diff():
    body = _body()

    # (1) The "About this diff" header and fork-point paragraph appear.
    assert "About this diff" in body, (
        "Tier 6 PR description must include the 'About this diff' header"
    )
    # The paragraph must explain that the candidate was forked from tp/{slug}
    # HEAD before design-side artifacts were written. Pin a phrase that
    # captures that semantics.
    assert "forked from `tp/{slug}` HEAD" in body, (
        "About this diff must explain fork-point semantics"
    )

    # (2) C2 — git merge-tree --name-only invocation present in Tier 6 — Step 2
    # prose.
    assert "git merge-tree --name-only" in body, (
        "Tier 6 must reference git merge-tree --name-only (merge-preview hook)"
    )


def test_artifact_policy_documented():
    body = _body()
    # Both new literal phrases must appear.
    assert "do not write under /tmp" in body, (
        "Artifact policy must state 'do not write under /tmp'"
    )
    assert "three-pillars-docs/tp-designs/{slug}/demos/" in body, (
        "Artifact policy must reference the per-design demos/ path"
    )
    # The existing 'do not write under candidates/' rule must remain adjacent.
    assert "do not write under" in body and "candidates/" in body, (
        "Existing candidates/ rule must remain present"
    )


def test_tier_3_5_uses_wrapper():
    body = _body()

    # (1) Tier 3.5 section invokes the wrapper subprocess via python3
    # (matching the repo convention used by tp-design, tp-spike-auto,
    # tp-migrate — avoids Python 2 ambiguity).
    assert "python3 skills/tp-run-full-design/scripts/run_tier_3_5.py" in body, (
        "Tier 3.5 must invoke the wrapper subprocess literally with python3"
    )
    # The legacy inline sys.path.insert(0, str(SCRIPTS_DIR)) Python block is
    # gone — the wrapper owns the helper composition now.
    assert "sys.path.insert(0, str(SCRIPTS_DIR))" not in body, (
        "The inline sys.path.insert Python pseudocode block must be removed; "
        "the wrapper owns helper composition now."
    )

    # (2) No `case (d)` substring survives anywhere in the SKILL.md.
    # Use the parenthesis-anchored regex from plan §Task 3.4.
    case_d_pattern = re.compile(r"case \(d\)")
    matches = case_d_pattern.findall(body)
    assert not matches, (
        f"All `case (d)` references must be removed (there is no case (d)); "
        f"found {len(matches)} occurrence(s)"
    )
