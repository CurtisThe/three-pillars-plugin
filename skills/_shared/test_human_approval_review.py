"""Tests for human_approval_review.py — the APPROVED-review merge-gate path.

All tests inject reviews/head dicts — NO live gh/git calls (the established
test_human_approval.py / test_review_readiness.py convention). This module
covers the review path that satisfies `human_approved_on_head` in ADDITION to
the SHA-tagged label path; the label path's own tests live in
test_human_approval.py and must stay green (regression — see Phase 2).
"""

from __future__ import annotations


# ============================================================
# Task 1.1: _review_current_on_head (commit_id == headRefOid)
# ============================================================


class TestReviewCurrentOnHead:
    def _head(self, oid):
        return {"headRefOid": oid}

    def test_equal_is_current(self):
        from human_approval_review import _review_current_on_head
        assert _review_current_on_head(
            {"commit_id": "abc123def456"}, self._head("abc123def456")
        ) is True

    def test_mismatch_not_current(self):
        from human_approval_review import _review_current_on_head
        assert _review_current_on_head(
            {"commit_id": "52b71e8"}, self._head("07bec3b")
        ) is False

    def test_case_folded_equal(self):
        from human_approval_review import _review_current_on_head
        # GitHub returns lowercase hex; a value typed/echoed uppercase still matches.
        assert _review_current_on_head(
            {"commit_id": "ABC123DEF456"}, self._head("abc123def456")
        ) is True

    def test_missing_commit_id(self):
        from human_approval_review import _review_current_on_head
        assert _review_current_on_head({}, self._head("abc123")) is False

    def test_empty_commit_id(self):
        from human_approval_review import _review_current_on_head
        assert _review_current_on_head(
            {"commit_id": ""}, self._head("abc123")
        ) is False

    def test_missing_head_oid(self):
        from human_approval_review import _review_current_on_head
        assert _review_current_on_head({"commit_id": "abc123"}, {}) is False

    def test_empty_head_oid(self):
        from human_approval_review import _review_current_on_head
        assert _review_current_on_head(
            {"commit_id": "abc123"}, {"headRefOid": ""}
        ) is False

    def test_non_dict_review(self):
        from human_approval_review import _review_current_on_head
        assert _review_current_on_head("nope", self._head("abc123")) is False

    def test_non_dict_head(self):
        from human_approval_review import _review_current_on_head
        assert _review_current_on_head({"commit_id": "abc123"}, "nope") is False

    def test_alien_input_never_raises(self):
        # Totality (Feynman F5): wholly alien inputs fail closed, never raise.
        from human_approval_review import _review_current_on_head
        for bad in (None, 7, [1, 2], {"commit_id": 3}, {"commit_id": None}):
            assert _review_current_on_head(bad, self._head("abc123")) is False
        assert _review_current_on_head({"commit_id": "abc"}, [None]) is False


# ============================================================
# Task 1.2: _review_author_is_human (reuse identity guards verbatim)
# ============================================================


class TestReviewAuthorIsHuman:
    def _automation(self, self_login="curtisthebot"):
        from human_approval import automation_identities
        return automation_identities(self_login=self_login, config=None)

    def _rev(self, login, type_="User"):
        return {"user": {"login": login, "type": type_}}

    def test_human_user_passes(self):
        from human_approval_review import _review_author_is_human
        assert _review_author_is_human(self._rev("curtisthe"), self._automation()) is True

    def test_bot_type_rejected(self):
        from human_approval_review import _review_author_is_human
        # type=="Bot" is the App-installation-token floor — rejected even off the set.
        assert _review_author_is_human(
            self._rev("some-app", type_="Bot"), self._automation()
        ) is False

    def test_bot_suffix_login_rejected(self):
        from human_approval_review import _review_author_is_human
        # [bot]-suffix catch-all backstop for unenumerated App actors.
        assert _review_author_is_human(
            self._rev("random-tool[bot]"), self._automation()
        ) is False

    def test_self_login_in_automation_rejected(self):
        from human_approval_review import _review_author_is_human
        # The framework's own gh-auth login lands in the automation set (case-folded).
        assert _review_author_is_human(self._rev("CurtisTheBot"), self._automation()) is False

    def test_missing_user_rejected(self):
        from human_approval_review import _review_author_is_human
        # adapter yields {"actor": None}; the guard's isinstance(actor, dict) backstops it.
        assert _review_author_is_human({}, self._automation()) is False

    def test_none_user_rejected(self):
        from human_approval_review import _review_author_is_human
        assert _review_author_is_human({"user": None}, self._automation()) is False

    def test_non_dict_review_rejected(self):
        from human_approval_review import _review_author_is_human
        assert _review_author_is_human("nope", self._automation()) is False
        assert _review_author_is_human(None, self._automation()) is False

    def test_empty_string_self_login_boundary(self):
        # Ada/Feynman: an UNRESOLVABLE self_login ("") must not authorize anyone.
        # automation_identities drops a falsy self_login, so the set is the bot floor;
        # a reviewer with an empty login fails the human-actor floor (fail-closed), and
        # a real human login still passes (the empty self_login didn't poison the set).
        from human_approval_review import _review_author_is_human
        automation = self._automation(self_login="")
        assert _review_author_is_human(self._rev(""), automation) is False
        assert _review_author_is_human(self._rev("curtisthe"), automation) is True


# ============================================================
# Task 1.3: latest_human_review (filter-to-human, then latest)
# ============================================================


class TestLatestHumanReview:
    def _automation(self):
        from human_approval import automation_identities
        return automation_identities(self_login="curtisthebot", config=None)

    def _human(self, state, t, login="curtisthe"):
        return {"user": {"login": login, "type": "User"}, "state": state,
                "submitted_at": t, "commit_id": "h"}

    def _bot(self, state, t, login="github-actions[bot]"):
        return {"user": {"login": login, "type": "Bot"}, "state": state,
                "submitted_at": t, "commit_id": "h"}

    def test_newest_human_wins(self):
        from human_approval_review import latest_human_review
        revs = [self._human("APPROVED", "2026-06-16T01:00:00Z"),
                self._human("CHANGES_REQUESTED", "2026-06-16T03:00:00Z")]
        assert latest_human_review(revs, self._automation())["submitted_at"] == "2026-06-16T03:00:00Z"

    def test_bot_reviews_excluded(self):
        from human_approval_review import latest_human_review
        # A bot review later than the only human review must not be selected.
        revs = [self._human("APPROVED", "2026-06-16T01:00:00Z"),
                self._bot("COMMENTED", "2026-06-16T09:00:00Z")]
        latest = latest_human_review(revs, self._automation())
        assert latest["user"]["login"] == "curtisthe"
        assert latest["state"] == "APPROVED"

    def test_older_human_not_chosen_over_newer_human(self):
        from human_approval_review import latest_human_review
        revs = [self._human("APPROVED", "2026-06-16T01:00:00Z"),
                self._human("CHANGES_REQUESTED", "2026-06-16T05:00:00Z")]
        # newer human (CHANGES_REQUESTED) is the selection — state is checked downstream.
        assert latest_human_review(revs, self._automation())["state"] == "CHANGES_REQUESTED"

    def test_bot_comment_then_human_approved(self):
        # Named security row (Feynman F2): bot COMMENTED at T2 > human APPROVED at T1.
        # The human-author filter fires BEFORE the max(submitted_at), so the trailing
        # bot comment cannot clobber the standing human approval.
        from human_approval_review import latest_human_review
        revs = [self._human("APPROVED", "2026-06-16T01:00:00Z"),
                self._bot("COMMENTED", "2026-06-16T02:00:00Z")]
        latest = latest_human_review(revs, self._automation())
        assert latest["state"] == "APPROVED"
        assert latest["submitted_at"] == "2026-06-16T01:00:00Z"

    def test_empty_list_none(self):
        from human_approval_review import latest_human_review
        assert latest_human_review([], self._automation()) is None

    def test_only_bots_none(self):
        from human_approval_review import latest_human_review
        assert latest_human_review([self._bot("APPROVED", "t")], self._automation()) is None

    def test_non_list_none(self):
        from human_approval_review import latest_human_review
        assert latest_human_review("nope", self._automation()) is None
        assert latest_human_review(None, self._automation()) is None

    def test_malformed_entries_skipped_never_raise(self):
        from human_approval_review import latest_human_review
        revs = [None, 7, "x", {"user": None}, self._human("APPROVED", "2026-06-16T01:00:00Z")]
        assert latest_human_review(revs, self._automation())["state"] == "APPROVED"


# ============================================================
# Task 1.4: review_path_satisfied (compose selection + state + currency)
# ============================================================


class TestReviewPathSatisfied:
    HEAD = {"headRefOid": "h"}

    def _automation(self):
        from human_approval import automation_identities
        return automation_identities(self_login="curtisthebot", config=None)

    def _human(self, state, t, commit_id="h", login="curtisthe"):
        return {"user": {"login": login, "type": "User"}, "state": state,
                "submitted_at": t, "commit_id": commit_id}

    def _call(self, revs):
        from human_approval_review import review_path_satisfied
        return review_path_satisfied(revs, self.HEAD, automation=self._automation())

    def test_approved_current_human_true(self):
        assert self._call([self._human("APPROVED", "t1")]) is True

    def test_latest_human_changes_requested_false(self):
        assert self._call([self._human("CHANGES_REQUESTED", "t1")]) is False

    def test_latest_human_commented_false(self):
        assert self._call([self._human("COMMENTED", "t1")]) is False

    def test_approved_but_stale_commit_false(self):
        assert self._call([self._human("APPROVED", "t1", commit_id="old")]) is False

    def test_bot_approved_no_human_false(self):
        revs = [{"user": {"login": "github-actions[bot]", "type": "Bot"},
                 "state": "APPROVED", "submitted_at": "t1", "commit_id": "h"}]
        assert self._call(revs) is False

    def test_changes_requested_supersedes_approved(self):
        # Named PRIMARY regression guard (Feynman F3): an early human APPROVED at T1
        # followed by a later human CHANGES_REQUESTED at T2 (a bad push) must NOT slip
        # through — the latest human review is CHANGES_REQUESTED → not satisfied.
        revs = [self._human("APPROVED", "2026-06-16T01:00:00Z"),
                self._human("CHANGES_REQUESTED", "2026-06-16T02:00:00Z")]
        assert self._call(revs) is False

    def test_empty_and_non_list_false(self):
        assert self._call([]) is False
        assert self._call("nope") is False
        assert self._call(None) is False

    def test_malformed_payloads_false(self):
        assert self._call([None, 7, {"user": None}]) is False


