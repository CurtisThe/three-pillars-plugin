"""test_design_run_rc_name.py — a role launch names its Remote Control entry after the slug.

design: router-alarm-and-rc-name (task 1.2). The launcher turns Remote Control on for a role
launch; the run's `claude` then registers an unnamed Remote Control session, so the seat's
picker shows a hash where the slug should be. Carrying `--remote-control=<slug>` right after
`--name <slug>` names it, and the slash prompt stays the last argument (a positional prompt
after a variadic flag is swallowed — see test_launch_design_run_mcp.py).
"""
from __future__ import annotations

import shlex
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import design_run_command as drc  # noqa: E402
import design_run_routing as drr  # noqa: E402

RUN_ROLE = "CLAUDE_LAUNCHER_ROLE=run"
SEAT_ROLE = "CLAUDE_LAUNCHER_ROLE=seat"


def _argv(cmd: str) -> "list[str]":
    """The command's words after `&&`, with the `; exec bash` tail dropped."""
    return shlex.split(cmd.split("&&", 1)[1].split(";", 1)[0])


# --- window_command: the `=` form rides right after `--name <slug>` -------------------

@pytest.mark.parametrize("role", [RUN_ROLE, SEAT_ROLE], ids=["run-role", "seat-role"])
def test_a_role_launch_carries_the_slug_form(role):
    cmd = drc.window_command("foo", "/w/foo", config_dir="/p", model="opus",
                             backend_env=role)
    argv = _argv(cmd)
    assert "--remote-control=foo" in argv
    assert "--remote-control" not in argv  # never the bare flag
    name_at = argv.index("--name")
    assert argv[name_at + 1] == "foo"
    assert argv[name_at + 2] == "--remote-control=foo"
    assert argv[-1] == "/tp-run-full-design foo"


def test_no_role_adds_no_remote_control_element():
    cmd = drc.window_command("foo", "/w/foo", config_dir="/p", model="opus", backend_env="")
    argv = _argv(cmd)
    assert not [a for a in argv if a.startswith("--remote-control")]
    assert argv[-1] == "/tp-run-full-design foo"


def test_an_unrouted_backend_assignment_is_not_a_role():
    # `env_prefix` takes `backend_env` verbatim; only the role env means Remote Control.
    cmd = drc.window_command("foo", "/w/foo", config_dir="/p", model="opus",
                             backend_env="CLAUDE_LAUNCHER_BACKEND=direct")
    assert not [a for a in _argv(cmd) if a.startswith("--remote-control")]


def test_the_rc_element_sits_after_model_and_the_prompt_stays_last():
    cmd = drc.window_command("foo", "/w/foo", config_dir="/p", model="opus",
                             backend_env=RUN_ROLE, mcp="--mcp-config a.json")
    argv = _argv(cmd)
    assert argv[argv.index("claude") + 1] == "--mcp-config"
    assert argv.index("--remote-control=foo") > argv.index("--model")
    assert argv[-1] == "/tp-run-full-design foo"


def test_without_a_role_the_command_line_is_byte_identical():
    assert drc.window_command("foo", "/w/foo", config_dir="/p", model="opus") == (
        "cd /w/foo && env -u CLAUDE_CODE_EFFORT_LEVEL TP_DESIGN_RUN=1 CLAUDE_CONFIG_DIR=/p "
        "claude --model opus --effort high --name foo '/tp-run-full-design foo'; exec bash"
    )


def test_resume_window_command_gains_no_rc_element():
    # No positional prompt to swallow, so resume keeps its line (task 1.2).
    sid = "0a1b2c3d-1111-2222-3333-444455556666"
    cmd = drc.resume_window_command("foo", "/w/foo", sid, model="opus", backend_env=RUN_ROLE)
    assert "--remote-control" not in cmd
    assert cmd.endswith("--name foo; exec bash")


# --- routing_line: the `=` form reads as Remote Control on ----------------------------

@pytest.mark.parametrize("argv,expected", [
    (["claude", "--remote-control=foo", "--name", "foo"], "on"),
    (["claude", "--remote-control", "--name", "foo"], "on"),
    (["claude", "--name", "foo"], "off"),
    (["claude"], "off"),
    (None, "unknown"),
], ids=["equals-form", "bare-flag", "no-flag", "no-args", "unreadable"])
def test_routing_line_reports_remote_control(argv, expected):
    line = drr.routing_line({}, argv)
    pairs = dict(w.split("=", 1) for w in line.split() if "=" in w)
    assert pairs["remote_control"] == expected
    if expected == "on":
        assert "remote_control=on" in line
