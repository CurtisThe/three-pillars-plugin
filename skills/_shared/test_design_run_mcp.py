"""test_design_run_mcp.py — the design-run MCP allow-list core.

design: strata-spend-leaks (Task 2.3) — a design run loads only the MCP servers
it needs. The fake seams are the `claude --help` text and the server-def dict, so
no subprocess and no real profile file is ever read here.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design_run_mcp as drm  # noqa: E402

HELP = "claude --help\n  --strict-mcp-config  Use only MCP servers in --mcp-config\n"
NO_HELP = "claude --help\n  --mcp-config <json>  Load MCP servers\n"

DEFS = {
    "notion": {"type": "http", "url": "https://mcp.notion.com/mcp"},
    "github": {"type": "stdio", "command": "gh-mcp"},
}

EMPTY_JSON = '{"mcpServers": {}}'
EMPTY_ARGS = "--strict-mcp-config --mcp-config '" + EMPTY_JSON + "'"
UNCHANGED = "design-run MCP: unchanged \u2014 this Claude Code build has no --strict-mcp-config"


def _payload(args: str) -> dict:
    return json.loads(args.split("--mcp-config ", 1)[1].strip("'"))


def test_default_allow_list_is_empty():
    assert drm.DEFAULT_ALLOW == ()
    for cfg in ({}, {"design_run_mcp": {}}, {"design_run_mcp": {"allow": []}}):
        p = drm.plan(cfg, HELP, DEFS)
        assert p.args == EMPTY_ARGS
        assert p.loaded == []
    p = drm.plan({}, HELP, DEFS)
    assert p.skipped_note == "design-run MCP: loaded none; skipped all others (strict)"
    assert p.lines == [p.skipped_note]


def test_allowed_server_is_loaded_others_skipped():
    p = drm.plan({"design_run_mcp": {"allow": ["github"]}}, HELP, DEFS)
    assert p.loaded == ["github"]
    assert "notion" not in p.args
    assert p.skipped_note.startswith("design-run MCP: loaded github;")
    assert p.skipped_note.endswith("(strict)")


def test_args_carry_strict_and_only_allowed_defs():
    p = drm.plan({"design_run_mcp": {"allow": ["github"]}}, HELP, DEFS)
    assert p.args.startswith("--strict-mcp-config --mcp-config ")
    assert _payload(p.args) == {"mcpServers": {"github": DEFS["github"]}}


def test_unknown_allowed_name_is_reported():
    p = drm.plan({"design_run_mcp": {"allow": ["github", "slack"]}}, HELP, DEFS)
    assert p.loaded == ["github"]
    assert any("not found: slack" in line for line in p.lines)
    assert list(_payload(p.args)["mcpServers"]) == ["github"]


def test_unsupported_build_degrades_one_line():
    assert drm.supported(HELP) is True
    assert drm.supported(NO_HELP) is False
    p = drm.plan({"design_run_mcp": {"allow": ["github"]}}, NO_HELP, DEFS)
    assert p.args == ""
    assert p.loaded == []
    assert p.lines == [UNCHANGED]


def test_bad_config_value_dropped_with_warning():
    p = drm.plan({"design_run_mcp": {"allow": "github"}}, HELP, DEFS)
    assert p.loaded == []
    assert p.args == EMPTY_ARGS
    assert len([line for line in p.lines if "warning" in line]) == 1
    assert len(p.lines) == 2


def test_non_string_allow_entries_ignored_with_warning():
    """A list/dict allow entry used to raise TypeError (unhashable) and crash the launch."""
    p = drm.plan({"design_run_mcp": {"allow": [["x"], {"a": 1}, "github"]}}, HELP, DEFS)
    assert p.loaded == ["github"]
    assert set(_payload(p.args)["mcpServers"]) == {"github"}
    warnings = [line for line in p.lines if "warning" in line]
    assert len(warnings) == 1 and "2 non-string" in warnings[0]


def test_read_server_defs_merges_project_and_profile(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"github": {"command": "a"}}}), encoding="utf-8")
    config_dir = tmp_path / "profile"
    config_dir.mkdir()
    (config_dir / ".claude.json").write_text(json.dumps({
        "mcpServers": {"notion": {"url": "u"}},
        "projects": {str(project): {"mcpServers": {"jira": {"command": "j"}}}},
    }), encoding="utf-8")
    assert drm.read_server_defs(project, config_dir) == {
        "notion": {"url": "u"},
        "github": {"command": "a"},
        "jira": {"command": "j"},
    }


def test_read_server_defs_fail_open(tmp_path):
    assert drm.read_server_defs(tmp_path / "nope", tmp_path / "none") == {}
    (tmp_path / ".mcp.json").write_text("{broken", encoding="utf-8")
    assert drm.read_server_defs(tmp_path, tmp_path / "none") == {}
