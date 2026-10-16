"""The design-run launcher loads only allow-listed MCP servers (strata-spend-leaks 3.4).

`window_command(mcp=...)` places the Task 2.3 fragment before `--model`; the
launcher prints the `design_run_mcp.plan` readout before the command line, a repo
opts a server back in through `design_run_mcp.allow`, and a build without
`--strict-mcp-config` leaves the command unchanged with one line.
"""
from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design_run_command as drc  # noqa: E402
import design_run_mcp as drm  # noqa: E402
import launch_design_run as ldr  # noqa: E402
from test_launch_design_run import rig  # noqa: E402,F401

HELP = "  --strict-mcp-config   Only use MCP servers from --mcp-config\n"
FRAGMENT = "--strict-mcp-config --mcp-config '{\"mcpServers\": {}}'"
DEFS = {"github": {"command": "gh-mcp"}, "notion": {"command": "notion-mcp"}}
REPO_CONFIG_MD = Path(__file__).resolve().parent / "repo-config.md"


def _write_defs(rig):
    (Path(rig["wt"]) / ".mcp.json").write_text(
        json.dumps({"mcpServers": DEFS}), encoding="utf-8")


def _allow(rig, names):
    (Path(rig["repo"]) / ".three-pillars").mkdir(parents=True, exist_ok=True)
    (Path(rig["repo"]) / ".three-pillars" / "config.json").write_text(
        json.dumps({"schema_version": 1, "design_run_mcp": {"allow": names}}),
        encoding="utf-8")


def _launch(rig, capsys, help_text):
    rc = ldr.main(["foo", "--dry-run"], env=dict(rig["env"]), cwd=rig["repo"],
                  help_probe=lambda e: help_text)
    assert rc == 0
    return capsys.readouterr().out.strip().splitlines()


def test_window_command_carries_strict_mcp():
    cmd = drc.window_command("foo", "/r/wt/foo", mcp=FRAGMENT)
    argv = shlex.split(cmd.split(" && ", 1)[1].split("; exec bash")[0])
    argv = argv[argv.index("claude"):]
    assert "--strict-mcp-config" in argv
    last_cfg = max(i for i, a in enumerate(argv) if a == "--mcp-config")
    assert argv[last_cfg + 1] == '{"mcpServers": {}}'
    # `--mcp-config` is variadic: a flag must end its values before the prompt.
    assert argv[last_cfg + 2].startswith("-")
    assert argv[-1] == "/tp-run-full-design foo"
    assert last_cfg < argv.index("--model")


def test_window_command_without_mcp_is_unchanged():
    expected = (
        f"cd /r/wt/foo && env -u {drc.EFFORT_ENV} {drc.MARKER}=1 "
        f"claude --model {shlex.quote(drc.DEFAULT_MODEL)} {drc.effort_args()} --name foo "
        "'/tp-run-full-design foo'; exec bash")
    assert drc.window_command("foo", "/r/wt/foo", mcp="") == expected
    assert drc.window_command("foo", "/r/wt/foo") == expected


def test_dry_run_prints_mcp_readout(rig, capsys):
    _write_defs(rig)
    lines = _launch(rig, capsys, HELP)
    readout = [i for i, ln in enumerate(lines) if ln.startswith("design-run MCP:")]
    assert len(readout) == 1 and readout[0] < len(lines) - 1
    assert lines[readout[0]] == "design-run MCP: loaded none; skipped all others (strict)"
    assert "--strict-mcp-config" in lines[-1] and "design-run MCP" not in lines[-1]


def test_config_opt_in_reaches_the_command(rig, capsys):
    _write_defs(rig)
    _allow(rig, ["github"])
    lines = _launch(rig, capsys, HELP)
    assert "design-run MCP: loaded github; skipped notion (strict)" in lines
    assert "gh-mcp" in lines[-1] and "notion-mcp" not in lines[-1]


def test_unsupported_build_prints_one_line(rig, capsys):
    _write_defs(rig)
    _allow(rig, ["github"])
    lines = _launch(rig, capsys, "Usage: claude [options]\n")
    assert [ln for ln in lines if ln.startswith("design-run MCP:")] == [drm.UNCHANGED]
    assert "--strict-mcp-config" not in lines[-1]
    assert lines[-1] == drc.window_command("foo", rig["wt"], config_dir=rig["cfg"])


def test_repo_config_documents_key():
    text = REPO_CONFIG_MD.read_text(encoding="utf-8")
    assert "design_run_mcp" in text and "allow" in text
