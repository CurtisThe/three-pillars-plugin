"""Tests for deterministic_gate.py — the fail-closed, stdlib-only merge gate.

All tests inject runners/stubs — NO live gh/git calls.
"""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


def _proof_comment_fn_for(head="abc123"):
    """A comments_fn yielding a head-bound proof digest (enforce-review-proof p7).

    All-PASS runner dicts inject this so the (default-required) review_proof_on_head
    predicate PASSes alongside the other predicates. Built via the real
    format_proof_digest so the gate parser is tested against the production string.
    Authored by "framework-bot" — the runner dicts' hermetic self login — so the
    trusted-author fold (review finding on PR #109) passes without a live
    `gh api user` self-login resolution.
    """
    import sys as _sys
    _pri = HERE.parent / "tp-pr-iterate" / "scripts"
    if str(_pri) not in _sys.path:
        _sys.path.insert(0, str(_pri))
    import review_proof  # noqa: E402
    body = review_proof.format_proof_digest({
        "base": "base000", "head": head, "files_changed": 3,
        "insertions": 5, "deletions": 1, "degraded": False, "reason": None,
    }, [("correctness", 0)])
    return lambda _url: [{"author": "framework-bot", "body": body}]


# ============================================================
# Task 1.1: FailureClass enum + _node_status normalizer
# ============================================================


def test_node_status_normalizes_conclusion_and_state():
    from deterministic_gate import FailureClass, _node_status

    # CheckRun: conclusion present
    assert _node_status({"conclusion": "SUCCESS"}) == "SUCCESS"
    assert _node_status({"conclusion": "success"}) == "SUCCESS"  # uppercased

    # StatusContext: no conclusion, has state
    assert _node_status({"state": "FAILURE"}) == "FAILURE"

    # conclusion is None, fallback to state
    assert _node_status({"conclusion": None, "state": "PENDING"}) == "PENDING"

    # empty node → empty/falsey, not a crash
    result = _node_status({})
    assert result == "" or result is None

    # FailureClass members exist and are str-subclass Enum with .value == name
    assert FailureClass.INFRA_BLOCK.value == "INFRA_BLOCK"
    assert FailureClass.CODE_FAILURE.value == "CODE_FAILURE"
    assert FailureClass.INDETERMINATE.value == "INDETERMINATE"

    # str subclass: value is a str
    assert isinstance(FailureClass.INFRA_BLOCK, str)


# ============================================================
# Task 1.2: _node_is_startup_crash
# ============================================================


def test_node_is_startup_crash_signature():
    from deterministic_gate import _node_is_startup_crash

    # Primary signal: conclusion == STARTUP_FAILURE
    assert _node_is_startup_crash({"conclusion": "STARTUP_FAILURE"}) is True
    assert _node_is_startup_crash({"conclusion": "startup_failure"}) is True  # normalized

    # Fallback: zero-step / zero-duration heuristic
    # A node that started and completed at the same time with empty steps
    assert _node_is_startup_crash(
        {"startedAt": "2024-01-01T00:00:00Z", "completedAt": "2024-01-01T00:00:00Z", "steps": []}
    ) is True

    # Normal conclusions → False
    assert _node_is_startup_crash({"conclusion": "SUCCESS"}) is False
    assert _node_is_startup_crash({"conclusion": "FAILURE"}) is False

    # Malformed/missing node → False (never raises)
    assert _node_is_startup_crash({}) is False
    assert _node_is_startup_crash(None) is False
    assert _node_is_startup_crash("garbage") is False


# ============================================================
# Task 1.3: classify_failure
# ============================================================


class TestClassifyFailure:
    def test_empty_rollup_is_indeterminate(self):
        from deterministic_gate import FailureClass, classify_failure

        # H3 vacuous-pass hole: zero checks is NEVER evidence of success
        assert classify_failure([]) == FailureClass.INDETERMINATE

    def test_uniform_startup_failure_is_infra_block(self):
        from deterministic_gate import FailureClass, classify_failure

        rollup = [
            {"conclusion": "STARTUP_FAILURE"},
            {"conclusion": "STARTUP_FAILURE"},
        ]
        assert classify_failure(rollup) == FailureClass.INFRA_BLOCK

    def test_mixed_one_ran_is_code_failure(self):
        from deterministic_gate import FailureClass, classify_failure

        # One startup crash + one that actually ran (FAILURE conclusion)
        rollup = [
            {"conclusion": "STARTUP_FAILURE"},
            {"conclusion": "FAILURE"},
        ]
        assert classify_failure(rollup) == FailureClass.CODE_FAILURE

    def test_unparsable_rollup_is_indeterminate(self):
        from deterministic_gate import FailureClass, classify_failure

        # Non-list / unparsable input → INDETERMINATE (caught, never raises)
        assert classify_failure(None) == FailureClass.INDETERMINATE
        assert classify_failure("garbage") == FailureClass.INDETERMINATE


# ============================================================
# Task 2.1: PredicateResult frozen dataclass + GateVerdict
# ============================================================


def test_predicate_result_shape():
    from deterministic_gate import GateVerdict, PredicateResult

    # GateVerdict members are str-Enum with .value == name
    assert GateVerdict.PASS.value == "PASS"
    assert GateVerdict.FAIL.value == "FAIL"
    assert GateVerdict.INDETERMINATE.value == "INDETERMINATE"
    assert isinstance(GateVerdict.PASS, str)

    # PredicateResult is frozen
    r = PredicateResult(name="threads_resolved", verdict=GateVerdict.PASS, detail="ok")
    assert r.name == "threads_resolved"
    assert r.verdict == GateVerdict.PASS
    assert r.detail == "ok"

    # Mutation raises FrozenInstanceError
    with pytest.raises(FrozenInstanceError):
        r.name = "changed"


# ============================================================
# Task 2.2: fetch_threads_or_none — the fail-closed thread seam
# ============================================================


class TestFetchThreadsOrNone:
    def test_threads_fn_raises_returns_none(self):
        from deterministic_gate import fetch_threads_or_none

        def raiser(url):
            raise RuntimeError("gh failed")

        result = fetch_threads_or_none("https://github.com/o/r/pull/1", threads_fn=raiser)
        assert result is None

    def test_threads_fn_returns_list_passthrough(self):
        from deterministic_gate import fetch_threads_or_none

        threads = [{"is_resolved": True, "thread_id": "T1"}]

        def stub(url):
            return threads

        result = fetch_threads_or_none("https://github.com/o/r/pull/1", threads_fn=stub)
        assert result == threads

    def test_threads_fn_returns_empty_list_passthrough(self):
        from deterministic_gate import fetch_threads_or_none

        def stub(url):
            return []

        # Empty list (proven no threads) → returns [], NOT None
        result = fetch_threads_or_none("https://github.com/o/r/pull/1", threads_fn=stub)
        assert result == []
        assert result is not None

    def test_threads_fn_returns_non_list_returns_none(self):
        from deterministic_gate import fetch_threads_or_none

        def stub_none(url):
            return None

        def stub_str(url):
            return "x"

        assert fetch_threads_or_none("https://github.com/o/r/pull/1", threads_fn=stub_none) is None
        assert fetch_threads_or_none("https://github.com/o/r/pull/1", threads_fn=stub_str) is None


# ============================================================
# Task 2.3: pred_threads_resolved
# ============================================================


class TestPredThreadsResolved:
    def test_none_is_indeterminate(self):
        from deterministic_gate import GateVerdict, pred_threads_resolved

        result = pred_threads_resolved(None)
        assert result.verdict == GateVerdict.INDETERMINATE

    def test_unresolved_thread_is_fail(self):
        from deterministic_gate import GateVerdict, pred_threads_resolved

        threads = [{"is_resolved": False, "author": "human"}]
        result = pred_threads_resolved(threads)
        assert result.verdict == GateVerdict.FAIL

    def test_all_resolved_is_pass(self):
        from deterministic_gate import GateVerdict, pred_threads_resolved

        # Empty proven list → PASS
        assert pred_threads_resolved([]).verdict == GateVerdict.PASS

        # All resolved → PASS
        threads = [{"is_resolved": True}, {"is_resolved": True}]
        assert pred_threads_resolved(threads).verdict == GateVerdict.PASS

    def test_only_unresolved_bot_thread_is_fail(self):
        from deterministic_gate import GateVerdict, pred_threads_resolved

        # D5 boundary: bot thread is still counted — no author carve-out at merge boundary
        threads = [{"is_resolved": False, "author": "dependabot[bot]"}]
        result = pred_threads_resolved(threads)
        assert result.verdict == GateVerdict.FAIL


# ============================================================
# Task 2.4: pred_mergeable
# ============================================================


class TestPredMergeable:
    def test_mergeable_is_pass(self):
        from deterministic_gate import GateVerdict, pred_mergeable

        assert pred_mergeable("MERGEABLE").verdict == GateVerdict.PASS

    def test_conflicting_is_fail(self):
        from deterministic_gate import GateVerdict, pred_mergeable

        assert pred_mergeable("CONFLICTING").verdict == GateVerdict.FAIL

    def test_unknown_is_indeterminate(self):
        from deterministic_gate import GateVerdict, pred_mergeable

        assert pred_mergeable("UNKNOWN").verdict == GateVerdict.INDETERMINATE

    def test_none_is_indeterminate(self):
        from deterministic_gate import GateVerdict, pred_mergeable

        assert pred_mergeable(None).verdict == GateVerdict.INDETERMINATE


# ============================================================
# Task 2.5: pred_checks_success
# ============================================================


class TestPredChecksSuccess:
    def test_infra_block_is_indeterminate(self):
        from deterministic_gate import FailureClass, GateVerdict, pred_checks_success

        rollup = [{"conclusion": "STARTUP_FAILURE"}]
        result = pred_checks_success(rollup, FailureClass.INFRA_BLOCK)
        assert result.verdict == GateVerdict.INDETERMINATE

    def test_indeterminate_class_is_indeterminate(self):
        from deterministic_gate import FailureClass, GateVerdict, pred_checks_success

        # Empty rollup path arrives as INDETERMINATE from classify_failure
        result = pred_checks_success([], FailureClass.INDETERMINATE)
        assert result.verdict == GateVerdict.INDETERMINATE

    def test_all_success_is_pass(self):
        from deterministic_gate import FailureClass, GateVerdict, pred_checks_success

        rollup = [{"conclusion": "SUCCESS"}, {"conclusion": "SUCCESS"}]
        result = pred_checks_success(rollup, FailureClass.CODE_FAILURE)
        assert result.verdict == GateVerdict.PASS

    @pytest.mark.parametrize("status", [
        "ERROR",
        "FAILURE",
        "TIMED_OUT",
        "CANCELLED",
        "STALE",
        "ACTION_REQUIRED",
    ])
    def test_settled_but_not_success_is_fail(self, status):
        from deterministic_gate import FailureClass, GateVerdict, pred_checks_success

        # D3b: settled ≠ success. A terminal node that is NOT success-equivalent → FAIL.
        # Asserts == FAIL (not merely != PASS): a future regression dropping a status
        # from _TERMINAL_STATUSES would route it to the pending branch (INDETERMINATE),
        # which the weaker != PASS assertion would have silently accepted.
        # NOTE: SKIPPED / NEUTRAL are deliberately ABSENT — they are success-equivalent
        # (GitHub-satisfied); see test_skipped_and_neutral_are_success_equivalent.
        rollup = [{"conclusion": status}]
        result = pred_checks_success(rollup, FailureClass.CODE_FAILURE)
        assert result.verdict == GateVerdict.FAIL, (
            f"Expected FAIL for settled-but-non-success {status!r}, got {result.verdict}"
        )

    @pytest.mark.parametrize("status", ["SKIPPED", "NEUTRAL"])
    def test_skipped_and_neutral_are_success_equivalent(self, status):
        from deterministic_gate import FailureClass, GateVerdict, pred_checks_success

        # Policy (audit call 1): SKIPPED (path-filtered / if:-gated / skipped matrix leg)
        # and NEUTRAL (advisory: CodeQL, license bots) are conclusions GitHub branch-
        # protection / `gh pr merge` treat as SATISFIED. Folding them to FAIL emitted the
        # exit-1 "code is broken" signal for a green PR and blocked a class of safe
        # merges. They must be success-equivalent → an all-SKIPPED/NEUTRAL rollup PASSes.
        rollup = [{"conclusion": "SUCCESS"}, {"conclusion": status}]
        result = pred_checks_success(rollup, FailureClass.CODE_FAILURE)
        assert result.verdict == GateVerdict.PASS, (
            f"Expected PASS for success-equivalent {status!r}, got {result.verdict}"
        )

    def test_in_flight_node_is_indeterminate(self):
        from deterministic_gate import FailureClass, GateVerdict, pred_checks_success

        # Non-terminal/in-flight → INDETERMINATE (pending never passes)
        for status in ["IN_PROGRESS", "QUEUED", "PENDING"]:
            rollup = [{"conclusion": status}]
            result = pred_checks_success(rollup, FailureClass.CODE_FAILURE)
            assert result.verdict == GateVerdict.INDETERMINATE, (
                f"Expected INDETERMINATE for in-flight {status!r}, got {result.verdict}"
            )


# ============================================================
# Task 2.6: pred_copilot_on_head
# ============================================================


class TestPredCopilotOnHead:
    def _make_runners(self, copilot_returns=True, raises=False):
        """Build a runners dict for testing pred_copilot_on_head.

        We inject runners for classify_readiness (via copilot_reviewed_successfully).
        When copilot_returns=True → returns 'reviewed-stable'
        When copilot_returns=False → returns 'awaiting-copilot'
        When raises=True → reviews_fn raises
        """
        def reviews_fn(url):
            if raises:
                raise RuntimeError("gh failed")
            if copilot_returns:
                # Provide a stable Copilot review on HEAD
                return [{
                    "user": {"login": "copilot-pull-request-reviewer[bot]"},
                    "submitted_at": "2024-01-01T00:00:00Z",
                    "commit_id": "abc123",
                    "body": "looks good",
                    "state": "COMMENTED",
                }]
            return []

        def threads_fn(url):
            return []  # no threads

        def ci_head_fn(url):
            return ("abc123", True)

        def requested_fn(url):
            return []

        return {
            "reviews_fn": reviews_fn,
            "threads_fn": threads_fn,
            "ci_head_fn": ci_head_fn,
            "requested_fn": requested_fn,
        }

    def test_copilot_true_is_pass(self):
        from deterministic_gate import GateVerdict, pred_copilot_on_head

        runners = self._make_runners(copilot_returns=True)
        result = pred_copilot_on_head("https://github.com/o/r/pull/1", runners=runners)
        assert result.verdict == GateVerdict.PASS

    def test_copilot_false_is_indeterminate(self):
        from deterministic_gate import GateVerdict, pred_copilot_on_head

        runners = self._make_runners(copilot_returns=False)
        result = pred_copilot_on_head("https://github.com/o/r/pull/1", runners=runners)
        assert result.verdict == GateVerdict.INDETERMINATE

    def test_copilot_raises_is_indeterminate(self):
        from deterministic_gate import GateVerdict, pred_copilot_on_head

        runners = self._make_runners(raises=True)
        result = pred_copilot_on_head("https://github.com/o/r/pull/1", runners=runners)
        assert result.verdict == GateVerdict.INDETERMINATE


# ============================================================
# Task 2.2: pred_human_approved (D6 — never FAIL)
# ============================================================

PR_URL = "https://github.com/o/r/pull/1"


class TestPredHumanApproved:
    """The thin gate predicate — PASS or INDETERMINATE only, NEVER FAIL (D6)."""

    def _patch(self, monkeypatch, *, returns=None, raises=False):
        """Stub human_approval.human_approved_on_head with a controlled result."""
        import human_approval

        def stub(pr_url, *, runners=None, config=None):
            if raises:
                raise RuntimeError("boom inside human_approved_on_head")
            return returns

        monkeypatch.setattr(human_approval, "human_approved_on_head", stub)

    def test_approved_true_is_pass(self, monkeypatch):
        from deterministic_gate import GateVerdict, pred_human_approved

        self._patch(monkeypatch, returns=True)
        result = pred_human_approved(PR_URL)
        assert result.verdict == GateVerdict.PASS
        assert result.name == "human_approved"

    def test_approved_false_is_indeterminate(self, monkeypatch):
        from deterministic_gate import GateVerdict, pred_human_approved

        self._patch(monkeypatch, returns=False)
        result = pred_human_approved(PR_URL)
        assert result.verdict == GateVerdict.INDETERMINATE
        assert result.name == "human_approved"
        # detail instructs the user to get an APPROVED review (not apply a label)
        assert "APPROVED" in result.detail or "approved" in result.detail.lower()
        # tp:human-approved label must NOT appear in the detail (path retired)
        assert "tp:human-approved" not in result.detail

    def test_internal_raise_is_indeterminate(self, monkeypatch):
        from deterministic_gate import GateVerdict, pred_human_approved

        self._patch(monkeypatch, raises=True)
        result = pred_human_approved(PR_URL)
        assert result.verdict == GateVerdict.INDETERMINATE
        assert result.name == "human_approved"

    def test_verdict_is_never_fail(self, monkeypatch):
        """D6 invariant: across True/False/raise, the verdict is NEVER FAIL."""
        from deterministic_gate import GateVerdict, pred_human_approved

        for kwargs in ({"returns": True}, {"returns": False}, {"raises": True}):
            self._patch(monkeypatch, **kwargs)
            result = pred_human_approved(PR_URL)
            assert result.verdict in (GateVerdict.PASS, GateVerdict.INDETERMINATE), (
                f"human_approved must never FAIL; got {result.verdict} for {kwargs}"
            )
            assert result.verdict != GateVerdict.FAIL

    def test_runners_and_config_pass_through(self, monkeypatch):
        """The raw runners dict and config are forwarded to human_approved_on_head."""
        import human_approval
        from deterministic_gate import pred_human_approved

        seen = {}

        def stub(pr_url, *, runners=None, config=None):
            seen["runners"] = runners
            seen["config"] = config
            return True

        monkeypatch.setattr(human_approval, "human_approved_on_head", stub)
        sentinel_runners = {"labels_fn": lambda u: []}
        sentinel_config = {"review": {"require_human_approval": True}}
        pred_human_approved(PR_URL, runners=sentinel_runners, config=sentinel_config)
        assert seen["runners"] is sentinel_runners
        assert seen["config"] is sentinel_config


# ============================================================
# Task 3.1: GateOutcome + GATE_LABEL + _fold helper
# ============================================================


class TestFold:
    def _make_result(self, verdict_str, name="test"):
        from deterministic_gate import GateVerdict, PredicateResult
        return PredicateResult(name=name, verdict=GateVerdict(verdict_str), detail=f"{name} detail")

    def test_all_pass_is_pass(self):
        from deterministic_gate import GATE_LABEL, GateVerdict, _fold

        results = [self._make_result("PASS", f"p{i}") for i in range(4)]
        outcome = _fold(results)
        assert outcome.verdict == GateVerdict.PASS
        assert outcome.blocking == []
        assert outcome.label == GATE_LABEL

    def test_one_fail_is_fail(self):
        from deterministic_gate import GATE_LABEL, GateVerdict, _fold

        results = [
            self._make_result("PASS", "p1"),
            self._make_result("FAIL", "p2"),
            self._make_result("PASS", "p3"),
        ]
        outcome = _fold(results)
        assert outcome.verdict == GateVerdict.FAIL
        assert any(r.name == "p2" for r in outcome.blocking)
        assert outcome.label == GATE_LABEL

    def test_one_indeterminate_is_indeterminate(self):
        from deterministic_gate import GATE_LABEL, GateVerdict, _fold

        results = [
            self._make_result("PASS", "p1"),
            self._make_result("INDETERMINATE", "p2"),
        ]
        outcome = _fold(results)
        assert outcome.verdict == GateVerdict.INDETERMINATE
        assert any(r.name == "p2" for r in outcome.blocking)
        assert outcome.label == GATE_LABEL

    def test_fail_beats_indeterminate(self):
        from deterministic_gate import GATE_LABEL, GateVerdict, _fold

        results = [
            self._make_result("FAIL", "p_fail"),
            self._make_result("INDETERMINATE", "p_indet"),
            self._make_result("PASS", "p_pass"),
        ]
        outcome = _fold(results)
        assert outcome.verdict == GateVerdict.FAIL
        assert outcome.label == GATE_LABEL


# ============================================================
# Task 3.2: _fetch_pr_state
# ============================================================


class TestFetchPrState:
    def test_fetch_returns_tuple(self):
        from deterministic_gate import _fetch_pr_state

        def pr_state_fn(url):
            return {
                "mergeable": "MERGEABLE",
                "headRefOid": "abc123",
                "statusCheckRollup": [{"conclusion": "SUCCESS"}],
            }

        mergeable, head_oid, rollup = _fetch_pr_state(
            "https://github.com/o/r/pull/1", pr_state_fn=pr_state_fn
        )
        assert mergeable == "MERGEABLE"
        assert head_oid == "abc123"
        assert rollup == [{"conclusion": "SUCCESS"}]

    def test_fetch_raises_yields_none_oid(self):
        from deterministic_gate import _fetch_pr_state

        def pr_state_fn(url):
            raise RuntimeError("gh failed")

        mergeable, head_oid, rollup = _fetch_pr_state(
            "https://github.com/o/r/pull/1", pr_state_fn=pr_state_fn
        )
        assert head_oid is None
        assert mergeable is None
        assert rollup == []

    def test_unparsable_yields_none_oid(self):
        from deterministic_gate import _fetch_pr_state

        def pr_state_fn(url):
            return "not a dict"

        mergeable, head_oid, rollup = _fetch_pr_state(
            "https://github.com/o/r/pull/1", pr_state_fn=pr_state_fn
        )
        assert head_oid is None
        assert rollup == []

    def test_null_head_oid_preserved(self):
        from deterministic_gate import _fetch_pr_state

        def pr_state_fn(url):
            return {"mergeable": "MERGEABLE", "headRefOid": None, "statusCheckRollup": []}

        mergeable, head_oid, rollup = _fetch_pr_state(
            "https://github.com/o/r/pull/1", pr_state_fn=pr_state_fn
        )
        # None headRefOid preserved as None (fail-closed downstream)
        assert head_oid is None


# ============================================================
# Task 3.3: evaluate_gate — the total function
# ============================================================


class TestEvaluateGate:
    PR_URL = "https://github.com/o/r/pull/1"

    def _all_pass_runners(self):
        """Full runners dict that yields all-PASS state."""
        def pr_state_fn(url):
            return {
                "mergeable": "MERGEABLE",
                "headRefOid": "abc123",
                "statusCheckRollup": [{"conclusion": "SUCCESS"}],
            }

        def threads_fn(url):
            return []  # no threads, proven-empty

        def reviews_fn(url):
            return [{
                "user": {"login": "copilot-pull-request-reviewer[bot]"},
                "submitted_at": "2024-01-01T00:00:00Z",
                "commit_id": "abc123",
                "body": "looks good",
                "state": "COMMENTED",
            }]

        def ci_head_fn(url):
            return ("abc123", True)

        def requested_fn(url):
            return []

        return {
            "pr_state_fn": pr_state_fn,
            "threads_fn": threads_fn,
            "reviews_fn": reviews_fn,
            "ci_head_fn": ci_head_fn,
            "requested_fn": requested_fn,
            "comments_fn": _proof_comment_fn_for("abc123"),
            # p7's trusted-author set resolves self hermetically via this key
            # (matches _proof_comment_fn_for's digest author).
            "self_login_fn": lambda: "framework-bot",
        }

    def test_all_predicates_pass_is_pass_with_label(self):
        from deterministic_gate import GATE_LABEL, GateVerdict, evaluate_gate

        # The original 4-predicate fold: opt out of the (strict-by-default)
        # human-approval predicate so this exercises exactly the pre-human-approval
        # predicate set. The strict-default p5 path is covered by
        # TestEvaluateGateHumanApproval below.
        config = {"review": {"require_human_approval": False}}
        outcome = evaluate_gate(self.PR_URL, config=config, runners=self._all_pass_runners())
        assert outcome.verdict == GateVerdict.PASS
        assert outcome.label == GATE_LABEL

    def test_empty_rollup_not_pass(self):
        from deterministic_gate import GateVerdict, evaluate_gate

        runners = self._all_pass_runners()

        def pr_state_fn(url):
            return {
                "mergeable": "MERGEABLE",
                "headRefOid": "abc123",
                "statusCheckRollup": [],  # empty!
            }

        runners["pr_state_fn"] = pr_state_fn
        outcome = evaluate_gate(self.PR_URL, config={}, runners=runners)
        assert outcome.verdict != GateVerdict.PASS

    def test_pr_state_fn_raises_is_indeterminate(self):
        from deterministic_gate import GateVerdict, evaluate_gate

        runners = self._all_pass_runners()

        def pr_state_fn(url):
            raise RuntimeError("gh failed")

        runners["pr_state_fn"] = pr_state_fn
        outcome = evaluate_gate(self.PR_URL, config={}, runners=runners)
        assert outcome.verdict == GateVerdict.INDETERMINATE

    def test_null_head_oid_is_indeterminate(self):
        from deterministic_gate import GateVerdict, evaluate_gate

        runners = self._all_pass_runners()

        def pr_state_fn(url):
            return {
                "mergeable": "MERGEABLE",
                "headRefOid": None,  # null SHA
                "statusCheckRollup": [{"conclusion": "SUCCESS"}],
            }

        runners["pr_state_fn"] = pr_state_fn
        outcome = evaluate_gate(self.PR_URL, config={}, runners=runners)
        assert outcome.verdict == GateVerdict.INDETERMINATE

    def test_threads_fn_raises_is_indeterminate(self):
        from deterministic_gate import GateVerdict, evaluate_gate

        runners = self._all_pass_runners()

        def threads_fn(url):
            raise RuntimeError("gh failed")

        runners["threads_fn"] = threads_fn
        outcome = evaluate_gate(self.PR_URL, config={}, runners=runners)
        assert outcome.verdict == GateVerdict.INDETERMINATE

    def test_uniform_startup_failure_is_indeterminate(self):
        from deterministic_gate import GateVerdict, evaluate_gate

        runners = self._all_pass_runners()

        def pr_state_fn(url):
            return {
                "mergeable": "MERGEABLE",
                "headRefOid": "abc123",
                "statusCheckRollup": [
                    {"conclusion": "STARTUP_FAILURE"},
                    {"conclusion": "STARTUP_FAILURE"},
                ],
            }

        runners["pr_state_fn"] = pr_state_fn
        outcome = evaluate_gate(self.PR_URL, config={}, runners=runners)
        # INFRA_BLOCK → pred_checks_success INDETERMINATE
        assert outcome.verdict == GateVerdict.INDETERMINATE

    def test_any_predicate_raises_caught_is_indeterminate_never_pass(self):
        from deterministic_gate import GateVerdict, evaluate_gate

        # Inject a runners dict where pr_state_fn raises an unexpected error
        # The gate body must catch this and fold to INDETERMINATE
        runners = self._all_pass_runners()

        def pr_state_fn(url):
            raise ZeroDivisionError("unexpected internal error")

        runners["pr_state_fn"] = pr_state_fn
        outcome = evaluate_gate(self.PR_URL, config={}, runners=runners)
        assert outcome.verdict != GateVerdict.PASS
        assert outcome.verdict == GateVerdict.INDETERMINATE


# ============================================================
# Task 2.3: Fold p5 into evaluate_gate (config-gated, default strict)
# ============================================================


class TestEvaluateGateHumanApproval:
    """The config-gated p5 fold: strict default, opt-out backward-compat, pass-through."""

    PR_URL = "https://github.com/o/r/pull/1"

    def _all_pass_runners(self):
        """4-predicate-PASS runners (mirrors TestEvaluateGate._all_pass_runners)."""
        def pr_state_fn(url):
            return {
                "mergeable": "MERGEABLE",
                "headRefOid": "abc123",
                "statusCheckRollup": [{"conclusion": "SUCCESS"}],
            }

        def threads_fn(url):
            return []

        def reviews_fn(url):
            return [{
                "user": {"login": "copilot-pull-request-reviewer[bot]"},
                "submitted_at": "2024-01-01T00:00:00Z",
                "commit_id": "abc123",
                "body": "looks good",
                "state": "COMMENTED",
            }]

        def ci_head_fn(url):
            return ("abc123", True)

        def requested_fn(url):
            return []

        return {
            "pr_state_fn": pr_state_fn,
            "threads_fn": threads_fn,
            "reviews_fn": reviews_fn,
            "ci_head_fn": ci_head_fn,
            "requested_fn": requested_fn,
            "comments_fn": _proof_comment_fn_for("abc123"),
            # p7's trusted-author set resolves self hermetically via this key
            # (matches _proof_comment_fn_for's digest author).
            "self_login_fn": lambda: "framework-bot",
        }

    def _stub_approval(self, monkeypatch, returns):
        import human_approval
        monkeypatch.setattr(
            human_approval, "human_approved_on_head", lambda *a, **k: returns
        )

    def test_required_and_absent_is_indeterminate_blocking_human_approved(self, monkeypatch):
        """require_human_approval:True, 4 preds PASS, approval absent -> INDETERMINATE
        with `human_approved` named in blocking."""
        from deterministic_gate import GateVerdict, evaluate_gate

        self._stub_approval(monkeypatch, returns=False)
        outcome = evaluate_gate(
            self.PR_URL,
            config={"review": {"require_human_approval": True}},
            runners=self._all_pass_runners(),
        )
        assert outcome.verdict == GateVerdict.INDETERMINATE
        assert any(p.name == "human_approved" for p in outcome.blocking), (
            f"human_approved must be named in blocking; got "
            f"{[p.name for p in outcome.blocking]}"
        )

    def test_optout_omits_predicate_backward_compat(self, monkeypatch):
        """require_human_approval:False -> predicate OMITTED; the existing 4-pred fold is
        UNCHANGED (backward-compat). Even with approval FALSE, the outcome is PASS because
        p5 is not appended — identical to the pre-change 4-pred fold for the same inputs."""
        from deterministic_gate import GateVerdict, evaluate_gate

        # Stub approval to False to PROVE the predicate is omitted, not merely passing.
        self._stub_approval(monkeypatch, returns=False)
        outcome = evaluate_gate(
            self.PR_URL,
            config={"review": {"require_human_approval": False}},
            runners=self._all_pass_runners(),
        )
        assert outcome.verdict == GateVerdict.PASS, (
            f"opt-out must yield the unchanged 4-pred PASS; got {outcome.verdict} "
            f"blocking={[p.name for p in outcome.blocking]}"
        )
        assert not any(p.name == "human_approved" for p in outcome.blocking)

    def test_optout_fold_identical_to_explicit_4pred(self, monkeypatch):
        """The opt-out fold is byte-identical to a fold over exactly p1..p4 — the new
        predicate leaves NO trace (no extra blocking entry, same verdict) when omitted."""
        from deterministic_gate import GateVerdict, evaluate_gate

        # Make one of the original 4 INDETERMINATE so the fold is non-trivially shaped.
        runners = self._all_pass_runners()
        runners["pr_state_fn"] = lambda url: {
            "mergeable": "UNKNOWN",  # -> pred_mergeable INDETERMINATE
            "headRefOid": "abc123",
            "statusCheckRollup": [{"conclusion": "SUCCESS"}],
        }
        self._stub_approval(monkeypatch, returns=True)  # would PASS if present
        outcome = evaluate_gate(
            self.PR_URL,
            config={"review": {"require_human_approval": False}},
            runners=runners,
        )
        # The fold reflects ONLY p1..p4: INDETERMINATE from mergeable, and human_approved
        # appears NOWHERE (neither blocking nor as a silent PASS contributor).
        assert outcome.verdict == GateVerdict.INDETERMINATE
        names = [p.name for p in outcome.blocking]
        assert "human_approved" not in names
        assert "mergeable" in names

    def test_absent_key_defaults_strict_predicate_present(self, monkeypatch):
        """Absent require_human_approval (default) -> predicate PRESENT (strict)."""
        from deterministic_gate import GateVerdict, evaluate_gate

        self._stub_approval(monkeypatch, returns=False)
        outcome = evaluate_gate(
            self.PR_URL,
            config={"review": {"expects_copilot": True}},  # no require_human_approval key
            runners=self._all_pass_runners(),
        )
        assert outcome.verdict == GateVerdict.INDETERMINATE
        assert any(p.name == "human_approved" for p in outcome.blocking)

    def test_approval_present_and_4_pass_is_pass(self, monkeypatch):
        """Approval present (stub->True) + 4 PASS -> outcome PASS."""
        from deterministic_gate import GateVerdict, evaluate_gate

        self._stub_approval(monkeypatch, returns=True)
        outcome = evaluate_gate(
            self.PR_URL,
            config={"review": {"require_human_approval": True}},
            runners=self._all_pass_runners(),
        )
        assert outcome.verdict == GateVerdict.PASS
        assert outcome.blocking == []

    def test_p5_receives_raw_runner_dict_with_human_keys(self, monkeypatch):
        """F4: the p5 path receives the RAW `r` dict — the human-approval runner keys
        pass through untouched (namespaced, no collision with copilot/pr_state seams)."""
        import human_approval
        from deterministic_gate import evaluate_gate

        seen = {}

        def stub(pr_url, *, runners=None, config=None):
            seen["runners"] = runners
            seen["config"] = config
            return True

        monkeypatch.setattr(human_approval, "human_approved_on_head", stub)

        runners = self._all_pass_runners()
        sentinel_labels_fn = lambda u: [{"name": "tp:human-approved"}]
        sentinel_self_login_fn = lambda: "alice"
        runners["labels_fn"] = sentinel_labels_fn
        runners["self_login_fn"] = sentinel_self_login_fn

        cfg = {"review": {"require_human_approval": True}}
        evaluate_gate(self.PR_URL, config=cfg, runners=runners)

        assert seen["runners"] is runners, "p5 must receive the raw runners dict"
        # The human-approval keys are present and unmodified in what p5 saw.
        assert seen["runners"]["labels_fn"] is sentinel_labels_fn
        assert seen["runners"]["self_login_fn"] is sentinel_self_login_fn
        assert seen["config"] is cfg


# ============================================================
# Task 3.4: C1 no-LLM invariant meta-test
# ============================================================


# ---- C1 no-LLM detector (shared by the invariant test + its positive controls) ----


def _is_subprocess_call(call: ast.Call) -> bool:
    """True iff `call` is a subprocess/os shell entry point.

    Catches `subprocess.run/Popen/call/check_output/check_call`, bare `run(...)` etc.
    via `from subprocess import run`, and `os.system/os.popen`.
    """
    f = call.func
    if isinstance(f, ast.Attribute):
        val = f.value
        if isinstance(val, ast.Name) and val.id == "subprocess":
            return True
        if isinstance(val, ast.Name) and val.id == "os" and f.attr in ("system", "popen"):
            return True
    if isinstance(f, ast.Name) and f.id in (
        "run", "Popen", "call", "check_output", "check_call", "system", "popen",
    ):
        return True
    return False


def _command_tokens_of_call(call: ast.Call):
    """Yield candidate executable tokens from a subprocess call's command.

    Covers the three list-literal/shell shapes the audit reproduced as bypasses of
    the original `arg.elts[0] == "claude"` check:
      - positional list/tuple:  subprocess.run(['timeout','60','claude',...])  → each element
      - args= keyword:          subprocess.run(args=['claude',...])            → each element
      - shell string:           subprocess.run('claude -p ...', shell=True)    → whitespace tokens
    """
    containers = list(call.args)
    for kw in call.keywords:
        if kw.arg == "args" or kw.arg is None:  # args= or **{...}
            containers.append(kw.value)
    for c in containers:
        if isinstance(c, (ast.List, ast.Tuple)):
            for el in c.elts:
                if isinstance(el, ast.Constant) and isinstance(el.value, str):
                    yield el.value
        elif isinstance(c, ast.Constant) and isinstance(c.value, str):
            for tok in c.value.split():
                yield tok


def _is_claude_token(tok: str) -> bool:
    return tok == "claude" or tok.endswith("/claude")


def _subprocess_claude_violations(source: str) -> list[str]:
    """Return every `claude`-executable token reachable as a subprocess command.

    Two complementary scans:
      (a) ANY list/tuple literal carrying a bare `claude` element — catches the
          variable-stored command shape (`cmd = ['claude', ...]; subprocess.run(cmd)`)
          that a call-args-only scan misses, plus the timeout-wrapped and direct forms.
      (b) subprocess/os shell-string calls whose command tokens include `claude`.
    A finding's prompt arg (e.g. "is this safe to merge?") is a non-`claude` constant,
    so it never false-positives. Module/function docstrings are string Constants, NOT
    List nodes, so the module's own `subprocess.run(["claude", ...])` prose in the
    docstring is not flagged.
    """
    tree = ast.parse(source)
    bad: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Tuple)):
            for el in node.elts:
                if isinstance(el, ast.Constant) and isinstance(el.value, str) and _is_claude_token(el.value):
                    bad.append(el.value)
        elif isinstance(node, ast.Call) and _is_subprocess_call(node):
            for tok in _command_tokens_of_call(node):
                if _is_claude_token(tok):
                    bad.append(tok)
    return bad


_CLAUDE_EVASION_SHAPES = [
    "subprocess.run(['claude', '-p', 'is this safe to merge?'])",          # direct
    "subprocess.run(['timeout', '60', 'claude', '-p', 'x'])",             # timeout-wrapped
    "subprocess.run(args=['claude', '-p', 'x'])",                          # args= kwarg
    "subprocess.run('claude -p x', shell=True)",                           # shell string
    "subprocess.Popen(['timeout', '5', 'claude'])",                        # Popen
    "os.system('claude -p x')",                                            # os.system shell
    "cmd = ['timeout', '60', 'claude']\nsubprocess.run(cmd)",             # variable-stored
    "from subprocess import run\nrun(['claude', '-p', 'x'])",             # bare run import
]

_NON_CLAUDE_SUBPROCESS_SHAPES = [
    "subprocess.run(['gh', 'pr', 'view', url, '--json', 'mergeable'])",
    "subprocess.run(['gh', 'api', 'graphql', '-f', 'query=...'])",
    "subprocess.run(['timeout', '60', 'gh', 'pr', 'view'])",
    "subprocess.run(['git', 'rev-parse', 'HEAD'])",
]


def _assert_no_llm(module_path: Path) -> None:
    """C1 invariant assertion for a single stdlib module: no `import anthropic`
    (in either import form) and no `claude` subprocess in any invocation shape.
    Shared by the deterministic_gate.py and human_approval.py guards (Task 1.9)."""
    name = module_path.name
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "anthropic" not in alias.name.lower(), (
                    f"{name} imports {alias.name!r} — violates C1"
                )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert "anthropic" not in module.lower(), (
                f"{name} does `from {module} import …` — violates C1"
            )

    violations = _subprocess_claude_violations(source)
    assert not violations, (
        f"{name} invokes a `claude` subprocess {violations!r} — violates C1"
    )


class TestNoLLMInvariant:
    """C1 invariant: deterministic_gate.py AND human_approval.py have no
    `import anthropic` and no `claude` subprocess in any invocation shape —
    stdlib plumbing only."""

    def test_no_llm_imports_invariant(self):
        _assert_no_llm(HERE / "deterministic_gate.py")

    def test_no_llm_imports_invariant_human_approval(self):
        """C1 invariant extended to human_approval.py (Task 1.9 / D9): the new
        read-path module is pure gh/stdlib — no `import anthropic`, no `claude`
        subprocess in any invocation shape."""
        _assert_no_llm(HERE / "human_approval.py")

    @pytest.mark.parametrize("snippet", _CLAUDE_EVASION_SHAPES)
    def test_detector_fires_on_every_claude_evasion_shape(self, snippet):
        """The detector's own coverage is regression-tested: it MUST flag each
        invocation shape, including the timeout-wrapped / args= / shell-string /
        variable-stored forms that defeated the original elts[0]-only check."""
        assert _subprocess_claude_violations(snippet), (
            f"C1 detector failed to flag a claude bypass shape: {snippet!r}"
        )

    @pytest.mark.parametrize("snippet", _NON_CLAUDE_SUBPROCESS_SHAPES)
    def test_detector_silent_on_non_claude_subprocess(self, snippet):
        """No false positives: legitimate gh/git subprocesses (incl. timeout-wrapped)
        must NOT trip the detector."""
        assert not _subprocess_claude_violations(snippet), (
            f"C1 detector false-positived on a benign subprocess: {snippet!r}"
        )


# ============================================================
# Review #59 regression tests
# ============================================================

PR_URL_R59 = "https://github.com/example/repo/pull/59"


def test_partial_runners_does_not_leak_pr_state_fn_to_copilot(monkeypatch):
    """Regression (review #59, finding 1): evaluate_gate with ONLY pr_state_fn
    injected must hand the copilot predicate runners=None (live defaults), NOT the
    full runners dict.

    The old `copilot_runners if copilot_runners else runners` ternary leaked a
    pr_state_fn-only dict into classify_readiness, which subscripts
    runners["reviews_fn"] directly (KeyError unless runners is None) — so the gate
    folded to a bogus 'gate-internal-error' INDETERMINATE instead of evaluating the
    copilot predicate.
    """
    import deterministic_gate
    import human_approval
    import review_readiness

    captured = {}

    def fake_copilot(pr_url, *, runners=None):
        captured["runners"] = runners
        return True  # pretend reviewed -> copilot predicate PASS

    monkeypatch.setattr(review_readiness, "copilot_reviewed_successfully", fake_copilot)
    # Hold the (strict-default) human-approval predicate at PASS — this regression is
    # about the COPILOT runner-leak, orthogonal to human approval; stub it green so the
    # "all predicates PASS -> fold PASS" assertion still isolates the leak under test.
    monkeypatch.setattr(
        human_approval, "human_approved_on_head", lambda *a, **k: True
    )
    # Stub the thread seam too: pr_state_fn is the ONLY key that is NOT copilot-relevant
    # (reviews_fn/threads_fn/ci_head_fn/requested_fn all are), so to inject *only*
    # pr_state_fn we must keep threads hermetic without passing threads_fn (which would
    # itself land in copilot_runners and defeat the "no copilot seams" premise).
    monkeypatch.setattr(deterministic_gate, "fetch_threads_or_none", lambda *a, **k: [])

    def pr_state_fn(url):
        return {
            "mergeable": "MERGEABLE",
            "headRefOid": "abc123def456",
            "statusCheckRollup": [{"conclusion": "SUCCESS"}],
        }

    # ONLY pr_state_fn injected — zero copilot-relevant seams, so copilot_runners -> None.
    # config forces strict copilot default (expects_copilot=True) so the copilot predicate
    # actually RUNS — otherwise the repo's real config (expects_copilot=false) would omit
    # p4 and this regression (which asserts what p4 received) would never exercise it.
    # require_review_proof:False omits the (default-required) review-proof predicate so this
    # copilot-leak regression isolates p4 without injecting an unrelated comments_fn seam.
    outcome = deterministic_gate.evaluate_gate(
        PR_URL_R59,
        runners={"pr_state_fn": pr_state_fn},
        config={"review": {"require_review_proof": False}},
    )

    # The copilot predicate must have received None, not the pr_state_fn dict.
    assert captured.get("runners") is None, (
        "copilot predicate must receive runners=None when no copilot seams are "
        f"injected; got {captured.get('runners')!r}"
    )
    # And the gate must NOT degrade into a gate-internal-error from a leaked dict.
    assert not any(p.name == "gate-internal-error" for p in outcome.blocking), (
        f"leaked partial runners must not force a gate-internal-error; "
        f"blocking={[p.name for p in outcome.blocking]}"
    )
    # With all four predicates PASS, the fold is PASS.
    assert outcome.verdict == deterministic_gate.GateVerdict.PASS, (
        f"expected PASS once the runners leak is fixed; got {outcome.verdict!r}"
    )


def test_fold_empty_results_is_indeterminate_not_vacuous_pass():
    """Regression (review #59, finding 4): _fold([]) must be INDETERMINATE, never a
    vacuous PASS (the any([])/all([]) trap the gate exists to prevent)."""
    from deterministic_gate import GateVerdict, _fold

    outcome = _fold([])
    assert outcome.verdict == GateVerdict.INDETERMINATE, (
        f"empty predicate set must fold to INDETERMINATE; got {outcome.verdict!r}"
    )
    assert outcome.blocking, "an empty fold must name a blocking entry, not pass silently"


def test_status_context_error_state_is_fail_not_indeterminate():
    """Regression (review #59, finding 6): a StatusContext in ERROR state is a
    SETTLED failure -> FAIL, not mis-keyed as in-flight -> INDETERMINATE.

    'ERROR' is absent from the CheckRun _CI_TERMINAL_CONCLUSIONS vocabulary; the
    fix adds it to the settle gate via _STATUS_CONTEXT_TERMINAL_STATES.
    """
    from deterministic_gate import FailureClass, GateVerdict, pred_checks_success

    rollup = [{"state": "ERROR"}]  # legacy commit-status that hard-errored
    result = pred_checks_success(rollup, FailureClass.CODE_FAILURE)
    assert result.verdict == GateVerdict.FAIL, (
        f"a StatusContext ERROR state must be FAIL (settled, non-SUCCESS), not "
        f"INDETERMINATE; got {result.verdict!r} ({result.detail!r})"
    )


def test_status_context_pending_state_still_indeterminate():
    """Guard the #6 fix didn't over-reach: a non-terminal PENDING StatusContext must
    remain INDETERMINATE (in-flight), not get swept into the terminal set."""
    from deterministic_gate import FailureClass, GateVerdict, pred_checks_success

    result = pred_checks_success([{"state": "PENDING"}], FailureClass.CODE_FAILURE)
    assert result.verdict == GateVerdict.INDETERMINATE, (
        f"a PENDING StatusContext must stay INDETERMINATE (in-flight); "
        f"got {result.verdict!r}"
    )


# ============================================================
# Thorough-audit regression tests (#59 review, round 2)
# ============================================================


def test_thread_is_resolved_must_be_literal_true_to_resolve():
    """Regression: a truthy non-bool is_resolved (e.g. string "false", 1, 0.1) must
    NOT be read as resolved — only literal True resolves. An unresolved thread with a
    string is_resolved previously leaked into PASS."""
    from deterministic_gate import GateVerdict, pred_threads_resolved

    # literal True → resolved → PASS
    assert pred_threads_resolved([{"is_resolved": True}]).verdict == GateVerdict.PASS
    # every truthy-non-True value → treated as UNRESOLVED → FAIL (fail-closed)
    for bad in ("false", "true", 1, 0.1, "0", "yes"):
        r = pred_threads_resolved([{"is_resolved": bad}])
        assert r.verdict == GateVerdict.FAIL, (
            f"is_resolved={bad!r} must be treated as unresolved (FAIL), got {r.verdict!r}"
        )
    # falsey / missing → unresolved → FAIL (unchanged)
    assert pred_threads_resolved([{"is_resolved": False}]).verdict == GateVerdict.FAIL
    assert pred_threads_resolved([{}]).verdict == GateVerdict.FAIL
    # genuinely empty → PASS
    assert pred_threads_resolved([]).verdict == GateVerdict.PASS


def test_checks_success_is_order_independent():
    """Regression: a pending node ordered before a failed node must NOT mask the FAIL.
    The same check set yields the same verdict regardless of node order (FAIL > INDETERMINATE)."""
    from deterministic_gate import FailureClass, GateVerdict, pred_checks_success

    pending_then_fail = [{"conclusion": None, "status": "IN_PROGRESS"}, {"conclusion": "FAILURE"}]
    fail_then_pending = [{"conclusion": "FAILURE"}, {"conclusion": None, "status": "IN_PROGRESS"}]
    a = pred_checks_success(pending_then_fail, FailureClass.CODE_FAILURE)
    b = pred_checks_success(fail_then_pending, FailureClass.CODE_FAILURE)
    assert a.verdict == GateVerdict.FAIL, f"pending-before-fail must still FAIL; got {a.verdict!r}"
    assert b.verdict == GateVerdict.FAIL
    assert a.verdict == b.verdict, "verdict must not depend on node order"
    # all-pending (no failure) is still INDETERMINATE
    allp = pred_checks_success([{"conclusion": None}, {"conclusion": None}], FailureClass.CODE_FAILURE)
    assert allp.verdict == GateVerdict.INDETERMINATE


def test_startup_crash_heuristic_never_fires_on_success_node():
    """Regression: an instant green check (SUCCESS, startedAt==completedAt, steps==[])
    must NOT be flagged a startup crash → must not block an all-green PR."""
    from deterministic_gate import (
        FailureClass,
        GateVerdict,
        _node_is_startup_crash,
        classify_failure,
        pred_checks_success,
    )

    green_instant = {"conclusion": "SUCCESS", "startedAt": "t", "completedAt": "t", "steps": []}
    assert _node_is_startup_crash(green_instant) is False
    # a rollup of such nodes classifies as CODE_FAILURE (not INFRA_BLOCK)...
    fc = classify_failure([green_instant, green_instant])
    assert fc != FailureClass.INFRA_BLOCK
    # ...and the checks predicate PASSES (green PR not blocked as INDETERMINATE)
    assert pred_checks_success([green_instant], fc).verdict == GateVerdict.PASS
    # the heuristic is preserved for NON-success zero-duration nodes
    crash = {"conclusion": "FAILURE", "startedAt": "t", "completedAt": "t", "steps": []}
    assert _node_is_startup_crash(crash) is True


def test_mergeable_is_case_insensitive():
    """Regression: pred_mergeable must normalize case (parity with _node_status) so a
    lowercase 'conflicting' is still FAIL, not a weakened INDETERMINATE."""
    from deterministic_gate import GateVerdict, pred_mergeable

    assert pred_mergeable("conflicting").verdict == GateVerdict.FAIL
    assert pred_mergeable("CONFLICTING").verdict == GateVerdict.FAIL
    assert pred_mergeable("mergeable").verdict == GateVerdict.PASS
    assert pred_mergeable("MERGEABLE").verdict == GateVerdict.PASS
    assert pred_mergeable(None).verdict == GateVerdict.INDETERMINATE


# ============================================================
# Audit blocker ①: strict thread fetch (transient gh failure → fail-closed)
# ============================================================


def test_default_threads_fn_is_strict_not_fail_open(monkeypatch):
    """Audit blocker ①: the gate's live thread fetcher MUST be the strict (raises)
    variant. Wired to the fail-open list_review_threads (which swallows every failure
    to []), fetch_threads_or_none was a production no-op — a transient gh failure read
    as a clean zero-thread PR and PASSed the gate. Assert the default delegates to
    list_review_threads_STRICT, so a fetch failure propagates as a raise that
    fetch_threads_or_none converts to the None sentinel → INDETERMINATE.
    """
    import deterministic_gate
    import thread_resolver

    calls = {"strict": 0, "fail_open": 0}

    def strict(pr_url):
        calls["strict"] += 1
        raise RuntimeError("transient gh failure")

    def fail_open(pr_url):
        calls["fail_open"] += 1
        return []

    monkeypatch.setattr(thread_resolver, "list_review_threads_strict", strict)
    monkeypatch.setattr(thread_resolver, "list_review_threads", fail_open)

    # The default seam must call the STRICT fetcher and therefore return None (not []).
    result = deterministic_gate.fetch_threads_or_none("https://github.com/o/r/pull/1")
    assert result is None, "default threads_fn must be strict — a fetch failure → None"
    assert calls["strict"] == 1 and calls["fail_open"] == 0, (
        "the gate must use list_review_threads_strict, never the fail-open variant"
    )


def test_transient_thread_fetch_failure_blocks_otherwise_green_pr():
    """End-to-end: a green PR (MERGEABLE, all checks SUCCESS, copilot reviewed) whose
    thread fetch transiently fails must fold to INDETERMINATE, never PASS — the H3
    fail-closed invariant the gate exists to hold."""
    from deterministic_gate import GateVerdict, evaluate_gate

    def pr_state_fn(url):
        return {
            "mergeable": "MERGEABLE",
            "headRefOid": "abc123",
            "statusCheckRollup": [{"conclusion": "SUCCESS"}],
        }

    def threads_fn_boom(url):
        raise RuntimeError("transient gh/graphql failure")

    outcome = evaluate_gate(
        "https://github.com/o/r/pull/1",
        config={},  # strict defaults: copilot expected, checks expected
        runners={
            "pr_state_fn": pr_state_fn,
            "threads_fn": threads_fn_boom,
            # copilot seam: pretend reviewed so ONLY the thread fetch failure is in play
            "reviews_fn": lambda *a, **k: True,
        },
    )
    assert outcome.verdict == GateVerdict.INDETERMINATE, (
        f"transient thread-fetch failure must block (INDETERMINATE), got {outcome.verdict}"
    )
    assert any(p.name == "threads_resolved" for p in outcome.blocking)


# ============================================================
# Audit blocker ③ + self-hosted-CI: config-aware gate (opt-outs)
# ============================================================


def _green_no_checks_no_copilot_runners():
    """A PR that is MERGEABLE, has an EMPTY check rollup, no Copilot review, and all
    threads resolved — i.e. the state an expects_copilot=false / expects_github_checks=
    false repo's loop converges and labels ready."""
    return {
        "pr_state_fn": lambda url: {
            "mergeable": "MERGEABLE",
            "headRefOid": "abc123",
            "statusCheckRollup": [],  # no GitHub CI
        },
        "threads_fn": lambda url: [],  # proven zero unresolved threads
        "reviews_fn": lambda *a, **k: False,  # Copilot never reviewed
    }


def test_config_blind_strict_default_deadlocks_optout_repo():
    """Baseline (strict config): the empty-rollup + no-Copilot PR folds to
    INDETERMINATE (exit 2) — the deadlock the audit flagged for opt-out repos."""
    from deterministic_gate import GateVerdict, evaluate_gate

    outcome = evaluate_gate(
        "https://github.com/o/r/pull/1",
        config={},  # strict: expects both checks and copilot
        runners=_green_no_checks_no_copilot_runners(),
    )
    assert outcome.verdict == GateVerdict.INDETERMINATE


def test_optout_config_passes_the_loop_ready_pr():
    """Audit blocker ③: with review.expects_copilot=false AND ci.expects_github_checks=
    false, the gate must PASS the exact PR the loop converges — the Copilot predicate is
    omitted and an empty rollup is not-applicable, so there is a tooling path to PASS."""
    from deterministic_gate import GateVerdict, evaluate_gate

    outcome = evaluate_gate(
        "https://github.com/o/r/pull/1",
        # A fully-relaxed opt-out repo: no Copilot, no GitHub checks, AND no required
        # human approval — the autonomous-loop-ready PR the loop converges must have a
        # tooling path to PASS. (require_human_approval:false also keeps p5 out of the
        # fold so this asserts exactly the loop-ready predicate set.)
        config={
            "review": {
                "expects_copilot": False,
                "require_human_approval": False,
                "require_review_proof": False,
            },
            "ci": {"expects_github_checks": False},
        },
        runners=_green_no_checks_no_copilot_runners(),
    )
    assert outcome.verdict == GateVerdict.PASS, (
        f"opt-out repo's ready PR must PASS, got {outcome.verdict} "
        f"(blocking={[p.name for p in outcome.blocking]})"
    )
    assert not any(p.name == "copilot_on_head" for p in outcome.blocking)


def test_optout_checks_still_fail_on_a_real_failing_check():
    """The ci.expects_github_checks=false relaxation applies ONLY to an EMPTY rollup. If
    checks actually ran and one FAILED, the gate must still FAIL — opt-out is not a
    blanket checks bypass."""
    from deterministic_gate import GateVerdict, evaluate_gate

    runners = _green_no_checks_no_copilot_runners()
    runners["pr_state_fn"] = lambda url: {
        "mergeable": "MERGEABLE",
        "headRefOid": "abc123",
        "statusCheckRollup": [{"conclusion": "FAILURE"}],  # a check ran AND failed
    }
    outcome = evaluate_gate(
        "https://github.com/o/r/pull/1",
        config={"review": {"expects_copilot": False}, "ci": {"expects_github_checks": False}},
        runners=runners,
    )
    assert outcome.verdict == GateVerdict.FAIL


def test_missing_config_subsection_defaults_fail_closed():
    """A config with no review/ci subsections (or a corrupt one) must default to the
    STRICT behavior — expects both — so a missing config never relaxes the gate."""
    from deterministic_gate import GateVerdict, evaluate_gate

    for cfg in ({}, {"unrelated": 1}, {"review": None, "ci": "garbage"}):
        outcome = evaluate_gate(
            "https://github.com/o/r/pull/1",
            config=cfg,
            runners=_green_no_checks_no_copilot_runners(),
        )
        assert outcome.verdict == GateVerdict.INDETERMINATE, (
            f"config {cfg!r} must fail-closed to strict (INDETERMINATE), got {outcome.verdict}"
        )


# ============================================================
# Task 1.1: Subset-injection regression (RED against current code)
# ============================================================


def test_subset_copilot_injection_no_internal_error(monkeypatch):
    """Regression: injecting a STRICT SUBSET of copilot runner keys must reach the
    TRUE gate verdict, not over-block.

    Old code: a partial dict (e.g. {reviews_fn, threads_fn} missing ci_head_fn /
    requested_fn) reached classify_readiness whose direct subscript
    runners["ci_head_fn"] raised KeyError. That KeyError was swallowed *inside*
    pred_copilot_on_head's own try/except (NOT the evaluate_gate outer except), so it
    surfaced as a `copilot_on_head` INDETERMINATE that over-blocked the gate -- it did
    NOT produce a `gate-internal-error`. (An earlier version of this docstring/asserts
    claimed gate-internal-error; that was wrong -- see the real-review finding on PR
    #62. The headline assert below was vacuous because it guarded a verdict the old
    code never emitted.)

    New code (Task 1.2): missing copilot keys are filled from
    review_readiness._build_live_runners, so classify_readiness always receives a
    complete 4-key dict, never KeyErrors, and the green hermetic setup reaches PASS.

    Load-bearing guard: verdict == PASS with `copilot_on_head` absent from blocking --
    RED on the old code (INDETERMINATE, copilot_on_head blocking), GREEN on the new.
    """
    import deterministic_gate
    import human_approval
    import review_readiness

    PR_URL = "https://github.com/o/r/pull/99"
    invoked = {}

    # This regression isolates the COPILOT subset-injection path; hold the
    # (strict-default) human-approval predicate at PASS so it doesn't mask the
    # copilot verdict under test.
    monkeypatch.setattr(
        human_approval, "human_approved_on_head", lambda *a, **k: True
    )

    # The two injected copilot seams -- record that they are actually called.
    def stub_reviews_fn(url):
        invoked["reviews_fn"] = True
        # Return a Copilot review on the current head so classify_readiness reaches
        # 'reviewed-stable' without needing ci_head_fn / requested_fn (short-circuit
        # at step 4 -- on-head review with zero unresolved threads).
        return [{
            "user": {"login": "copilot-pull-request-reviewer[bot]"},
            "submitted_at": "2024-01-01T00:00:00Z",
            "commit_id": "def456",
            "body": "LGTM",
            "state": "COMMENTED",
        }]

    def stub_threads_fn(url):
        invoked["threads_fn"] = True
        return []  # no open threads

    # Monkeypatch _build_live_runners so that ci_head_fn / requested_fn (the missing
    # copilot keys) are provided by hermetic stubs -- no live gh/git.
    def fake_build_live_runners(pr_url=None):
        def live_ci_head_fn(url):
            return ("def456", True)  # settled, matches the review commit_id

        def live_requested_fn(url):
            return []

        return {
            "reviews_fn": stub_reviews_fn,   # will be overridden by merge
            "threads_fn": stub_threads_fn,   # will be overridden by merge
            "ci_head_fn": live_ci_head_fn,
            "requested_fn": live_requested_fn,
        }

    monkeypatch.setattr(review_readiness, "_build_live_runners", fake_build_live_runners)

    # Inject ONLY the two copilot seams (strict subset -- ci_head_fn / requested_fn absent)
    # plus a pr_state_fn giving a green head.
    def pr_state_fn(url):
        return {
            "mergeable": "MERGEABLE",
            "headRefOid": "def456",
            "statusCheckRollup": [{"conclusion": "SUCCESS"}],
        }

    subset_runners = {
        "pr_state_fn": pr_state_fn,
        "reviews_fn": stub_reviews_fn,
        "threads_fn": stub_threads_fn,
        # ci_head_fn and requested_fn deliberately OMITTED
    }

    # config forces expects_copilot=True so the copilot predicate actually runs;
    # require_review_proof:False omits the unrelated default-required proof predicate
    # so this copilot-subset regression isolates p4.
    outcome = deterministic_gate.evaluate_gate(
        PR_URL, runners=subset_runners,
        config={"review": {"require_review_proof": False}},
    )

    blocking_names = [p.name for p in outcome.blocking]
    # LOAD-BEARING: the subset injection must now reach the TRUE verdict. The old
    # partial-dict path over-blocked as a `copilot_on_head` INDETERMINATE (KeyError
    # swallowed inside the predicate); these two asserts are RED on the old code and
    # GREEN on the new.
    assert outcome.verdict == deterministic_gate.GateVerdict.PASS, (
        "strict-subset copilot injection must reach the true PASS verdict once the "
        f"missing keys are back-filled; got {outcome.verdict!r}, blocking={blocking_names}"
    )
    assert "copilot_on_head" not in blocking_names, (
        "old failure mode (partial dict -> KeyError swallowed as a copilot_on_head "
        f"INDETERMINATE) must be gone; blocking={blocking_names}"
    )
    # Secondary: no spurious gate-internal-error, and the injected seams were invoked
    # (merge preserved the injected keys).
    assert "gate-internal-error" not in blocking_names, f"blocking={blocking_names}"
    assert invoked.get("reviews_fn"), "stub_reviews_fn was not called -- injection lost"
    assert invoked.get("threads_fn"), "stub_threads_fn was not called -- injection lost"


# ============================================================
# Phase 2: FAIL-verdict integration coverage (Tasks 2.1-2.4)
# ============================================================


class TestEvaluateGateFail:
    """End-to-end FAIL-verdict cases, each driving a distinct FAIL source.

    Each starts from an all-PASS runners dict and perturbs exactly one signal.
    config={} (strict defaults: expects_copilot=True, expects_github_checks=True)
    so every predicate runs. These are regression guards -- the fold wiring is already
    correct; they are expected GREEN immediately.
    """

    PR_URL = "https://github.com/o/r/pull/1"

    def _all_pass_runners(self):
        """Full runners dict that yields all-PASS state."""
        def pr_state_fn(url):
            return {
                "mergeable": "MERGEABLE",
                "headRefOid": "abc123",
                "statusCheckRollup": [{"conclusion": "SUCCESS"}],
            }

        def threads_fn(url):
            return []

        def reviews_fn(url):
            return [{
                "user": {"login": "copilot-pull-request-reviewer[bot]"},
                "submitted_at": "2024-01-01T00:00:00Z",
                "commit_id": "abc123",
                "body": "looks good",
                "state": "COMMENTED",
            }]

        def ci_head_fn(url):
            return ("abc123", True)

        def requested_fn(url):
            return []

        return {
            "pr_state_fn": pr_state_fn,
            "threads_fn": threads_fn,
            "reviews_fn": reviews_fn,
            "ci_head_fn": ci_head_fn,
            "requested_fn": requested_fn,
        }

    # Task 2.1: _blocking_names helper
    def _blocking_names(self, outcome):
        """Return the set of blocking predicate names for terse assertions."""
        return {p.name for p in outcome.blocking}

    # Task 2.2: FAIL via CONFLICTING mergeable
    def test_conflicting_mergeable_is_fail(self):
        """CONFLICTING mergeable -> pred_mergeable FAIL -> gate FAIL."""
        from deterministic_gate import GateVerdict, evaluate_gate

        runners = self._all_pass_runners()
        runners["pr_state_fn"] = lambda url: {
            "mergeable": "CONFLICTING",
            "headRefOid": "abc123",
            "statusCheckRollup": [{"conclusion": "SUCCESS"}],
        }
        outcome = evaluate_gate(self.PR_URL, runners=runners, config={})
        assert outcome.verdict == GateVerdict.FAIL, (
            f"CONFLICTING mergeable must fold to FAIL; got {outcome.verdict!r}"
        )
        assert "mergeable" in self._blocking_names(outcome), (
            f"'mergeable' must be a blocking predicate; got {self._blocking_names(outcome)!r}"
        )

    # Task 2.3: FAIL via settled non-success check
    def test_settled_non_success_check_is_fail(self):
        """conclusion=FAILURE (CODE_FAILURE) -> pred_checks_success FAIL -> gate FAIL.

        Deliberately distinct from the existing STARTUP_FAILURE / INFRA_BLOCK case,
        which folds to INDETERMINATE. FAILURE is a real, settled non-success check.
        """
        from deterministic_gate import GateVerdict, evaluate_gate

        runners = self._all_pass_runners()
        runners["pr_state_fn"] = lambda url: {
            "mergeable": "MERGEABLE",
            "headRefOid": "abc123",
            "statusCheckRollup": [{"conclusion": "FAILURE"}],
        }
        outcome = evaluate_gate(self.PR_URL, runners=runners, config={})
        assert outcome.verdict == GateVerdict.FAIL, (
            f"settled FAILURE check must fold to FAIL; got {outcome.verdict!r}"
        )
        assert "checks_success" in self._blocking_names(outcome), (
            f"'checks_success' must be a blocking predicate; got {self._blocking_names(outcome)!r}"
        )

    # Task 2.4: FAIL via unresolved thread
    def test_unresolved_thread_is_fail(self):
        """Unresolved thread -> pred_threads_resolved FAIL -> gate FAIL.

        Note: an unresolved thread ALSO defeats copilot_on_head (the review is no longer
        'reviewed-stable' when threads are open), so copilot_on_head may co-block as
        INDETERMINATE. Assert by MEMBERSHIP, not set-equality, so the co-blocker is
        tolerated. FAIL still dominates INDETERMINATE in _fold.
        """
        from deterministic_gate import GateVerdict, evaluate_gate

        runners = self._all_pass_runners()
        runners["threads_fn"] = lambda url: [{"is_resolved": False, "author": "human"}]
        outcome = evaluate_gate(self.PR_URL, runners=runners, config={})
        assert outcome.verdict == GateVerdict.FAIL, (
            f"unresolved thread must fold to FAIL; got {outcome.verdict!r}"
        )
        assert "threads_resolved" in self._blocking_names(outcome), (
            f"'threads_resolved' must be a blocking predicate; got {self._blocking_names(outcome)!r}"
        )
