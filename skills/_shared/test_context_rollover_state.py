"""test_context_rollover_state.py - the once-per-crossing rollover ledger.

design: strata-spend-leaks (Task 3.2). A rollover may fire at most once per session
id: the second claim for the same session is refused (no double `/clear`), a session
whose rollover aborted is never reclaimed, and a ledger that cannot be read refuses
every claim - never risk a second `/clear` on a session that already had one.

The ledger is a JSON object at a path the caller passes (in the run it is
`<worktree>/.three-pillars/run/context-rollover.json`), so `tmp_path` stands in for
the gitignored run dir and no real worktree is touched here.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import context_rollover_state as state  # noqa: E402


def test_first_claim_wins(tmp_path):
    """The first claim for a session id wins; the second is refused, so one
    crossing fires one rollover. The claim is what lands on disk."""
    path = tmp_path / "context-rollover.json"
    assert state.claim(path, "s1") is True
    assert state.claim(path, "s1") is False
    with open(path, encoding="utf-8") as fh:
        assert json.load(fh)["s1"]["state"] == "claimed"


def test_same_session_never_claims_twice(tmp_path):
    """A finished rollover stays closed: the same session id is refused forever."""
    path = tmp_path / "context-rollover.json"
    assert state.claim(path, "s1") is True
    state.finish(path, "s1", "done")
    assert state.claim(path, "s1") is False


def test_new_session_may_claim(tmp_path):
    """After a save -> /clear -> restore the session id is new, so the next
    crossing is claimable while the old session stays closed."""
    path = tmp_path / "context-rollover.json"
    assert state.claim(path, "s1") is True
    state.finish(path, "s1", "done")
    assert state.claim(path, "s2") is True
    assert state.claim(path, "s2") is False


def test_aborted_session_not_reclaimed(tmp_path):
    """A rollover that aborted (a failed save, so no `/clear` was sent) is recorded
    `aborted` and never claimed again - retrying it is a human call, not a re-fire."""
    path = tmp_path / "context-rollover.json"
    assert state.claim(path, "s1") is True
    state.finish(path, "s1", "aborted")
    assert state.claim(path, "s1") is False
    with open(path, encoding="utf-8") as fh:
        assert json.load(fh)["s1"]["state"] == "aborted"


def test_unreadable_ledger_refuses(tmp_path):
    """Garbage in the ledger, a ledger that is a directory, or a read that fails
    refuses every claim - fail-safe, because a fresh claim on an unreadable ledger
    could send a second `/clear` to a session that already rolled over."""
    path = tmp_path / "context-rollover.json"
    path.write_text("{not json at all", encoding="utf-8")
    assert state.claim(path, "s1") is False
    assert state.finish(path, "s1", "done") is False

    dir_ledger = tmp_path / "ledger-dir"
    dir_ledger.mkdir()
    assert state.claim(dir_ledger, "s1") is False

    unreadable = tmp_path / "unreadable.json"
    unreadable.write_text("{}", encoding="utf-8")
    unreadable.chmod(0)
    try:
        assert state.claim(unreadable, "s1") is False
    finally:
        unreadable.chmod(0o644)
    assert os.path.exists(unreadable)
