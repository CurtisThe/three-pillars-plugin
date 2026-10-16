"""test_design_run_routing_role.py — the launch readout names backend and Remote Control.

design: launch-role-precedence (task 1.6). No `role=` field, by decision: the launcher deletes
CLAUDE_LAUNCHER_ROLE from the final env, so a running session's role cannot be read back.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design_run_routing as drr  # noqa: E402
from launcher_export_fixture import DIRECT_EXPORT, HYBRID_EXPORT  # noqa: E402

PREFIX = "routing: base_url="


def _pairs(line):
    return dict(w.split("=", 1) for w in line.split() if "=" in w)


def _environ(env):
    return "\0".join(f"{k}={v}" for k, v in env.items()).encode() + b"\0"


def test_direct_with_remote_control_on():
    line = drr.routing_line(DIRECT_EXPORT, ["claude", "--remote-control", "--model", "x"])
    assert line.startswith(PREFIX)
    assert _pairs(line)["backend"] == "direct" and _pairs(line)["remote_control"] == "on"


def test_hybrid_without_remote_control_is_off():
    pairs = _pairs(drr.routing_line(HYBRID_EXPORT, ["claude", "--model", "x"]))
    assert pairs["backend"] == "hybrid" and pairs["remote_control"] == "off"


def test_missing_backend_and_unreadable_argv_are_unknown():
    pairs = _pairs(drr.routing_line({}))
    assert pairs["backend"] == "unknown" and pairs["remote_control"] == "unknown"


def test_no_role_field():
    for env in (DIRECT_EXPORT, HYBRID_EXPORT, {"CLAUDE_LAUNCHER_ROLE": "run"}):
        assert "role" not in _pairs(drr.routing_line(env, ["claude"]))


def test_prefix_is_unchanged():
    line = drr.routing_line({"CLAUDE_CONFIG_DIR": "/p/aris/"}, [])
    assert line.startswith("routing: base_url=unset haiku=unset profile=aris ")


def test_read_routing_reads_cmdline_through_read():
    seen = []

    def read(path):
        seen.append(path)
        if path.endswith("environ"):
            return _environ(DIRECT_EXPORT)
        return b"claude\0--remote-control\0"
    line = drr.read_routing("42", read=read)
    assert sorted(seen) == ["/proc/42/cmdline", "/proc/42/environ"]
    assert _pairs(line)["backend"] == "direct" and _pairs(line)["remote_control"] == "on"


def test_unreadable_cmdline_keeps_the_environ_part():
    def read(path):
        if path.endswith("cmdline"):
            raise OSError("gone")
        return _environ(HYBRID_EXPORT)
    pairs = _pairs(drr.read_routing("42", read=read))
    assert pairs["remote_control"] == "unknown" and pairs["backend"] == "hybrid"
    assert pairs["base_url"] == "http://127.0.0.1:3457"
