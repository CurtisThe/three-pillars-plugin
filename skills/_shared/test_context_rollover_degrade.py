"""test_context_rollover_degrade.py — rollover when its inputs are missing.

design: strata-spend-leaks (Task 4.1), Constraints + Non-goals: with no tmux the
rollover is unavailable and says so in one line; with no transcript the context size is
unknown and it says that in one line. Either way it **sends nothing** and exits 0 —
never a silent clear, never a guess. (The driver's own degrade cases live here, split
from test_context_rollover_drive.py by scenario.)

Same fakes as the drive tests: `tmux_blocker` stands in for "no tmux binary / no run
session", `session` and `records` for the transcript lookup. Nothing here touches a
real tmux server, git or config dir.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import context_rollover_drive as drive  # noqa: E402
from test_context_rollover_drive import Harness, _assistant  # noqa: E402


def test_no_tmux_prints_one_unavailable_line(tmp_path):
    """No tmux: exactly one line naming the reason, exit 0, and nothing else printed."""
    h = Harness(tmp_path, [_assistant()], tmux_blocker="tmux binary not found")
    assert h.run() == 0
    lines = h.lines_starting("context rollover unavailable:")
    assert len(lines) == 1
    assert len(h.lines) == 1
    assert "tmux binary not found" in lines[0]


def test_no_transcript_prints_size_unknown(tmp_path):
    """No readable transcript: one `context size unknown:` line, exit 0.

    Both shapes of "no transcript" count: no session id to read, and a transcript
    whose records cannot be read at all.
    """
    h = Harness(tmp_path, [_assistant()], session_id=None)
    assert h.run() == 0
    assert len(h.lines_starting("context size unknown:")) == 1

    h = Harness(tmp_path, [])
    h.ledger = tmp_path / "ctx-empty.json"
    assert h.run() == 0
    assert len(h.lines_starting("context size unknown:")) == 1


def test_degrade_never_sends(tmp_path):
    """A degraded run sends no keys at all — an unavailable rollover is advice, not a
    `/clear` into a window nobody measured."""
    cases = [({"tmux_blocker": "no tmux"}, [_assistant()]),
             ({"session_id": None}, [_assistant()]), ({}, [])]
    for kwargs, recs in cases:
        h = Harness(tmp_path, recs, **kwargs)
        assert h.run() == 0
        assert h.sent == []
        assert not h.ledger.exists()
