"""Tests for auto_strip_hook.run — the thin push-time stale-approval strip hook.

Task 3.2: run(pr_url, new_head_oid, *, runners=None) delegates to
human_approval.strip_stale_approval and is FAIL-OPEN — a raised exception inside is
swallowed (returns False), so it can NEVER block a push.

All tests stub strip_stale_approval — NO live gh/git calls.

Run with: pytest skills/tp-merge-from-main/scripts/test_auto_strip_hook.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add scripts dir for auto_strip_hook imports
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

# Add _shared dir for human_approval imports (the hook imports strip_stale_approval)
SHARED = Path(__file__).resolve().parent.parent.parent / "_shared"
sys.path.insert(0, str(SHARED))

import auto_strip_hook  # noqa: E402


PR_URL = "https://github.com/example/repo/pull/7"
NEW_HEAD = "newsha40"


class TestRun:
    def test_delegates_to_strip_with_right_args(self, monkeypatch):
        """run forwards (pr_url, new_head_oid) and the runners kwarg to
        strip_stale_approval and returns its result."""
        calls = []

        def fake_strip(pr_url, head_oid, *, runners=None):
            calls.append((pr_url, head_oid, runners))
            return True

        monkeypatch.setattr(auto_strip_hook, "strip_stale_approval", fake_strip)

        result = auto_strip_hook.run(PR_URL, NEW_HEAD)
        assert result is True
        assert calls == [(PR_URL, NEW_HEAD, None)]

    def test_passes_runners_through(self, monkeypatch):
        """A test-seam runners dict is threaded straight into strip_stale_approval."""
        seen = {}

        def fake_strip(pr_url, head_oid, *, runners=None):
            seen["runners"] = runners
            return False

        monkeypatch.setattr(auto_strip_hook, "strip_stale_approval", fake_strip)

        sentinel = {"labels_fn": lambda u: []}
        result = auto_strip_hook.run(PR_URL, NEW_HEAD, runners=sentinel)
        assert result is False
        assert seen["runners"] is sentinel

    def test_returns_false_result_through(self, monkeypatch):
        """When strip finds nothing stale (returns False), run returns False."""
        monkeypatch.setattr(
            auto_strip_hook, "strip_stale_approval", lambda *a, **k: False
        )
        assert auto_strip_hook.run(PR_URL, NEW_HEAD) is False

    def test_fail_open_swallows_raise(self, monkeypatch):
        """FAIL-OPEN: a raising strip_stale_approval must NOT propagate — run returns
        False so the hook can never block a push. This is the defining property."""

        def boom(*a, **k):
            raise RuntimeError("gh exploded mid-strip")

        monkeypatch.setattr(auto_strip_hook, "strip_stale_approval", boom)

        # must not raise
        result = auto_strip_hook.run(PR_URL, NEW_HEAD)
        assert result is False

    def test_fail_open_swallows_raise_with_runners(self, monkeypatch):
        def boom(*a, **k):
            raise ValueError("boom")

        monkeypatch.setattr(auto_strip_hook, "strip_stale_approval", boom)
        result = auto_strip_hook.run(PR_URL, NEW_HEAD, runners={"x": 1})
        assert result is False
