"""Integration tests for the review path wired into the merge-gate predicate.

Split from test_human_approval_review.py (Phase-2 integration vs Phase-1 unit helpers)
to keep each test module under the soft-warn cap. Covers: the `reviews_fn` runner key,
the dual-path (label OR review) `human_approved_on_head`, and the `pred_human_approved`
gate-output contract. All tests inject runners — NO live gh/git.
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
# Task 2.2: human_approved_on_head dual-path (label OR review)
# ============================================================


def _raises(_url=None):
    raise RuntimeError("review fetch failed")


class TestHumanApprovedDualPath:
    """Integration over human_approved_on_head with fully-injected runners.

    All six runner keys are provided so the F4 per-key resolution never falls back to
    live gh. self_login is `curtisthebot` (lands in the automation set).
    """

    def _runners(self, *, labels, timeline, head, reviews):
        return {
            "self_login_fn": lambda: "curtisthebot",
            "labels_fn": lambda u: labels,
            "timeline_fn": lambda u: timeline,
            "head_fn": lambda u: head,
            "commits_fn": lambda u: [],
            "reviews_fn": (reviews if callable(reviews) else (lambda u: reviews)),
        }

    # --- review-path fixtures (currency = commit_id == headRefOid, any string) ---
    def _review(self, state="APPROVED", commit_id="h", login="curtisthe"):
        return {"user": {"login": login, "type": "User"}, "state": state,
                "submitted_at": "2026-06-16T01:00:00Z", "commit_id": commit_id}

    REVIEW_HEAD = {"headRefOid": "h", "commits": []}

    # --- label-path fixtures (currency = hex tag prefix of headRefOid) ---
    LABEL_HEAD = {"headRefOid": "abc1234def", "commits": []}

    def _label_runner_parts(self):
        labels = [{"name": "tp:human-approved:abc1234"}]
        timeline = [{"event": "labeled",
                     "label": {"name": "tp:human-approved:abc1234"},
                     "actor": {"login": "curtisthe", "type": "User"},
                     "created_at": "2026-06-16T01:00:00Z"}]
        return labels, timeline

    def test_review_only_passes(self):
        from human_approval import human_approved_on_head
        r = self._runners(labels=[], timeline=[], head=self.REVIEW_HEAD,
                          reviews=[self._review()])
        assert human_approved_on_head("https://github.com/o/r/pull/1", runners=r) is True

    def test_label_only_passes_regression(self):
        from human_approval import human_approved_on_head
        labels, timeline = self._label_runner_parts()
        r = self._runners(labels=labels, timeline=timeline, head=self.LABEL_HEAD, reviews=[])
        assert human_approved_on_head("https://github.com/o/r/pull/1", runners=r) is True

    def test_neither_false(self):
        from human_approval import human_approved_on_head
        r = self._runners(labels=[], timeline=[], head=self.REVIEW_HEAD, reviews=[])
        assert human_approved_on_head("https://github.com/o/r/pull/1", runners=r) is False

    def test_both_true(self):
        from human_approval import human_approved_on_head
        labels, timeline = self._label_runner_parts()
        r = self._runners(labels=labels, timeline=timeline, head=self.LABEL_HEAD,
                          reviews=[self._review(commit_id="abc1234def")])
        assert human_approved_on_head("https://github.com/o/r/pull/1", runners=r) is True

    def test_stale_review_and_no_label_false(self):
        from human_approval import human_approved_on_head
        r = self._runners(labels=[], timeline=[], head=self.REVIEW_HEAD,
                          reviews=[self._review(commit_id="old")])
        assert human_approved_on_head("https://github.com/o/r/pull/1", runners=r) is False

    def test_reviews_fn_raises_label_path_still_carries(self):
        # Mechanism-level isolation (Ada/Feynman E): a raising reviews_fn must be swallowed
        # by _safe_fetch to [] (review path -> False) while the VALID label path is still
        # evaluated and carries the True. Asserts the return is the label path's value, not
        # merely that no exception escaped.
        from human_approval import human_approved_on_head
        labels, timeline = self._label_runner_parts()
        r = self._runners(labels=labels, timeline=timeline, head=self.LABEL_HEAD,
                          reviews=_raises)
        assert human_approved_on_head("https://github.com/o/r/pull/1", runners=r) is True


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
