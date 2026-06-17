"""Regression fixture — the acceptance bar for impl-audit-code-access.

A reproducible fixture drawn from the **PR-#69 defect class** (a dual-source
wire-contract gap: a producer writes one field name and a consumer reads another,
plus a dedup/cache wedge that hides the drift from the artifact-level read). It is
**mocked at the council layer** — NO network, NO live orchestrator dispatch. The
load-bearing change this design ships is *what input the members see*, so the
fixture pins:

  1. a frozen three-dot ``tp/{slug}...origin/candidate/{slug}/single`` code-input
     pair (refs + touched files) carrying the defect, and
  2. two stubbed member-verdict sets — the **with-code** set (members ran their
     own ``git diff`` / ``git show`` and saw the wire-contract gap) and the
     **artifact-only** set (members read only ``design.md`` + ``plan.md`` and
     never saw the code, so they missed it).

A tiny deterministic synth resolver (``_synthesize``) stands in for the live
synthesizer subagent: it merges the stubbed Round-1 findings exactly as the real
synth prompt instructs and computes the verdict from the confidence mix.

**What is and isn't proven here.** The surfacing/missing of the wire-contract gap
is *hand-baked* into the two stub Round-1 sets, so the verdict-contrast
assertions are **stub-merge demonstrations** of the synth plumbing — they show
that a non-pass stub set merges to needs-work and an all-clean stub set merges to
pass over a fixture shaped like the design's contrast. They are NOT behavioral
proof that members or the synth *detect* the defect. The **load-bearing**
assertions are the prompt-wiring ones: the synth PROMPT is exercised via
``build_synth_prompt`` so the wiring (frozen three-dot refs + touched files reach
the synth on the with-code path, and never leak onto the artifact-only path) is
pinned. See the per-test docstrings, which label each assertion LOAD-BEARING or
DEMONSTRATIVE.
"""
from __future__ import annotations

from build_synth_prompt import build_synth_prompt


# --------------------------------------------------------------------------- #
# Frozen fixture — the PR-#69 defect class, pinned three-dot ref pair.
# --------------------------------------------------------------------------- #
SLUG = "pr69-wire-contract"

# The exact ## Branch hygiene three-dot refs (origin/ prefix on the candidate).
FROZEN_CODE_INPUT = {
    "base": f"tp/{SLUG}",
    "candidate": f"origin/candidate/{SLUG}/single",
    # name-only touched files — a path list, never the diff body.
    "touched_files": [
        "skills/orchestrator/scripts/emit_envelope.py",   # producer side
        "skills/orchestrator/scripts/consume_envelope.py",  # consumer side
        "skills/orchestrator/scripts/dedup_cache.py",       # the wedge
    ],
}

ARTIFACT_PATHS = [
    f"three-pillars-docs/tp-designs/{SLUG}/design.md",
    f"three-pillars-docs/tp-designs/{SLUG}/plan.md",
]

# The defect description, in the words a code-reading member would use.
WIRE_CONTRACT_FINDING = (
    "dual-source wire-contract gap: emit_envelope.py writes `candidate_sha` but "
    "consume_envelope.py reads `sha`; dedup_cache.py serves a stale hit that masks "
    "the drift, so the consumer silently sees None"
)


def _round1_with_code() -> list[dict]:
    """Members who ran their own git diff/git show over the candidate code and
    SAW the wire-contract gap — at least one high-confidence finding naming it."""
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
                    "description": WIRE_CONTRACT_FINDING,
                    "suggested_fix": "align the field name across producer/consumer",
                }
            ],
            "argument_summary": "The code does not honor the envelope wire contract.",
        },
        {
            "schema": "tp-run-full-design/council-round1/v1",
            "member": "council-ada",
            "verdict": "needs-work",
            "confidence": "high",
            "findings": [
                {
                    "confidence": "high",
                    "category": "INCORRECT",
                    "description": "dedup_cache.py wedge hides the wire-contract drift",
                    "suggested_fix": "invalidate the cache key on schema change",
                }
            ],
            "argument_summary": "The dedup cache masks the contract break.",
        },
        {
            "schema": "tp-run-full-design/council-round1/v1",
            "member": "council-feynman",
            "verdict": "pass-with-notes",
            "confidence": "medium",
            "findings": [],
            "argument_summary": "Structurally plausible from the artifacts alone.",
        },
    ]


def _round1_artifact_only() -> list[dict]:
    """Members who read ONLY design.md + plan.md (code_input=None) — the design and
    plan are internally consistent, so they never surface the wire-contract gap."""
    return [
        {
            "schema": "tp-run-full-design/council-round1/v1",
            "member": "council-torvalds",
            "verdict": "pass-with-notes",
            "confidence": "high",
            "findings": [],
            "argument_summary": "Design and plan are internally consistent.",
        },
        {
            "schema": "tp-run-full-design/council-round1/v1",
            "member": "council-ada",
            "verdict": "pass",
            "confidence": "high",
            "findings": [],
            "argument_summary": "The plan covers every design behavior.",
        },
        {
            "schema": "tp-run-full-design/council-round1/v1",
            "member": "council-feynman",
            "verdict": "pass-with-notes",
            "confidence": "high",
            "findings": [
                {
                    "confidence": "high",
                    "category": "STYLE",
                    "description": "a doc cross-reference could be tighter",
                    "suggested_fix": "add a link",
                }
            ],
            "argument_summary": "Minor doc polish only.",
        },
    ]


def _synthesize(round1: list[dict]) -> dict:
    """Deterministic stand-in for the live synthesizer subagent.

    Merges the Round-1 findings and computes the overall verdict from the
    confidence/verdict mix exactly as build_synth_prompt instructs. Verdict
    strings match the real audit-return.v1 schema (lowercase-hyphenated):
      - any needs-work member OR any Medium/Low finding  -> needs-work
      - else findings present (all High)                 -> pass-with-notes
      - else                                             -> pass
    Returns an audit-return-shaped dict {verdict, findings[]}.
    """
    merged_findings: list[dict] = []
    for r in round1:
        merged_findings.extend(r.get("findings", []))

    any_needs_work = any(r.get("verdict") == "needs-work" for r in round1)
    any_med_low = any(
        f.get("confidence") in ("medium", "low") for f in merged_findings
    )

    if any_needs_work or any_med_low:
        verdict = "needs-work"
    elif merged_findings:
        verdict = "pass-with-notes"
    else:
        verdict = "pass"

    return {
        "schema": "tp-run-full-design/audit-return/v1",
        "verdict": verdict,
        "findings": merged_findings,
    }


def _finding_names_wire_contract(audit_return: dict) -> bool:
    return any(
        "wire-contract" in f.get("description", "")
        for f in audit_return.get("findings", [])
    )


# --------------------------------------------------------------------------- #
# Task 3.1 — with-code vs artifact-only contrast.
#
# TWO KINDS OF ASSERTION live in these tests, and the distinction matters:
#
#   * LOAD-BEARING (prompt-wiring): assertions on `build_synth_prompt(...)` output.
#     These prove the real wiring — that the frozen three-dot refs + touched files
#     reach the synth prompt on the with-code path, and that NO code section leaks
#     onto the artifact-only path. A regression here means the plumbing broke.
#
#   * DEMONSTRATIVE (stub-merge): assertions on the `_synthesize(...)` verdict and
#     whether a finding names the wire-contract gap. These are NOT behavioral proof
#     that members/synth *detect* the defect — the surfacing/missing is hand-baked
#     into the `_round1_with_code()` / `_round1_artifact_only()` stub sets and merely
#     passes through the deterministic `_synthesize` resolver. They demonstrate the
#     synth merge plumbing (a non-pass set yields needs-work; an all-clean set yields
#     pass) over a fixture shaped like the design's contrast — nothing more.
# --------------------------------------------------------------------------- #
def test_with_code_synth_merge_yields_needs_work_over_stub_set():
    """LOAD-BEARING: the frozen three-dot refs + touched files reach the synth
    prompt on the with-code (Slot-8) path. DEMONSTRATIVE: feeding the with-code
    STUB Round-1 set (which has the wire-contract finding hand-baked in) through
    `_synthesize` yields a needs-work verdict whose findings name the gap — a
    stub-merge check of the synth plumbing, NOT proof the synth detected anything."""
    # --- LOAD-BEARING: the synth prompt carries the frozen three-dot refs. ---
    prompt = build_synth_prompt(
        ARTIFACT_PATHS,
        _round1_with_code(),
        None,
        "impl-audit",
        code_input=FROZEN_CODE_INPUT,
    )
    # The frozen three-dot pair (origin/ prefix on the candidate) reaches the synth.
    assert f"tp/{SLUG}...origin/candidate/{SLUG}/single" in prompt
    assert f"git show origin/candidate/{SLUG}/single:" in prompt
    for f in FROZEN_CODE_INPUT["touched_files"]:
        assert f in prompt

    # --- DEMONSTRATIVE (stub-merge): the verdict/finding is hand-baked into the
    # stub set and merely passes through _synthesize. NOT behavioral proof. ---
    audit_return = _synthesize(_round1_with_code())
    # Non-pass verdict (schema-conforming lowercase-hyphenated string).
    assert audit_return["verdict"] == "needs-work"
    # The hand-baked finding names the wire-contract gap (stub passthrough).
    assert _finding_names_wire_contract(audit_return), (
        "stub-merge: the with-code STUB set's wire-contract finding must pass "
        "through _synthesize (demonstrative plumbing check, not detection proof)"
    )


def test_artifact_only_synth_merge_yields_pass_over_stub_set():
    """LOAD-BEARING: with code_input=None (the artifact-only Slots 4/6 path) NO
    candidate-code section reaches the synth prompt. DEMONSTRATIVE: feeding the
    artifact-only STUB Round-1 set (which has NO wire-contract finding baked in)
    through `_synthesize` yields pass / pass-with-notes — a stub-merge check of the
    synth plumbing, NOT proof the artifact-only path is incapable of detection."""
    # --- LOAD-BEARING: no candidate-code section leaks onto the artifact path. ---
    prompt = build_synth_prompt(
        ARTIFACT_PATHS,
        _round1_artifact_only(),
        None,
        "impl-audit",
        code_input=None,
    )
    # No Candidate-code section on the artifact-only path.
    assert "## Candidate code under audit" not in prompt
    assert f"origin/candidate/{SLUG}/single" not in prompt

    # --- DEMONSTRATIVE (stub-merge): the artifact-only stub set has no
    # wire-contract finding baked in, so _synthesize passes. NOT proof of a miss. ---
    audit_return = _synthesize(_round1_artifact_only())
    # pass or pass-with-notes — never needs-work (schema-conforming strings).
    assert audit_return["verdict"] in ("pass", "pass-with-notes")
    # No wire-contract finding to surface (stub passthrough, not a real miss).
    assert not _finding_names_wire_contract(audit_return), (
        "stub-merge: the artifact-only STUB set carries no wire-contract finding, "
        "so _synthesize surfaces none (demonstrative plumbing check, not a "
        "behavioral miss proof)"
    )
