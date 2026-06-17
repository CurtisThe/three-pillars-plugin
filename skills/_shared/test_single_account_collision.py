"""Tests for single-account collision detection helpers — solo-operator-identity-split.

Covers Tasks 1.1, 1.2, 3.1:
  - pure single_account_collision(...)
  - live wrapper single_account_collision_live(...)
  - pure approval_collision_signature(...) + live wrapper

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
# Task 3.1 — pure approval_collision_signature(...) + live wrapper
# ---------------------------------------------------------------------------

class TestApprovalCollisionSignaturePure:
    """Covers approval_collision_signature (pure, no gh) truth-table cases."""

    HA_LABEL = "tp:human-approved"
    HA_TAGGED = "tp:human-approved:a1b2c3d4e5f6"

    def _label(self, name):
        return {"name": name}

    def _event(self, label_name, actor_login, actor_type="User"):
        return {
            "event": "labeled",
            "label": {"name": label_name},
            "actor": {"login": actor_login, "type": actor_type},
            "created_at": "2026-06-14T00:00:00Z",
        }

    def test_label_present_actor_matches_self_login_collision(self):
        from single_account_detect import approval_collision_signature
        labels = [self._label(self.HA_TAGGED)]
        timeline = [self._event(self.HA_TAGGED, "CurtisThe")]
        assert approval_collision_signature(
            labels=labels, timeline=timeline, self_login="CurtisThe"
        ) is True

    def test_label_present_actor_different_from_self_login_no_collision(self):
        from single_account_detect import approval_collision_signature
        labels = [self._label(self.HA_TAGGED)]
        timeline = [self._event(self.HA_TAGGED, "CurtisThe")]
        assert approval_collision_signature(
            labels=labels, timeline=timeline, self_login="CurtisTheBot"
        ) is False

    def test_label_absent_returns_false(self):
        from single_account_detect import approval_collision_signature
        assert approval_collision_signature(
            labels=[], timeline=[], self_login="CurtisThe"
        ) is False

    def test_self_login_falsy_returns_false(self):
        from single_account_detect import approval_collision_signature
        labels = [self._label(self.HA_TAGGED)]
        timeline = [self._event(self.HA_TAGGED, "CurtisThe")]
        assert approval_collision_signature(
            labels=labels, timeline=timeline, self_login=""
        ) is False

    def test_self_login_none_returns_false(self):
        from single_account_detect import approval_collision_signature
        labels = [self._label(self.HA_TAGGED)]
        timeline = [self._event(self.HA_TAGGED, "CurtisThe")]
        assert approval_collision_signature(
            labels=labels, timeline=timeline, self_login=None
        ) is False

    def test_case_insensitive_actor_match(self):
        from single_account_detect import approval_collision_signature
        labels = [self._label(self.HA_TAGGED)]
        timeline = [self._event(self.HA_TAGGED, "CURTISTHE")]
        assert approval_collision_signature(
            labels=labels, timeline=timeline, self_login="curtisthe"
        ) is True

    def test_tagged_label_form_is_recognized(self):
        """Tagged family label tp:human-approved:<sha7+> must be recognized."""
        from single_account_detect import approval_collision_signature
        tagged = "tp:human-approved:abcdef1234567"
        labels = [self._label(tagged)]
        timeline = [self._event(tagged, "bot1")]
        assert approval_collision_signature(
            labels=labels, timeline=timeline, self_login="bot1"
        ) is True

    def test_no_timeline_event_returns_false(self):
        from single_account_detect import approval_collision_signature
        labels = [self._label(self.HA_TAGGED)]
        # label present but no timeline event
        assert approval_collision_signature(
            labels=labels, timeline=[], self_login="CurtisThe"
        ) is False

    def test_non_list_inputs_return_false(self):
        from single_account_detect import approval_collision_signature
        assert approval_collision_signature(
            labels=None, timeline=None, self_login="CurtisThe"
        ) is False


class TestApprovalCollisionSignatureLive:
    """Live-wrapper approval_collision_signature_live with injected runners."""

    HA_TAGGED = "tp:human-approved:a1b2c3d4e5f6"

    def _event(self, label_name, actor_login):
        return {
            "event": "labeled",
            "label": {"name": label_name},
            "actor": {"login": actor_login, "type": "User"},
            "created_at": "2026-06-14T00:00:00Z",
        }

    def test_raising_runner_returns_false(self):
        from single_account_detect import approval_collision_signature_live

        def bad_labels(url):
            raise RuntimeError("gh down")

        result = approval_collision_signature_live(
            "https://github.com/example/repo/pull/1",
            runners={
                "labels_fn": bad_labels,
                "self_login_fn": lambda: "CurtisThe",
            },
        )
        assert result is False

    def test_collision_signature_detected_live(self):
        """Injected runners: label present + actor == self_login -> True."""
        from single_account_detect import approval_collision_signature_live

        tagged = self.HA_TAGGED
        result = approval_collision_signature_live(
            "https://github.com/example/repo/pull/1",
            runners={
                "labels_fn": lambda url: [{"name": tagged}],
                "timeline_fn": lambda url: [self._event(tagged, "CurtisThe")],
                "self_login_fn": lambda: "CurtisThe",
            },
        )
        assert result is True

    def test_different_actor_not_detected_live(self):
        """actor != self_login -> False (not a collision signature)."""
        from single_account_detect import approval_collision_signature_live

        tagged = self.HA_TAGGED
        result = approval_collision_signature_live(
            "https://github.com/example/repo/pull/1",
            runners={
                "labels_fn": lambda url: [{"name": tagged}],
                "timeline_fn": lambda url: [self._event(tagged, "CurtisThe")],
                "self_login_fn": lambda: "CurtisTheBot",
            },
        )
        assert result is False
