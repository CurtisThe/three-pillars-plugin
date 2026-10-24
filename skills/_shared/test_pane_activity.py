"""test_pane_activity.py — one classifier names what a run's pane is doing.

design: fleet-watcher-reliability (Task 1.1). The rollover boundary, the delivery verdict
and the status table all read the same pane, so all three must name its activity the same
way. `classify(pane)` reads the pane's last 12 lines and returns `Activity(kind, line)`
with the kinds in this precedence: card, shell, busy, background, idle — and `unknown` for
a pane that could not be read at all.

Pure: the pane text is the argument, so this test needs no tmux and no clock. The fixtures
are the real 2026-10-22 pane shapes (`esc to interrupt` while busy, `1 shell still
running` for a live shell, a `background` line for background agents).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pane_activity  # noqa: E402

IDLE_PANE = "✻ Baked for 3s"
BUSY_PANE = "✻ Thinking… (esc to interrupt)"
SHELL_PANE = "✻ Baked for 3s\n1 shell still running"
BACKGROUND_PANE = "✻ Baked for 3s\n2 background agents running"
CARD_MENU_PANE = "Do you want to continue?\n❯ 1. Yes, run it\n  2. No, stop here"


def kind_of(pane):
    return pane_activity.classify(pane).kind


def test_unreadable_pane_is_unknown():
    """A pane that could not be read names no activity at all."""
    act = pane_activity.classify(None)
    assert act.kind == "unknown"
    assert act.line == ""


def test_menu_row_is_a_card():
    """The numbered menu's selected row is a card waiting for an answer."""
    assert kind_of(CARD_MENU_PANE) == "card"


def test_question_marker_is_a_card():
    """The question above a menu is enough on its own — mirrors the watcher's marker."""
    assert kind_of("Keep going? Do you want to run the suite again?") == "card"


def test_one_shell_still_running_is_shell():
    """A live shell in the window is the 2026-10-22 case that read as idle."""
    assert kind_of(SHELL_PANE) == "shell"


def test_two_shells_still_running_is_shell():
    """The plural form of the same line is the same kind."""
    assert kind_of("2 shells still running") == "shell"


def test_shell_wins_over_a_spinner_in_the_same_frame():
    """Busy and a live shell at once: the shell is the longer-lived blocker."""
    assert kind_of(BUSY_PANE + "\n2 shells still running") == "shell"


def test_spinner_is_busy():
    """`esc to interrupt` is what the TUI shows while a turn is running."""
    assert kind_of(BUSY_PANE) == "busy"


def test_busy_wins_over_a_background_line_in_the_same_frame():
    """A spinner plus background agents is busy: the run itself has not stopped."""
    assert kind_of(BUSY_PANE + "\n2 background agents running") == "busy"


def test_background_line_names_its_own_line():
    """The background kind carries the line the table shows."""
    act = pane_activity.classify(BACKGROUND_PANE)
    assert act.kind == "background"
    assert act.line == "2 background agents running"


def test_a_card_frame_blocks_everything_below_it():
    """A frame with a card, a shell, a spinner and background agents is a card."""
    pane = "\n".join([CARD_MENU_PANE, BUSY_PANE, SHELL_PANE, BACKGROUND_PANE])
    assert kind_of(pane) == "card"


def test_idle_pane_is_idle_with_no_line():
    """Nothing blocking: kind `idle`, no line to show."""
    act = pane_activity.classify(IDLE_PANE)
    assert act.kind == "idle"
    assert act.line == ""


def test_only_the_last_twelve_lines_are_read():
    """`background` in prose 13 lines above the bottom is history, not a live agent."""
    pane = "the design says background agents hold the rollover\n" + "\n".join(
        f"note {i}" for i in range(13))
    assert kind_of(pane) == "idle"
    assert kind_of(pane + "\n1 background agent running") == "background"


def test_background_in_the_runs_own_reply_is_not_a_live_agent():
    """Only the harness's `N background agents/tasks` count line is `background`; a parked
    run whose reply mentions background agents is idle (PR #381 r1)."""
    reply = "⏺ Handoff saved; the background agents had finished. Stopping as asked.\n│ > │"
    assert kind_of(reply) == "idle"
    assert kind_of(reply + "\n  2 background tasks · ↓ to manage") == "background"


def test_reply_quoting_a_count_is_idle_and_a_joined_status_segment_is_background():
    """The count inside a reply's prose is still prose (PR #381 r2); the harness count as
    a `·`-joined status segment is still the count line."""
    reply = "⏺ Waited for the 2 background agents to finish; handoff saved. Stopping.\n│ > │"
    assert kind_of(reply) == "idle"
    assert kind_of("⏵⏵ accept edits on · 2 background tasks · ↓ to manage") == "background"


def test_wrapped_reply_continuation_opening_on_the_count_is_idle():
    """The TUI wraps a reply onto indented visual lines; one opening on the count is still
    prose, because no harness tail (`· …`, `running`, line end) closes it (PR #381 r2.1)."""
    pane = "⏺ Waited for the\n  2 background agents to finish; handoff saved.\n│ > │"
    assert kind_of(pane) == "idle"


def test_line_is_clipped_to_80_chars():
    """A long matched line reaches the table clipped, never wrapping the row."""
    pane = "2 background tasks · ↓ to manage · " + "x" * 120
    act = pane_activity.classify(pane)
    assert act.kind == "background"
    assert len(act.line) <= 80
    assert act.line.startswith("2 background tasks · ↓ to manage")


def test_line_is_one_line_and_stripped():
    """The matched line arrives as one display line, indentation removed."""
    act = pane_activity.classify("   1 shell still running   ")
    assert act.kind == "shell"
    assert act.line == "1 shell still running"


def test_kinds_are_the_documented_set():
    """The kinds every caller branches on are exactly the design's six, and the blocking
    ones are exactly the four a rollover holds on."""
    assert set(pane_activity.HOLD_REASONS) == {"card", "shell", "busy", "background"}
    assert pane_activity.TAIL_LINES == 12
