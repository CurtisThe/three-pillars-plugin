"""Grep-level lint tests over skills/tp-promote/SKILL.md.

These assert that load-bearing literal phrases in the prose skill survive
future edits. They are not a substitute for behavioral tests — they catch
silent prose drift on the contract the `/tp-promote` flow depends on.

`/tp-promote` is a prose skill (interactive — deliberately no --auto mode)
that turns a rich seed into a committed, floor-clearing design.md on the
tp/<slug> branch before a design-ready fleet pass. The SKILL.md is the only
place the nine-step flow, the single-batched-confirm human gate, the
floor-validator invocation, and the --skip-design handoff are written down.
This suite pins each of those so a careless edit can't quietly drop one.

Mirrors the fleet SKILL.md lint test pattern.
"""
from __future__ import annotations

import re
from pathlib import Path


SKILL_MD = Path(__file__).resolve().parent.parent / "SKILL.md"


def _body() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def test_promote_skill_prose():
    """The /tp-promote SKILL.md must exist with frontmatter and document the
    full 9-step promote flow, plus every load-bearing anchor the downstream
    pipeline depends on.

    One consolidated test so a missing/empty SKILL.md fails red on the first
    assertion (mirrors test_fleet_skill_prose structure).
    """
    assert SKILL_MD.exists(), "skills/tp-promote/SKILL.md must exist"
    body = _body()
    assert body.strip(), "skills/tp-promote/SKILL.md must not be empty"

    # --- Frontmatter: name + description ---
    assert "name: tp-promote" in body, (
        "SKILL.md frontmatter must declare `name: tp-promote`"
    )
    assert "description:" in body, (
        "SKILL.md frontmatter must include a `description`"
    )

    # --- Invariant 24 negative: --auto must NOT appear in argument-hint ---
    # tp-promote is deliberately non-auto; having --auto in argument-hint would
    # trip framework-check invariant 24 (requires auto-mode.md ref) and violate
    # the design decision to keep the human confirm gate intact.
    arg_hint_match = re.search(r'^argument-hint:.*$', body, re.MULTILINE)
    if arg_hint_match:
        assert "--auto" not in arg_hint_match.group(0), (
            "SKILL.md argument-hint must NOT contain --auto "
            "(tp-promote has no autonomous mode — invariant 24)"
        )

    # --- First-run preflight invocation (framework-check invariant 14) ---
    # Canonical form: a numbered-step line `N. **Run first-run preflight** per`
    assert "**Run first-run preflight** per" in body, (
        "SKILL.md must invoke the first-run preflight via the canonical "
        "'**Run first-run preflight** per skills/_shared/first-run.md' step"
    )
    assert "skills/_shared/first-run.md" in body, (
        "SKILL.md first-run preflight step must reference skills/_shared/first-run.md"
    )

    # --- Design-name validation (framework-check invariant 2) ---
    assert "validate-name" in body or "a-z0-9-" in body, (
        "SKILL.md must reference design-name validation (validate-name.md or "
        "the a-z0-9- pattern)"
    )

    # --- Floor-validator invocation with tp-designs path ---
    # The literal script name + the three-pillars-docs/tp-designs/<slug> argument
    # pattern must both appear so the operator knows what to run.
    assert "validate_design_floor.py" in body, (
        "SKILL.md must reference validate_design_floor.py (the floor-validator "
        "invocation that gates the commit)"
    )
    assert "three-pillars-docs/tp-designs/" in body, (
        "SKILL.md must show the three-pillars-docs/tp-designs/<slug> argument "
        "to the floor-validator invocation"
    )

    # --- Single-batched-confirm / one-human-touch phrasing ---
    # The design mandates exactly ONE human interaction: a single block of
    # confirm prompts derived from the seed's Open questions.
    body_lower = body.lower()
    assert "batched confirm" in body_lower or "batched-confirm" in body_lower, (
        "SKILL.md must describe the 'batched confirm' mechanism "
        "(the single block of prompts the operator answers once)"
    )
    assert (
        "one human" in body_lower
        or "single" in body_lower
    ), (
        "SKILL.md must assert the one-human-touch / single confirm constraint "
        "(e.g. 'one human touch' or 'single batched confirm')"
    )

    # --- --skip-design handoff phrase ---
    # After committing design.md the skill hands off to Mode B.
    assert "/tp-run-full-design" in body, (
        "SKILL.md must reference /tp-run-full-design for the Mode B handoff"
    )
    assert "--skip-design" in body, (
        "SKILL.md must include the --skip-design flag in the handoff step "
        "('/tp-run-full-design <slug> --skip-design')"
    )


def test_weight_class_carry():
    """design-depth-axis Task 2.3 — seed-class carry into the promoted design."""
    body = _body()
    # Read the class from seed frontmatter.
    assert "weight-class" in body, (
        "SKILL.md must instruct reading `weight-class` from seed.md frontmatter"
    )
    assert "frontmatter" in body.lower()
    # If absent, fold ONE class question (rubric-assisted) into the batched confirm.
    assert "batched confirm" in body.lower()
    assert "rubric" in body.lower() or "recommend" in body.lower(), (
        "the folded class question must be rubric-assisted "
        "(weight_class.py recommend / weight-class.md rubric)"
    )
    assert "weight_class.py" in body or "weight-class.md" in body
    # Stamp the drafted design.md with the class.
    assert "stamp" in body.lower(), (
        "SKILL.md must instruct stamping the drafted design.md with the class"
    )
