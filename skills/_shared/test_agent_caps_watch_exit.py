"""When every slot delivered, the caps watch has nothing to poll.

design: review-convergence (Task 7.2), detailed-design-caps.md §The watch loop.
Behaviour 14: exits when all replies exist, only running agents are polled, an
unrecorded dispatched slot gets one loud `caps:` line. Assertions are on parsed
lines only — the single sleep assertion here is the loop's exit, not a count.
"""
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent_caps_watch  # noqa: E402


class Clock:
    """Fake clock: `now()` reads `t`, `sleep(s)` just moves `t` forward."""

    def __init__(self, t=0.0):
        self.t = float(t)
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.t += seconds


def json_lines(out):
    """The JSON verdict lines from a StringIO sink or a captured str."""
    text = out.getvalue() if hasattr(out, "getvalue") else str(out)
    return [json.loads(line) for line in text.splitlines() if line.startswith("{")]


def spawn(root, slot, agent_id="a1", started=0):
    return agent_caps_watch.record_spawn(root, slot, agent_id, started)


def deliver(root, slot):
    (Path(root) / slot / agent_caps_watch.REPLY).write_text("done\n", encoding="utf-8")


def test_exits_when_every_reply_exists(tmp_path):
    spawn(tmp_path, "s1")
    deliver(tmp_path, "s1")
    clock, out = Clock(5000), io.StringIO()
    assert agent_caps_watch.run(tmp_path, now_fn=clock.now, sleep_fn=clock.sleep,
                                out=out) == 0
    assert out.getvalue() == ""
    assert clock.slept == []


def test_only_running_slots_are_polled(tmp_path):
    spawn(tmp_path, "a", "x1")
    spawn(tmp_path, "b", "x2")
    deliver(tmp_path, "a")
    clock, out = Clock(1600), io.StringIO()
    assert agent_caps_watch.run(tmp_path, now_fn=clock.now, sleep_fn=clock.sleep,
                                out=out, once=True) == 0
    assert [line["slot"] for line in json_lines(out)] == ["b"]


def test_unrecorded_slot_is_reported_once(tmp_path):
    spawn(tmp_path, "a", "x1")
    deliver(tmp_path, "a")
    clock, out = Clock(1600), io.StringIO()
    assert agent_caps_watch.run(tmp_path, now_fn=clock.now, sleep_fn=clock.sleep,
                                out=out, dispatched=("a", "b"), once=True) == 0
    plain = [line for line in out.getvalue().splitlines() if not line.startswith("{")]
    assert plain == ["caps: b dispatched without spawn record"]


def test_cli_records_then_watches_once(tmp_path, capsys):
    assert agent_caps_watch.main(["spawned", "--slot-root", str(tmp_path),
                                  "--slot", "s1", "--agent-id", "x1",
                                  "--started", "0"]) == 0
    capsys.readouterr()
    assert agent_caps_watch.main(["watch", "--slot-root", str(tmp_path),
                                  "--once"]) == 0
    parsed = json_lines(capsys.readouterr().out)
    assert [line["verdict"] for line in parsed] == ["stop"]
    assert parsed[0]["slot"] == "s1"
