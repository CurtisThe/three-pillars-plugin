#!/usr/bin/env python3
"""agent_ref.py — the ONE resolver from a bare agent name to the reference a spawn uses.

design: run-throughput (seat ruling: PR #178 merge held — agent-name resolver fix)

Why: Claude Code registers a plugin's agents as ``<plugin-name>:<agent>``. The Agent
tool REJECTS a bare ``subagent_type="tp-task-worker-local-medium"``; only
``"three-pillars:tp-task-worker-local-medium"`` spawns (seat live check, 2026-09-29).
The plugin name is per release tier (``release.sh`` writes the tier's ``plugin_name``
into the shipped ``plugin.json``: core ``three-pillars``, pro ``three-pillars-pro``),
so it is read at runtime from ``<root>/.claude-plugin/plugin.json`` and never
hardcoded. ``<root>`` defaults to the framework root this file is installed in, which
is ``$TP_ROOT`` when run as documented. Every spawn of a three-pillars agent
(``tp-worker``, ``tp-certifier``, ``tp-generator``, ``tp-review-confirmer``,
``tp-readonly-auditor``, ``tp-impl-auditor``, ``council-<name>``, the
``tp-task-worker-<rung>`` variants) passes this reference as ``subagent_type``;
the one documented command is::

    python3 "$TP_ROOT"/skills/_shared/agent_ref.py <agent> [--root R]

(Its own module, not ``model_policy``: that module is pinned to stdlib imports and
300 lines. ``model_policy.AGENTS`` keeps the bare names.)

Bare names stay the telemetry key (``dispatch_log``, ``model_policy.AGENTS``, ladder
records); only the spawn uses the reference.

Loud, never guessed: an absent, unreadable or malformed ``plugin.json``, one with no
``name``, an agent with no ``agents/<agent>.md`` under the root, or one missing from
the manifest's ``agents`` list raises ``AgentRefError`` (the CLI exits 1 with one
stderr line). There is no fallback to the bare name or to a hardcoded prefix. A spawn
the Agent tool rejects is a loud halt too: ``tier_ladder.py next --outcome env-error
--reason "agent-unresolved: <ref>"`` (never ``unavailable``, never a retry under
another name). Stdlib only; imports no project module.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

UNRESOLVED = "agent-unresolved"  # the ladder reason prefix (tier_ladder halts on it)
_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")  # a concrete agent name: no glob, no {name}
_DEFAULT_ROOT = Path(__file__).resolve().parents[2]


class AgentRefError(ValueError):
    """The agent reference cannot be resolved; ``str()`` starts ``agent-unresolved: ``."""

    def __init__(self, agent, why: str):
        super().__init__(f"{UNRESOLVED}: {agent}: {why}")


def _manifest(path: Path, agent) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise AgentRefError(agent, f"{path} not found") from None
    except (OSError, UnicodeDecodeError) as exc:
        raise AgentRefError(agent, f"{path} unreadable ({exc})") from None
    except ValueError as exc:
        raise AgentRefError(agent, f"{path} is not valid JSON ({exc})") from None
    if not isinstance(data, dict):
        raise AgentRefError(agent, f"{path} is not a JSON object")
    return data


def resolve(agent: str, root=None) -> str:
    """``"<plugin name>:<agent>"`` for a concrete agent shipped under ``root``."""
    base = Path(root or _DEFAULT_ROOT)
    if not isinstance(agent, str) or not _NAME.match(agent):
        raise AgentRefError(agent, "not a concrete agent name (no globs or placeholders)")
    manifest = base / ".claude-plugin" / "plugin.json"
    data = _manifest(manifest, agent)
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise AgentRefError(agent, f"{manifest} has no plugin name")
    if not (base / "agents" / f"{agent}.md").is_file():
        raise AgentRefError(agent, f"no agents/{agent}.md under {base}")
    listed = data.get("agents")
    if isinstance(listed, list) and f"./agents/{agent}.md" not in listed:
        raise AgentRefError(agent, f"{manifest} does not list ./agents/{agent}.md")
    return f"{name.strip()}:{agent}"


def main(argv=None) -> int:
    """``<agent> [--root R]``: print the reference, or one stderr line + exit 1."""
    parser = argparse.ArgumentParser(description="Print <plugin name>:<agent>, the spawn "
                                     "reference for a three-pillars agent.")
    parser.add_argument("agent")
    parser.add_argument("--root", default=None, help="framework root (default: this install)")
    args = parser.parse_args(argv)
    try:
        print(resolve(args.agent, args.root))
    except AgentRefError as exc:
        print(f"agent-ref: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
