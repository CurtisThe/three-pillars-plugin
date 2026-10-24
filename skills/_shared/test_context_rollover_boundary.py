"""test_context_rollover_boundary.py — when a session may be rolled over.

design: strata-spend-leaks (Task 3.1) — a rollover may only land at a turn boundary:
the transcript's last record ends the turn (`stop_reason: "end_turn"`, nothing after
it), the session has been idle for at least `idle_s`, and no background agents are
running in the pane. `due` is size >= threshold.

`at_turn_boundary(records, pane, idle_for_s, idle_s)` is pure: the caller supplies the
pane text, the idle seconds and the records, so this test needs no tmux and no clock.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import context_rollover as rollover  # noqa: E402
import design_run_watch as drw  # noqa: E402

PANE_IDLE = "✻ Baked for 3s"


def _assistant(stop_reason="end_turn", msg_id="m1"):
    return {"type": "assistant", "isSidechain": False,
            "message": {"id": msg_id, "role": "assistant",
                        "content": [{"type": "text", "text": "done"}],
                        "stop_reason": stop_reason}}


def _user(text="keep going"):
    return {"type": "user", "isSidechain": False,
            "message": {"role": "user", "content": [{"type": "text", "text": text}]}}


def _tool_result():
    return {"type": "user", "isSidechain": False,
            "message": {"role": "user",
                        "content": [{"type": "tool_result",
                                     "tool_use_id": "t1", "content": "ok"}]}}


def _system():
    return {"type": "system", "subtype": "turn_duration", "isSidechain": False}


def test_boundary_on_idle_end_turn():
    """A final `end_turn`, a trailing system record (allowed), an idle pane and enough
    idle seconds is a boundary."""
    records = [_assistant(), _system()]
    ok, reason = rollover.at_turn_boundary(records, PANE_IDLE, 45.0, 30.0)
    assert ok is True
    assert isinstance(reason, str)


def test_not_boundary_on_tool_use():
    """The last assistant record stopped on `tool_use`: a tool is still in flight."""
    records = [_assistant(stop_reason="tool_use")]
    ok, reason = rollover.at_turn_boundary(records, PANE_IDLE, 45.0, 30.0)
    assert ok is False
    assert reason


def test_not_boundary_when_user_record_last():
    """A trailing user record (here a `tool_result` answer) means the next turn has
    already started."""
    records = [_assistant(), _tool_result()]
    ok, reason = rollover.at_turn_boundary(records, PANE_IDLE, 45.0, 30.0)
    assert ok is False
    assert reason
    records = [_assistant(), _user()]
    ok, reason = rollover.at_turn_boundary(records, PANE_IDLE, 45.0, 30.0)
    assert ok is False
    assert reason


def test_not_boundary_with_background_agents():
    """A pane naming background agents means work is still running in the window."""
    pane = PANE_IDLE + "\n2 background agents running"
    assert drw.pane_activity.is_background_line("2 background agents running")
    records = [_assistant()]
    ok, reason = rollover.at_turn_boundary(records, pane, 45.0, 30.0)
    assert ok is False
    assert reason


def test_not_boundary_before_idle():
    """`idle_for_s` under `idle_s` is mid-turn as far as the run is concerned."""
    records = [_assistant()]
    ok, reason = rollover.at_turn_boundary(records, PANE_IDLE, 5.0, 30.0)
    assert ok is False
    assert reason


def test_due_at_threshold_inclusive():
    """Due is >= threshold; the default threshold is the design's 300k."""
    assert rollover.DEFAULT_THRESHOLD == 300_000
    assert rollover.due(300_000, 300_000) is True
    assert rollover.due(299_999, 300_000) is False
    assert rollover.due(400_000, 300_000) is True
