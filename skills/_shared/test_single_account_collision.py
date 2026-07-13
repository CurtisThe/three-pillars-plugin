"""Tests for single-account collision detection helpers — solo-operator-identity-split.

Covers Tasks 1.1, 1.2:
  - pure single_account_collision(...)
  - live wrapper single_account_collision_live(...)

After retire-approval-tags: approval_collision_signature* functions REMOVED (they
were pure Path-A label logic). Tests for those symbols are deleted. The collision
advisory message now states "no distinct reviewer → no gate; use a two-account setup"
(A8 positive no-gate message test added here).

Gate-regression (Task 3.3) and advisory (Task 2.1) tests live in
test_single_account_collision_gate.py.

Run with: python -m pytest skills/_shared/test_single_account_collision.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


# ---------------------------------------------------------------------------
# Task 1.1 — pure single_account_collision(...)
# ---------------------------------------------------------------------------

class TestSingleAccountCollisionPure:
    """Truth-table tests for single_account_collision (pure, no gh calls)."""

    def _cfg(self, extras=None):
        cfg = {"review": {}}
        if extras:
            cfg["review"]["automation_identities"] = extras
        return cfg

    def _collab(self, login, type_="User"):
        return {"login": login, "type": type_}

    def test_self_login_falsy_returns_false(self):
        from single_account_detect import single_account_collision
        assert single_account_collision(
            self_login="", collaborators=[], config={}
        ) is False

    def test_self_login_none_returns_false(self):
        from single_account_detect import single_account_collision
        assert single_account_collision(
            self_login=None, collaborators=[], config={}
        ) is False

    def test_collaborators_not_list_returns_false(self):
        from single_account_detect import single_account_collision
        assert single_account_collision(
            self_login="bot", collaborators=None, config={}
        ) is False

    def test_collaborators_non_list_string_returns_false(self):
        from single_account_detect import single_account_collision
        assert single_account_collision(
            self_login="bot", collaborators="notalist", config={}
        ) is False

    def test_sole_human_collab_is_self_login_collision(self):
        """Only human collaborator == self_login -> True (collision)."""
        from single_account_detect import single_account_collision
        assert single_account_collision(
            self_login="CurtisThe",
            collaborators=[self._collab("CurtisThe")],
            config=self._cfg(),
        ) is True

    def test_sole_collab_is_self_login_case_insensitive(self):
        """Case-insensitive: CurtisThe vs curtisthe."""
        from single_account_detect import single_account_collision
        assert single_account_collision(
            self_login="curtisthe",
            collaborators=[self._collab("CurtisThe")],
            config=self._cfg(),
        ) is True

    def test_distinct_human_collab_outside_automation_no_collision(self):
        """CurtisThe (human) + CurtisTheBot (self_login) -> False (healthy)."""
        from single_account_detect import single_account_collision
        assert single_account_collision(
            self_login="CurtisTheBot",
            collaborators=[
                self._collab("CurtisThe"),
                self._collab("CurtisTheBot"),
            ],
            config=self._cfg(),
        ) is False

    def test_bot_collab_ignored_collision_fires(self):
        """Only non-self-login collaborator is a [bot] -> still collision."""
        from single_account_detect import single_account_collision
        assert single_account_collision(
            self_login="CurtisTheBot",
            collaborators=[
                self._collab("CurtisTheBot"),
                self._collab("github-actions[bot]"),
            ],
            config=self._cfg(),
        ) is True

    def test_bot_type_collab_ignored(self):
        """type == 'Bot' collaborator is ignored."""
        from single_account_detect import single_account_collision
        assert single_account_collision(
            self_login="CurtisTheBot",
            collaborators=[
                self._collab("CurtisTheBot"),
                {"login": "app-bot", "type": "Bot"},
            ],
            config=self._cfg(),
        ) is True

    def test_non_user_type_collab_ignored(self):
        """type != 'User' collaborator is ignored."""
        from single_account_detect import single_account_collision
        assert single_account_collision(
            self_login="mybot",
            collaborators=[
                self._collab("mybot"),
                {"login": "orgname", "type": "Organization"},
            ],
            config=self._cfg(),
        ) is True

    def test_collab_in_config_automation_identities_ignored(self):
        """A collaborator in config review.automation_identities is inside automation."""
        from single_account_detect import single_account_collision
        # deploybot is an extra automation identity; only it + self_login -> collision
        assert single_account_collision(
            self_login="CurtisTheBot",
            collaborators=[
                self._collab("CurtisTheBot"),
                self._collab("deploybot"),
            ],
            config=self._cfg(extras=["deploybot"]),
        ) is True

    def test_collab_outside_automation_no_collision(self):
        """A [bot]-login outside config extras is still filtered."""
        from single_account_detect import single_account_collision
        assert single_account_collision(
            self_login="CurtisTheBot",
            collaborators=[
                self._collab("CurtisTheBot"),
                self._collab("dependabot[bot]"),
            ],
            config=self._cfg(),
        ) is True

    def test_row_c_self_login_as_sole_collab_equals_operator_git_identity(self):
        """Row (c) design note: no git-identity input; subsumed by row (b).

        The collaborative-set view (sole-human-collab == self_login) is the
        decisive, forge-agnostic signal. Row (c) exercises the same path.
        """
        from single_account_detect import single_account_collision
        # Simulates: gh-auth == operator git identity == "CurtisThe"; no
        # distinct machine account. The collaborator list has only one human.
        assert single_account_collision(
            self_login="CurtisThe",
            collaborators=[self._collab("CurtisThe")],
            config=self._cfg(),
        ) is True

    def test_empty_collaborators_is_collision(self):
        """No collaborators at all (edge) -> still True (no distinct human path)."""
        from single_account_detect import single_account_collision
        assert single_account_collision(
            self_login="CurtisTheBot",
            collaborators=[],
            config=self._cfg(),
        ) is True

    def test_never_raises_on_bad_collab_entry(self):
        """Malformed collaborator entries are skipped; total/never raises."""
        from single_account_detect import single_account_collision
        result = single_account_collision(
            self_login="CurtisTheBot",
            collaborators=[None, 42, {"nologin": True}, {"login": None}],
            config=self._cfg(),
        )
        # No distinct human found -> True
        assert result is True


# ---------------------------------------------------------------------------
# Task 1.2 — live wrapper single_account_collision_live(...)
# ---------------------------------------------------------------------------

class TestSingleAccountCollisionLive:
    """Live-wrapper tests with injected runners (no real gh)."""

    def _make_collab(self, login, type_="User"):
        return {"login": login, "type": type_}

    def test_raising_self_login_fn_returns_false(self):
        from single_account_detect import single_account_collision_live

        def bad_self_login():
            raise RuntimeError("gh down")

        result = single_account_collision_live(
            runners={"self_login_fn": bad_self_login},
            config={},
        )
        assert result is False

    def test_raising_collaborators_fn_returns_false(self):
        from single_account_detect import single_account_collision_live

        def bad_collabs():
            raise RuntimeError("no network")

        result = single_account_collision_live(
            runners={
                "self_login_fn": lambda: "mybot",
                "collaborators_fn": bad_collabs,
            },
            config={},
        )
        assert result is False

    def test_two_account_roster_returns_false(self):
        """Distinct human (CurtisThe) + self_login (CurtisTheBot) -> False."""
        from single_account_detect import single_account_collision_live

        result = single_account_collision_live(
            runners={
                "self_login_fn": lambda: "CurtisTheBot",
                "collaborators_fn": lambda: [
                    self._make_collab("CurtisThe"),
                    self._make_collab("CurtisTheBot"),
                ],
            },
            config={},
        )
        assert result is False

    def test_single_account_roster_returns_true(self):
        """Sole human collaborator == self_login -> True."""
        from single_account_detect import single_account_collision_live

        result = single_account_collision_live(
            runners={
                "self_login_fn": lambda: "CurtisThe",
                "collaborators_fn": lambda: [self._make_collab("CurtisThe")],
            },
            config={},
        )
        assert result is True


# ---------------------------------------------------------------------------
# A8 — positive no-gate-message test (advisory fires with new wording)
# ---------------------------------------------------------------------------

class TestNoGateMessagePositive:
    """A8: after retire-approval-tags, a single-account collision means the review-path
    gate has no distinct human reviewer → no gate. The advisory message must state
    this clearly (not the old 'label rejected' text).

    This test pins the framework-check advisory prose (the un-numbered
    # solo-operator-identity-split: block in framework-check.sh) by confirming
    collision_advisory.py fires with 'COLLISION' when the collision is detected,
    and that single_account_detect no longer exports approval_collision_signature.
    """

    def test_approval_collision_signature_not_exported(self):
        """approval_collision_signature must NOT be importable from single_account_detect
        (the symbol was removed with the label path)."""
        import single_account_detect
        assert not hasattr(single_account_detect, "approval_collision_signature"), (
            "approval_collision_signature must be removed from single_account_detect"
        )

    def test_approval_collision_signature_live_not_exported(self):
        """approval_collision_signature_live must NOT be importable."""
        import single_account_detect
        assert not hasattr(single_account_detect, "approval_collision_signature_live"), (
            "approval_collision_signature_live must be removed from single_account_detect"
        )

    def test_single_account_collision_still_exported(self):
        """The collaborator-set collision helper must still be importable (kept)."""
        from single_account_detect import single_account_collision  # noqa: F401
        assert callable(single_account_collision)

    def test_single_account_collision_live_still_exported(self):
        """The live wrapper must still be importable (kept)."""
        from single_account_detect import single_account_collision_live  # noqa: F401
        assert callable(single_account_collision_live)

    def test_collision_advisory_fires_collision_token_on_single_account(self):
        """A8: collision_advisory.main() outputs a line containing 'COLLISION'
        when single_account_collision_live() returns True.

        This pins the advisory FIRES path with the new semantics: the single-account
        topology means 'no distinct human reviewer → no gate; use two-account setup'.
        The collision advisory is the mechanism that surfaces this warning to the operator.
        """
        import io
        from unittest import mock
        import collision_advisory

        with mock.patch("single_account_detect.single_account_collision_live",
                        return_value=True), \
             mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout="CurtisThe\n")
            buf = io.StringIO()
            import sys as _sys
            old_stdout = _sys.stdout
            _sys.stdout = buf
            try:
                collision_advisory.main(["."])
            finally:
                _sys.stdout = old_stdout
            output = buf.getvalue()

        assert "COLLISION" in output, (
            f"Advisory must print 'COLLISION' on single-account topology; got: {output!r}"
        )
        assert "CurtisThe" in output, (
            f"Advisory must include the self_login; got: {output!r}"
        )

    def test_no_collision_advisory_silent_on_two_account(self):
        """No collision -> advisory prints nothing (silent, no-gate message is absent)."""
        import io
        from unittest import mock
        import collision_advisory

        with mock.patch("single_account_detect.single_account_collision_live",
                        return_value=False):
            buf = io.StringIO()
            import sys as _sys
            old_stdout = _sys.stdout
            _sys.stdout = buf
            try:
                collision_advisory.main(["."])
            finally:
                _sys.stdout = old_stdout
            output = buf.getvalue()

        assert output.strip() == "", (
            f"Advisory must be silent on two-account topology; got: {output!r}"
        )
