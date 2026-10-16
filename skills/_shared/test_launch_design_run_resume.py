"""`launch_design_run.main` resumes a run in place: its `<slug>` session exists, no run is live.

design: design-run-launch-fixes (Task 1.7)

The rig (fixture repo, profile, stub tmux on PATH) is test_launch_design_run.py's; the
tmux server is the in-memory fake, so `design_run_tmux.open` takes its resume branch.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design_run_command as drc  # noqa: E402
import launch_design_run as ldr  # noqa: E402
from fake_tmux_fixture import FakeTmux  # noqa: E402
from test_launch_design_run import _run, rig  # noqa: E402,F401


def _server(monkeypatch):
    """A fake server: the operator's `seat` and an ended run's `foo` session (dead pane)."""
    fake = FakeTmux()
    fake.sessions["seat"] = [{"id": "@0", "index": 1, "dead": False, "cmd": "bash"}]
    fake.sessions["foo"] = [{"id": "@7", "index": 1, "dead": True, "cmd": "old"}]
    monkeypatch.setattr(ldr.design_run_tmux, "subprocess_runner", lambda *a, **k: fake)
    reports = []
    monkeypatch.setattr(ldr, "_report", lambda *a: reports.append(a[0].slug))
    return fake, reports


def test_main_respawns_the_existing_session(rig, capsys, monkeypatch):
    fake, reports = _server(monkeypatch)
    assert _run(rig, ["foo", "--skip-design"]) == 0
    cmd = drc.window_command("foo", rig["wt"], skip_design=True, config_dir=rig["cfg"])
    assert fake.sub("respawn-window") == [["respawn-window", "-k", "-t", "@7", cmd]]
    assert not fake.sub("new-session")
    assert fake.sessions["foo"][0]["dead"] is False and fake.links["seat"] == {"@7"}
    assert reports == ["foo"]
    assert "linked into session seat" in capsys.readouterr().out


def test_main_refuses_when_the_existing_session_is_live(rig, capsys, monkeypatch):
    fake, reports = _server(monkeypatch)
    fake.sessions["foo"][0]["dead"] = False
    monkeypatch.setattr(ldr.design_run_tmux, "live", lambda slug, runner: "claude")
    assert _run(rig, ["foo", "--skip-design"]) == 2
    assert not fake.sub("respawn-window") and reports == []
    assert "already live" in capsys.readouterr().err
