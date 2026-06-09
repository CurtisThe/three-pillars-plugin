"""Grep + ast invariants for `/tp-pr-iterate` SKILL.md.

Five tests:
- four grep substrings (`Agent(`, `claude-sonnet-4-6`, `classifier-flip`, `--dry-run`)
- one ast walk asserting `classifier_judge.py` does not `import anthropic`
  nor `from anthropic …` — the C1 constraint that helpers compute/parse
  and prose orchestrates.

Run with: pytest skills/tp-pr-iterate/scripts/test_pr_iterate_skill_md.py -q
"""

from __future__ import annotations

import ast
from pathlib import Path

SKILL_MD = Path(__file__).parent.parent / "SKILL.md"
# C1 architectural constraint applies to every model-adjacent helper: the model
# invocation lives in SKILL.md prose via Agent(); helpers compute/parse/gate only.
# review_merge.py + thread_resolver.py joined the family with Enhancement 1.
C1_HELPERS = [
    Path(__file__).parent / "classifier_judge.py",
    Path(__file__).parent / "review_merge.py",
    Path(__file__).parent.parent.parent / "_shared" / "thread_resolver.py",
    # Phase 4 (pr-iterate-codereview-real-harness): run_round.py is the B1 CLI
    # wrapper — C1-clean (no anthropic, no claude subprocess; fan-out is caller-driven).
    Path(__file__).parent / "run_round.py",
]


def _read_skill() -> str:
    return SKILL_MD.read_text()


def test_agent_call_documented_for_sonnet_judge() -> None:
    assert "Agent(" in _read_skill(), "Agent() invocation for the Sonnet judge must be documented"


def test_judge_model_named_sonnet_4_6() -> None:
    assert "claude-sonnet-4-6" in _read_skill(), "model `claude-sonnet-4-6` must be named"


def test_classifier_flip_termination_explained() -> None:
    assert "classifier-flip" in _read_skill().lower(), "classifier-flip termination must be explained"


def test_dry_run_flag_documented() -> None:
    assert "--dry-run" in _read_skill(), "`--dry-run` flag must be documented"


def _assert_no_anthropic(py: Path) -> None:
    tree = ast.parse(py.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "anthropic" not in alias.name.lower(), (
                    f"{py.name} imports {alias.name!r} — violates C1"
                )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert "anthropic" not in module.lower(), (
                f"{py.name} does `from {module} import …` — violates C1"
            )


def _assert_no_claude_subprocess(py: Path) -> None:
    """No `subprocess.run(["claude", ...])` CALL — the model is invoked from
    SKILL prose via Agent(), never shelled out to from a helper. AST-based so a
    docstring that merely *names* the forbidden pattern is not a false positive.
    """
    tree = ast.parse(py.read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for arg in node.args:
            if isinstance(arg, (ast.List, ast.Tuple)) and arg.elts:
                first = arg.elts[0]
                if isinstance(first, ast.Constant) and first.value == "claude":
                    raise AssertionError(
                        f"{py.name} invokes a `claude` subprocess — violates C1"
                    )


def test_no_anthropic_import_in_c1_helpers() -> None:
    """C1 architectural constraint over every model-adjacent helper.

    The Sonnet judge call and the /code-review dispatch happen in SKILL.md
    prose via `Agent()`. Helpers (classifier_judge, review_merge,
    thread_resolver) own prompt construction + response parsing + plumbing
    only — no `import anthropic`, no `subprocess.run(["claude", …])`.
    """
    for py in C1_HELPERS:
        _assert_no_anthropic(py)
        _assert_no_claude_subprocess(py)


# ---------- Enhancement 1: dual-source loop prose ----------


def test_code_review_dispatch_documented() -> None:
    body = _read_skill()
    assert "/code-review" in body, "the local /code-review dispatch must be documented"
    assert "subagent_type" in body, "the dispatch must use Agent(subagent_type=...)"
    assert "∥" in body or "concurrent" in body.lower(), (
        "the /code-review dispatch must run concurrently with the Copilot poll"
    )
    assert "--effort" in body, "the /code-review effort flag must be documented"


def test_normalize_and_dedupe_referenced() -> None:
    body = _read_skill().lower()
    assert "normalize" in body and "dedupe" in body, (
        "both review sources must be normalized + deduped (review_merge)"
    )


def test_reply_precedes_resolve() -> None:
    body = _read_skill()
    assert "resolveReviewThread" in body, "thread resolution via GraphQL resolveReviewThread"
    # reply-before-resolve: a reply literal must appear before the resolve call.
    reply_idx = body.find("reply_to_thread")
    resolve_idx = body.find("resolve_thread")
    assert reply_idx != -1 and resolve_idx != -1, "both reply and resolve must be documented"
    assert reply_idx < resolve_idx, (
        "reply-and-resolve is reply-BEFORE-resolve: the loop never resolves a "
        "thread without first leaving the evidence reply"
    )


def test_two_stable_termination_documented() -> None:
    body = _read_skill()
    assert "two-stable" in body, "two-stable termination must be documented"
    assert "review-instructions.md" in body, "the shared review-instructions.md must be referenced"


def test_run_round_call_passes_head_ref_and_loop_mode() -> None:
    body = _read_skill()
    assert "head_ref=" in body and "loop_mode=True" in body, (
        "the loop's run_round call must pass head_ref + loop_mode=True (F1 wiring)"
    )


# ---------- Copilot review gotchas (observed 2026-06-04, PRs #45/#46) ----------


def test_copilot_login_per_surface_gotcha_documented() -> None:
    """The login-differs-by-surface gotcha must be documented: a single hard-coded
    Copilot login filter yields a false zero on a successful review."""
    body = _read_skill()
    # the distinct login spellings the loop's REST/GraphQL polls see. Pin the
    # BACKTICKED exact tokens: `copilot-pull-request-reviewer` is a substring of
    # `copilot-pull-request-reviewer[bot]`, so an un-delimited `in` check would
    # pass even if the GraphQL spelling were removed (Copilot review, PR #47).
    # The backticks differ (…reviewer` vs …reviewer[bot]`), so they pin distinctly.
    assert "`copilot-pull-request-reviewer[bot]`" in body, "the REST review-author login must be named"
    assert "`copilot-pull-request-reviewer`" in body, "the GraphQL author login (no [bot]) must be named distinctly"
    assert "false zero" in body.lower() or "matches nothing" in body.lower(), (
        "the false-zero consequence of a wrong per-surface login filter must be documented"
    )


def test_copilot_transient_error_gotcha_documented() -> None:
    """The 'encountered an error' = transient GitHub-side build crash gotcha must be
    documented so the loop never classifies or terminates on it."""
    body = _read_skill()
    assert "encountered an error" in body, "the Copilot error-body string must be named"
    assert "detect-libc" in body, "the observed detect-libc root cause must be named"
    body_lower = body.lower()
    assert "transient" in body_lower and "no signal" in body_lower, (
        "an error-body review must be flagged transient + treated as no signal"
    )


def test_copilot_rerequest_new_sha_gotcha_documented() -> None:
    """The re-request-only-fires-on-a-new-SHA dedupe gotcha must be documented."""
    body = _read_skill()
    body_lower = body.lower()
    assert "dedupe" in body_lower or "deduped" in body_lower, (
        "the unchanged-SHA re-request dedupe behavior must be documented"
    )
    assert "unchanged" in body_lower and "sha" in body_lower, (
        "the re-request gotcha must explain that an unchanged head SHA does not re-fire"
    )


# ---------- Phase 6: run_loop and _request_copilot_review references ----------


def test_terminal_mentions_reviewed_conjunct() -> None:
    """Phase 2.4 — the terminal section must name the third copilot_reviewed_successfully
    conjunct, the tp:ready-for-human-merge readiness signal, and the fail-open behavior."""
    body = _read_skill()

    assert "copilot_reviewed_successfully" in body, (
        "SKILL.md terminal section must name the copilot_reviewed_successfully "
        "third conjunct (pr-readiness-surface)"
    )
    assert "tp:ready-for-human-merge" in body, (
        "SKILL.md terminal section must name the tp:ready-for-human-merge readiness label "
        "applied on convergence"
    )
    # The loop stays fail-open when the predicate is false/unverifiable.
    body_lower = body.lower()
    assert "fail-open" in body_lower or "fail open" in body_lower, (
        "SKILL.md must document that the loop stays fail-open when the readiness "
        "predicate is false/unverifiable"
    )


def test_skill_md_points_loop_body_at_run_loop() -> None:
    """Phase 6, Task 6.1: SKILL.md loop-body section must reference run_loop
    and the per-round Copilot re-request must delegate to _request_copilot_review
    rather than restating raw REST prose as the source of truth."""
    body = _read_skill()
    assert "run_loop" in body, (
        "SKILL.md loop-body section must name run_loop (the assembled driver)"
    )
    assert "_request_copilot_review" in body, (
        "SKILL.md must reference _request_copilot_review for the per-round Copilot re-request"
    )
    assert "awaiting-copilot" in body, (
        "SKILL.md must note the awaiting-copilot phase around the CI/Copilot wait"
    )


def test_code_review_comment_post_is_mandatory() -> None:
    """Every /code-review invocation must post a summary comment (no silent reviews).
    The SKILL step 2.5 must mandate review_merge.post_codereview_comment."""
    body = _read_skill()
    assert "post_codereview_comment" in body, (
        "step 2.5 must call review_merge.post_codereview_comment after the /code-review parse"
    )
    assert "mandatory" in body.lower() and "silent" in body.lower(), (
        "the SKILL must state the review-summary comment is mandatory and that there are no "
        "silent reviews"
    )


def test_code_review_is_multi_angle_and_fail_closed_parse() -> None:
    """Step 2.5 must fan out MULTIPLE review angles (not a single /code-review subagent,
    which can't fan out under L23) and parse fail-closed (unparseable != clean). Locked
    tightly enough that a rewrite back to a single-angle / fail-soft form fails here."""
    body = _read_skill()
    assert "merge_codereview_angles" in body, (
        "step 2.5 must use review_merge.merge_codereview_angles (multi-angle, fail-closed)"
    )
    # The fan-out must be explicit (an ANGLES set the driver dispatches), not rewordable
    # to a single dispatch while still passing.
    assert "ANGLES" in body, "step 2.5 must define the explicit ANGLES fan-out set"
    assert "fan out" in body.lower() or "fans out" in body.lower(), (
        "step 2.5 must state the loop driver FANS OUT the angles (multi-angle, not single-pass)"
    )
    # The unparseable-is-not-clean contract must be stated.
    assert "unparseable" in body.lower(), (
        "the SKILL must state that an unparseable review is NOT a clean one"
    )
    # The anti-pattern the change exists to prevent must be called out negatively.
    assert "parse_codereview_response" in body and "never use the bare" in body.lower(), (
        "the SKILL must warn never to use the bare parse_codereview_response on the convergence path"
    )


# ---------- Phase 5 (pr-iterate-codereview-real-harness): Tier 7 prose + step 10b ----------

TIER7_SKILL_MD = Path(__file__).parent.parent.parent / "tp-run-full-design" / "SKILL.md"


def _read_tier7_skill() -> str:
    return TIER7_SKILL_MD.read_text()


def test_tier7_orchestrator_owns_round_loop() -> None:
    """Tier 7 / Slot 11: the orchestrator MUST drive run_round iteration-by-iteration —
    it must NOT delegate the whole loop to one Slot 11 subagent (the B1 regression this
    design fixes). Asserts: (a) the orchestrator drives each round; (b) uses
    run_round.py shell-out; (c) dispatches ANGLES fan-out at top level; (d) dispatches
    /tp-pr-fix per round; (e) the old 'delegate-whole-loop' anti-pattern is absent."""
    body = _read_tier7_skill()

    # (a) The orchestrator-driven round loop must name run_round.py shell-out.
    assert "run_round.py" in body, (
        "Tier 7 prose must name run_round.py (the B1 shell-out seam, not an in-process call)"
    )

    # (b) Must reference the ANGLES fan-out at top level (general-purpose sub-agents).
    assert "ANGLES" in body, (
        "Tier 7 prose must reference the ANGLES fan-out set (per-head review dispatch)"
    )
    assert "merge_codereview_angles" in body, (
        "Tier 7 prose must name merge_codereview_angles (multi-angle merge step)"
    )

    # (c) Must reference post_codereview_comment (mandatory review-summary comment).
    assert "post_codereview_comment" in body, (
        "Tier 7 prose must name post_codereview_comment"
    )

    # (d) Per-head /tp-pr-fix dispatch.
    assert "/tp-pr-fix" in body, (
        "Tier 7 prose must name /tp-pr-fix dispatch per round"
    )

    # (e) blocked-no-independent-review terminal must be acknowledged.
    assert "blocked-no-independent-review" in body, (
        "Tier 7 prose must name the blocked-no-independent-review terminal"
    )

    # (f) The old 'delegate whole loop to Slot 11' anti-pattern must NOT appear.
    bad_phrases = [
        "runs /tp-pr-iterate {slug} inline",
        "runs `/tp-pr-iterate {slug}` inline",
    ]
    for bad in bad_phrases:
        assert bad not in body, (
            f"Tier 7 prose must NOT say the old 'delegate whole loop to Slot 11' form; "
            f"found: {bad!r}"
        )


def test_step_10b_blocked_no_independent_review_terminal() -> None:
    """tp-pr-iterate SKILL.md step 10b must document the blocked-no-independent-review
    fail-closed terminal and the honest-attribution rule (a single-context self-pass
    is never signed /code-review).

    The honest-attribution assertions pin the ACTUAL rule text — a distinctive phrase
    that only appears because the rule is present. They must be RED if the rule is
    removed: a generic 'self in body' / 'review in body' check would pass even if the
    rule were deleted (both words appear in other contexts throughout the skill). (F-T1)
    """
    body = _read_skill()

    assert "blocked-no-independent-review" in body, (
        "SKILL.md must document the blocked-no-independent-review fail-closed terminal"
    )

    # Pin the SPECIFIC honest-attribution rule text. The phrase
    # "single-context self-pass" is the load-bearing descriptor: it names the exact
    # pattern being forbidden. This assertion is genuinely RED if the rule is removed
    # or reworded away from this concept — unlike a generic 'self in body' check.
    assert "single-context self-pass" in body, (
        "SKILL.md honest-attribution rule must use the phrase 'single-context self-pass' "
        "to name the forbidden pattern (a /code-review running in the loop's own context). "
        "This is the distinctive marker that makes the test RED when the rule is removed."
    )
    # Also pin the prohibition itself: that a self-pass must NOT be signed as /code-review.
    assert "must never be signed as" in body, (
        "SKILL.md honest-attribution rule must state the prohibition: "
        "'must never be signed as /code-review on the convergence path'. "
        "This pins the rule text, not just a tangentially relevant word."
    )
