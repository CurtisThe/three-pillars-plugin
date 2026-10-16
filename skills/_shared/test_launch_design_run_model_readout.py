"""The launcher names the design-run model and its source before the command."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design_run_command as drc  # noqa: E402
from test_launch_design_run import _run, _set_design_run, rig  # noqa: E402,F401


def _lines(capsys):
    return capsys.readouterr().out.strip().splitlines()


def test_readout_names_default_model(rig, capsys):
    assert _run(rig, ["foo", "--dry-run"]) == 0
    assert "design-run model: sonnet[1m] (default)" in _lines(capsys)


def test_readout_names_cli_override(rig, capsys):
    assert _run(rig, ["foo", "--model", "opus[1m]", "--dry-run"]) == 0
    assert "design-run model: opus[1m] (--model)" in _lines(capsys)


def test_readout_names_config_model(rig, capsys):
    _set_design_run(rig, "opus[1m]")
    assert _run(rig, ["foo", "--dry-run"]) == 0
    assert "design-run model: opus[1m] (models.design_run)" in _lines(capsys)


def test_command_stays_last_line(rig, capsys):
    assert _run(rig, ["foo", "--dry-run"]) == 0
    lines = _lines(capsys)
    readout = lines.index("design-run model: sonnet[1m] (default)")
    assert readout < len(lines) - 1
    assert "claude" in lines[-1] and "design-run model" not in lines[-1]


def test_window_command_carries_the_config_model(rig, capsys):
    # No --model: the window the run opens in runs claude on models.design_run.
    _set_design_run(rig, "opus")
    assert _run(rig, ["foo", "--wait", "0"]) == 0
    logged = rig["log"].read_text(encoding="utf-8").splitlines()
    cmd = drc.window_command("foo", rig["wt"], config_dir=rig["cfg"],
                             model="opus", configured="opus")
    assert cmd in logged and "--model opus" in cmd
    assert "design-run model: opus (models.design_run)" in _lines(capsys)
