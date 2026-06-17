"""Tests for land.py — the /tp-merge land-skill driver (Task 4.4).

The land driver is the ONLY code site that crosses the irreversible `gh pr merge`
boundary, and it does so ONLY when the deterministic merge gate PASSES. These
tests inject `require_fn` (the gate enforcer) and `merge_fn` (the irreversible
action) so NO live gh/gate runs:

  - gate raises MergeGateBlocked  -> merge_fn is NEVER called, exit 2, blockers printed.
  - gate PASSES                   -> merge_fn called exactly once, exit 0.

Run with: pytest skills/tp-merge/scripts/test_land.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
# merge_gate (with MergeGateBlocked) lives in the base-sync half's scripts dir.
sys.path.insert(0, str(HERE.parent.parent / "tp-merge-from-main" / "scripts"))

import land  # noqa: E402
from merge_gate import MergeGateBlocked  # noqa: E402


PR_URL = "https://github.com/example/repo/pull/7"


class _FakePred:
    def __init__(self, name, detail):
        self.name = name
        self.detail = detail


class _FakeOutcome:
    """Mimic the GateOutcome surface MergeGateBlocked reads (.verdict, .blocking)."""

    def __init__(self, blocking):
        self.blocking = blocking

        class _V:
            value = "INDETERMINATE"

        self.verdict = _V()


def _blocked_outcome():
    return _FakeOutcome([_FakePred("human_approved", "no current tp:human-approved on head")])


class TestLandRefusesOnBlockedGate:
    def test_blocked_gate_does_not_merge(self, capsys):
        """A MergeGateBlocked from the gate -> merge_fn is NEVER called, exit 2."""
        merge_calls = []

        def require_fn(pr_url, *, config=None):
            raise MergeGateBlocked(_blocked_outcome())

        def merge_fn(pr_url):
            merge_calls.append(pr_url)

        rc = land.land(PR_URL, require_fn=require_fn, merge_fn=merge_fn)

        assert rc == 2, "a blocked gate must exit 2 (REFUSED)"
        assert merge_calls == [], "gh pr merge must NEVER be called on a blocked gate"

        out = capsys.readouterr().out
        assert "REFUSED" in out
        assert "human_approved" in out, "the blocking predicate must be printed"
        assert "human-approval-howto.md" in out, "the howto pointer must be printed"

    def test_blocked_gate_prints_gate_message(self, capsys):
        def require_fn(pr_url, *, config=None):
            raise MergeGateBlocked(_blocked_outcome())

        rc = land.land(PR_URL, require_fn=require_fn, merge_fn=lambda u: None)
        assert rc == 2
        out = capsys.readouterr().out
        assert "did not PASS" in out


class TestLandMergesOnPass:
    def test_passing_gate_merges_once(self, capsys):
        """A PASSING gate (require_fn returns normally) -> merge_fn called exactly once, exit 0."""
        merge_calls = []

        def require_fn(pr_url, *, config=None):
            return object()  # PASS: returns an outcome, does not raise

        def merge_fn(pr_url):
            merge_calls.append(pr_url)

        rc = land.land(PR_URL, require_fn=require_fn, merge_fn=merge_fn)

        assert rc == 0
        assert merge_calls == [PR_URL], "gh pr merge must be invoked exactly once on PASS"
        assert "Merged" in capsys.readouterr().out

    def test_config_threaded_into_gate(self):
        seen = {}

        def require_fn(pr_url, *, config=None):
            seen["config"] = config
            return object()

        land.land(PR_URL, require_fn=require_fn, merge_fn=lambda u: None,
                  config={"review": {"require_human_approval": True}})
        assert seen["config"] == {"review": {"require_human_approval": True}}

    def test_merge_failure_is_refusal_class(self, capsys):
        """If the irreversible merge itself errors, exit 2 (not a silent 0)."""

        def require_fn(pr_url, *, config=None):
            return object()

        def merge_fn(pr_url):
            raise RuntimeError("gh exploded")

        rc = land.land(PR_URL, require_fn=require_fn, merge_fn=merge_fn)
        assert rc == 2
        assert "REFUSED" in capsys.readouterr().out


class TestLandBackstopNonDictReview:
    """Land-boundary backstop: non-dict review values must NOT raise AttributeError.

    _require_human_approval is documented total over non-dict review (folds to strict
    default True). The _rha_raw echo must only execute inside the refusal branch, where
    review is guaranteed to be a dict — so configs with review=None or review="false"
    must proceed to the gate without crashing.
    """

    def _pass_gate(self, pr_url, *, config=None):
        """Stub gate that always passes (returns an outcome object)."""
        return object()

    def test_review_none_proceeds_to_gate_no_error(self, capsys):
        """config {"review": None} — review is non-dict, backstop folds to True, gate runs."""
        merge_calls = []

        rc = land.land(
            PR_URL,
            require_fn=self._pass_gate,
            merge_fn=lambda u: merge_calls.append(u),
            config={"review": None},
        )

        # No AttributeError; gate ran and passed; merge was invoked
        assert rc == 0, "review=None must fold to strict default (True) and proceed"
        assert merge_calls == [PR_URL], "merge must be called when gate passes"

    def test_review_string_false_proceeds_to_gate_no_error(self, capsys):
        """config {"review": "false"} — review is non-dict string, backstop folds to True."""
        merge_calls = []

        rc = land.land(
            PR_URL,
            require_fn=self._pass_gate,
            merge_fn=lambda u: merge_calls.append(u),
            config={"review": "false"},
        )

        # No AttributeError; string "false" is non-dict, so strict default applies
        assert rc == 0, "review='false' must fold to strict default (True) and proceed"
        assert merge_calls == [PR_URL], "merge must be called when gate passes"

    def test_review_none_gate_blocked_exits_2_no_error(self):
        """config {"review": None} with a blocked gate — exits 2, no AttributeError."""
        from merge_gate import MergeGateBlocked

        def blocked_gate(pr_url, *, config=None):
            raise MergeGateBlocked(_blocked_outcome())

        rc = land.land(
            PR_URL,
            require_fn=blocked_gate,
            merge_fn=lambda u: None,
            config={"review": None},
        )

        assert rc == 2, "blocked gate must exit 2 even with non-dict review"

    def test_review_string_gate_blocked_exits_2_no_error(self):
        """config {"review": "false"} with a blocked gate — exits 2, no AttributeError."""
        from merge_gate import MergeGateBlocked

        def blocked_gate(pr_url, *, config=None):
            raise MergeGateBlocked(_blocked_outcome())

        rc = land.land(
            PR_URL,
            require_fn=blocked_gate,
            merge_fn=lambda u: None,
            config={"review": "false"},
        )

        assert rc == 2, "blocked gate must exit 2 even with non-dict review"


class TestMain:
    def test_usage_error_exits_2(self, capsys):
        assert land.main([]) == 2
        assert land.main(["a", "b"]) == 2
        assert land.main(["--flag", PR_URL]) == 2


class TestLandBindingOnLivePath:
    """Pin that the binding check (W4) runs through the gate chain on land's live path.

    land() must pass config=None to require_fn on the live path so that evaluate_gate
    performs the binding check itself. If land pre-loaded cfg and passed config=cfg,
    the binding check inside evaluate_gate's `if config is None:` block would be
    skipped — the wrong-cwd relaxation hazard remains open.

    Hermetic test: monkeypatch the _load_repo_config used by land's backstop to return
    a permissive backstop config (so the backstop doesn't refuse), and inject a
    require_fn that captures the config argument. On the live path (config=None at
    call site), require_fn must see config=None — confirming the binding check will run
    inside evaluate_gate.
    """

    def test_live_path_passes_config_none_to_gate(self, monkeypatch):
        """Live path (config=None at call): require_fn receives config=None."""
        captured = {}

        def require_fn(pr_url, *, config=None):
            captured["config"] = config
            return object()  # PASS

        # Monkeypatch land's _load_repo_config (backstop) to return permissive config
        permissive = {"review": {"require_human_approval": True}}
        monkeypatch.setattr(land, "_load_repo_config", lambda: permissive)

        land.land(PR_URL, require_fn=require_fn, merge_fn=lambda u: None)

        assert "config" in captured, "require_fn was not called"
        assert captured["config"] is None, (
            f"Live path must pass config=None to require_fn so the binding check runs "
            f"inside evaluate_gate; got config={captured['config']!r}. "
            "If land pre-loads cfg and passes config=cfg, the `if config is None:` "
            "guard in evaluate_gate is skipped and the W4 binding check is dead."
        )

    def test_explicit_config_passed_through_to_gate(self, monkeypatch):
        """Explicit config= (tests): require_fn receives that exact dict (not None)."""
        captured = {}

        def require_fn(pr_url, *, config=None):
            captured["config"] = config
            return object()  # PASS

        explicit = {"review": {"require_human_approval": True}}
        land.land(PR_URL, require_fn=require_fn, merge_fn=lambda u: None, config=explicit)

        assert captured.get("config") is explicit, (
            f"When config= is explicitly provided, require_fn must receive that exact "
            f"dict; got {captured.get('config')!r}"
        )


class TestLandCollisionRefusalBranch:
    """Task 3.2: collision-signature branch in the refuse path.

    When human_approved blocks AND the collision signature holds (label present,
    actor == self_login), the refusal prints flip instructions INSTEAD of the
    generic howto line. Exit code stays 2 in both branches.
    """

    def _blocked_human_approved(self):
        return _FakeOutcome([_FakePred("human_approved",
                                       "self-login applied tp:human-approved")])

    def _require_fn_blocked(self, pr_url, *, config=None):
        raise MergeGateBlocked(self._blocked_human_approved())

    def test_collision_branch_prints_flip_instructions(self, capsys, monkeypatch):
        """Collision signature True -> flip instructions printed, NOT generic howto."""
        monkeypatch.setattr(
            land, "approval_collision_signature_live",
            lambda pr_url, runners=None: True,
        )

        rc = land.land(
            PR_URL,
            require_fn=self._require_fn_blocked,
            merge_fn=lambda u: None,
            config={"review": {"require_human_approval": True}},
        )
        out = capsys.readouterr().out
        assert rc == 2, "exit code must still be 2 on collision branch"
        assert "human-approval-howto.md" in out, "howto pointer must still appear"
        # Flip instructions must contain the collision-specific text
        assert "single-account" in out or "machine account" in out or "flip" in out, (
            "collision branch must print flip instructions: "
            f"got output: {out!r}"
        )

    def test_no_collision_branch_prints_generic_howto(self, capsys, monkeypatch):
        """Collision signature False -> generic howto line printed (unchanged)."""
        monkeypatch.setattr(
            land, "approval_collision_signature_live",
            lambda pr_url, runners=None: False,
        )

        rc = land.land(
            PR_URL,
            require_fn=self._require_fn_blocked,
            merge_fn=lambda u: None,
            config={"review": {"require_human_approval": True}},
        )
        out = capsys.readouterr().out
        assert rc == 2
        # Generic howto line must appear
        assert "To authorize this merge" in out or "human-approval-howto.md" in out

    def test_non_human_approved_blocker_no_collision_check(self, capsys, monkeypatch):
        """When human_approved is NOT among blockers, collision branch is never taken."""
        collision_called = []
        monkeypatch.setattr(
            land, "approval_collision_signature_live",
            lambda pr_url, runners=None: collision_called.append(1) or True,
        )

        # Gate blocks on threads_resolved only (not human_approved)
        def require_fn(pr_url, *, config=None):
            raise MergeGateBlocked(
                _FakeOutcome([_FakePred("threads_resolved", "open threads")])
            )

        rc = land.land(
            PR_URL,
            require_fn=require_fn,
            merge_fn=lambda u: None,
            config={"review": {"require_human_approval": True}},
        )
        assert rc == 2
        # Collision check must NOT be called when human_approved is not blocking
        assert collision_called == [], "collision check must not run for non-human_approved blockers"
