"""test_measure_window_history.py — the append-only window history (post-hoc reads it).

design: cheap-tier-local-routing (B4)

The live file vanishes at expiry, but the post-hoc analysis still has to know which design
owned the GPU when. ``start`` and ``stop`` each append one line to
``measure-windows.ndjson`` and never rewrite it; ``history`` folds the lines into
``{design, start, end}`` windows and ``role_at`` answers owner/other/off at any instant.
Every test points the env at ``tmp_path`` and injects the clock.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

import measure_window

T0 = dt.datetime(2026, 10, 1, 12, 0, 0, tzinfo=dt.timezone.utc)
HOUR = dt.timedelta(hours=1)
MINUTE = dt.timedelta(minutes=1)


@pytest.fixture
def env(tmp_path):
    return {"HOME": str(tmp_path), "XDG_STATE_HOME": str(tmp_path / "state")}


@pytest.fixture
def ndjson(env):
    return Path(env["XDG_STATE_HOME"]) / "tp-local" / "measure-windows.ndjson"


def run(env, *argv, now=T0):
    return measure_window.main(list(argv), env=env, clock=lambda: now)


def when(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value)


def lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# ---- the append-only log ------------------------------------------------------------

def test_start_and_stop_each_append_one_line(env, ndjson):
    run(env, "start", "--design", "d1", "--hours", "2")
    assert len(lines(ndjson)) == 1
    run(env, "stop", now=T0 + HOUR)
    first, second = lines(ndjson)
    assert first["event"] == "start" and first["design"] == "d1"
    assert set(first) == {"event", "design", "started_at", "until", "set_by"}
    assert when(first["started_at"]) == T0 and when(first["until"]) == T0 + 2 * HOUR
    assert second["event"] == "stop" and second["design"] == "d1"
    assert set(second) == {"event", "design", "at"} and when(second["at"]) == T0 + HOUR


def test_the_log_is_only_ever_appended_to(env, ndjson):
    run(env, "start", "--design", "d1", "--hours", "2")
    before = ndjson.read_bytes()
    run(env, "stop", now=T0 + HOUR)
    run(env, "start", "--design", "d2", "--hours", "1", now=T0 + 3 * HOUR)
    after = ndjson.read_bytes()
    assert after.startswith(before) and len(after) > len(before)
    assert len(lines(ndjson)) == 3


def test_a_refused_start_appends_nothing(env, ndjson):
    run(env, "start", "--design", "d1", "--hours", "2")
    before = ndjson.read_bytes()
    assert run(env, "start", "--design", "d2", "--hours", "1", now=T0 + HOUR) == 2
    assert ndjson.read_bytes() == before


def test_a_stop_with_nothing_live_appends_nothing(env, ndjson):
    assert run(env, "stop") == 0
    assert not ndjson.exists()


# ---- history after expiry -----------------------------------------------------------

def test_history_outlives_the_live_window(env):
    run(env, "start", "--design", "d1", "--hours", "2")
    assert measure_window.load(env, clock=lambda: T0 + 3 * HOUR) is None
    (window,) = measure_window.history(env)
    assert window["design"] == "d1"
    assert when(window["start"]) == T0 and when(window["end"]) == T0 + 2 * HOUR


def test_role_at_reads_owner_other_or_off(env):
    run(env, "start", "--design", "d1", "--hours", "2")
    windows = measure_window.history(env)
    assert measure_window.role_at(windows, "d1", T0 + HOUR) == "owner"
    assert measure_window.role_at(windows, "d2", T0 + HOUR) == "other"
    assert measure_window.role_at(windows, None, T0 + HOUR) == "other"
    assert measure_window.role_at(windows, "d1", T0) == "owner"  # the start instant is inside
    assert measure_window.role_at(windows, "d1", T0 - MINUTE) == "off"
    assert measure_window.role_at(windows, "d1", T0 + 2 * HOUR) == "off"  # `until` is outside
    assert measure_window.role_at(windows, "d2", T0 + 5 * HOUR) == "off"
    assert measure_window.role_at([], "d1", T0) == "off"


def test_a_stop_before_until_ends_the_window_at_the_stop(env):
    run(env, "start", "--design", "d1", "--hours", "4")
    run(env, "stop", now=T0 + HOUR)
    windows = measure_window.history(env)
    assert [when(w["end"]) for w in windows] == [T0 + HOUR]
    assert measure_window.role_at(windows, "d1", T0 + HOUR - MINUTE) == "owner"
    assert measure_window.role_at(windows, "d1", T0 + HOUR) == "off"
    assert measure_window.role_at(windows, "d2", T0 + 2 * HOUR) == "off"


def test_a_stop_after_expiry_does_not_extend_the_window(env):
    run(env, "start", "--design", "d1", "--hours", "1")
    run(env, "stop", now=T0 + 3 * HOUR)
    (window,) = measure_window.history(env)
    assert when(window["end"]) == T0 + HOUR


def test_successive_windows_stay_separate(env):
    run(env, "start", "--design", "d1", "--hours", "1")
    run(env, "start", "--design", "d2", "--hours", "1", now=T0 + 2 * HOUR)
    windows = measure_window.history(env)
    assert [w["design"] for w in windows] == ["d1", "d2"]
    assert measure_window.role_at(windows, "d2", T0 + 30 * MINUTE) == "other"
    assert measure_window.role_at(windows, "d2", T0 + 2 * HOUR + 5 * MINUTE) == "owner"
    assert measure_window.role_at(windows, "d1", T0 + 90 * MINUTE) == "off"


def test_restarting_a_design_ends_its_earlier_window_at_the_restart(env):
    run(env, "start", "--design", "d1", "--hours", "5")
    run(env, "start", "--design", "d1", "--hours", "1", now=T0 + HOUR)
    first, second = measure_window.history(env)
    assert when(first["end"]) == T0 + HOUR
    assert when(second["start"]) == T0 + HOUR and when(second["end"]) == T0 + 2 * HOUR


# ---- tolerance ----------------------------------------------------------------------

def test_history_without_a_log_is_empty(env):
    assert measure_window.history(env) == []


def test_history_skips_malformed_lines(env, ndjson):
    run(env, "start", "--design", "d1", "--hours", "2")
    good = ndjson.read_bytes()
    junk = [b"not json", b"[]", b"7", b'{"event": "start"}', b'{"event": "other", "design": "d1"}',
            json.dumps({"event": "start", "design": "d9", "started_at": "soon",
                        "until": "later"}).encode(),
            json.dumps({"event": "stop", "design": "d1", "at": "yesterday"}).encode(),
            json.dumps({"event": "stop", "design": 3, "at": T0.isoformat()}).encode(),
            b"", b"\xff\xfe"]
    ndjson.write_bytes(b"\n".join(junk) + b"\n" + good + b"\n".join(junk) + b"\n")
    (window,) = measure_window.history(env)
    assert window["design"] == "d1" and when(window["end"]) == T0 + 2 * HOUR


def test_history_of_an_unreadable_log_is_empty(env, ndjson):
    ndjson.mkdir(parents=True)  # a directory: open() fails
    assert measure_window.history(env) == []


def test_history_ignores_a_stop_for_another_design(env, ndjson):
    run(env, "start", "--design", "d1", "--hours", "4")
    stop = {"event": "stop", "design": "d2", "at": (T0 + HOUR).isoformat()}
    with ndjson.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(stop) + "\n")
    (window,) = measure_window.history(env)
    assert when(window["end"]) == T0 + 4 * HOUR
