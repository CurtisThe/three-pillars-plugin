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
    Path(__file__).parent / "thread_resolver.py",
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
