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


class TestMain:
    def test_usage_error_exits_2(self, capsys):
        assert land.main([]) == 2
        assert land.main(["a", "b"]) == 2
        assert land.main(["--flag", PR_URL]) == 2
