"""Hermetic tests for the `queued` / `occupied` verdicts of design_run_send.deliver.

design: fleet-watcher-reliability (Task 1.4). A scripted fake tmux, an injected clock and an
injected transcript-size seam: no real tmux server, no sleep, no git. The contract is the
outcome plus the exact keys the runner saw, never how the verdict is computed
(skills/_shared/test-fragility.md).
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design_run_delivery as drd  # noqa: E402
import design_run_routing as drr  # noqa: E402
import design_run_send as drs  # noqa: E402
from test_design_run_send import LINE, Clock, FakeTmux  # noqa: E402

SPINNER = "✻ Working… (esc to interrupt)"
IDLE_EMPTY = "out\n│ > │\n"
IDLE_HELD = f"out\n│ > {LINE} │\n"
BUSY_EMPTY = f"out\n{SPINNER}\n│ > │\n"
BUSY_HELD = f"out\n{SPINNER}\n│ > {LINE} │\n"
OLD_IDLE = "out\n│ > old text │\n"
OLD_BUSY = f"out\n{SPINNER}\n│ > old text │\n"
TYPED = [["C-e"], ["C-u"], ["-l", LINE], ["Enter"]]


class Sizes:
    """A transcript-size seam that walks a script, then repeats its last value."""

    def __init__(self, *sizes):
        self.sizes, self.calls = list(sizes), 0

    def __call__(self):
        self.calls += 1
        return self.sizes.pop(0) if len(self.sizes) > 1 else self.sizes[0]


def _deliver(tmux, **kw):
    clk = Clock()
    return drs.deliver("foo", LINE, tmux, clock=clk.now, sleep=clk.sleep, **kw)


def _enters(tmux):
    return tmux.keys().count(["Enter"])


# --- queued -----------------------------------------------------------------------------------


def test_a_busy_run_holding_the_typed_line_is_queued_with_one_enter():
    tmux = FakeTmux([BUSY_EMPTY, BUSY_HELD, BUSY_HELD])
    assert _deliver(tmux) == "queued"
    assert tmux.keys() == TYPED  # the one Enter, never the second
    assert _enters(tmux) == 1


def test_queued_wins_while_the_busy_runs_transcript_grows():
    sizes = Sizes(100, 180, 260)
    tmux = FakeTmux([BUSY_EMPTY, BUSY_HELD, BUSY_HELD])
    assert _deliver(tmux, transcript_size=sizes) == "queued"
    assert _enters(tmux) == 1 and sizes.calls >= 2


def test_a_busy_box_already_holding_exactly_the_line_is_queued_without_keys():
    tmux = FakeTmux([BUSY_HELD])
    assert _deliver(tmux) == "queued"
    assert tmux.keys() == []


def test_the_held_line_is_matched_whitespace_normalized():
    tmux = FakeTmux([f"out\n{SPINNER}\n│ > {LINE.replace(' ', '  ')} │\n"])
    assert _deliver(tmux) == "queued"
    assert tmux.keys() == []


# --- occupied ---------------------------------------------------------------------------------


@pytest.mark.parametrize("frame", [OLD_IDLE, OLD_BUSY], ids=["idle", "busy"])
def test_a_box_holding_other_text_is_occupied_and_gets_no_keys_at_all(frame):
    tmux = FakeTmux([frame])
    assert _deliver(tmux) == "occupied"
    assert not any(c[0] == "send-keys" for c in tmux.calls)  # no C-e, no C-u either


def test_an_idle_box_holding_exactly_the_line_is_occupied_without_keys():
    tmux = FakeTmux([IDLE_HELD])
    assert _deliver(tmux) == "occupied"
    assert not any(c[0] == "send-keys" for c in tmux.calls)


# --- delivered evidence beyond an empty box ----------------------------------------------------


def test_a_frame_that_turns_busy_after_enter_with_the_line_in_the_box_is_delivered():
    tmux = FakeTmux([IDLE_EMPTY, BUSY_HELD, BUSY_HELD])
    assert _deliver(tmux) == "delivered"
    assert _enters(tmux) == 1  # the spinner is the evidence: no second Enter


def test_a_transcript_growing_from_100_to_180_is_delivered():
    tmux = FakeTmux([IDLE_EMPTY, IDLE_HELD, IDLE_HELD])
    assert _deliver(tmux, transcript_size=Sizes(100, 180)) == "delivered"
    assert _enters(tmux) == 1


def test_a_transcript_that_does_not_grow_is_no_evidence():
    tmux = FakeTmux([IDLE_EMPTY, IDLE_HELD, IDLE_HELD])
    assert _deliver(tmux, transcript_size=Sizes(100, 100)) == "not-delivered"
    assert _enters(tmux) == 2  # today's path: one more Enter


@pytest.mark.parametrize("seam", [lambda: None, lambda: 1 / 0], ids=["none", "raises"])
def test_a_seam_with_no_answer_is_treated_as_not_checked(seam):
    tmux = FakeTmux([IDLE_EMPTY, IDLE_HELD, IDLE_HELD])
    assert _deliver(tmux, transcript_size=seam) == "not-delivered"
    assert _enters(tmux) == 2


def test_an_empty_idle_box_is_still_delivered_with_the_seam_off():
    tmux = FakeTmux([IDLE_EMPTY, IDLE_EMPTY])
    assert _deliver(tmux) == "delivered"
    assert tmux.keys() == TYPED


def test_a_menu_still_blocks_even_when_the_transcript_grew():
    menu = "Bash command\n  rm x\nDo you want to proceed?\n│ ❯ 1. Yes │\n│   2. No │\n"
    tmux = FakeTmux([IDLE_EMPTY, menu])
    assert _deliver(tmux, transcript_size=Sizes(100, 180)) == "menu"
    assert _enters(tmux) == 1


# --- the CLI ------------------------------------------------------------------------------------


@pytest.fixture
def no_seam(monkeypatch):
    import design_run_verdict as drv  # noqa: E402  (a function-level import: the red fails on behaviour)
    monkeypatch.setattr(drv, "transcript_sizer", lambda *a, **k: None)
    return drv


def test_main_prints_queued_and_exits_0(capsys, monkeypatch, no_seam):
    monkeypatch.setattr(drs, "_tmux_runner", lambda: FakeTmux([BUSY_EMPTY, BUSY_HELD]))
    assert drs.main(["foo", LINE]) == 0
    assert capsys.readouterr().out.strip() == "queued: foo"


@pytest.mark.parametrize("frame", [OLD_IDLE, OLD_BUSY], ids=["idle", "busy"])
def test_main_exits_1_for_occupied(capsys, monkeypatch, no_seam, frame):
    monkeypatch.setattr(drs, "_tmux_runner", lambda: FakeTmux([frame]))
    assert drs.main(["foo", LINE]) == 1
    assert capsys.readouterr().out.strip() == "occupied: foo"


def test_main_hands_the_sizer_the_slug_and_the_runner_and_uses_what_it_returns(
        capsys, monkeypatch, no_seam):
    runner = FakeTmux([IDLE_EMPTY, IDLE_HELD])
    seen = []
    monkeypatch.setattr(drs, "_tmux_runner", lambda: runner)
    monkeypatch.setattr(no_seam, "transcript_sizer",
                        lambda slug, run, **k: seen.append((slug, run)) or Sizes(100, 180))
    assert drs.main(["foo", LINE]) == 0
    assert seen == [("foo", runner)]
    assert capsys.readouterr().out.strip() == "delivered: foo"


# --- the launcher report ------------------------------------------------------------------------


def _report(monkeypatch, tmp_path, outcome):
    brief = tmp_path / "seat-brief.md"
    brief.write_text("brief\n", encoding="utf-8")
    monkeypatch.setattr(drr, "wait_for_run", lambda *a, **k: None)
    monkeypatch.setattr(drs, "deliver", lambda *a, **k: outcome)
    return drd.report("foo", None, 5.0, brief=(str(brief), "seed"), env={"PATH": ""})


def test_the_report_prints_no_resend_command_for_queued(capsys, monkeypatch, tmp_path):
    assert _report(monkeypatch, tmp_path, "queued") == "queued"
    out = capsys.readouterr().out
    assert "first message queued" in out
    assert "send it with:" not in out and "design_run_send.py" not in out


@pytest.mark.parametrize("outcome", ["not-delivered", "unverified"])
def test_the_report_still_prints_the_resend_command_for_the_other_outcomes(
        capsys, monkeypatch, tmp_path, outcome):
    assert _report(monkeypatch, tmp_path, outcome) == outcome
    assert f"first message {outcome}; send it with:" in capsys.readouterr().out
