"""Integration tests for the review path wired into the merge-gate predicate.

Split from test_human_approval_review.py (Phase-2 integration vs Phase-1 unit helpers)
to keep each test module under the soft-warn cap. Covers: the `reviews_fn` runner key,
the review-sole-path `human_approved_on_head`, and the `pred_human_approved`
gate-output contract. All tests inject runners — NO live gh/git.

After retire-approval-tags: label path REMOVED. human_approved_on_head is satisfied
ONLY by a non-automation human APPROVED review current on head (review_path_satisfied).
Label-only scenarios MUST return False; the review path is the sole path.
"""

from __future__ import annotations


# ============================================================
# Task 2.1: reviews_fn runner key wiring
# ============================================================


class TestReviewsRunnerWiring:
    def test_reviews_fn_in_keys(self):
        from human_approval import _HUMAN_APPROVAL_KEYS
        assert "reviews_fn" in _HUMAN_APPROVAL_KEYS

    def test_build_live_runners_has_callable_reviews_fn(self):
        from human_approval import _build_live_runners
        runners = _build_live_runners("https://github.com/o/r/pull/1")
        assert callable(runners["reviews_fn"])


# ============================================================
# Task 2.2: human_approved_on_head — review is sole path
# ============================================================


class TestHumanApprovedReviewPath:
    """Integration over human_approved_on_head with fully-injected runners.

    All runner keys are provided so the F4 per-key resolution never falls back to
    live gh. self_login is `curtisthebot` (lands in the automation set).

    After retire-approval-tags: label presence has NO effect. The SOLE path is
    a non-automation human APPROVED review current on the head.
    """

    def _runners(self, *, reviews, head=None):
        h = head or {"headRefOid": "h", "commits": []}
        return {
            "self_login_fn": lambda: "curtisthebot",
            "head_fn": lambda u: h,
            "reviews_fn": (reviews if callable(reviews) else (lambda u: reviews)),
            "labels_fn": lambda u: [],
            "timeline_fn": lambda u: [],
            "commits_fn": lambda u: [],
        }

    def _review(self, state="APPROVED", commit_id="h", login="curtisthe"):
        return {"user": {"login": login, "type": "User"}, "state": state,
                "submitted_at": "2026-06-16T01:00:00Z", "commit_id": commit_id}

    REVIEW_HEAD = {"headRefOid": "h", "commits": []}

    def test_review_only_passes(self):
        """APPROVED review current on head -> True (the sole path)."""
        from human_approval import human_approved_on_head
        r = self._runners(reviews=[self._review()])
        assert human_approved_on_head("https://github.com/o/r/pull/1", runners=r) is True

    def test_label_only_no_review_is_false(self):
        """Label present but no review -> False. Label path is retired."""
        from human_approval import human_approved_on_head
        # Even with a label in labels_fn, the predicate returns False with no review.
        runners = {
            "self_login_fn": lambda: "curtisthebot",
            "head_fn": lambda u: {"headRefOid": "abc1234def", "commits": []},
            "reviews_fn": lambda u: [],
            "labels_fn": lambda u: [{"name": "tp:human-approved:abc1234"}],
            "timeline_fn": lambda u: [{
                "event": "labeled",
                "label": {"name": "tp:human-approved:abc1234"},
                "actor": {"login": "curtisthe", "type": "User"},
                "created_at": "2026-06-16T01:00:00Z",
            }],
            "commits_fn": lambda u: [],
        }
        assert human_approved_on_head("https://github.com/o/r/pull/1", runners=runners) is False

    def test_neither_false(self):
        """No review, no label -> False."""
        from human_approval import human_approved_on_head
        r = self._runners(reviews=[])
        assert human_approved_on_head("https://github.com/o/r/pull/1", runners=r) is False

    def test_review_passes_regardless_of_label(self):
        """Both review and label present: True — from the review alone.

        (Previously test_both_true asserted the OR; now we assert the review
        is the SOLE carrier of the True value.)
        """
        from human_approval import human_approved_on_head
        runners = {
            "self_login_fn": lambda: "curtisthebot",
            "head_fn": lambda u: {"headRefOid": "abc1234def", "commits": []},
            "reviews_fn": lambda u: [self._review(commit_id="abc1234def")],
            "labels_fn": lambda u: [{"name": "tp:human-approved:abc1234"}],
            "timeline_fn": lambda u: [{
                "event": "labeled",
                "label": {"name": "tp:human-approved:abc1234"},
                "actor": {"login": "curtisthe", "type": "User"},
                "created_at": "2026-06-16T01:00:00Z",
            }],
            "commits_fn": lambda u: [],
        }
        assert human_approved_on_head("https://github.com/o/r/pull/1", runners=runners) is True

    def test_stale_review_and_no_label_false(self):
        """Stale review (wrong commit_id) -> False."""
        from human_approval import human_approved_on_head
        r = self._runners(reviews=[self._review(commit_id="old")])
        assert human_approved_on_head("https://github.com/o/r/pull/1", runners=r) is False

    def test_reviews_fn_raises_is_false(self):
        """A raising reviews_fn -> _safe_fetch -> [] -> review path not satisfied -> False.

        After retire-approval-tags there is no label path to fall back to.
        """
        from human_approval import human_approved_on_head

        def _raises(_url=None):
            raise RuntimeError("review fetch failed")

        r = self._runners(reviews=_raises)
        assert human_approved_on_head("https://github.com/o/r/pull/1", runners=r) is False


# ============================================================
# Task 2.3: gate-output contract — pred_human_approved mapping
# ============================================================


class TestGateOutputContract:
    """The thin wrapper's verdict mapping must survive the Phase-2 restructure.

    pred_human_approved maps human_approved_on_head True->PASS and False->INDETERMINATE
    (never FAIL, never PASS-on-False). No production change is expected here — this pins
    the contract so a future edit to the predicate that leaks a wrong boolean is caught at
    the GATE-OUTPUT level, not just the predicate level.
    """

    REVIEW_HEAD = {"headRefOid": "h", "commits": []}

    def _runners(self, *, reviews, labels=None, timeline=None, head=None):
        return {
            "self_login_fn": lambda: "curtisthebot",
            "labels_fn": lambda u: labels or [],
            "timeline_fn": lambda u: timeline or [],
            "head_fn": lambda u: head or self.REVIEW_HEAD,
            "commits_fn": lambda u: [],
            "reviews_fn": lambda u: reviews,
        }

    def _approved(self):
        return [{"user": {"login": "curtisthe", "type": "User"}, "state": "APPROVED",
                 "submitted_at": "2026-06-16T01:00:00Z", "commit_id": "h"}]

    def test_review_path_satisfied_maps_to_PASS(self):
        from deterministic_gate import pred_human_approved, GateVerdict
        r = self._runners(reviews=self._approved())
        res = pred_human_approved("https://github.com/o/r/pull/1", runners=r)
        assert res.verdict == GateVerdict.PASS

    def test_neither_path_maps_to_INDETERMINATE_not_FAIL(self):
        from deterministic_gate import pred_human_approved, GateVerdict
        r = self._runners(reviews=[])  # no label, no review
        res = pred_human_approved("https://github.com/o/r/pull/1", runners=r)
        assert res.verdict == GateVerdict.INDETERMINATE
        assert res.verdict != GateVerdict.FAIL
        assert res.verdict != GateVerdict.PASS
