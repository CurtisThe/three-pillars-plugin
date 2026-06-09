"""Tests for merge_gate.merge_readiness_warning.

Advisory, read-only, never raises, fail-open on fetch error.

Run with: pytest skills/tp-merge-from-main/scripts/test_merge_gate.py -q
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Add merge scripts dir to path for imports
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
# Add review_readiness shared module
SHARED = Path(__file__).resolve().parent.parent.parent / "_shared"
sys.path.insert(0, str(SHARED))


def _runners_for_state(target: str) -> dict:
    """Build a stub runners dict designed to produce the target classify_readiness result.

    Uses the simplest path through the decision ladder for each state.
    """
    REVIEW_COMMIT = "abc1234abc1234"  # 14-char hex sha (review was on this head)
    CURRENT_HEAD = "deadbeefdeadbeef"  # 16-char hex sha (current head, different for stale)

    def reviews_fn(url):
        if target in ("reviewed-stable", "copilot-errored", "review-stale"):
            body = (
                "encountered an error and was unable to review"
                if target == "copilot-errored"
                else "Looks good."
            )
            commit = REVIEW_COMMIT  # same as head for stable, old for stale
            return [{
                "user": {"login": "copilot-pull-request-reviewer[bot]"},
                "body": body,
                "state": "APPROVED",
                "commit_id": commit,
                "submitted_at": "2026-06-05T12:00:00Z",
            }]
        # awaiting-copilot and unreviewed: no review
        return []

    def threads_fn(url):
        return []  # no unresolved threads in any test case

    def ci_head_fn(url):
        if target == "review-stale":
            # Head is ahead of the review commit; review_exempt_delta will fail-closed
            # because the git diff will return non-zero (refs don't exist in test)
            # which is interpreted as non-exempt → review-stale
            return (CURRENT_HEAD, True)
        # For reviewed-stable: head must match review commit_id
        return (REVIEW_COMMIT, True)

    def requested_fn(url):
        # awaiting-copilot (no review path): Copilot is requested
        if target == "awaiting-copilot":
            return ["copilot-pull-request-reviewer[bot]"]
        return []

    def run_subprocess(*args, **kwargs):
        # review-stale path: force review_exempt_delta's fail-closed (non-exempt)
        # branch deterministically — no git shell-out on fabricated SHAs (#57 nit).
        return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="test stub")

    return {
        "reviews_fn": reviews_fn,
        "threads_fn": threads_fn,
        "ci_head_fn": ci_head_fn,
        "requested_fn": requested_fn,
        "run_subprocess": run_subprocess,
    }


def _make_runners(classify_result: str | Exception) -> dict:
    """Thin shim for backward compat — delegates to _runners_for_state."""
    return _runners_for_state(str(classify_result))


PR_URL = "https://github.com/example/repo/pull/42"


def test_merge_readiness_warning_copilot_errored():
    """copilot-errored sub-state → warning string naming error no-op."""
    from merge_gate import merge_readiness_warning

    runners = _runners_for_state("copilot-errored")
    warning = merge_readiness_warning(PR_URL, runners=runners)

    assert warning is not None, "copilot-errored must produce a warning"
    assert isinstance(warning, str), "warning must be a string"
    assert "error" in warning.lower() or "errored" in warning.lower(), (
        f"warning must mention the errored state; got: {warning!r}"
    )


def test_merge_readiness_warning_review_stale():
    """review-stale sub-state → warning string mentioning stale / re-request."""
    from merge_gate import merge_readiness_warning

    runners = _runners_for_state("review-stale")
    warning = merge_readiness_warning(PR_URL, runners=runners)

    assert warning is not None, "review-stale must produce a warning"
    assert "stale" in warning.lower(), (
        f"warning must mention the stale state; got: {warning!r}"
    )


def test_merge_readiness_warning_awaiting_copilot():
    """awaiting-copilot sub-state → warning string saying still pending."""
    from merge_gate import merge_readiness_warning

    runners = _runners_for_state("awaiting-copilot")
    warning = merge_readiness_warning(PR_URL, runners=runners)

    assert warning is not None, "awaiting-copilot must produce a warning"
    assert "pending" in warning.lower() or "awaiting" in warning.lower(), (
        f"warning must mention pending/awaiting; got: {warning!r}"
    )


def test_merge_readiness_warning_unreviewed():
    """unreviewed sub-state → warning string saying No Copilot review."""
    from merge_gate import merge_readiness_warning

    runners = _runners_for_state("unreviewed")
    warning = merge_readiness_warning(PR_URL, runners=runners)

    assert warning is not None, "unreviewed must produce a warning"
    assert "copilot" in warning.lower() or "review" in warning.lower(), (
        f"warning must mention Copilot review; got: {warning!r}"
    )


def test_merge_readiness_warning_reviewed_stable_returns_none():
    """reviewed-stable → None (no warning)."""
    from merge_gate import merge_readiness_warning

    runners = _runners_for_state("reviewed-stable")
    warning = merge_readiness_warning(PR_URL, runners=runners)

    assert warning is None, (
        f"reviewed-stable must return None (no warning); got: {warning!r}"
    )


def test_merge_readiness_warning_fetch_error_returns_none():
    """Fetch error at the merge_gate level → None (fail-open — must not nag).

    We patch classify_readiness itself to raise so the error surfaces at the
    merge_gate boundary regardless of how classify_readiness handles its runners.
    """
    import importlib
    import merge_gate as mg

    original = mg.classify_readiness
    try:
        # Monkeypatch classify_readiness in the merge_gate module namespace
        def raising_classify(pr_url, *, runners=None):
            raise RuntimeError("simulated gh network error")
        mg.classify_readiness = raising_classify

        warning = mg.merge_readiness_warning(PR_URL, runners=None)
        assert warning is None, (
            f"a fetch/classify error must be fail-open (return None); got: {warning!r}"
        )
    finally:
        mg.classify_readiness = original


def test_merge_readiness_warning_never_raises():
    """The function must NEVER raise for any input."""
    from merge_gate import merge_readiness_warning

    # Various edge cases that should never raise; None runners wires live defaults
    # but we don't want network calls — use an empty runners dict which will cause
    # classify_readiness to fail-soft gracefully (it catches most exceptions).
    empty_runners = {
        "reviews_fn": lambda url: [],
        "threads_fn": lambda url: [],
        "ci_head_fn": lambda url: (None, False),
        "requested_fn": lambda url: [],
    }

    test_inputs = [
        ("https://github.com/o/r/pull/1", empty_runners),
        ("https://github.com/o/r/pull/99", empty_runners),
    ]

    for url, runners in test_inputs:
        try:
            result = merge_readiness_warning(url, runners=runners)
            # result may be None or a string — both are fine
            assert result is None or isinstance(result, str)
        except Exception as exc:
            raise AssertionError(
                f"merge_readiness_warning({url!r}) raised: {exc!r}"
            )


# ============================================================
# Task 5.1: merge_gate_blocking re-export tests
# ============================================================

def _make_gate_runners_pass() -> dict:
    """Stub runners that produce an all-PASS GateOutcome from evaluate_gate.

    Now a FULL 5-predicate PASS (the strict-default gate includes pred_human_approved):
    the human-approval runner keys describe a deliberate human (`alice`, not automation)
    who applied `tp:human-approved` on THIS head, current on the head commit. The
    framework's own gh identity (`self_login_fn` -> `framework-ci`) is DISTINCT from the
    human approver, so the F2 self-applied rejection (self is always added to the
    automation set) does not bite. Committer-equality is advisory (never a reject), so
    `alice` having also committed the head is fine — this is the 'solo-operator PASS
    through the full gate' regression with a separate framework gh identity.
    """
    # PASS path: merged + reviews all resolved + all CI succeeded + Copilot on head
    HEAD_OID = "abc123def456"
    REVIEW_COMMIT = HEAD_OID
    HEAD_COMMITTED = "2026-06-05T11:00:00Z"     # head commit time
    APPROVAL_AT = "2026-06-05T12:00:00Z"        # approval >= head commit (current)

    def pr_state_fn(url):
        return {
            "mergeable": "MERGEABLE",
            "headRefOid": HEAD_OID,
            "statusCheckRollup": [
                {"conclusion": "SUCCESS"},
                {"conclusion": "SUCCESS"},
            ],
        }

    def threads_fn(url):
        return []  # no unresolved threads

    def reviews_fn(url):
        return [{
            "user": {"login": "copilot-pull-request-reviewer[bot]"},
            "body": "Looks good.",
            "state": "APPROVED",
            "commit_id": REVIEW_COMMIT,
            "submitted_at": "2026-06-05T12:00:00Z",
        }]

    def ci_head_fn(url):
        return (HEAD_OID, True)

    def requested_fn(url):
        return []

    # ---- human-approval seams (5th predicate) ----
    def labels_fn(url):
        return [{"name": "tp:human-approved"}]

    def timeline_fn(url):
        return [{
            "event": "labeled",
            "label": {"name": "tp:human-approved"},
            "actor": {"type": "User", "login": "alice"},
            "created_at": APPROVAL_AT,
            # commit_id = the head SHA at the instant the label event was recorded.
            # Currency is SHA-equality (commit_id == headRefOid), not a timestamp.
            "commit_id": HEAD_OID,
        }]

    def head_fn(url):
        return {"headRefOid": HEAD_OID, "commits": [{"committedDate": HEAD_COMMITTED}]}

    def commits_fn(url):
        # Solo operator: head committer == approver login (advisory only, never a reject).
        return [{"committer": {"login": "alice"}, "author": {"login": "alice"}}]

    def self_login_fn():
        # The framework's gh identity — DISTINCT from the human approver `alice` so the
        # F2 self-applied rejection (self is always in the automation set) does not bite.
        return "framework-ci"

    import subprocess as _subprocess
    def run_subprocess(*args, **kwargs):
        return _subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    return {
        "pr_state_fn": pr_state_fn,
        "threads_fn": threads_fn,
        "reviews_fn": reviews_fn,
        "ci_head_fn": ci_head_fn,
        "requested_fn": requested_fn,
        "labels_fn": labels_fn,
        "timeline_fn": timeline_fn,
        "head_fn": head_fn,
        "commits_fn": commits_fn,
        "self_login_fn": self_login_fn,
        "run_subprocess": run_subprocess,
    }


def _make_gate_runners_empty_rollup() -> dict:
    """Stub runners with empty statusCheckRollup -> non-PASS (INDETERMINATE)."""
    HEAD_OID = "abc123def456"

    def pr_state_fn(url):
        return {
            "mergeable": "MERGEABLE",
            "headRefOid": HEAD_OID,
            "statusCheckRollup": [],  # empty -> INDETERMINATE
        }

    def threads_fn(url):
        return []

    def reviews_fn(url):
        return []

    def ci_head_fn(url):
        return (HEAD_OID, True)

    def requested_fn(url):
        return []

    import subprocess as _subprocess
    def run_subprocess(*args, **kwargs):
        return _subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="test stub")

    return {
        "pr_state_fn": pr_state_fn,
        "threads_fn": threads_fn,
        "reviews_fn": reviews_fn,
        "ci_head_fn": ci_head_fn,
        "requested_fn": requested_fn,
        "run_subprocess": run_subprocess,
    }


def test_merge_gate_blocking_reexports_evaluate_gate():
    """Task 5.1: merge_gate_blocking is a thin re-export of evaluate_gate.

    Asserts:
    - same GateOutcome for an all-PASS runners set
    - same GateOutcome (non-PASS) for empty-rollup runners
    - advisory merge_readiness_warning is unchanged (still importable, same signature)
    """
    import merge_gate
    import deterministic_gate

    # --- All-PASS path ---  (config={} → strict hermetic defaults, repo-config-independent)
    pass_runners = _make_gate_runners_pass()
    outcome_blocking = merge_gate.merge_gate_blocking(PR_URL, runners=pass_runners, config={})
    outcome_direct = deterministic_gate.evaluate_gate(PR_URL, runners=pass_runners, config={})

    assert outcome_blocking.verdict == outcome_direct.verdict, (
        f"merge_gate_blocking must return same verdict as evaluate_gate; "
        f"got {outcome_blocking.verdict!r} vs {outcome_direct.verdict!r}"
    )
    assert outcome_blocking.label == outcome_direct.label, (
        f"merge_gate_blocking must return same label as evaluate_gate"
    )

    # --- Degenerate (empty-rollup) path -> non-PASS ---  (config={} → strict: empty rollup INDETERMINATE)
    empty_runners = _make_gate_runners_empty_rollup()
    outcome_blocking_empty = merge_gate.merge_gate_blocking(PR_URL, runners=empty_runners, config={})
    outcome_direct_empty = deterministic_gate.evaluate_gate(PR_URL, runners=empty_runners, config={})

    assert outcome_blocking_empty.verdict != deterministic_gate.GateVerdict.PASS, (
        f"empty rollup must yield non-PASS from merge_gate_blocking; "
        f"got {outcome_blocking_empty.verdict!r}"
    )
    assert outcome_blocking_empty.verdict == outcome_direct_empty.verdict, (
        f"merge_gate_blocking must return same verdict as evaluate_gate for degenerate case; "
        f"got {outcome_blocking_empty.verdict!r} vs {outcome_direct_empty.verdict!r}"
    )

    # --- Advisory merge_readiness_warning is unchanged (still importable, same signature) ---
    assert callable(merge_gate.merge_readiness_warning), (
        "merge_readiness_warning must still be importable and callable after adding merge_gate_blocking"
    )
    # Call with a minimal valid runners to confirm same signature works
    minimal_runners = {
        "reviews_fn": lambda url: [],
        "threads_fn": lambda url: [],
        "ci_head_fn": lambda url: (None, False),
        "requested_fn": lambda url: [],
    }
    warning = merge_gate.merge_readiness_warning(PR_URL, runners=minimal_runners)
    assert warning is None or isinstance(warning, str), (
        f"merge_readiness_warning signature unchanged; got unexpected type: {type(warning)}"
    )


# ============================================================
# Review #59, finding 5: require_merge_gate_pass enforces the "blocking" promise
# ============================================================

def test_require_merge_gate_pass_raises_on_non_pass():
    """A non-PASS verdict must RAISE MergeGateBlocked (carrying the outcome), so a
    caller that ignores the return value still cannot proceed to merge."""
    import deterministic_gate
    from merge_gate import MergeGateBlocked, require_merge_gate_pass

    empty_runners = _make_gate_runners_empty_rollup()  # empty rollup -> INDETERMINATE
    try:
        require_merge_gate_pass(PR_URL, runners=empty_runners, config={})  # strict defaults
    except MergeGateBlocked as exc:
        assert exc.outcome.verdict != deterministic_gate.GateVerdict.PASS, (
            f"MergeGateBlocked must carry the non-PASS outcome; got {exc.outcome.verdict!r}"
        )
        # The outcome's blocking predicate(s) must be inspectable on the exception.
        assert exc.outcome.blocking, "blocked outcome must name its blocking predicate(s)"
    else:
        raise AssertionError(
            "require_merge_gate_pass must raise MergeGateBlocked on a non-PASS verdict"
        )


def test_require_merge_gate_pass_returns_outcome_on_pass():
    """On PASS, require_merge_gate_pass returns the GateOutcome (no raise) — symmetric
    with merge_gate_blocking so callers can still inspect the passing outcome."""
    import deterministic_gate
    from merge_gate import require_merge_gate_pass

    pass_runners = _make_gate_runners_pass()
    outcome = require_merge_gate_pass(PR_URL, runners=pass_runners)
    assert outcome.verdict == deterministic_gate.GateVerdict.PASS, (
        f"a PASS runners set must return a PASS outcome without raising; "
        f"got {outcome.verdict!r}"
    )


def test_merge_gate_blocking_still_returns_not_raises_on_non_pass():
    """Guard: the inspectable re-export must keep RETURNING the non-PASS outcome (the
    SKILL.md / CLI enforcement path depends on it), not adopt require_'s raise."""
    import deterministic_gate
    from merge_gate import merge_gate_blocking

    outcome = merge_gate_blocking(PR_URL, runners=_make_gate_runners_empty_rollup(), config={})
    assert outcome.verdict != deterministic_gate.GateVerdict.PASS, (
        f"merge_gate_blocking must return the non-PASS outcome (no raise); "
        f"got {outcome.verdict!r}"
    )
