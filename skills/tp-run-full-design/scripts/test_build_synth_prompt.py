"""Unit tests for build_synth_prompt — the pure synthesizer-prompt assembler.

The synthesizer subagent prompt embeds artifact PATHS (never inlined
contents — the subagent reads them), every Round-1 verdict dict (verdict +
findings + per-finding confidence + argument_summary) and every Round-2
rebuttal dict (including challenged_finding_indices, F4). No I/O, no dispatch.
"""

import json
import re
from pathlib import Path

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


@pytest.mark.parametrize("slot", ["design-audit", "plan-audit"])
def test_map_check_slots_require_the_category_tag(slot):
    from build_synth_prompt import MAP_CHECK_CATEGORY
    out = build_synth_prompt(["a/design.md"], [{"member": "ada", "findings": []}], None, slot)
    assert f'`category: "{MAP_CHECK_CATEGORY}"`' in out
    assert "straight to the operator" in out


def test_impl_audit_has_no_map_check_tag():
    out = build_synth_prompt(["a/design.md"], [{"member": "ada", "findings": []}], None, "impl-audit")
    assert "map-check" not in out


SCHEMA = Path(__file__).resolve().parent.parent / "schemas" / "audit-return.v1.json"


def schema_claim_keys() -> set[str]:
    """Every key a guard claim may carry, read from the audit-return envelope schema."""
    doc = json.loads(SCHEMA.read_text(encoding="utf-8"))
    return set(doc["properties"]["guard_claims"]["items"]["properties"])


def brief_claim_keys(out: str) -> set[str]:
    """The keys of the claim shape the brief gives right after `guard_claims[]`: the first
    backticked `{...}` there, split on commas (order and spacing are free)."""
    after = out[out.index("`guard_claims[]`"):]
    shape = re.search(r"`\{([^`}]*)\}`", after)
    assert shape, "the brief gives no `{...}` claim shape after `guard_claims[]`"
    return {key.strip() for key in shape.group(1).split(",")}


@pytest.mark.parametrize("slot", ["design-audit", "impl-audit"])
def test_guard_claims_brief(slot):
    # audit-pass-does-not-bind 7.3: Slots 4/8 return claims only; the certifier authors RED/GREEN.
    from build_synth_prompt import GUARD_CLAIM_SLOTS
    assert slot in GUARD_CLAIM_SLOTS
    out = build_synth_prompt(["a/design.md"], [{"member": "ada", "findings": []}], None, slot)
    # The claim shape asks for every key the envelope schema declares (a claim without
    # `subjects` certifies nothing), and no other.
    assert brief_claim_keys(out) == schema_claim_keys()
    # Contract tokens the envelope schema and the Step 2b fold read, never prose (their
    # code-span quoting is formatting, so it is not pinned).
    for needle in ("guard_claims[]", "guards_certified", "No guard claims.", "[cert:<id>]"):
        assert needle in out, needle


def test_the_brief_claim_shape_tracks_the_schema():
    """The brief's claim shape is read as a key set (order and spacing free) and equals the
    schema's; a key dropped from the brief's source is caught by that same key-set check."""
    import build_synth_prompt as bsp
    args = (["a/design.md"], [{"member": "ada", "findings": []}], None, "impl-audit")
    assert brief_claim_keys(bsp.build_synth_prompt(*args)) == schema_claim_keys()
    for key in schema_claim_keys():
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(bsp, "GUARD_CLAIM_KEYS",
                          tuple(k for k in bsp.GUARD_CLAIM_KEYS if k != key))
            assert brief_claim_keys(bsp.build_synth_prompt(*args)) == schema_claim_keys() - {key}


def test_cert_phrase_examples_in_the_brief_are_what_the_fold_counts():
    """Every certifying-phrase example the brief warns about is an unmatched scan hit when
    untagged, and a `[cert:<id>]` tag alone (no guard path) certifies it [R8][R9]."""
    from build_synth_prompt import CERT_PHRASE_EXAMPLES
    from skills._shared import cert_phrase_scan as scan

    out = build_synth_prompt(["a/design.md"], [{"member": "ada", "findings": []}], None,
                             "impl-audit")
    claims = [{"id": "c1", "guard": "skills/x/test_y.py::test_z"}]
    for example in CERT_PHRASE_EXAMPLES:
        assert example in out, example
        hits = scan.scan_field(f"Note: {example}.", "summary", claims)
        assert hits and not any(h["matched"] for h in hits), example
        tagged = scan.scan_field(f"Note: {example} [cert:c1].", "summary", claims)
        assert tagged and all(h["matched"] for h in tagged), example


def test_plan_audit_has_no_guard_claims_brief():
    out = build_synth_prompt(["a/plan.md"], [{"member": "ada", "findings": []}], None, "plan-audit")
    assert "guard_claims" not in out
