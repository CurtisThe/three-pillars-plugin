"""child_permissions.py — the permission policy a Strata child launch carries as flags.

design: strata-classifier-cost-followups §A1, §A2 (task 1.1)

A Strata child runs with `--permission-mode dontAsk`, so every tool call the allow list
does not cover is refused instead of asking the classifier — the classifier call is what
costs a paid Sonnet request. The allow list is shipped plus one rule for the attempt
worktree's own files (Claude Code rule syntax: an absolute path takes the `//` prefix, so the
worktree rule is `Edit(//abs/path/**)` — an `Edit` path rule covers every file-editing tool,
including `Write`; a `Write(<path>)` allow rule is never honoured, measured on CLI 2.1.296).
The deny list is shipped and closed: per-repo
config may only *add* to it, never remove from it. An entry config gets that is not a
rule string is skipped with one warning, so a typo in `.three-pillars/config.json` can
never silently widen a child's permissions.

The module is pure bar one read: `rules` returns its warnings, the caller prints them to
stderr, `argv_flags` only renders the flags (only the two modes in `MODES` are accepted), and
nothing here writes a settings file or spawns a child. `dont_ask_supported` (§A4) asks the CLI
itself — one `claude --help`, read for `dontAsk` — so a caller can pick `auto` on an older CLI
instead of launching a mode the CLI rejects.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

# §A1 shipped allow list. The worktree-scoped Edit rule is added per call by `rules`.
DEFAULT_ALLOW_TOOLS = ["Agent", "Read", "Grep", "Glob", "Bash(*)"]

# §A1: the exact --disallowedTools values, in this order — the destructive Bash verbs, then
# Edit/Write on the settings/agent-definition paths a child may never touch. Deliberately NOT
# all of `.claude/**`: S2 Strata drafters wrote scratch under the legacy scratch parent (a
# `worktrees/<slot>-<id>/` dir inside `.claude`; new scratch is `.tp-scratch/`, outside `.claude`),
# and under dontAsk a deny would beat the worktree allow.
# tp-allow-fragile: design §A1 ships this exact list as the CLI --disallowedTools policy (closed spec set, not a filter over open input)
DEFAULT_DENY = [
    "Bash(rm -r*)", "Bash(rm -fr*)", "Bash(rm -rf*)", "Bash(rm -Rf*)",
    "Bash(kill*)", "Bash(pkill*)", "Bash(killall*)",
    "Bash(git push --force*)", "Bash(git push -f*)", "Bash(git push --delete*)",
    "Bash(git branch -D*)", "Bash(git push origin :*)",
    "Bash(gh pr merge*)", "Bash(gh repo delete*)",
    "Bash(tea pr merge*)", "Bash(tea repo delete*)",
    "Bash(curl * | sh*)", "Bash(curl * | bash*)", "Bash(wget * | sh*)",
    "Edit(.claude/settings.json)", "Write(.claude/settings.json)",
    "Edit(.claude/settings.local.json)", "Write(.claude/settings.local.json)",
    "Edit(.claude/agents/**)", "Write(.claude/agents/**)",
    "Edit(.claude/commands/**)", "Write(.claude/commands/**)",
    "Edit(.claude/hooks/**)", "Write(.claude/hooks/**)",
    "Edit(.claude/skills/**)", "Write(.claude/skills/**)",
    "Edit(**/.git/hooks/**)", "Write(**/.git/hooks/**)",
    "Edit(**/.git/config)", "Write(**/.git/config)",
]

# §A1/§A4: the only modes a child may launch in — never a mode that skips the fence.
MODES = ("dontAsk", "auto")

# §A4: the bound on the one `claude --help` that answers the capability question.
HELP_TIMEOUT_S = 30

# A rule is a tool name, optionally followed by a parenthesised matcher.
# `mcp__server__tool` tool names and matchers containing parens both fit.
_RULE_SHAPE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\(.+\))?$")

_CONFIG_KEY = "strata_spawn"
_PERMISSIONS_KEY = "permissions"
_EXTRA_KEYS = ("allow_extra", "deny_extra")


def load_config(cwd: str) -> dict:
    """The raw JSON of `<cwd>/.three-pillars/config.json`; `{}` if absent or unparsable."""
    path = Path(cwd) / ".three-pillars" / "config.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _worktree_rules(worktree: Path) -> list[str]:
    """The one allow rule scoped to `worktree`: `Edit(//<abs>/**)`.

    An `Edit` path rule covers every file-editing tool, so it is what lets the child `Write`
    inside its own worktree. A `Write(<path>)` rule is never honoured by the CLI at all —
    measured on 2.1.296 under `dontAsk`, `Write(//<dir>/**)` was refused where
    `Edit(//<dir>/**)` was allowed — so emitting one would only mislead the reader.
    """
    scoped = worktree.resolve().as_posix().lstrip("/") + "/**"
    return [f"Edit(//{scoped})"]


def _permissions_of(config: dict) -> dict:
    """The `strata_spawn.permissions` mapping, or `{}` when absent or the wrong shape."""
    section = config.get(_CONFIG_KEY)
    if not isinstance(section, dict):
        return {}
    perms = section.get(_PERMISSIONS_KEY)
    return perms if isinstance(perms, dict) else {}


def _append(extra, base: list[str], warnings: list[str]) -> list[str]:
    """`base` plus each valid entry in `extra` once; an invalid entry warns and is skipped."""
    out = list(base)
    if not isinstance(extra, list):
        warnings.append(f"W: {_CONFIG_KEY}.{_PERMISSIONS_KEY}: skipped invalid rule "
                        f"{extra!r} (expected a list of rule strings)")
        return out
    for entry in extra:
        if isinstance(entry, str) and _RULE_SHAPE.match(entry):
            if entry not in out:
                out.append(entry)
        else:
            warnings.append(f"W: {_CONFIG_KEY}.{_PERMISSIONS_KEY}: skipped invalid rule "
                            f"{entry!r} (want Tool or Tool(matcher))")
    return out


def rules(cwd: str, config: dict) -> tuple[list[str], list[str], list[str]]:
    """`(allow, deny, warnings)` for a child whose working dir is `cwd`.

    `cwd` may be relative — it is resolved to absolute first, because a `//` rule is an
    absolute path. Additions from config append after the shipped entries; the shipped
    deny list is never shortened by config.
    """
    worktree = Path(str(cwd))
    perms = _permissions_of(config)
    warnings: list[str] = []
    for key in perms:
        if key not in _EXTRA_KEYS:
            warnings.append(f"W: {_CONFIG_KEY}.{_PERMISSIONS_KEY}: skipped invalid rule "
                            f"{key!r} (unknown key; only {' and '.join(_EXTRA_KEYS)} are "
                            f"additions)")
    allow = _append(perms.get("allow_extra", []),
                    DEFAULT_ALLOW_TOOLS + _worktree_rules(worktree), warnings)
    deny = _append(perms.get("deny_extra", []), DEFAULT_DENY, warnings)
    return allow, deny, warnings


def argv_flags(mode: str, allow: list[str], deny: list[str]) -> list[str]:
    """The launch flags: `--permission-mode <mode>` then one argv element per rule."""
    if mode not in MODES:
        raise ValueError(f"unsupported permission mode {mode!r} (want one of {MODES})")
    flags = ["--permission-mode", mode]
    if allow:
        flags += ["--allowedTools", *allow]
    if deny:
        flags += ["--disallowedTools", *deny]
    return flags


def dont_ask_supported(env: dict) -> bool:
    """§A4: does the CLI in `env` accept `dontAsk`? Its own `--help` says so.

    One `claude --help` (timeout `HELP_TIMEOUT_S`), read for the word `dontAsk` among the
    `--permission-mode` choices it prints. Anything that is not evidence — no binary, a
    non-zero exit, empty output, a timeout — answers False, so an older CLI falls back to
    `auto` instead of failing, and this never raises past its answer.
    """
    import child_spawn_ops  # deferred: that module imports this one for its launch flags

    try:
        done = subprocess.run([child_spawn_ops.claude_bin(env), "--help"],
                              capture_output=True, text=True, timeout=HELP_TIMEOUT_S)
    except Exception:  # noqa: BLE001 — a CLI nobody can ask is a no, not a crash
        return False
    return done.returncode == 0 and "dontAsk" in (done.stdout or "")
