"""The caps watch loop: one line per verdict crossing, never repeated.

design: review-convergence (Task 7.2), detailed-design-caps.md §The watch loop.
Behaviour 14. Assertions are on parsed verdict lines only — never on how many
times the loop slept or on the exact text of a line.
"""
import datetime
import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent_caps_watch  # noqa: E402

ISO = "2026-10-11T04:51:34-06:00"  # as phase-check.md and convergence-rules.md document it


class Clock:
    """Fake clock: `now()` reads `t`, `sleep(s)` just moves `t` forward."""

    def __init__(self, t=0.0):
        self.t = float(t)

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


def json_lines(out):
    """The JSON verdict lines from a StringIO sink or a captured str."""
    text = out.getvalue() if hasattr(out, "getvalue") else str(out)
    return [json.loads(line) for line in text.splitlines() if line.startswith("{")]


def verdicts(out):
    return [line["verdict"] for line in json_lines(out)]


def spawn(root, slot="s1", agent_id="a1", started=0):
    return agent_caps_watch.record_spawn(root, slot, agent_id, started)


def test_soft_cap_prints_wrap_up_once(tmp_path):
    clock, out = Clock(1000), io.StringIO()
    spawn(tmp_path)
    assert agent_caps_watch.run(tmp_path, now_fn=clock.now, sleep_fn=clock.sleep,
                                out=out, once=True) == 0
    got = json_lines(out)
    assert len(got) == 1
    assert got[0]["verdict"] == "wrap-up"
    assert got[0]["slot"] == "s1"
    assert got[0]["agent_id"] == "a1"


def test_hard_cap_prints_stop_once(tmp_path):
    clock, out = Clock(1600), io.StringIO()
    spawn(tmp_path)
    assert agent_caps_watch.run(tmp_path, now_fn=clock.now, sleep_fn=clock.sleep,
                                out=out, once=True) == 0
    assert verdicts(out) == ["stop"]


def test_full_loop_wrap_up_then_stop(tmp_path):
    clock, out = Clock(900), io.StringIO()
    spawn(tmp_path)
    assert agent_caps_watch.run(tmp_path, now_fn=clock.now, sleep_fn=clock.sleep,
                                out=out, interval=300) == 0
    assert verdicts(out) == ["wrap-up", "stop"]


def test_later_run_prints_nothing(tmp_path):
    spawn(tmp_path)
    first = Clock(900)  # one clock: its sleep advances the time `now` reports
    agent_caps_watch.run(tmp_path, now_fn=first.now, sleep_fn=first.sleep,
                         out=io.StringIO(), interval=300)
    out, later = io.StringIO(), Clock(5000)
    assert agent_caps_watch.run(tmp_path, now_fn=later.now, sleep_fn=later.sleep,
                                out=out, once=True) == 0
    assert json_lines(out) == []


def test_unwatched_role_raises_and_writes_nothing(tmp_path):
    with pytest.raises(ValueError):
        agent_caps_watch.record_spawn(tmp_path, "s1", "a1", 0, role="nope")
    assert not (tmp_path / "s1" / agent_caps_watch.SPAWN).exists()


def read_spawn(root, slot="finder"):
    p = Path(root) / slot / agent_caps_watch.SPAWN
    return json.loads(p.read_text(encoding="utf-8"))


def test_cli_started_accepts_iso_timestamp(tmp_path):
    """impl-audit s8: `spawned --started` takes an ISO timestamp, not only epoch."""
    assert agent_caps_watch.main(["spawned", "--slot-root", str(tmp_path),
                                  "--slot", "finder", "--agent-id", "a",
                                  "--started", ISO]) == 0
    assert read_spawn(tmp_path)["started"] == datetime.datetime.fromisoformat(
        ISO).timestamp()


def test_cli_started_epoch_input_unchanged(tmp_path):
    assert agent_caps_watch.main(["spawned", "--slot-root", str(tmp_path),
                                  "--slot", "finder", "--agent-id", "a",
                                  "--started", "1791716432.5"]) == 0
    assert read_spawn(tmp_path)["started"] == 1791716432.5


def test_cli_started_unparseable_returns_2(tmp_path):
    assert agent_caps_watch.main(["spawned", "--slot-root", str(tmp_path),
                                  "--slot", "finder", "--agent-id", "a",
                                  "--started", "not-a-time"]) == 2
    assert not (tmp_path / "finder" / agent_caps_watch.SPAWN).exists()
