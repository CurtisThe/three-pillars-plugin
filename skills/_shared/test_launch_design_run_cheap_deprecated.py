"""The launcher parses the retired cheap-tier switches, prints one `deprecated:`
line each, and never forwards `--cheap-tier` to the run (one-cheap-engine 2.6)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import launch_design_run as ldr  # noqa: E402
from test_launch_design_run import rig  # noqa: E402,F401  (fixture)


def _config(rig, block):
    path = Path(rig["repo"]) / ".three-pillars" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": 1, **block}), encoding="utf-8")


def _dry(rig, capsys, argv):
    env = {k: v for k, v in rig["env"].items() if k != "TP_LOCAL"}
    assert ldr.main(["foo", *argv, "--dry-run"], env=env, cwd=rig["repo"]) == 0
    cap = capsys.readouterr()
    return cap.out.strip().splitlines()[-1], cap.err


@pytest.mark.parametrize("argv,name", [
    (["--cheap-tier"], "--cheap-tier"),
    (["--cheap-tier=ab"], "--cheap-tier=ab"),
    (["--no-cheap-tier"], "--no-cheap-tier"),
])
def test_cheap_tier_flags_parse_and_forward_nothing(rig, capsys, argv, name):
    cmd, err = _dry(rig, capsys, argv)
    assert cmd.endswith("'/tp-run-full-design foo'; exec bash")
    assert "--cheap-tier" not in cmd
    lines = [ln for ln in err.splitlines() if ln.startswith("deprecated:")]
    assert len(lines) == 1 and name in lines[0]


@pytest.mark.parametrize("value", ["ab", "on", "off", "AB"])
def test_default_run_flag_gives_one_line(rig, capsys, value):
    _config(rig, {"cheap_tier": {"default_run_flag": value}})
    cmd, err = _dry(rig, capsys, [])
    assert "--cheap-tier" not in cmd
    lines = [ln for ln in err.splitlines() if ln.startswith("deprecated:")]
    assert len(lines) == 1 and "cheap_tier.default_run_flag" in lines[0]


def test_local_forwarding_unchanged(rig, capsys):
    cmd, _ = _dry(rig, capsys, ["--local", "--cheap-tier=ab"])
    assert cmd.endswith("'/tp-run-full-design foo --local'; exec bash")
    env = dict(rig["env"], TP_LOCAL="on")
    _config(rig, {"local_implement": {"enabled": True, "full_design": True}})
    assert ldr.main(["foo", "--dry-run"], env=env, cwd=rig["repo"]) == 0
    assert "--cheap-tier" not in capsys.readouterr().out
