#!/usr/bin/env python3
"""Grep-level test that SKILL.md documents the Round-2 short-circuit step."""

from pathlib import Path


SKILL_MD = Path(__file__).resolve().parent.parent / "SKILL.md"


def test_skill_md_has_step_3_5():
    body = SKILL_MD.read_text()

    # (1) The Step 3.5 heading appears verbatim.
    expected_heading = "### Step 3.5: Round-2 short-circuit (`--auto` only)"
    assert expected_heading in body, (
        f"SKILL.md must contain heading: {expected_heading!r}"
    )

    # (2) The section references the helper module and the decisions-log token.
    assert "round2_short_circuit.should_short_circuit" in body, (
        "SKILL.md must reference the helper function"
    )
    assert "round-2-short-circuit-unanimous" in body, (
        "SKILL.md must reference the decisions-log token"
    )

    # (3) Interactive-mode negative path — the verbatim sentence asserting
    # interactive runs always walk through Round 2.
    assert "interactive mode always runs Round 2" in body, (
        "SKILL.md must include the literal sentence "
        "'interactive mode always runs Round 2'"
    )


if __name__ == "__main__":
    test_skill_md_has_step_3_5()
    print("ALL PASSED")
