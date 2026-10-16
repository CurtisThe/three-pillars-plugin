"""Hermetic tests for design_run_send.py — a scripted fake tmux, no real server."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design_run_send as drs  # noqa: E402

LINE = "Seat (under operator delegation): read seat-brief.md and follow it"
EMPTY = "some output\n│ > │\n"
FULL = f"some output\n│ > {LINE} │\n"


class Clock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


class FakeTmux:
    """Canned `capture-pane` frames (the last one repeats); records every call."""

    def __init__(self, frames, session=True, fail_keys=False):
        self.frames, self.session, self.fail_keys = list(frames), session, fail_keys
        self.calls = []

    def __call__(self, args):
        args = list(args)
        self.calls.append(args)
        if args[0] == "has-session":
            return (0 if self.session else 1), ""
        if args[0] == "list-windows":
            return 0, "3 @8\n1 @5"
        if args[0] == "capture-pane":
            frame = self.frames.pop(0) if len(self.frames) > 1 else self.frames[0]
            return 0, frame
        if args[0] == "send-keys":
            return (1, "boom") if self.fail_keys else (0, "")
        return 0, ""

    def keys(self):
        return [c[3:] for c in self.calls if c[0] == "send-keys"]


def _deliver(tmux, clk=None, **kw):
    clk = clk or Clock()
    return drs.deliver("foo", LINE, tmux, clock=clk.now, sleep=clk.sleep, **kw)


def test_empty_box_delivers_with_exact_keys():
    tmux = FakeTmux([EMPTY, EMPTY, EMPTY])
    assert _deliver(tmux) == "delivered"
    assert tmux.keys() == [["C-e"], ["C-u"], ["-l", LINE], ["Enter"]]
    assert all(c[2] == "@5" for c in tmux.calls if c[0] == "send-keys")  # lowest-index window
    assert not any("Escape" in c for c in tmux.calls)
    assert all("-e" in c for c in tmux.calls if c[0] == "capture-pane")


def test_text_left_after_enter_gets_one_more_enter():
    tmux = FakeTmux([EMPTY, FULL, EMPTY])
    assert _deliver(tmux) == "delivered"
    assert tmux.keys()[-2:] == [["Enter"], ["Enter"]]


def test_text_never_clears_is_not_delivered():
    tmux = FakeTmux([EMPTY, FULL, FULL])
    assert _deliver(tmux) == "not-delivered"
    assert tmux.keys().count(["Enter"]) == 2


def test_no_prompt_line_is_unverified_without_typing():
    tmux = FakeTmux(["just a spinner\n"])
    clk = Clock()
    assert _deliver(tmux, clk, ready_timeout=10) == "unverified"
    assert tmux.keys() == [] and clk.t <= 10


def test_missing_session():
    assert _deliver(FakeTmux([EMPTY], session=False)) == "no-session"


def test_failing_send_keys_is_tmux_error():
    assert _deliver(FakeTmux([EMPTY], fail_keys=True)) == "tmux-error"


def test_ghost_text_counts_as_empty():
    for sgr in ("\x1b[2m", "\x1b[90m", "\x1b[38;5;244m", "\x1b[38;2;120;120;120m"):
        ghost = f"out\n│ > {sgr}try asking something\x1b[0m │\n"
        assert drs.box_text(ghost) == ("try asking something", True), sgr
        assert _deliver(FakeTmux([ghost, ghost])) == "delivered", sgr


def test_coloured_text_is_not_a_ghost():
    for sgr in ("\x1b[38;5;100m", "\x1b[38;2;120;121;120m", "\x1b[1m", ""):
        frame = f"out\n│ ❯ {sgr}hello\x1b[0m │\n"
        assert drs.box_text(frame) == ("hello", False), sgr


def test_box_text_uses_the_last_prompt_line_and_handles_missing():
    assert drs.box_text("> old\nstuff\n│ > new │\n") == ("new", False)
    assert drs.box_text("nothing here\n") is None
    assert drs.box_text("│ > │") == ("", False)


def test_manual_command_quotes_the_line():
    cmd = drs.manual_command("foo", LINE)
    assert cmd.endswith(f"design_run_send.py foo '{LINE}'")


def test_main_exit_codes(capsys, monkeypatch):
    monkeypatch.setattr(drs, "_tmux_runner", lambda: FakeTmux([EMPTY]))
    assert drs.main(["foo", LINE]) == 0
    assert "delivered" in capsys.readouterr().out
    monkeypatch.setattr(drs, "_tmux_runner", lambda: FakeTmux([EMPTY], session=False))
    assert drs.main(["foo", LINE]) == 1
    assert "no-session" in capsys.readouterr().out
    monkeypatch.setattr(drs, "_tmux_runner", lambda: None)
    assert drs.main(["foo", LINE]) == 1
    assert drs.main(["foo"]) == 2


MENU_FRAME = ("Bash command\n  rm x\nDo you want to proceed?\n"
              "│ ❯ 1. Yes │\n│   2. No │\n")


def test_menu_row_is_not_the_input_box():
    assert drs.box_text("│ ❯ 1. Yes │\n│   2. No │\n") is None
    assert drs.box_text("> real\n│ ❯ 2.  Other │\n") == ("real", False)
    assert drs.box_text("│ ❯ 1st place │\n") == ("1st place", False)


def test_menu_frame_sends_no_keys():
    for frame in (MENU_FRAME, "out\n❯ 1. Yes\n", "Do you want to proceed?\n> \n"):
        tmux = FakeTmux([frame])
        assert _deliver(tmux) == "menu", frame
        assert tmux.keys() == []


def test_menu_appearing_after_typing_blocks_the_retry_enter():
    tmux = FakeTmux([EMPTY, MENU_FRAME])
    assert _deliver(tmux) == "menu"
    assert tmux.keys().count(["Enter"]) == 1  # the first Enter only, no retry


def test_main_menu_exits_1(capsys, monkeypatch):
    monkeypatch.setattr(drs, "_tmux_runner", lambda: FakeTmux([MENU_FRAME]))
    assert drs.main(["foo", LINE]) == 1
    assert "menu" in capsys.readouterr().out


def test_bright_and_white_text_is_typed_text_not_a_ghost():
    for sgr in ("\x1b[97m", "\x1b[91m", "\x1b[38;2;255;255;255m", "\x1b[38;2;200;200;200m"):
        frame = f"out\n│ > {sgr}hello\x1b[0m │\n"
        assert drs.box_text(frame) == ("hello", False), sgr


def test_dim_boundaries_are_ghosts():
    for sgr in ("\x1b[2m", "\x1b[90m", "\x1b[38;5;244m", "\x1b[38;2;128;128;128m",
                "\x1b[38;2;160;160;160m"):
        assert drs.box_text(f"│ > {sgr}ghost\x1b[0m │")[1] is True, sgr


def test_numbered_line_in_the_input_box_is_text_not_a_menu():
    """A relayed line like `1. Yes, continue` typed into the `>` box is input text, so
    deliver verifies it (one more Enter) instead of bailing out as `menu`."""
    line = "1. Yes, continue with the plan"
    full = f"some output\n│ > {line} │\n"
    assert drs.box_text(full) == (line, False) and drs.has_menu(full) is False
    assert drs.has_menu(f"> {line}\n│ > │\n") is False  # the echoed message in scrollback
    clk = Clock()
    tmux = FakeTmux([EMPTY, full, EMPTY])
    assert drs.deliver("foo", line, tmux, clock=clk.now, sleep=clk.sleep) == "delivered"
    assert tmux.keys()[-2:] == [["Enter"], ["Enter"]]
