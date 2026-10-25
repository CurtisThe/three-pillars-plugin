"""test_context_rollover_settle.py — the driver's default idle at a transcript boundary.

design: followups-1024 (Task 1.6, Behavior 6) — `end_turn` with nothing after it is the
boundary proof; the idle stretch only lets the pane settle, so the default is short enough
that a pane which changes every 10 s (a spinner clock) no longer holds a due run. A last
turn that calls a tool is still held.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import context_rollover_drive as drive  # noqa: E402
from test_context_rollover_drive import SLUG, Harness, _assistant  # noqa: E402


class SettlingPane(Harness):
    """A pane whose text changes every 10 s on the fake clock; default idle_s."""

    def pane(self):
        return f"✻ Baked for {int(self.now // 10)}s"

    def run(self):
        return drive.rollover(
            SLUG, str(self.tmp_path), threshold=self.threshold,
            save_timeout_s=self.save_timeout_s, send=self.send,
            handoff_sha=self.handoff_sha, records=self.records, pane=self.pane,
            clock=self.clock, sleep=self.sleep, ledger=self.ledger,
            out=self.lines.append, session=self.session,
            tmux_blocker=self.tmux_blocker)


def test_end_turn_rolls_under_the_default_idle(tmp_path):
    """A changing pane is no reason to hold: `end_turn` is the boundary proof."""
    h = SettlingPane(tmp_path, [_assistant()])
    assert h.run() == 0
    assert h.sent == [f"/tp-session-save {SLUG}", "/clear",
                      f"/tp-session-restore {SLUG}", drive.resume_line(SLUG)]
    assert h.lines_starting("rollover done")


def test_tool_call_turn_is_still_held(tmp_path):
    """A last turn that calls a tool is mid-turn: held, nothing sent."""
    h = SettlingPane(tmp_path, [_assistant(tool_use=True)])
    assert h.run() == 0
    assert h.sent == []
    assert len(h.lines_starting("context rollover held:")) == 1
