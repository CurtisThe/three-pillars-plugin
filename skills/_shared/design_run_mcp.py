"""design_run_mcp.py — which MCP servers a design-run session is allowed to load.

An unused MCP server (claude.ai Notion is ~60 tools) widens the cached prefix of
every main-thread turn and every all-tools subagent, so a design run starts with
`--strict-mcp-config --mcp-config '<json>'` carrying only the servers the repo's
`.three-pillars/config.json` names under `design_run_mcp.allow` (empty by
default). `plan` is pure: the launcher passes the `claude --help` text and the
server definitions in, so nothing here shells out — a build without
`--strict-mcp-config` degrades to one readout line and an unchanged command.
The only I/O is `read_server_defs`, fail-open to `{}` (design: strata-spend-leaks).
"""
from __future__ import annotations

import json
import os
import shlex
from dataclasses import dataclass, field
from typing import Any, Mapping

STRICT_FLAG = "--strict-mcp-config"
MCP_CONFIG_FLAG = "--mcp-config"
CONFIG_KEY = "design_run_mcp"
DEFAULT_ALLOW: "tuple[str, ...]" = ()

UNCHANGED = ("design-run MCP: unchanged \u2014 this Claude Code build has no "
             + STRICT_FLAG)


@dataclass
class McpPlan:
    """The argv fragment plus the readout lines a launch prints for it."""

    args: str
    loaded: "list[str]" = field(default_factory=list)
    skipped_note: str = ""
    lines: "list[str]" = field(default_factory=list)


def supported(help_text: str) -> bool:
    """True when this Claude Code build documents `--strict-mcp-config`."""
    return STRICT_FLAG in (help_text or "")


def _servers(blob: Any) -> "dict[str, Any]":
    """The `mcpServers` mapping of a parsed config blob (non-dict → empty)."""
    servers = blob.get("mcpServers") if isinstance(blob, dict) else None
    return dict(servers) if isinstance(servers, dict) else {}


def _load(path: str) -> "dict[str, Any]":
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def read_server_defs(project_root: Any, config_dir: Any) -> "dict[str, Any]":
    """Every MCP server definition the session could load, name → definition.

    Project `.mcp.json`, the profile's `.claude.json` top-level `mcpServers`, and
    that project's own entry in it, in that precedence order (the project file
    wins). Fail-open: a missing or unreadable file contributes nothing.
    """
    root = str(project_root or "")
    cfg_dir = str(config_dir or "")
    defs: "dict[str, Any]" = {}
    profile = _load(os.path.join(cfg_dir, ".claude.json")) if cfg_dir else {}
    defs.update(_servers(profile))
    projects = profile.get("projects") if isinstance(profile, dict) else None
    if isinstance(projects, dict):
        for key in (root, os.path.abspath(root), os.path.realpath(root)):
            entry = projects.get(key)
            if entry is not None:
                defs.update(_servers(entry))
                break
    defs.update(_servers(_load(os.path.join(root, ".mcp.json")) if root else {}))
    return defs


def allow_list(cfg: Mapping[str, Any]) -> "tuple[str, ...]":
    """`design_run_mcp.allow` as a tuple; a non-list value drops to the default."""
    block = cfg.get(CONFIG_KEY) if isinstance(cfg, Mapping) else None
    if not isinstance(block, Mapping):
        return DEFAULT_ALLOW
    allow = block.get("allow", DEFAULT_ALLOW)
    return tuple(allow) if isinstance(allow, list) else DEFAULT_ALLOW


def allow_is_bad(cfg: Mapping[str, Any]) -> bool:
    """True when `design_run_mcp.allow` is present but not a list."""
    block = cfg.get(CONFIG_KEY) if isinstance(cfg, Mapping) else None
    if not isinstance(block, Mapping):
        return False
    allow = block.get("allow", ())
    return "allow" in block and not isinstance(allow, list)


def _note(loaded: "list[str]", skipped: "list[str]", explicit: bool) -> str:
    loaded_txt = ", ".join(loaded) if loaded else "none"
    if not explicit:
        skipped_txt = "skipped all others"
    else:
        skipped_txt = "skipped " + (", ".join(skipped) if skipped else "none")
    return f"design-run MCP: loaded {loaded_txt}; {skipped_txt} (strict)"


def plan(cfg: Mapping[str, Any], help_text: str,
         server_defs: Mapping[str, Any]) -> McpPlan:
    """The argv fragment and readout for one design-run launch.

    Unsupported build → empty args and exactly one `unchanged` line. Otherwise a
    non-list `allow` warns once and the default (load nothing) applies; an allowed
    name with no definition on disk is reported, never fatal.
    """
    if not supported(help_text):
        return McpPlan(args="", lines=[UNCHANGED])

    cfg = cfg if isinstance(cfg, Mapping) else {}
    defs = server_defs if isinstance(server_defs, Mapping) else {}
    lines: "list[str]" = []
    if allow_is_bad(cfg):
        lines.append(f"design-run MCP: warning \u2014 {CONFIG_KEY}.allow is not a list; "
                     "using the default (load none)")
    explicit = isinstance((cfg.get(CONFIG_KEY) or {}).get("allow")
                          if isinstance(cfg.get(CONFIG_KEY), Mapping) else None, list)
    wanted = allow_list(cfg)
    bad = [name for name in wanted if not isinstance(name, str)]
    if bad:  # a list/dict entry is unhashable: warn and skip, never crash a launch
        lines.append(f"design-run MCP: warning \u2014 ignored {len(bad)} non-string "
                     f"{CONFIG_KEY}.allow entr{'y' if len(bad) == 1 else 'ies'}")
        wanted = tuple(name for name in wanted if isinstance(name, str))

    loaded = [name for name in wanted if name in defs]
    for name in wanted:
        if name not in defs:
            lines.append(f"design-run MCP: not found: {name}")
    skipped = [name for name in defs if name not in loaded]

    payload = json.dumps({"mcpServers": {name: defs[name] for name in loaded}})
    note = _note(loaded, skipped, explicit)
    args = f"{STRICT_FLAG} {MCP_CONFIG_FLAG} {shlex.quote(payload)}"
    return McpPlan(args=args, loaded=loaded, skipped_note=note, lines=lines + [note])
