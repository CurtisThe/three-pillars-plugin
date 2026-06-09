"""Tests for human_approval.py — the REQUIRED human-approval read-path predicate.

All tests inject runners/stubs — NO live gh/git calls (the established
test_deterministic_gate.py / test_review_readiness.py convention).
"""

from __future__ import annotations

import os
from pathlib import Path

HERE = Path(__file__).resolve().parent

LABEL = "tp:human-approved"


# ============================================================
# Task 1.1: HUMAN_APPROVED_LABEL constant + _label_present
# ============================================================


class TestLabelPresent:
    def test_constant_value(self):
        from human_approval import HUMAN_APPROVED_LABEL

        assert HUMAN_APPROVED_LABEL == "tp:human-approved"

    def test_present(self):
        from human_approval import _label_present, HUMAN_APPROVED_LABEL

        assert _label_present([{"name": "tp:human-approved"}], HUMAN_APPROVED_LABEL) is True

    def test_present_among_others(self):
        from human_approval import _label_present, HUMAN_APPROVED_LABEL

        labels = [{"name": "other"}, {"name": "tp:human-approved"}, {"name": "x"}]
        assert _label_present(labels, HUMAN_APPROVED_LABEL) is True

    def test_absent(self):
        from human_approval import _label_present, HUMAN_APPROVED_LABEL

        assert _label_present([{"name": "other"}], HUMAN_APPROVED_LABEL) is False

    def test_empty_list(self):
        from human_approval import _label_present, HUMAN_APPROVED_LABEL

        assert _label_present([], HUMAN_APPROVED_LABEL) is False

    def test_malformed_entries_never_raise(self):
        from human_approval import _label_present, HUMAN_APPROVED_LABEL

        # non-dict entries, missing "name" keys, None — none should raise
        labels = [{}, None, 42, {"name": None}, "tp:human-approved", {"name": "tp:human-approved"}]
        assert _label_present(labels, HUMAN_APPROVED_LABEL) is True

    def test_malformed_only_is_false(self):
        from human_approval import _label_present, HUMAN_APPROVED_LABEL

        assert _label_present([{}, None, 42, {"name": None}], HUMAN_APPROVED_LABEL) is False

    def test_non_list_input(self):
        from human_approval import _label_present, HUMAN_APPROVED_LABEL

        assert _label_present(None, HUMAN_APPROVED_LABEL) is False
        assert _label_present("nope", HUMAN_APPROVED_LABEL) is False


# ============================================================
# Task 1.2: _latest_label_event
# ============================================================


HEAD_OID = "sha40"


def _labeled(login, created_at, *, name=LABEL, actor_type="User", commit_id=HEAD_OID):
    return {
        "event": "labeled",
        "created_at": created_at,
        # commit_id = the immutable head SHA at the instant GitHub recorded this event.
        # Currency binds to THIS (SHA-equality with the current head), not created_at.
        "commit_id": commit_id,
        "actor": {"login": login, "type": actor_type},
        "label": {"name": name},
    }


class TestLatestLabelEvent:
    def test_single_event(self):
        from human_approval import _latest_label_event

        tl = [_labeled("alice", "2026-06-08T14:03:11Z")]
        ev = _latest_label_event(tl, LABEL)
        assert ev is not None
        assert ev["actor"]["login"] == "alice"

    def test_most_recent_wins(self):
        from human_approval import _latest_label_event

        tl = [
            _labeled("old", "2026-06-08T10:00:00Z"),
            _labeled("new", "2026-06-08T14:00:00Z"),
        ]
        ev = _latest_label_event(tl, LABEL)
        assert ev["actor"]["login"] == "new"

    def test_most_recent_wins_regardless_of_list_order(self):
        from human_approval import _latest_label_event

        tl = [
            _labeled("new", "2026-06-08T14:00:00Z"),
            _labeled("old", "2026-06-08T10:00:00Z"),
        ]
        ev = _latest_label_event(tl, LABEL)
        assert ev["actor"]["login"] == "new"

    def test_ignores_non_labeled_events(self):
        from human_approval import _latest_label_event

        tl = [
            {"event": "unlabeled", "created_at": "2026-06-08T15:00:00Z",
             "label": {"name": LABEL}, "actor": {"login": "x", "type": "User"}},
            {"event": "commented", "created_at": "2026-06-08T16:00:00Z"},
            _labeled("alice", "2026-06-08T10:00:00Z"),
        ]
        ev = _latest_label_event(tl, LABEL)
        assert ev["actor"]["login"] == "alice"

    def test_ignores_other_labels(self):
        from human_approval import _latest_label_event

        tl = [
            _labeled("bob", "2026-06-08T16:00:00Z", name="tp:ready-for-human-merge"),
            _labeled("alice", "2026-06-08T10:00:00Z"),
        ]
        ev = _latest_label_event(tl, LABEL)
        assert ev["actor"]["login"] == "alice"

    def test_none_when_no_matching_event(self):
        from human_approval import _latest_label_event

        tl = [_labeled("bob", "2026-06-08T16:00:00Z", name="other")]
        assert _latest_label_event(tl, LABEL) is None

    def test_empty_list(self):
        from human_approval import _latest_label_event

        assert _latest_label_event([], LABEL) is None

    def test_non_list(self):
        from human_approval import _latest_label_event

        assert _latest_label_event(None, LABEL) is None
        assert _latest_label_event("nope", LABEL) is None

    def test_malformed_events_never_raise(self):
        from human_approval import _latest_label_event

        tl = [
            None,
            42,
            {},
            {"event": "labeled"},  # no label, no created_at
            {"event": "labeled", "label": None},
            {"event": "labeled", "label": {"name": LABEL}},  # no created_at
            _labeled("alice", "2026-06-08T10:00:00Z"),
        ]
        ev = _latest_label_event(tl, LABEL)
        assert ev is not None
        assert ev["actor"]["login"] == "alice"


# ============================================================
# Task 1.3: _committer_logins (F1 REST shape)
# ============================================================


class TestCommitterLogins:
    def test_rest_top_level_committer_and_author(self):
        from human_approval import _committer_logins

        commits = [
            {"sha": "a", "committer": {"login": "Old"}, "author": {"login": "Old"}},
            {"sha": "b", "committer": {"login": "CurtisThe"}, "author": {"login": "AuthorX"}},
        ]
        # last entry only, lowercased
        assert _committer_logins(commits) == frozenset({"curtisthe", "authorx"})

    def test_f1_graphql_shape_yields_empty(self):
        """F1 regression: the GraphQL `gh pr view --json commits` shape has NO
        top-level committer/author login — only commit.committer name/email/date.
        Reading committer from THIS shape (the old bug) must yield the empty set,
        proving _committer_logins reads the REST top-level source, not commit.committer."""
        from human_approval import _committer_logins

        graphql_shaped = [
            {
                "oid": "sha40",
                "committedDate": "2026-06-08T13:59:00Z",
                "authoredDate": "2026-06-08T13:59:00Z",
                "authors": [{"login": "bob", "email": "b@x", "name": "Bob"}],
                "commit": {"committer": {"name": "Bob", "email": "b@x", "date": "..."}},
            }
        ]
        assert _committer_logins(graphql_shaped) == frozenset()

    def test_null_account_committer_dropped(self):
        from human_approval import _committer_logins

        commits = [{"committer": {"login": None}, "author": {}}]
        assert _committer_logins(commits) == frozenset()

    def test_empty_list(self):
        from human_approval import _committer_logins

        assert _committer_logins([]) == frozenset()

    def test_non_list(self):
        from human_approval import _committer_logins

        assert _committer_logins(None) == frozenset()
        assert _committer_logins("nope") == frozenset()

    def test_malformed_last_entry_never_raises(self):
        from human_approval import _committer_logins

        assert _committer_logins([{"committer": "notadict"}]) == frozenset()
        assert _committer_logins([None]) == frozenset()
        assert _committer_logins([42]) == frozenset()


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
# Task 1.7: _approval_current_on_head (currency, load-bearing)
# ============================================================


def _head(committed_date=None, *, oid="sha40"):
    """A head payload. committed_date is retained as an optional positional for the
    legacy call sites' readability but is NOT consulted by the SHA-equality currency
    predicate — only headRefOid (oid) is load-bearing now."""
    return {
        "headRefOid": oid,
        "commits": [
            {"oid": "older", "committedDate": "2026-06-08T10:00:00Z"},
            {"oid": oid, "committedDate": committed_date or "2026-06-08T13:00:00Z"},
        ],
    }


class TestApprovalCurrentOnHead:
    def test_current_oid_matches_head(self):
        from human_approval import _approval_current_on_head

        ev = {"commit_id": "sha40", "created_at": "2026-06-08T14:00:00Z"}
        assert _approval_current_on_head(ev, _head(oid="sha40")) is True

    def test_stale_oid_differs_from_head(self):
        from human_approval import _approval_current_on_head

        # approval recorded against an OLD head; the PR head has since advanced
        ev = {"commit_id": "oldsha", "created_at": "2026-06-08T14:00:00Z"}
        assert _approval_current_on_head(ev, _head(oid="newsha")) is False

    def test_backdated_committer_date_cannot_revive_stale(self):
        """CRITICAL regression: a backdated label event timestamp (created_at far in
        the past, or a head whose committer date was forged via GIT_COMMITTER_DATE)
        must NOT make a stale approval current. Currency is SHA-equality, so even an
        event timestamp >= a forged head committedDate FAILS when the OIDs differ."""
        from human_approval import _approval_current_on_head

        ev = {"commit_id": "approved_old_sha", "created_at": "2030-01-01T00:00:00Z"}
        # head's committer date forged to look OLD (2020) — irrelevant; OID differs
        head = {
            "headRefOid": "new_unapproved_sha",
            "commits": [{"oid": "new_unapproved_sha", "committedDate": "2020-01-01T00:00:00Z"}],
        }
        assert _approval_current_on_head(ev, head) is False

    def test_missing_head_oid(self):
        from human_approval import _approval_current_on_head

        ev = {"commit_id": "sha40"}
        assert _approval_current_on_head(ev, {"commits": []}) is False
        assert _approval_current_on_head(ev, {}) is False
        assert _approval_current_on_head(ev, {"headRefOid": ""}) is False

    def test_missing_event_commit_id(self):
        from human_approval import _approval_current_on_head

        # no commit_id on the event -> cannot bind -> fail-closed (NOT fail-open to ts)
        assert _approval_current_on_head({"created_at": "2026-06-08T13:00:00Z"}, _head(oid="sha40")) is False
        assert _approval_current_on_head({"commit_id": ""}, _head(oid="sha40")) is False
        assert _approval_current_on_head({}, _head(oid="sha40")) is False
        assert _approval_current_on_head(None, _head(oid="sha40")) is False

    def test_malformed_head_never_raises(self):
        from human_approval import _approval_current_on_head

        ev = {"commit_id": "sha40"}
        assert _approval_current_on_head(ev, None) is False
        assert _approval_current_on_head(ev, "nope") is False
        assert _approval_current_on_head(ev, {"headRefOid": None}) is False
        assert _approval_current_on_head(ev, {"headRefOid": 42}) is False


# ============================================================
# Task 1.8: human_approved_on_head (per-key F4 + F2 fail-closed self)
# ============================================================

PR_URL = "https://github.com/example/repo/pull/7"


def _runners(
    *,
    labels=None,
    timeline=None,
    head=None,
    commits=None,
    self_login="ci-bot",
    labels_raises=False,
    timeline_raises=False,
    head_raises=False,
    commits_raises=False,
    self_raises=False,
):
    """Build an injected runners dict. Defaults form a happy-path PASS scenario."""
    if labels is None:
        labels = [{"name": LABEL}]
    if timeline is None:
        timeline = [_labeled("alice", "2026-06-08T14:00:00Z")]
    if head is None:
        head = _head("2026-06-08T13:00:00Z")
    if commits is None:
        commits = [{"committer": {"login": "alice"}, "author": {"login": "alice"}}]

    def _ret(value, raises):
        def fn(*a, **k):
            if raises:
                raise RuntimeError("injected gh failure")
            return value
        return fn

    def self_fn(*a, **k):
        if self_raises:
            raise RuntimeError("self resolve failed")
        return self_login

    return {
        "labels_fn": _ret(labels, labels_raises),
        "timeline_fn": _ret(timeline, timeline_raises),
        "head_fn": _ret(head, head_raises),
        "commits_fn": _ret(commits, commits_raises),
        "self_login_fn": self_fn,
    }


class TestHumanApprovedOnHead:
    def test_pass_human_current(self):
        from human_approval import human_approved_on_head

        assert human_approved_on_head(PR_URL, runners=_runners()) is True

    def test_pass_solo_operator_f3(self):
        """F3 regression / critical satisfiability: approver == committer == self,
        and that single login is NOT in the automation set -> True."""
        from human_approval import human_approved_on_head

        r = _runners(
            timeline=[_labeled("solo", "2026-06-08T14:00:00Z")],
            commits=[{"committer": {"login": "solo"}, "author": {"login": "solo"}}],
            self_login=None,  # self unresolvable would fail; use a non-automation self below
        )
        # self must be resolvable and NOT equal to the approver for this to PASS,
        # OR self must be resolvable but a different login. The point: a single-account
        # operator whose login is not in automation passes. Here self resolves to "ci-bot"
        # (some other resolvable login) so the approver "solo" stays human.
        r = _runners(
            timeline=[_labeled("solo", "2026-06-08T14:00:00Z")],
            commits=[{"committer": {"login": "solo"}, "author": {"login": "solo"}}],
            self_login="ci-bot",
        )
        assert human_approved_on_head(PR_URL, runners=r) is True

    def test_pass_true_solo_self_equals_approver_would_fail(self):
        """When the approver login EQUALS the resolved self login, it is in the
        automation set (self is always added) -> rejected. This is the F2 user-PAT
        self-applied case; the genuinely-solo-but-distinct-from-self operator passes
        via test_pass_solo_operator_f3. Documents the boundary."""
        from human_approval import human_approved_on_head

        r = _runners(
            timeline=[_labeled("curtisthe", "2026-06-08T14:00:00Z")],
            commits=[{"committer": {"login": "curtisthe"}, "author": {"login": "curtisthe"}}],
            self_login="curtisthe",
        )
        assert human_approved_on_head(PR_URL, runners=r) is False

    def test_absent_label(self):
        from human_approval import human_approved_on_head

        assert human_approved_on_head(PR_URL, runners=_runners(labels=[])) is False

    def test_bot_actor(self):
        from human_approval import human_approved_on_head

        r = _runners(
            timeline=[
                {
                    "event": "labeled",
                    "created_at": "2026-06-08T14:00:00Z",
                    "actor": {"login": "github-actions[bot]", "type": "Bot"},
                    "label": {"name": LABEL},
                }
            ]
        )
        assert human_approved_on_head(PR_URL, runners=r) is False

    def test_bot_suffix_not_in_hardcoded_set(self):
        from human_approval import human_approved_on_head

        r = _runners(timeline=[_labeled("randombot[bot]", "2026-06-08T14:00:00Z")])
        assert human_approved_on_head(PR_URL, runners=r) is False

    def test_f2_user_pat_self_applied(self):
        """F2: actor {type:User, login:curtisthe} where self_login_fn -> curtisthe.
        Self is in the automation set, so _actor_is_human / _approver_not_automation
        reject it — the user-PAT spoof the type==User test alone would have admitted."""
        from human_approval import human_approved_on_head

        r = _runners(
            timeline=[_labeled("curtisthe", "2026-06-08T14:00:00Z")],
            self_login="curtisthe",
        )
        assert human_approved_on_head(PR_URL, runners=r) is False

    def test_configured_automation_approver(self):
        """Multi-account SoD: approver in review.automation_identities -> False."""
        from human_approval import human_approved_on_head

        r = _runners(timeline=[_labeled("svc-ci", "2026-06-08T14:00:00Z")])
        config = {"review": {"automation_identities": ["svc-ci"]}}
        assert human_approved_on_head(PR_URL, runners=r, config=config) is False

    def test_f2_self_unresolvable_raises_fail_closed(self):
        from human_approval import human_approved_on_head

        r = _runners(self_raises=True)
        assert human_approved_on_head(PR_URL, runners=r) is False

    def test_f2_self_unresolvable_empty_fail_closed(self):
        from human_approval import human_approved_on_head

        assert human_approved_on_head(PR_URL, runners=_runners(self_login="")) is False
        assert human_approved_on_head(PR_URL, runners=_runners(self_login=None)) is False

    def test_stale(self):
        from human_approval import human_approved_on_head

        # approval recorded its commit_id against an OLD head; PR head has advanced
        r = _runners(
            timeline=[_labeled("alice", "2026-06-08T12:00:00Z", commit_id="oldsha")],
            head=_head(oid="newsha"),  # head SHA differs from the approval's commit_id
        )
        assert human_approved_on_head(PR_URL, runners=r) is False

    def test_stale_backdated_committer_date_still_fails(self):
        """CRITICAL end-to-end regression: the autonomous pipeline pushes a NEW head
        and back-dates its committer date below a prior human approval's timestamp
        (GIT_COMMITTER_DATE). The label event present, latest actor still the human,
        the OLD timestamp predicate would have PASSED — but SHA-equality currency FAILS
        because the approval's commit_id no longer equals the (new) head OID."""
        from human_approval import human_approved_on_head

        r = _runners(
            # human approved the old head at 14:00, recorded commit_id=approved_sha
            timeline=[_labeled("alice", "2026-06-08T14:00:00Z", commit_id="approved_sha")],
            # autonomous push: new head, committer date forged to 2020 (looks old)
            head={
                "headRefOid": "new_unapproved_sha",
                "commits": [
                    {"oid": "new_unapproved_sha", "committedDate": "2020-01-01T00:00:00Z"}
                ],
            },
        )
        assert human_approved_on_head(PR_URL, runners=r) is False

    def test_most_recent_wins_old_bot_new_human(self):
        from human_approval import human_approved_on_head

        r = _runners(
            timeline=[
                {
                    "event": "labeled",
                    "created_at": "2026-06-08T10:00:00Z",
                    "actor": {"login": "github-actions[bot]", "type": "Bot"},
                    "label": {"name": LABEL},
                },
                _labeled("alice", "2026-06-08T14:00:00Z"),
            ]
        )
        assert human_approved_on_head(PR_URL, runners=r) is True

    def test_most_recent_wins_old_human_new_bot(self):
        from human_approval import human_approved_on_head

        r = _runners(
            timeline=[
                _labeled("alice", "2026-06-08T10:00:00Z"),
                {
                    "event": "labeled",
                    "created_at": "2026-06-08T14:00:00Z",
                    "actor": {"login": "github-actions[bot]", "type": "Bot"},
                    "label": {"name": LABEL},
                },
            ]
        )
        assert human_approved_on_head(PR_URL, runners=r) is False

    def test_no_label_event(self):
        from human_approval import human_approved_on_head

        # label present but no labeled timeline event -> cannot prove actor -> False
        assert human_approved_on_head(PR_URL, runners=_runners(timeline=[])) is False

    def test_fetch_failure_labels(self):
        from human_approval import human_approved_on_head

        assert human_approved_on_head(PR_URL, runners=_runners(labels_raises=True)) is False

    def test_fetch_failure_timeline(self):
        from human_approval import human_approved_on_head

        assert human_approved_on_head(PR_URL, runners=_runners(timeline_raises=True)) is False

    def test_fetch_failure_head(self):
        from human_approval import human_approved_on_head

        assert human_approved_on_head(PR_URL, runners=_runners(head_raises=True)) is False

    def test_fetch_failure_commits_does_not_block(self):
        """commits_fn is advisory-only; a commits fetch failure must not raise and
        the predicate stays decidable from labels/timeline/head."""
        from human_approval import human_approved_on_head

        assert human_approved_on_head(PR_URL, runners=_runners(commits_raises=True)) is True

    def test_fetch_returns_non_list(self):
        from human_approval import human_approved_on_head

        assert human_approved_on_head(PR_URL, runners=_runners(labels="notalist")) is False
        assert human_approved_on_head(PR_URL, runners=_runners(timeline="notalist")) is False

    def test_never_raises_on_garbage(self):
        from human_approval import human_approved_on_head

        # head returns a non-dict -> currency fails closed, no raise
        assert human_approved_on_head(PR_URL, runners=_runners(head="notadict")) is False

    def test_f4_per_key_partial_injection(self):
        """F4: a partial runners dict (some keys missing) must NOT KeyError and must
        NOT fall back to whole-dict-None. Missing keys resolve to live defaults; here
        we provide only the keys needed to reach a deterministic False without live gh.
        Provide self_login_fn (so no live gh user call) returning '' -> fail-closed."""
        from human_approval import human_approved_on_head

        partial = {"self_login_fn": lambda *a, **k: ""}
        # self resolves to "" -> fail-closed BEFORE any other live fetch -> False, no KeyError
        assert human_approved_on_head(PR_URL, runners=partial) is False

    def test_empty_runners_dict_does_not_keyerror(self):
        """F4: evaluate_gate passes r = runners or {} (never None). An empty {} must
        wire ALL live defaults per-key, not KeyError. We can't call live gh here, so
        we assert it raises no KeyError by intercepting via a self_login_fn-only dict
        is covered above; here we confirm {} doesn't KeyError at resolution time by
        checking the function is total (any internal failure -> False)."""
        from human_approval import human_approved_on_head

        # With a fully-injected dict that has every key, no live default is needed.
        # The per-key resolution must use .get(k) or live[k], never runners[k].
        full = _runners()
        # remove one key to force a per-key fallback path resolution; we replace the
        # live default for that key by monkeypatching is overkill — instead assert the
        # resolution uses .get (no KeyError) by passing a dict missing 'commits_fn'
        # but providing a benign self/labels/timeline/head that reach a decision.
        import human_approval
        orig = human_approval._build_live_runners

        def fake_live(pr_url):
            return {
                "labels_fn": lambda u: [],
                "timeline_fn": lambda u: [],
                "head_fn": lambda u: {},
                "commits_fn": lambda u: [],
                "self_login_fn": lambda: "x",
            }

        human_approval._build_live_runners = fake_live
        try:
            partial = {"self_login_fn": lambda: "x", "labels_fn": lambda u: []}
            # missing timeline_fn/head_fn/commits_fn -> resolved from fake_live, no KeyError
            assert human_approved_on_head(PR_URL, runners=partial) is False
        finally:
            human_approval._build_live_runners = orig

    def test_keys_constant_present(self):
        from human_approval import _HUMAN_APPROVAL_KEYS

        assert _HUMAN_APPROVAL_KEYS == (
            "labels_fn",
            "timeline_fn",
            "head_fn",
            "commits_fn",
            "self_login_fn",
        )


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


# ============================================================
# Task 3.1: strip_stale_approval (REST DELETE, fail-open, D2)
# ============================================================

STRIP_PR_URL = "https://github.com/example/repo/pull/7"
STALE_HEAD_OID = "newsha40"


def _strip_runners(
    *,
    labels=None,
    timeline=None,
    labels_raises=False,
    timeline_raises=False,
):
    """Injected runners for strip_stale_approval — the two fetch keys the strip path
    consumes (labels/timeline). Staleness is judged against the passed head_oid by
    SHA-equality with the approving event's commit_id; no head_fn fetch is made.
    Defaults form a present+STALE scenario: the approval recorded commit_id='sha40'
    but the call passes STALE_HEAD_OID='newsha40', so the default call issues a DELETE."""
    if labels is None:
        labels = [{"name": LABEL}]
    if timeline is None:
        timeline = [_labeled("alice", "2026-06-08T12:00:00Z")]  # commit_id defaults to sha40

    def _ret(value, raises):
        def fn(*a, **k):
            if raises:
                raise RuntimeError("injected gh failure")
            return value
        return fn

    return {
        "labels_fn": _ret(labels, labels_raises),
        "timeline_fn": _ret(timeline, timeline_raises),
    }


class _RunRecorder:
    """A subprocess.run stub recording the last argv; optionally raising."""

    def __init__(self, *, raises=False, returncode=0):
        self.calls = []
        self.raises = raises
        self.returncode = returncode

    def __call__(self, argv, *a, **k):
        self.calls.append(argv)
        if self.raises:
            raise RuntimeError("injected DELETE failure")

        class _CP:
            pass

        cp = _CP()
        cp.returncode = self.returncode
        cp.stdout = ""
        cp.stderr = ""
        return cp


class TestStripStaleApproval:
    def test_present_stale_deletes_returns_true(self, monkeypatch):
        import human_approval

        rec = _RunRecorder()
        monkeypatch.setattr(human_approval.subprocess, "run", rec)
        result = human_approval.strip_stale_approval(
            STRIP_PR_URL, STALE_HEAD_OID, runners=_strip_runners()
        )
        assert result is True
        assert len(rec.calls) == 1

    def test_delete_argv_is_rest_not_pr_edit(self, monkeypatch):
        """Asserts the REST DELETE argv (mirrors label_manager._add_label_rest's
        REST choice), NOT `gh pr edit`."""
        import human_approval

        rec = _RunRecorder()
        monkeypatch.setattr(human_approval.subprocess, "run", rec)
        human_approval.strip_stale_approval(
            STRIP_PR_URL, STALE_HEAD_OID, runners=_strip_runners()
        )
        argv = rec.calls[0]
        assert argv[0] == "gh"
        assert argv[1] == "api"
        assert "--method" in argv
        assert argv[argv.index("--method") + 1] == "DELETE"
        # REST issues/labels endpoint, label as the final path segment
        assert (
            "repos/example/repo/issues/7/labels/tp:human-approved" in argv
        )
        # never `gh pr edit`
        assert "edit" not in argv

    def test_present_current_no_delete_returns_false(self, monkeypatch):
        """Label present but CURRENT on the pushed head_oid -> no DELETE, returns False.
        Currency is now SHA-equality: the approving event's commit_id == the passed
        head_oid means the human already approved THIS exact head -> nothing stale."""
        import human_approval

        rec = _RunRecorder()
        monkeypatch.setattr(human_approval.subprocess, "run", rec)
        # the approval's recorded commit_id equals the just-pushed head -> current
        runners = _strip_runners(
            timeline=[_labeled("alice", "2026-06-08T15:00:00Z", commit_id=STALE_HEAD_OID)],
        )
        result = human_approval.strip_stale_approval(
            STRIP_PR_URL, STALE_HEAD_OID, runners=runners
        )
        assert result is False
        assert rec.calls == []

    def test_absent_label_no_delete_returns_false(self, monkeypatch):
        """Idempotent: label absent -> no DELETE, returns False (no error)."""
        import human_approval

        rec = _RunRecorder()
        monkeypatch.setattr(human_approval.subprocess, "run", rec)
        result = human_approval.strip_stale_approval(
            STRIP_PR_URL, STALE_HEAD_OID, runners=_strip_runners(labels=[])
        )
        assert result is False
        assert rec.calls == []

    def test_no_label_event_no_delete(self, monkeypatch):
        """Label present but no labeled timeline event -> cannot prove staleness ->
        no DELETE, returns False (conservative: don't strip what we can't reason about)."""
        import human_approval

        rec = _RunRecorder()
        monkeypatch.setattr(human_approval.subprocess, "run", rec)
        result = human_approval.strip_stale_approval(
            STRIP_PR_URL, STALE_HEAD_OID, runners=_strip_runners(timeline=[])
        )
        assert result is False
        assert rec.calls == []

    def test_fetch_error_fail_open_returns_false(self, monkeypatch):
        """fail-OPEN: a fetch fn raising must NOT raise out of strip_stale_approval."""
        import human_approval

        rec = _RunRecorder()
        monkeypatch.setattr(human_approval.subprocess, "run", rec)
        for kw in ("labels_raises", "timeline_raises"):
            r = _strip_runners(**{kw: True})
            assert (
                human_approval.strip_stale_approval(STRIP_PR_URL, STALE_HEAD_OID, runners=r)
                is False
            )
        assert rec.calls == []

    def test_empty_head_oid_fail_open_no_delete(self, monkeypatch):
        """A missing/empty head_oid means we CANNOT prove staleness against a concrete
        head -> fail-OPEN-to-no-action (no DELETE), even though the label is present."""
        import human_approval

        rec = _RunRecorder()
        monkeypatch.setattr(human_approval.subprocess, "run", rec)
        for bad in ("", None):
            assert (
                human_approval.strip_stale_approval(STRIP_PR_URL, bad, runners=_strip_runners())
                is False
            )
        assert rec.calls == []

    def test_delete_raises_fail_open_returns_false(self, monkeypatch):
        """fail-OPEN: a raising `subprocess.run` during the DELETE must be swallowed
        — strip_stale_approval returns False, NEVER propagates (a strip failure must
        not block a push)."""
        import human_approval

        rec = _RunRecorder(raises=True)
        monkeypatch.setattr(human_approval.subprocess, "run", rec)
        result = human_approval.strip_stale_approval(
            STRIP_PR_URL, STALE_HEAD_OID, runners=_strip_runners()
        )
        assert result is False
        # the DELETE was attempted (argv recorded) before it raised
        assert len(rec.calls) == 1

    def test_delete_404_tolerated_idempotent(self, monkeypatch):
        """Idempotent: a DELETE returning non-zero (e.g. 404 label-already-absent) is
        tolerated — fail-OPEN, returns False, never raises."""
        import human_approval

        rec = _RunRecorder(returncode=1)
        monkeypatch.setattr(human_approval.subprocess, "run", rec)
        result = human_approval.strip_stale_approval(
            STRIP_PR_URL, STALE_HEAD_OID, runners=_strip_runners()
        )
        # the DELETE was issued; a non-zero return does not raise or block
        assert len(rec.calls) == 1
        assert result is False

    def test_malformed_pr_url_fail_open(self, monkeypatch):
        """A pr_url the parser rejects -> fail-OPEN -> False, no raise, no DELETE."""
        import human_approval

        rec = _RunRecorder()
        monkeypatch.setattr(human_approval.subprocess, "run", rec)
        result = human_approval.strip_stale_approval(
            "not-a-pr-url", STALE_HEAD_OID, runners=_strip_runners()
        )
        assert result is False
        assert rec.calls == []


# ============================================================
# CRITICAL: backdated GIT_COMMITTER_DATE must NOT revive a stale approval
# (the wave2 review's must-fix #1 — currency bound to the immutable head OID,
#  not the forgeable committer timestamp)
# ============================================================


class TestBackdatedCommitterDateSpoof:
    """Reproduces the exact spoof the wave2 review identified: the autonomous pipeline
    commits a NEW head with GIT_COMMITTER_DATE set BELOW a prior human approval's
    timestamp. The OLD timestamp-only predicate (created_at >= committedDate) would
    have PASSED on that new, never-human-seen head. The SHA-equality currency binding
    FAILS it, because the new commit has a different (immutable) OID.

    This is a real, hermetic git test: it makes an actual back-dated commit and shows
    (a) committedDate IS forgeable, but (b) the OID is NOT — so binding to the OID is
    the sound fix."""

    def _git(self, repo, *args, env=None):
        import subprocess

        full = dict(os.environ)
        if env:
            full.update(env)
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, check=True, env=full,
        ).stdout.strip()

    def test_backdated_new_head_fails_currency(self, tmp_path):
        from human_approval import _approval_current_on_head

        repo = tmp_path / "repo"
        repo.mkdir()
        env = {
            "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@x",
            "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@x",
        }
        self._git(repo, "init", "-q")
        (repo / "a.txt").write_text("approved content\n")
        self._git(repo, "add", "-A")
        # the head the human approved, committed "now" (2026)
        self._git(
            repo, "commit", "-q", "-m", "approved head",
            env={**env, "GIT_COMMITTER_DATE": "2026-06-08T14:00:00 +0000"},
        )
        approved_oid = self._git(repo, "rev-parse", "HEAD")

        # the human approval: recorded against approved_oid, created_at 2026-06-08T14:00
        approval_event = {"commit_id": approved_oid, "created_at": "2026-06-08T14:00:00Z"}

        # ... the autonomous pipeline pushes a NEW commit, FORGING the committer date
        # to 2020 (BELOW the approval timestamp) via GIT_COMMITTER_DATE.
        (repo / "a.txt").write_text("content no human ever saw\n")
        self._git(repo, "add", "-A")
        self._git(
            repo, "commit", "-q", "-m", "sneaky head",
            env={**env, "GIT_COMMITTER_DATE": "2020-01-01T00:00:00 +0000"},
        )
        new_oid = self._git(repo, "rev-parse", "HEAD")
        committed_date = self._git(repo, "show", "-s", "--format=%cI", "HEAD")

        # (a) the committer date IS forgeable — proves the OLD predicate was unsound:
        assert committed_date.startswith("2020-01-01"), committed_date
        # (b) the OID is distinct and NOT forgeable:
        assert new_oid != approved_oid

        # the live head payload the gate would see for this PR
        head = {
            "headRefOid": new_oid,
            "commits": [{"oid": new_oid, "committedDate": committed_date}],
        }

        # OLD predicate would PASS (created_at 2026 >= committedDate 2020) — the spoof.
        # Demonstrate the unsoundness of the prior compare explicitly:
        assert (approval_event["created_at"] >= committed_date) is True

        # NEW predicate (SHA-equality) correctly FAILS: the approval's commit_id is the
        # approved_oid, which != the new head OID -> stale -> gate blocks.
        assert _approval_current_on_head(approval_event, head) is False
