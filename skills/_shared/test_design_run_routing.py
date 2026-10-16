"""test_design_run_routing.py — the run's routing line, read from its process environ.

design: design-run-launch-defaults (Behavior 3)
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design_run_routing as drr  # noqa: E402
from test_design_run_tmux import FakeTmux  # noqa: E402

ENVIRON = (b"A=1\0ANTHROPIC_BASE_URL=http://h:1\0ANTHROPIC_DEFAULT_HAIKU_MODEL=strata\0"
           b"CLAUDE_CONFIG_DIR=/p/personal\0")


def test_parse_environ_splits_on_nul():
    env = drr.parse_environ(ENVIRON)
    assert env["A"] == "1" and env["ANTHROPIC_BASE_URL"] == "http://h:1"
    assert drr.parse_environ(b"") == {}
    assert drr.parse_environ(b"X=a=b\0junk\0")["X"] == "a=b"


def test_routing_line():
    assert drr.routing_line(drr.parse_environ(ENVIRON)).startswith(
        "routing: base_url=http://h:1 haiku=strata profile=personal")
    assert drr.routing_line({}).startswith("routing: base_url=unset haiku=unset profile=default")
    assert "profile=aris " in drr.routing_line({"CLAUDE_CONFIG_DIR": "/p/aris/"})


def test_read_routing_reads_the_given_pid():
    seen = []
    line = drr.read_routing("42", read=lambda path: seen.append(path) or ENVIRON)
    assert seen == ["/proc/42/environ", "/proc/42/cmdline"] and line.startswith("routing: base_url=http://h:1")


def test_read_routing_never_raises():
    for exc in (FileNotFoundError(), PermissionError(), OSError("boom")):
        def reader(path, exc=exc):
            raise exc
        assert drr.read_routing("42", read=reader) == "routing: unavailable (no /proc)"


def _world():
    fake = FakeTmux()
    fake.sessions["myrun"] = [{"id": "@7", "index": 2, "dead": False, "cmd": "bash"},
                              {"id": "@6", "index": 1, "dead": False, "cmd": "bash"}]
    return fake


class Clock:
    def __init__(self):
        self.t, self.slept = 0.0, []

    def __call__(self):
        return self.t

    def sleep(self, secs):
        self.slept.append(secs)
        self.t += secs


def test_wait_for_run_finds_the_pid_under_the_run_window():
    table = [("p@6", "1", "bash"), ("500", "p@6", "node /x/cli.js /tp-run-full-design myrun")]
    clock = Clock()
    pid = drr.wait_for_run(_world(), "myrun", 30, table=lambda: table,
                           clock=clock, sleep=clock.sleep)
    assert pid == "500" and clock.slept == []


def test_wait_for_run_polls_until_the_run_appears():
    up = [("p@6", "1", "bash"), ("500", "p@6", "claude --model opus")]
    tables = iter([[("p@6", "1", "bash")], [("p@6", "1", "bash")], up])
    clock = Clock()
    pid = drr.wait_for_run(_world(), "myrun", 30, table=lambda: next(tables),
                           clock=clock, sleep=clock.sleep)
    assert pid == "500" and len(clock.slept) == 2


def test_wait_for_run_times_out_without_sleeping_past_the_deadline():
    clock = Clock()
    pid = drr.wait_for_run(_world(), "myrun", 7, table=lambda: [("p@6", "1", "bash")],
                           clock=clock, sleep=clock.sleep)
    assert pid is None and clock.t <= 7 and sum(clock.slept) <= 7


def test_wait_for_run_zero_checks_once_and_does_not_sleep():
    clock = Clock()
    assert drr.wait_for_run(_world(), "myrun", 0, table=lambda: [],
                            clock=clock, sleep=clock.sleep) is None
    assert clock.slept == []


def test_wait_for_run_survives_an_unreadable_process_table_and_missing_session():
    clock = Clock()
    assert drr.wait_for_run(_world(), "myrun", 3, table=lambda: None,
                            clock=clock, sleep=clock.sleep) is None
    assert drr.wait_for_run(FakeTmux(), "ghost", 3, table=lambda: [],
                            clock=clock, sleep=clock.sleep) is None
