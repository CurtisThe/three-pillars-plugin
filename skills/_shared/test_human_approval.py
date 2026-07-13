"""Tests for human_approval.py — the REQUIRED human-approval read-path predicate.

All tests inject runners/stubs — NO live gh/git calls (the established
test_deterministic_gate.py / test_review_readiness.py convention).

After retire-approval-tags: label path REMOVED. tp:human-approved label has NO
effect; the sole path is a non-automation human APPROVED review current on head
(Path B, human_approval_review.review_path_satisfied). Label-only scenarios
MUST return False.
"""

from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent


# ============================================================
# Task 1.4: automation_identities (hybrid set, D3)
# ============================================================


class TestAutomationIdentities:
    def test_hardcoded_floor_present(self):
        from human_approval import automation_identities

        s = automation_identities(self_login="alice", config=None)
        for bot in (
            "github-actions[bot]",
            "github-actions",
            "copilot[bot]",
            "copilot-pull-request-reviewer[bot]",
            "github-copilot[bot]",
            "copilot",
            "dependabot[bot]",
        ):
            assert bot in s, f"{bot} missing from automation floor"

    def test_self_login_included_lowercased(self):
        from human_approval import automation_identities

        s = automation_identities(self_login="CurtisThe", config=None)
        assert "curtisthe" in s

    def test_self_login_none_no_crash(self):
        from human_approval import automation_identities

        s = automation_identities(self_login=None, config=None)
        # floor still present, no empty-string member
        assert "github-actions" in s
        assert "" not in s

    def test_config_additions_lowercased(self):
        from human_approval import automation_identities

        config = {"review": {"automation_identities": ["Svc-CI", "another-bot"]}}
        s = automation_identities(self_login="alice", config=config)
        assert "svc-ci" in s
        assert "another-bot" in s
        assert "alice" in s

    def test_non_dict_config_ignored(self):
        from human_approval import automation_identities

        s = automation_identities(self_login="alice", config="nope")
        assert "github-actions" in s
        assert "alice" in s

    def test_non_dict_review_ignored(self):
        from human_approval import automation_identities

        s = automation_identities(self_login="alice", config={"review": "nope"})
        assert "alice" in s

    def test_non_list_automation_identities_ignored(self):
        from human_approval import automation_identities

        s = automation_identities(
            self_login="alice", config={"review": {"automation_identities": "svc-ci"}}
        )
        # not exploded into characters; just ignored
        assert "svc-ci" not in s
        assert "alice" in s

    def test_all_members_lowercase(self):
        from human_approval import automation_identities

        s = automation_identities(
            self_login="MiXeD", config={"review": {"automation_identities": ["UPPER"]}}
        )
        assert all(m == m.lower() for m in s)


# ============================================================
# Task 1.5: _actor_is_human (bot/App/automation floor, F2)
# ============================================================


class TestActorIsHuman:
    def test_human_user_not_in_automation(self):
        from human_approval import _actor_is_human

        ev = {"actor": {"login": "alice", "type": "User"}}
        assert _actor_is_human(ev, frozenset({"github-actions"})) is True

    def test_bot_type_rejected(self):
        from human_approval import _actor_is_human

        ev = {"actor": {"login": "github-actions[bot]", "type": "Bot"}}
        assert _actor_is_human(ev, frozenset()) is False

    def test_bot_suffix_backstop_not_in_set(self):
        """A [bot]-suffixed login not in the hardcoded set is still rejected via
        the _is_bot_login backstop, even with type User."""
        from human_approval import _actor_is_human

        ev = {"actor": {"login": "randombot[bot]", "type": "User"}}
        assert _actor_is_human(ev, frozenset()) is False

    def test_f2_self_login_in_automation_rejected(self):
        """F2: a User-type actor whose login is the resolved self login (in the
        automation set) is rejected — the user-PAT spoof the type==User test alone
        would have admitted."""
        from human_approval import _actor_is_human

        ev = {"actor": {"login": "curtisthe", "type": "User"}}
        assert _actor_is_human(ev, frozenset({"curtisthe"})) is False

    def test_automation_login_case_insensitive(self):
        from human_approval import _actor_is_human

        ev = {"actor": {"login": "Svc-CI", "type": "User"}}
        assert _actor_is_human(ev, frozenset({"svc-ci"})) is False

    def test_missing_actor_rejected(self):
        from human_approval import _actor_is_human

        assert _actor_is_human({}, frozenset()) is False
        assert _actor_is_human({"actor": None}, frozenset()) is False
        assert _actor_is_human({"actor": {}}, frozenset()) is False

    def test_malformed_never_raises(self):
        from human_approval import _actor_is_human

        assert _actor_is_human(None, frozenset()) is False
        assert _actor_is_human({"actor": "notadict"}, frozenset()) is False


class TestIsBotLogin:
    def test_bot_suffix(self):
        from human_approval import _is_bot_login

        assert _is_bot_login("github-actions[bot]") is True
        assert _is_bot_login("randombot[bot]") is True

    def test_human_login(self):
        from human_approval import _is_bot_login

        assert _is_bot_login("alice") is False

    def test_empty_or_none(self):
        from human_approval import _is_bot_login

        assert _is_bot_login("") is False
        assert _is_bot_login(None) is False


# ============================================================
# Task 1.6: _approver_not_automation (distinctness, F3)
# ============================================================


class TestApproverNotAutomation:
    def test_approver_not_in_automation(self):
        from human_approval import _approver_not_automation

        ev = {"actor": {"login": "alice", "type": "User"}}
        assert _approver_not_automation(ev, frozenset({"svc-ci"})) is True

    def test_approver_in_automation_rejected(self):
        from human_approval import _approver_not_automation

        ev = {"actor": {"login": "svc-ci", "type": "User"}}
        assert _approver_not_automation(ev, frozenset({"svc-ci"})) is False

    def test_f3_approver_equals_committer_allowed(self):
        """F3 regression: an approver login that equals the head committer login but
        is NOT in the automation set must PASS — committer-equality is ADVISORY, not
        a hard reject. This guards against re-introducing an approver != committer rule.
        The committer login is deliberately NOT a parameter of this fn."""
        from human_approval import _approver_not_automation

        # committer login is "curtisthe"; approver is also "curtisthe"; not in automation
        ev = {"actor": {"login": "curtisthe", "type": "User"}}
        assert _approver_not_automation(ev, frozenset({"github-actions"})) is True

    def test_case_insensitive(self):
        from human_approval import _approver_not_automation

        ev = {"actor": {"login": "Svc-CI", "type": "User"}}
        assert _approver_not_automation(ev, frozenset({"svc-ci"})) is False

    def test_missing_actor_rejected(self):
        from human_approval import _approver_not_automation

        assert _approver_not_automation({}, frozenset()) is False
        assert _approver_not_automation({"actor": {}}, frozenset()) is False
        assert _approver_not_automation(None, frozenset()) is False

    def test_signature_takes_no_committer(self):
        """Asserts the fn never compares approver against a committer — it has a
        2-arg signature (event, automation), no committer parameter."""
        import inspect
        from human_approval import _approver_not_automation

        params = list(inspect.signature(_approver_not_automation).parameters)
        assert params == ["event", "automation"], (
            f"_approver_not_automation must not take a committer arg; got {params}"
        )


# ============================================================
# Task 1.8: human_approved_on_head (review-sole-path, label-no-effect)
# ============================================================

PR_URL = "https://github.com/example/repo/pull/7"

HEAD_OID = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
OTHER_OID = "9988776655443322110aabbccddeeff001122334"
LABEL = "tp:human-approved"
TAG = "a1b2c3d4e5f6"
TAGGED_LABEL = LABEL + ":" + TAG


def _review(state="APPROVED", commit_id=HEAD_OID, login="alice", user_type="User"):
    """Build a review entry (REST shape: user.login/user.type/state/commit_id)."""
    return {
        "user": {"login": login, "type": user_type},
        "state": state,
        "submitted_at": "2026-06-08T14:00:00Z",
        "commit_id": commit_id,
    }


def _head(oid=HEAD_OID):
    return {"headRefOid": oid, "commits": []}


def _runners(
    *,
    reviews=None,
    head=None,
    self_login="ci-bot",
    self_raises=False,
    reviews_raises=False,
    # label-path keys still accepted so callers can confirm labels have NO effect
    labels=None,
    timeline=None,
):
    """Build a fully-injected runners dict.

    reviews_fn and head_fn drive the sole approval path (Path B).
    labels_fn and timeline_fn are provided if the caller wants to confirm
    label presence has no effect; they default to empty so Path A can't fire.
    """
    if head is None:
        head = _head()
    if reviews is None:
        reviews = [_review()]
    if labels is None:
        labels = []
    if timeline is None:
        timeline = []

    def self_fn():
        if self_raises:
            raise RuntimeError("self resolve failed")
        return self_login

    def reviews_fn(_url):
        if reviews_raises:
            raise RuntimeError("injected reviews failure")
        return reviews

    return {
        "self_login_fn": self_fn,
        "reviews_fn": reviews_fn,
        "head_fn": lambda _u: head,
        "labels_fn": lambda _u: labels,
        "timeline_fn": lambda _u: timeline,
        "commits_fn": lambda _u: [],
    }


class TestHumanApprovedOnHead:
    """human_approved_on_head — review is the SOLE path; label has no effect."""

    def test_pass_review_approved_current(self):
        """Core: APPROVED review with commit_id == headRefOid -> True."""
        from human_approval import human_approved_on_head

        assert human_approved_on_head(PR_URL, runners=_runners()) is True

    def test_label_only_no_review_is_false(self):
        """CRITICAL: tp:human-approved label present but NO review -> False.

        After retire-approval-tags the label path is REMOVED; label presence
        alone MUST NOT satisfy the predicate.
        """
        from human_approval import human_approved_on_head

        r = _runners(
            reviews=[],
            labels=[{"name": TAGGED_LABEL}],
            timeline=[{
                "event": "labeled",
                "label": {"name": TAGGED_LABEL},
                "actor": {"login": "alice", "type": "User"},
                "created_at": "2026-06-08T14:00:00Z",
            }],
        )
        assert human_approved_on_head(PR_URL, runners=r) is False

    def test_review_approved_current_passes_regardless_of_label(self):
        """Review alone satisfies the gate (label presence is ignored)."""
        from human_approval import human_approved_on_head

        # Both label present AND review present: passes via the review.
        r = _runners(
            reviews=[_review()],
            labels=[{"name": TAGGED_LABEL}],
        )
        assert human_approved_on_head(PR_URL, runners=r) is True

    def test_absent_review_is_false(self):
        """No review -> False."""
        from human_approval import human_approved_on_head

        assert human_approved_on_head(PR_URL, runners=_runners(reviews=[])) is False

    def test_stale_review_is_false(self):
        """Review with commit_id != headRefOid -> False (currency check)."""
        from human_approval import human_approved_on_head

        r = _runners(reviews=[_review(commit_id="stale000")])
        assert human_approved_on_head(PR_URL, runners=r) is False

    def test_bot_reviewer_is_false(self):
        """Bot-type reviewer is rejected by the automation floor."""
        from human_approval import human_approved_on_head

        r = _runners(reviews=[_review(login="github-actions[bot]", user_type="Bot")])
        assert human_approved_on_head(PR_URL, runners=r) is False

    def test_automation_login_reviewer_is_false(self):
        """Reviewer in config automation_identities -> False."""
        from human_approval import human_approved_on_head

        config = {"review": {"automation_identities": ["svc-ci"]}}
        r = _runners(reviews=[_review(login="svc-ci")])
        assert human_approved_on_head(PR_URL, runners=r, config=config) is False

    def test_f2_self_login_reviewer_is_false(self):
        """F2: reviewer login == self_login (automation set member) -> False."""
        from human_approval import human_approved_on_head

        r = _runners(reviews=[_review(login="curtisthe")], self_login="curtisthe")
        assert human_approved_on_head(PR_URL, runners=r) is False

    def test_f2_self_unresolvable_raises_fail_closed(self):
        from human_approval import human_approved_on_head

        r = _runners(self_raises=True)
        assert human_approved_on_head(PR_URL, runners=r) is False

    def test_f2_self_unresolvable_empty_fail_closed(self):
        from human_approval import human_approved_on_head

        assert human_approved_on_head(PR_URL, runners=_runners(self_login="")) is False
        assert human_approved_on_head(PR_URL, runners=_runners(self_login=None)) is False

    def test_reviews_fetch_failure_is_false(self):
        """reviews_fn raising -> _safe_fetch -> [] -> review path not satisfied -> False."""
        from human_approval import human_approved_on_head

        r = _runners(reviews_raises=True)
        assert human_approved_on_head(PR_URL, runners=r) is False

    def test_never_raises_on_garbage(self):
        """Total/fail-closed: any internal error -> False, never raises."""
        from human_approval import human_approved_on_head

        assert human_approved_on_head(PR_URL, runners=_runners(head="notadict")) is False

    def test_f4_partial_injection_no_keyerror(self):
        """F4: a partial runners dict (self_login_fn only, empty -> fail-closed)."""
        from human_approval import human_approved_on_head

        partial = {"self_login_fn": lambda: ""}
        assert human_approved_on_head(PR_URL, runners=partial) is False

    def test_f4_partial_injection_uses_live_fallback(self, monkeypatch):
        """F4: keys MISSING from a partial runners dict resolve via the per-key
        live fallback (``_build_live_runners``), not KeyError.

        Only ``self_login_fn`` is injected; ``head_fn`` + ``reviews_fn`` come from
        the live fallback, which here supplies a distinct human APPROVED review
        current on head -> True. Mutating ``_resolve`` to ``provided[key]`` (dropping
        the live fallback) raises KeyError -> the outer try/except fail-closes to
        False -> this assertion goes red. Pins what the removed
        ``test_empty_runners_dict_does_not_keyerror`` covered, for the surviving keys.
        """
        import human_approval

        monkeypatch.setattr(
            human_approval,
            "_build_live_runners",
            lambda pr_url: {
                "head_fn": lambda u: _head(),
                "reviews_fn": lambda u: [_review()],
                "self_login_fn": lambda: "framework-ci",
            },
        )
        partial = {"self_login_fn": lambda: "framework-ci"}
        assert human_approval.human_approved_on_head(PR_URL, runners=partial) is True

    def test_keys_constant_present(self):
        """reviews_fn key is in _HUMAN_APPROVAL_KEYS."""
        from human_approval import _HUMAN_APPROVAL_KEYS

        assert "reviews_fn" in _HUMAN_APPROVAL_KEYS
        assert "self_login_fn" in _HUMAN_APPROVAL_KEYS
        assert "head_fn" in _HUMAN_APPROVAL_KEYS


# ============================================================
# Task 2.1: _require_human_approval config interpreter (D4)
# ============================================================


class TestRequireHumanApproval:
    """The strict-by-default config interpreter (mirrors _expects_copilot_review)."""

    def test_none_config_is_strict_default_true(self):
        from human_approval import _require_human_approval

        assert _require_human_approval(None) is True

    def test_empty_dict_is_strict_default_true(self):
        from human_approval import _require_human_approval

        assert _require_human_approval({}) is True

    def test_explicit_false_opts_out(self):
        from human_approval import _require_human_approval

        assert _require_human_approval(
            {"review": {"require_human_approval": False}}
        ) is False

    def test_explicit_true_is_required(self):
        from human_approval import _require_human_approval

        assert _require_human_approval(
            {"review": {"require_human_approval": True}}
        ) is True

    def test_non_dict_review_is_strict_default_true(self):
        from human_approval import _require_human_approval

        assert _require_human_approval({"review": "yes"}) is True

    def test_absent_key_in_review_is_strict_default_true(self):
        from human_approval import _require_human_approval

        # review present but no require_human_approval key -> strict default
        assert _require_human_approval({"review": {"expects_copilot": False}}) is True

    def test_non_dict_config_is_strict_default_true(self):
        from human_approval import _require_human_approval

        assert _require_human_approval("not-a-dict") is True
