"""test_context_rollover_shell_busy.py — a running shell is not a turn boundary.

design: fleet-watcher-reliability (Task 1.1). Today `at_turn_boundary` only looks for the
word `background` anywhere in the pane, so a run with `1 shell still running` (a merge in
flight) reads as a boundary and gets `/clear`ed mid-shell, while the same word in prose
13 lines above the bottom holds a run that is genuinely parked. The boundary now asks the
one pane classifier: it holds on exactly the kinds `pane_activity.HOLD_REASONS` names, over
the classifier's 12-line tail, and says which of them it held on.

Pure, like `test_context_rollover_boundary.py`: the records, the pane text and the idle
seconds are arguments — no tmux, no clock.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import context_rollover as rollover  # noqa: E402
import pane_activity  # noqa: E402

IDLE_PANE = "✻ Baked for 3s"
SHELL_PANE = "✻ Baked for 3s\n1 shell still running"
BUSY_PANE = "✻ Thinking… (esc to interrupt)"
CARD_PANE = "Do you want to continue?\n❯ 1. Yes, run it\n  2. No, stop here"
BACKGROUND_PANE = "✻ Baked for 3s\n2 background agents running"


def _assistant(stop_reason="end_turn", msg_id="m1"):
    return {"type": "assistant", "isSidechain": False,
            "message": {"id": msg_id, "role": "assistant",
                        "content": [{"type": "text", "text": "done"}],
                        "stop_reason": stop_reason}}


def _boundary(pane):
    """An end_turn transcript, an idle run: the only variable is the pane."""
    return rollover.at_turn_boundary([_assistant()], pane, 60.0, 30.0)


def test_shell_still_running_holds_the_rollover():
    """The 2026-10-22 case: the run looks parked, a shell is still working."""
    assert _boundary(SHELL_PANE) == (False, "a shell is still running")


def test_spinner_holds_the_rollover():
    """A turn in flight is not a boundary either."""
    assert _boundary(BUSY_PANE) == (False, "the run is busy")


def test_open_card_holds_the_rollover():
    """A run waiting on a card is parked, but not at a turn boundary."""
    assert _boundary(CARD_PANE) == (False, "a card is open")


def test_background_line_holds_with_todays_text():
    """The background reason keeps its existing wording, so the boundary test that
    already covers it is unchanged."""
    assert _boundary(BACKGROUND_PANE) == (False, "background agents in the pane")


def test_holds_are_exactly_the_classifiers_blocking_kinds():
    """Every blocking kind the classifier names holds, with that kind's reason; nothing
    else does. One assertion per kind, driven off the classifier's own table."""
    panes_by_kind = {"card": CARD_PANE, "shell": SHELL_PANE, "busy": BUSY_PANE,
                     "background": BACKGROUND_PANE}
    assert set(panes_by_kind) == set(pane_activity.HOLD_REASONS)
    for kind, pane in panes_by_kind.items():
        assert pane_activity.classify(pane).kind == kind
        assert _boundary(pane) == (False, pane_activity.HOLD_REASONS[kind])


def test_background_in_older_prose_does_not_hold():
    """The word only in prose 13+ lines above the bottom is history: an idle tail is a
    boundary."""
    pane = ("the design mentions background agents holding a rollover\n"
            + "\n".join(f"note {i}" for i in range(13)))
    assert pane_activity.classify(pane).kind == "idle"
    assert _boundary(pane) == (True, "")


def test_idle_pane_is_still_a_boundary():
    """The same records over an idle pane still answer yes."""
    assert _boundary(IDLE_PANE) == (True, "")
