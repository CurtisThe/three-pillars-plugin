"""Unit tests for build_synth_prompt — the pure synthesizer-prompt assembler.

The synthesizer subagent prompt embeds artifact PATHS (never inlined
contents — the subagent reads them), every Round-1 verdict dict (verdict +
findings + per-finding confidence + argument_summary) and every Round-2
rebuttal dict (including challenged_finding_indices, F4). No I/O, no dispatch.
"""

import pytest

from build_synth_prompt import build_synth_prompt


SENTINEL_CONTENT = "THIS_IS_FILE_CONTENT_THAT_MUST_NOT_BE_INLINED"


def _round1() -> list[dict]:
    return [
        {
            "schema": "tp-run-full-design/council-round1/v1",
            "member": "council-torvalds",
            "verdict": "needs-work",
            "confidence": "high",
            "findings": [
                {
                    "confidence": "high",
                    "category": "INCONSISTENT",
                    "description": "task 2 field drifts",
                    "suggested_fix": "rename field",
                }
            ],
            "argument_summary": "Task 2 drifts from the design.",
        },
        {
            "schema": "tp-run-full-design/council-round1/v1",
            "member": "council-ada",
            "verdict": "pass-with-notes",
            "confidence": "medium",
            "findings": [],
            "argument_summary": "Formally sound.",
        },
    ]


def _round2() -> list[dict]:
    return [
        {
            "schema": "tp-run-full-design/council-round2/v1",
            "member": "council-torvalds",
            "position_held": "held",
            "counter_argument": "I uphold my finding 0.",
            "challenged_finding_indices": [0],
        },
        {
            "schema": "tp-run-full-design/council-round2/v1",
            "member": "council-ada",
            "position_held": "revised",
            "counter_argument": "I now agree with torvalds.",
        },
    ]


# --------------------------------------------------------------------------- #
# Task 2.1 — happy path, path-not-content, challenged indices
# --------------------------------------------------------------------------- #
def test_happy_path_embeds_all():
    paths = ["three-pillars-docs/tp-designs/x/design.md", "three-pillars-docs/tp-designs/x/plan.md"]
    prompt = build_synth_prompt(paths, _round1(), _round2(), "design-audit")
    for p in paths:
        assert p in prompt
    # Round-1 content: verdicts, members, per-finding confidence, argument_summary.
    assert "council-torvalds" in prompt
    assert "council-ada" in prompt
    assert "needs-work" in prompt
    assert "task 2 field drifts" in prompt
    assert "Task 2 drifts from the design." in prompt
    # Round-2 content.
    assert "I uphold my finding 0." in prompt
    # Slot named.
    assert "design-audit" in prompt


def test_embeds_paths_not_contents():
    paths = ["three-pillars-docs/tp-designs/x/design.md"]
    prompt = build_synth_prompt(paths, _round1(), _round2(), "plan-audit")
    assert paths[0] in prompt
    # The function does no file I/O; a sentinel content string is never present.
    assert SENTINEL_CONTENT not in prompt


def test_challenged_indices_embedded():
    # PA4 — challenged_finding_indices carried forward verbatim.
    r2 = _round2()
    r2[0]["challenged_finding_indices"] = [0, 2]
    prompt = build_synth_prompt(["a/design.md"], _round1(), r2, "design-audit")
    assert "challenged_finding_indices" in prompt
    assert "0" in prompt and "2" in prompt
    # The serialized list form appears verbatim.
    assert "[0, 2]" in prompt or "[0,2]" in prompt


# --------------------------------------------------------------------------- #
# Task 2.2 — fast-audit branch (round2=None)
# --------------------------------------------------------------------------- #
def test_round2_none_omits_round2_section():
    prompt = build_synth_prompt(["a/design.md"], _round1(), None, "design-audit")
    # Round-1 + paths still present.
    assert "a/design.md" in prompt
    assert "council-torvalds" in prompt
    assert "Task 2 drifts from the design." in prompt
    # No Round-2 section / content.
    assert "I uphold my finding 0." not in prompt
    assert "position_held" not in prompt


# --------------------------------------------------------------------------- #
# Task 2.3 — validation guards
# --------------------------------------------------------------------------- #
def test_empty_round1_raises():
    with pytest.raises(ValueError):
        build_synth_prompt(["a/design.md"], [], None, "design-audit")


def test_member_mismatch_raises():
    r1 = _round1()
    r2 = _round2()
    r2[1]["member"] = "council-feynman"  # ada -> feynman: member sets diverge
    with pytest.raises(ValueError):
        build_synth_prompt(["a/design.md"], r1, r2, "design-audit")
