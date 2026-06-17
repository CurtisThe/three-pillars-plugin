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


# --------------------------------------------------------------------------- #
# Phase 1 — Slot-8-only code_input seam (impl-audit code-access)
# --------------------------------------------------------------------------- #
def _code_input(touched_files=None) -> dict:
    """A Slot-8 code_input — three-dot refs (origin/ prefix on candidate) +
    the touched-files name-only list. Refs only; NEVER the diff body."""
    return {
        "base": "tp/x",
        "candidate": "origin/candidate/x/single",
        "touched_files": ["a.py", "b.md"] if touched_files is None else touched_files,
    }


def test_code_input_embeds_refs_and_files():
    # Task 1.1 — with code_input + slot=impl-audit, the prompt names both refs,
    # every touched path, the heading, and the three-dot self-read instruction.
    paths = [
        "three-pillars-docs/tp-designs/x/design.md",
        "three-pillars-docs/tp-designs/x/plan.md",
    ]
    prompt = build_synth_prompt(
        paths, _round1(), _round2(), "impl-audit", code_input=_code_input()
    )
    # Both refs present (candidate carries the origin/ prefix).
    assert "tp/x" in prompt
    assert "origin/candidate/x/single" in prompt
    # Every touched path present.
    assert "a.py" in prompt
    assert "b.md" in prompt
    # The Candidate-code heading.
    assert "## Candidate code under audit" in prompt
    # The three-dot self-read instruction naming both git verbs.
    assert "git diff tp/x...origin/candidate/x/single" in prompt
    assert "git show origin/candidate/x/single:" in prompt
    # The literal three-dot form.
    assert "..." in prompt
    # The no-inline contract for code.
    assert "do NOT expect the diff inlined" in prompt


def test_code_input_embeds_paths_not_contents():
    # Task 1.2 — the no-inline contract extends to code: a fake diff body never
    # appears (the function does no I/O, so it can only appear if code inlines it).
    paths = ["three-pillars-docs/tp-designs/x/design.md"]
    ci = _code_input()
    # If a future edit mistakenly inlined a diff body, SENTINEL_CONTENT would leak.
    ci_with_sentinel = dict(ci)
    ci_with_sentinel["diff_body_DO_NOT_INLINE"] = SENTINEL_CONTENT
    prompt = build_synth_prompt(paths, _round1(), _round2(), "impl-audit", code_input=ci)
    assert SENTINEL_CONTENT not in prompt
    # Even if a body sneaks into the dict, the assembler must not emit it.
    prompt2 = build_synth_prompt(
        paths, _round1(), _round2(), "impl-audit", code_input=ci_with_sentinel
    )
    assert SENTINEL_CONTENT not in prompt2
    # Key-name-agnostic leanness guard: the original sentinel sat under a key the
    # assembler never reads (diff_body_DO_NOT_INLINE), so the guard could pass
    # trivially. Repeat the check under `diff_body` — a conventionally-named key a
    # future edit might actually read and inline — so the guard catches a realistic
    # future regression, not just an obviously-ignored one.
    ci_realistic = {
        "base": "tp/x",
        "candidate": "origin/candidate/x/single",
        "touched_files": [],
        "diff_body": SENTINEL_CONTENT,
    }
    prompt3 = build_synth_prompt(
        paths, _round1(), _round2(), "impl-audit", code_input=ci_realistic
    )
    assert SENTINEL_CONTENT not in prompt3


def test_code_input_none_is_back_compat():
    # Task 1.3 — code_input=None (Slots 4/6) is byte-identical to the old arity.
    paths = ["three-pillars-docs/tp-designs/x/design.md", "x/plan.md"]
    old_arity = build_synth_prompt(paths, _round1(), _round2(), "design-audit")
    explicit_none = build_synth_prompt(
        paths, _round1(), _round2(), "design-audit", code_input=None
    )
    assert old_arity == explicit_none
    # No Candidate-code section on the None path.
    assert "## Candidate code under audit" not in old_arity
    # Existing happy-path expectations still hold.
    for p in paths:
        assert p in old_arity
    assert "council-torvalds" in old_arity
    assert "council-ada" in old_arity


def test_code_input_empty_touched_files():
    # Task 1.4 — empty touched_files ⇒ refs + empty-diff note, no crash.
    paths = ["x/design.md", "x/plan.md"]
    prompt = build_synth_prompt(
        paths,
        _round1(),
        _round2(),
        "impl-audit",
        code_input=_code_input(touched_files=[]),
    )
    # Both refs still present.
    assert "tp/x" in prompt
    assert "origin/candidate/x/single" in prompt
    # An empty-diff note is emitted (empty candidate diff is an audit signal).
    assert "empty" in prompt.lower()
    # Still has the Candidate-code heading; no exception was raised reaching here.
    assert "## Candidate code under audit" in prompt
