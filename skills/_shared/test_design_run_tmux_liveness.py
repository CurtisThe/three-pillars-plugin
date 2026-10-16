"""test_design_run_tmux_liveness.py — run liveness: whole-token match, `ps` failure = unknown.

design: design-run-launch-defaults (Behavior 6)
"""
from __future__ import annotations

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design_run_tmux as drt  # noqa: E402
from test_design_run_tmux import FakeTmux  # noqa: E402


def _table(child_args):
    return [("10", "1", "-bash"), ("11", "10", child_args)]


def test_substring_of_the_token_is_not_a_run():
    assert drt.run_process("10", _table("python3 skills/tp-run-full-design/scripts/x.py")) == []
    assert drt.run_process("10", _table("grep /tp-run-full-design-old")) == []


def test_whole_token_is_a_run():
    args = "node /x/cli.js --model opus /tp-run-full-design slug --local"
    assert drt.run_process("10", _table(args)) == ["claude"]


def test_find_run_pid_returns_the_matching_pid():
    table = [("10", "1", "-bash"), ("11", "10", "bash /w/launch.sh"),
             ("12", "11", "node /x/cli.js /tp-run-full-design foo")]
    assert drt.find_run_pid("10", table) == "12"
    assert drt.find_run_pid("10", _table("sleep 5")) is None
    assert drt.find_run_pid("99", table) is None


def test_ps_oserror_is_none(monkeypatch):
    def boom(*a, **k):
        raise OSError("no ps")
    monkeypatch.setattr(drt.subprocess, "run", boom)
    assert drt._ps_table() is None


def test_ps_nonzero_exit_is_none(monkeypatch):
    monkeypatch.setattr(drt.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "denied"))
    assert drt._ps_table() is None


def test_ps_failure_makes_run_process_unknown(monkeypatch):
    monkeypatch.setattr(drt, "_ps_table", lambda: None)
    assert drt.run_process("10") == ["unknown"]


def test_open_refuses_as_live_when_ps_fails(monkeypatch):
    monkeypatch.setattr(drt, "_ps_table", lambda: None)
    fake = FakeTmux()
    fake.sessions["myrun"] = [{"id": "@7", "index": 1, "dead": False, "cmd": "bash"}]
    res = drt.open("myrun", "claude --resume", runner=fake)
    assert res.live and not res.ok and not fake.sub("respawn-window")


def test_close_without_tmux_is_skipped_and_exits_zero(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PATH", str(tmp_path))  # an empty dir: no tmux, so never the real server
    assert drt.main(["close", "x"]) == 0
    assert "tmux: not available (skipped)" in capsys.readouterr().out


def test_run_window_is_the_lowest_index_window_id():
    calls = []

    def runner(args):
        calls.append(list(args))
        return 0, "10 @9\n2 @4\n3 @7"
    assert drt.run_window(runner, "foo") == "@4"
    assert calls == [["list-windows", "-t", "=foo", "-F", "#{window_index} #{window_id}"]]
    assert drt.run_window(lambda a: (1, "no session"), "foo") is None
    assert drt.run_window(lambda a: (0, ""), "foo") is None
