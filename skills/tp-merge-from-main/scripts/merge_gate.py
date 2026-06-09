"""merge_gate.py — advisory readiness check for tp-merge.

Provides `merge_readiness_warning(pr_url, *, runners=None)` which is called
by tp-merge step 6.6 as an advisory, non-blocking check. It NEVER raises,
NEVER blocks, NEVER exits non-zero — mirrors the step-6.5 detect_unarchived
warn-never-block contract.

Imports `classify_readiness` from `skills/_shared/review_readiness.py`.
All predicate logic lives in review_readiness — this module NEVER re-implements
any predicate logic (tier-boundary contract: the free predicate is imported,
not copied).

See `three-pillars-docs/completed-tp-designs/pr-readiness-surface/detailed-design.md`
for the full interface specification.
"""

from __future__ import annotations

import sys
from pathlib import Path

# ---- sys.path: ensure _shared/ is on path so review_readiness is importable ----
_SHARED_DIR = Path(__file__).resolve().parent.parent.parent / "_shared"
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

from review_readiness import classify_readiness  # noqa: E402


# Advisory warning strings per readiness sub-state
_STATE_WARNINGS: dict[str, str] = {
    "copilot-errored": (
        "Copilot review is an error no-op (never reviewed) — "
        "remediate via pr-thread-disposition before merge."
    ),
    "review-stale": (
        "Copilot review is stale: head advanced past the last review with "
        "code changes — re-request before merge."
    ),
    "awaiting-copilot": (
        "Copilot review still pending — PR not yet reviewed-stable."
    ),
    "unreviewed": (
        "No Copilot review on this PR."
    ),
}


def merge_readiness_warning(pr_url: str, *, runners=None) -> str | None:
    """ADVISORY, NON-BLOCKING readiness check for tp-merge.

    Returns a human-readable warning string when the PR is NOT
    copilot_reviewed_successfully (i.e. classify_readiness != 'reviewed-stable'),
    else None.

    NEVER raises, NEVER blocks, NEVER exits non-zero — tp-merge is a conflict
    resolver, not a gate (mirrors the step-6.5 detect_unarchived contract).

    Fail-OPEN on any fetch error: return None (a detector failure must not nag).

    Args:
        pr_url: the PR URL to check.
        runners: optional dict of injected fetchers for tests; None wires live defaults.
    """
    try:
        state = classify_readiness(pr_url, runners=runners)
    except Exception:
        # Fail-open: any fetch/classify error → return None (no nagging)
        return None

    if state == "reviewed-stable":
        return None

    return _STATE_WARNINGS.get(state, f"Copilot review state: {state}")


# ============================================================
# Task 5.1: merge_gate_blocking — blocking entry point (thin re-export)
# ============================================================

# ---- sys.path: ensure tp-pr-iterate/scripts for loop_driver (_CI_TERMINAL_CONCLUSIONS) ----
_LOOP_DIR = Path(__file__).resolve().parent.parent.parent / "tp-pr-iterate" / "scripts"
if str(_LOOP_DIR) not in sys.path:
    sys.path.insert(0, str(_LOOP_DIR))

from deterministic_gate import evaluate_gate  # noqa: E402


def merge_gate_blocking(pr_url: str, *, runners=None, config=None):
    """Evaluate the pre-merge gate and RETURN its GateOutcome (does not raise).

    Thin re-export of deterministic_gate.evaluate_gate. Returns a GateOutcome
    whose verdict is PASS (0), FAIL (1), or INDETERMINATE (2). This is the
    INSPECTABLE form: the caller reads ``.verdict`` / ``.blocking`` and decides.

    The caller (tp-merge mandatory pre-merge step) MUST refuse to merge on a
    non-PASS verdict. Because this returns rather than raises, that obligation is
    on the caller — if you want the obligation enforced in code (so an ignored
    return cannot silently merge), call ``require_merge_gate_pass`` instead.

    DISTINCT from merge_readiness_warning (step 6.6, warn-never-block):
    - merge_readiness_warning: advisory, fail-open, never blocks.
    - merge_gate_blocking: fail-closed verdict, but RETURNS it (no raise).
    - require_merge_gate_pass: fail-closed AND raises MergeGateBlocked on non-PASS.

    Args:
        pr_url: the PR URL to gate.
        runners: optional dict of injected seam functions for tests.
        config: optional repo-config dict (review.expects_copilot /
            ci.expects_github_checks). None → evaluate_gate reads it fail-closed from
            disk (live); inject {} for strict-default hermetic tests.

    Returns:
        GateOutcome with .verdict, .blocking, and .label (always GATE_LABEL).
    """
    return evaluate_gate(pr_url, runners=runners, config=config)


class MergeGateBlocked(Exception):
    """Raised by require_merge_gate_pass when the gate verdict is not PASS.

    Carries the full GateOutcome so the handler can inspect the blocking
    predicate(s) without re-running the gate.
    """

    def __init__(self, outcome):
        self.outcome = outcome
        blockers = ", ".join(
            f"{p.name}: {p.detail}" for p in getattr(outcome, "blocking", [])
        ) or "(no detail)"
        super().__init__(
            f"merge gate did not PASS (verdict={outcome.verdict.value}): {blockers}"
        )


def require_merge_gate_pass(pr_url: str, *, runners=None, config=None):
    """Fail-closed ENFORCING gate: raise MergeGateBlocked unless the verdict is PASS.

    This is the form whose name's "blocking" promise is enforced in code: a
    caller that ignores the return value still cannot proceed to merge, because a
    non-PASS verdict raises. On PASS it returns the GateOutcome (for symmetry /
    optional inspection).

    Use this when the merge decision is made in Python; use the gate_cli.py exit
    code (0/1/2) when the decision is made in shell. Both are fail-closed.

    Args:
        pr_url: the PR URL to gate.
        runners: optional dict of injected seam functions for tests.

    Returns:
        GateOutcome (verdict == PASS).

    Raises:
        MergeGateBlocked: if the verdict is FAIL or INDETERMINATE.
    """
    outcome = merge_gate_blocking(pr_url, runners=runners, config=config)
    # Import here to avoid widening the module's top-level import surface; the
    # symbol already came in via `from deterministic_gate import evaluate_gate`.
    from deterministic_gate import GateVerdict  # noqa: E402

    if outcome.verdict != GateVerdict.PASS:
        raise MergeGateBlocked(outcome)
    return outcome
