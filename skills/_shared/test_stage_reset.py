"""Tests for stage_reset.py — idle detection and the reset gate (run-throughput 7.1).

`idle()` runs over the hand-built, scrubbed top-level tails in
`fixtures/stage_reset/tails.json`; the mtime-stability clock is injected through `now=`.
`should_reset()` is a table over the marker, the pane, each `--mode`, and light's two
boundaries (detailed-design-stage-reset.md §When a reset fires).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import stage_reset as sr  # noqa: E402

CASES = json.loads((HERE / "fixtures" / "stage_reset" / "tails.json").read_text(encoding="utf-8"))["cases"]
MTIME = 1_800_000_000.0


def _epoch(ts: str) -> float:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


def _write(tmp_path, records, mtime=MTIME):
    path = tmp_path / "session.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    os.utime(path, (mtime, mtime))
    return path


def _first_ts(case):
    return _epoch(CASES[case][0]["timestamp"])


# --- idle ------------------------------------------------------------------------------

def test_end_turn_with_trailing_stop_hook_and_system_records_is_idle(tmp_path):
    path = _write(tmp_path, CASES["end_turn_trailing"])
    assert sr.idle(path, _first_ts("end_turn_trailing"), now=MTIME + 3) is True


def test_streamed_null_chunk_then_end_turn_is_idle(tmp_path):
    path = _write(tmp_path, CASES["streamed_null_then_end_turn"])
    assert sr.idle(path, _first_ts("streamed_null_then_end_turn"), now=MTIME + 5) is True


def test_tool_use_after_end_turn_is_not_idle(tmp_path):
    path = _write(tmp_path, CASES["tool_use_after_end_turn"])
    assert sr.idle(path, _first_ts("tool_use_after_end_turn"), now=MTIME + 60) is False


def test_tool_use_record_after_end_turn_without_user_record_is_not_idle(tmp_path):
    records = [r for r in CASES["tool_use_after_end_turn"] if r["type"] != "user"]
    path = _write(tmp_path, records)
    assert sr.idle(path, _first_ts("tool_use_after_end_turn"), now=MTIME + 60) is False


def test_mtime_must_be_stable_for_three_seconds(tmp_path):
    path = _write(tmp_path, CASES["end_turn_trailing"])
    since = _first_ts("end_turn_trailing")
    assert sr.STABLE_S == 3
    assert sr.idle(path, since, now=MTIME + 2.9) is False
    assert sr.idle(path, since, now=MTIME + 3.0) is True


def test_end_turn_written_before_since_does_not_count(tmp_path):
    records = CASES["end_turn_trailing"]
    path = _write(tmp_path, records)
    after_end_turn = _epoch(records[-1]["timestamp"]) + 1
    assert sr.idle(path, after_end_turn, now=MTIME + 60) is False


def test_since_mid_reply_keeps_the_records_written_after_it(tmp_path):
    records = CASES["end_turn_trailing"]
    path = _write(tmp_path, records)
    since = _epoch(records[2]["timestamp"])  # the end_turn record itself
    assert sr.idle(path, since, now=MTIME + 60) is True


def test_missing_or_empty_transcript_is_not_idle(tmp_path):
    assert sr.idle(tmp_path / "absent.jsonl", 0.0, now=MTIME) is False
    assert sr.idle(_write(tmp_path, []), 0.0, now=MTIME + 60) is False


def test_undecodable_lines_are_skipped(tmp_path):
    path = _write(tmp_path, CASES["end_turn_trailing"])
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("{not json\n")
    os.utime(path, (MTIME, MTIME))
    assert sr.idle(path, _first_ts("end_turn_trailing"), now=MTIME + 3) is True


# --- should_reset ----------------------------------------------------------------------

INTERACTIVE = {"TP_STAGE_RESET": "pane", "TMUX_PANE": "%7"}


def test_marker_absent_is_non_interactive_even_inside_tmux():
    assert sr.should_reset({"TMUX_PANE": "%7"}, "full", "full", "plan") == (False, "non-interactive")
    assert sr.should_reset({"TP_STAGE_RESET": "other", "TMUX_PANE": "%7"},
                           "full", "full", "plan") == (False, "non-interactive")


def test_marker_without_a_pane_is_no_tmux_pane():
    assert sr.should_reset({"TP_STAGE_RESET": "pane"}, "full", "full", "plan") == (False, "no tmux pane")
    assert sr.should_reset({"TP_STAGE_RESET": "pane", "TMUX_PANE": ""},
                           "full", "full", "plan") == (False, "no tmux pane")


@pytest.mark.parametrize("mode, weight, boundary, expected", [
    ("full", "full", "plan", True),
    ("full", "full", "implement", True),
    ("full", "full", "review", True),
    ("full", "light", "plan", False),
    ("full", "light", "implement", True),
    ("full", "light", "review", True),
    ("design", "full", "plan", False),
    ("design", "full", "implement", False),
    ("design", "full", "review", False),
    ("plan", "full", "plan", False),
    ("plan", "full", "implement", False),
    ("plan", "full", "review", False),
    ("build", "full", "plan", False),
    ("build", "full", "implement", False),
    ("build", "full", "review", True),
    ("build", "light", "review", True),
])
def test_mode_window_table(mode, weight, boundary, expected):
    got = sr.should_reset(INTERACTIVE, mode, weight, boundary)
    assert got == ((True, "reset") if expected else (False, "outside mode window"))


def test_light_has_exactly_two_boundaries():
    resets = [b for b in sr.STAGES if sr.should_reset(INTERACTIVE, "full", "light", b)[0]]
    assert resets == ["implement", "review"]


@pytest.mark.parametrize("mode, weight, boundary", [
    ("fast", "full", "plan"), ("full", "spike", "plan"), ("full", "full", "design"),
])
def test_unknown_mode_weight_or_boundary_raises(mode, weight, boundary):
    with pytest.raises(ValueError):
        sr.should_reset(INTERACTIVE, mode, weight, boundary)
