"""Tests for stage_reset.schedule — the detached sender (run-throughput 7.2).

A fake `tmux` shim logs its argv; a fake `claude` shim fails the test if invoked.
Waits only via os.waitpid on the returned child pid.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import stage_reset as sr  # noqa: E402

CASES = json.loads((HERE / "fixtures" / "stage_reset" / "tails.json").read_text(encoding="utf-8"))["cases"]
PANE = "%7"
RESUME = "/tp-run-full-design foo --resume-stage plan"


@pytest.fixture
def env(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "tmux.log"
    marker = tmp_path / "claude.marker"
    tmux = bin_dir / "tmux"
    tmux.write_text(
        f"#!{sys.executable}\nimport json, sys\n"
        f"open({str(log)!r}, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
    )
    claude = bin_dir / "claude"
    claude.write_text(f"#!/bin/sh\ntouch {marker}\nexit 1\n")
    for f in (tmux, claude):
        f.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    cwd = tmp_path / "work" / "proj"
    cwd.mkdir(parents=True)
    design = tmp_path / "design"
    design.mkdir()
    return dict(log=log, marker=marker, cwd=str(cwd), cfg=tmp_path / "cfg", design=design)


def _put_transcript(e, case):
    slug = re.sub(r"[^a-zA-Z0-9]", "-", os.path.normpath(e["cwd"]))
    d = e["cfg"] / "projects" / slug
    d.mkdir(parents=True)
    path = d / "s.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in CASES[case]), encoding="utf-8")
    return path


def _calls(e):
    if not e["log"].exists():
        return []
    return [json.loads(x) for x in e["log"].read_text(encoding="utf-8").splitlines()]


def _run(e, **kw):
    pid = sr.schedule(PANE, e["cwd"], RESUME, design_dir=e["design"], config_dir=e["cfg"], **kw)
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status)


def test_idle_path_sends_clear_then_resume(env):
    _put_transcript(env, "end_turn_trailing")
    assert _run(env, since=0, stable_s=0, gap_s=0, poll_s=0.05, timeout_s=30) == 0
    assert _calls(env) == [
        ["send-keys", "-t", PANE, "-l", "/clear"],
        ["send-keys", "-t", PANE, "Enter"],
        ["send-keys", "-t", PANE, "-l", RESUME],
        ["send-keys", "-t", PANE, "Enter"],
    ]
    assert not (env["design"] / ".handoffs" / "stage-reset.log").exists()
    assert not env["marker"].exists()


@pytest.mark.parametrize("case", [None, "tool_use_after_end_turn"])
def test_timeout_path_sends_only_resume(env, case):
    if case:
        _put_transcript(env, case)
    assert _run(env, since=0, stable_s=0, gap_s=0, poll_s=0.05, timeout_s=0.3) == 0
    assert _calls(env) == [
        ["send-keys", "-t", PANE, "-l", RESUME],
        ["send-keys", "-t", PANE, "Enter"],
    ]
    log = env["design"] / ".handoffs" / "stage-reset.log"
    assert "stage-reset: idle-timeout" in log.read_text(encoding="utf-8")
    assert not env["marker"].exists()


def test_cli_idle_subcommand(env):
    path = _put_transcript(env, "end_turn_trailing")
    os.utime(path, (1_000_000_000, 1_000_000_000))
    out = subprocess.run(
        [sys.executable, str(HERE / "stage_reset.py"), "idle", "--transcript", str(path), "--since", "0"],
        capture_output=True, text=True,
    )
    assert out.returncode == 0
    assert json.loads(out.stdout) == {"idle": True}
