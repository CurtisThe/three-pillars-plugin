"""Hermetic tests for design_run_verdict.py — pure reads of one frame, no tmux, no clock.

design: fleet-watcher-reliability (Task 1.4). `before_send` judges the box before any key is
typed (`None` = go ahead, `queued`, `occupied`); `after_send` judges the frame after Enter
(`queued` before any `delivered` evidence, so a busy run's growing transcript never turns a
held line into a delivered one). Fixtures follow skills/_shared/test-fragility.md: the
contract is the verdict, never the helper that computes it.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design_run_send as drs  # noqa: E402
import design_run_verdict as drv  # noqa: E402

LINE = "Seat (under operator delegation): read seat-brief.md and follow it"
SPINNER = "✻ Working… (esc to interrupt)"


def frame(box: str, busy: bool = False) -> str:
    return "some output\n" + (SPINNER + "\n" if busy else "") + f"│ > {box} │\n"


def ghost_frame(busy: bool = False) -> str:
    return ("some output\n" + (SPINNER + "\n" if busy else "")
            + "│ > \x1b[2mtry asking something\x1b[0m │\n")


# --- before_send ------------------------------------------------------------------------------


@pytest.mark.parametrize("busy", [False, True], ids=["idle", "busy"])
def test_an_empty_or_ghost_box_is_clear_to_type_into(busy):
    assert drv.before_send(frame("", busy), LINE) is None
    assert drv.before_send(ghost_frame(busy), LINE) is None


def test_a_frame_with_no_input_box_has_nothing_to_judge():
    assert drv.before_send("just a spinner\n" + SPINNER + "\n", LINE) is None


def test_a_busy_box_holding_exactly_the_line_is_queued():
    assert drv.before_send(frame(LINE, busy=True), LINE) == "queued"


def test_the_line_is_compared_whitespace_normalized():
    spaced = "Seat  (under operator   delegation):  read seat-brief.md and follow it"
    assert drv.before_send(frame(spaced, busy=True), LINE) == "queued"
    assert drv.before_send(frame(LINE, busy=True), "  " + spaced + " ") == "queued"


def test_an_idle_box_holding_exactly_the_line_is_occupied():
    assert drv.before_send(frame(LINE, busy=False), LINE) == "occupied"


@pytest.mark.parametrize("busy", [False, True], ids=["idle", "busy"])
def test_a_box_holding_other_text_is_occupied_busy_or_not(busy):
    assert drv.before_send(frame("old text", busy), LINE) == "occupied"
    assert drv.before_send(frame(LINE + " and more", busy), LINE) == "occupied"
    assert drv.before_send(frame(LINE[:20], busy), LINE) == "occupied"


def test_busy_is_read_through_escape_codes():
    split = f"out\n\x1b[2m✻ Working… (\x1b[0mesc to \x1b[1minterrupt\x1b[0m)\n│ > {LINE} │\n"
    assert drv.before_send(split, LINE) == "queued"


# --- after_send -------------------------------------------------------------------------------


def test_a_busy_run_still_holding_the_line_is_queued_even_when_the_transcript_grew():
    busy_held = frame(LINE, busy=True)
    assert drv.after_send(busy_held, was_busy=True, grew=True) == "queued"
    assert drv.after_send(busy_held, was_busy=True, grew=False) == "queued"


def test_queued_needs_the_run_to_have_been_busy_before_the_line_went_in():
    held = frame(LINE, busy=True)
    assert drv.after_send(held, was_busy=False, grew=False) == "delivered"  # it turned busy
    assert drv.after_send(frame(LINE), was_busy=False, grew=True) == "delivered"


def test_idle_before_busy_after_with_the_line_in_the_box_is_delivered():
    assert drv.after_send(frame(LINE, busy=True), was_busy=False, grew=False) == "delivered"


def test_a_grown_transcript_counts_as_delivered_for_an_idle_run():
    assert drv.after_send(frame(LINE), was_busy=False, grew=True) == "delivered"


@pytest.mark.parametrize("was_busy", [False, True], ids=["was-idle", "was-busy"])
def test_an_empty_or_ghost_box_after_enter_is_delivered(was_busy):
    for busy in (False, True):
        assert drv.after_send(frame("", busy), was_busy=was_busy, grew=False) == "delivered"
        assert drv.after_send(ghost_frame(busy), was_busy=was_busy, grew=False) == "delivered"


def test_no_evidence_keeps_the_existing_path():
    assert drv.after_send(frame(LINE), was_busy=False, grew=False) is None
    assert drv.after_send("just a spinner\n", was_busy=False, grew=False) is None
    assert drv.after_send("nothing\n", was_busy=True, grew=False) is None


def test_the_verdict_words_are_the_senders_words():
    assert (drv.DELIVERED, drv.QUEUED, drv.OCCUPIED) == (
        drs.DELIVERED, drs.QUEUED, drs.OCCUPIED) == ("delivered", "queued", "occupied")


# --- the transcript-size seam the CLI builds ----------------------------------------------------


PORCELAIN = ("worktree /r\nHEAD abc\nbranch refs/heads/master\n\n"
             "worktree /r/wt/foo\nHEAD def\nbranch refs/heads/tp/foo\n")


def _sizer(tmp_path, *, listing=lambda: PORCELAIN, runner=object()):
    seen = []

    def project_dir(slug, worktree, run, env):
        seen.append((slug, worktree, run is runner))
        return tmp_path

    return drv.transcript_sizer("foo", runner, listing=listing, project_dir=project_dir), seen


def test_the_sizer_measures_the_newest_transcript_of_the_runs_worktree(tmp_path):
    old, new = tmp_path / "old.jsonl", tmp_path / "new.jsonl"
    old.write_text("x" * 500, encoding="utf-8")
    new.write_text("y" * 100, encoding="utf-8")
    os.utime(old, (1, 1))
    size, seen = _sizer(tmp_path)
    assert size() == 100 and seen == [("foo", "/r/wt/foo", True)]
    new.write_text("y" * 180, encoding="utf-8")
    assert size() == 180  # re-read every call: a new line in the transcript shows


def test_the_sizer_has_no_answer_for_an_empty_transcript_dir(tmp_path):
    size, _ = _sizer(tmp_path)
    assert size() is None


@pytest.mark.parametrize("why", ["no-runner", "no-listing", "no-worktree", "listing-raises"])
def test_any_failure_to_find_the_transcript_means_no_seam(tmp_path, why):
    def raises():
        raise OSError("git is gone")

    runner = None if why == "no-runner" else object()
    listing = {"no-listing": lambda: None, "no-worktree": lambda: "worktree /r\n",
               "listing-raises": raises}.get(why, lambda: PORCELAIN)
    assert drv.transcript_sizer("foo", runner, listing=listing,
                                project_dir=lambda *a: tmp_path) is None


def test_a_project_dir_that_raises_means_no_seam():
    def broken(*args):
        raise RuntimeError("no config dir")

    assert drv.transcript_sizer("foo", object(), listing=lambda: PORCELAIN,
                                project_dir=broken) is None
